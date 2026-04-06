"""Main agent pipeline: event → classify → RAG → prompt → LLM → route.

AgentPipeline is the single entry point for processing any incoming event.
It wires together Classifier, MemoryClient, PromptBuilder, LLMClient,
ConfidenceScorer, DraftQueue, and MatrixSender.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..memory.client import MemoryClient
from ..memory.config import MemoryConfig
from .classifier import Classifier
from .confidence import ConfidenceScorer
from .draft_queue import DraftQueue
from .llm_client import LLMClient, LLMResponse
from .matrix_sender import MatrixSender
from .prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

# Memory search limit for RAG context
RAG_LIMIT = 10
SENDER_CONTEXT_LIMIT = 5

# Episodic event type for agent-sent messages
EPISODIC_TYPE_AGENT_REPLY = "agent.reply.sent"
EPISODIC_TYPE_DRAFT_QUEUED = "agent.reply.drafted"


@dataclass
class AgentResult:
    """Result of processing one event through the pipeline."""

    mode: str                          # 'outward' | 'inward'
    intent: str                        # classified intent label
    reply_text: str                    # generated reply
    confidence: float                  # final confidence score (0.0–1.0)
    action: str                        # 'auto_sent' | 'drafted' | 'inward_response' | 'error'
    draft_id: Optional[str] = None     # set when action == 'drafted'
    matrix_event_id: Optional[str] = None  # set when action == 'auto_sent'
    error: Optional[str] = None        # set when action == 'error'
    latency_ms: int = 0
    tokens_used: int = 0


class AgentPipeline:
    """Main orchestrator: event → classify → RAG → prompt → LLM → route.

    Usage:
        pipeline = AgentPipeline.from_env()
        await pipeline.connect()
        result = await pipeline.process_event(event)
        await pipeline.close()
    """

    def __init__(
        self,
        memory_client: MemoryClient,
        llm_client: LLMClient,
        draft_queue: DraftQueue,
        matrix_sender: MatrixSender,
    ) -> None:
        self._memory = memory_client
        self._llm = llm_client
        self._drafts = draft_queue
        self._sender = matrix_sender
        self._classifier = Classifier()
        self._prompt_builder = PromptBuilder()
        self._scorer = ConfidenceScorer()
        self._style_examples = self._load_style_examples()

    @classmethod
    def from_env(cls) -> "AgentPipeline":
        """Construct pipeline from environment variables.

        Required env vars:
            ANTHROPIC_API_KEY
            MATRIX_HOMESERVER
            MATRIX_ACCESS_TOKEN
            OPENKHANG_DATABASE_URL  (defaults to localhost:5433)
        """
        config = MemoryConfig.from_env()
        memory_client = MemoryClient(config)
        llm_client = LLMClient(
            meridian_url=os.environ.get("MERIDIAN_URL", ""),
            anthropic_api_key=config.anthropic_api_key,
        )
        draft_queue = DraftQueue(database_url=config.database_url)
        matrix_sender = MatrixSender(
            homeserver=os.environ.get("MATRIX_HOMESERVER", "http://localhost:8008"),
            access_token=os.environ.get("MATRIX_ACCESS_TOKEN", ""),
        )
        return cls(
            memory_client=memory_client,
            llm_client=llm_client,
            draft_queue=draft_queue,
            matrix_sender=matrix_sender,
        )

    async def connect(self) -> None:
        """Initialise all backends. Must be called before process_event()."""
        await self._memory.connect()
        await self._drafts.connect()

    async def close(self) -> None:
        """Flush and close all connections."""
        await self._memory.close()
        await self._drafts.close()

    async def process_event(
        self, event: dict, chat_history: list[dict] | None = None,
    ) -> AgentResult:
        """Process one incoming event through the full pipeline.

        Args:
            event: Dict with keys:
                - body (str): message text
                - source (str): 'matrix'|'chat'|'cli'|'dashboard'
                - room_id (str, optional): Matrix room ID
                - room_name (str, optional): human-readable room name
                - sender_id (str, optional): sender identifier
                - thread_event_id (str, optional): for threading replies
                - event_id (str, optional): upstream event UUID
            chat_history: Optional prior conversation turns for inward mode.
                Each entry: {"role": "user"|"assistant", "content": str}.

        Returns:
            AgentResult describing what happened.
        """
        import time
        t0 = time.monotonic()

        body = event.get("body", "").strip()
        if not body:
            return AgentResult(
                mode="unknown", intent="unknown", reply_text="",
                confidence=0.0, action="error", error="Empty event body",
            )

        try:
            # Step 1: classify mode and intent
            mode = self._classifier.classify_mode(event)
            intent = self._classifier.classify_intent(body, mode)
            has_deadline_risk = self._classifier.has_deadline_risk(body)

            logger.debug("Event classified: mode=%s intent=%s deadline_risk=%s", mode, intent, has_deadline_risk)

            # Step 1b: enforce group chat behavioral rules
            # Skip social/humor/greeting/fyi in group chats UNLESS mentioned
            is_group = self._is_group_chat(event)
            is_mentioned = self._is_mentioned(body)
            if mode == "outward" and is_group and not is_mentioned and intent in ("social", "humor", "greeting", "fyi"):
                logger.info("Skipping group chat %s intent=%s (behavioral rule: ignore_in_group)",
                            event.get("room_name", ""), intent)
                return AgentResult(
                    mode=mode, intent=intent, reply_text="",
                    confidence=0.0, action="skipped",
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )

            # Step 2: RAG — search relevant memories
            memories = await self._memory.search(
                body,
                agent_id=mode,
                limit=RAG_LIMIT,
            )

            # Step 2b: search code events for technical questions
            # Inward mode always searches code (Khanh asks work questions)
            # Outward mode only when keywords match
            code_keywords = ["code", "logic", "function", "class", "implement",
                             "api", "endpoint", "bug", "fix", "error", "crash",
                             "build", "pipeline", "method", "screen", "view",
                             "model", "repository", "service", "compose",
                             "enum", "value", "constant", "config", "source",
                             "type", "field", "param", "variable", "string",
                             "money", "payment", "transaction", "wallet"]
            body_lower = body.lower()
            # Always search code for: inward mode, questions, requests, or keyword matches
            should_search_code = (
                mode == "inward"
                or intent in ("question", "request")
                or any(kw in body_lower for kw in code_keywords)
            )
            if should_search_code:
                # Search Mem0 inward memories
                code_memories = await self._memory.search(
                    body, agent_id="inward", limit=5,
                )
                seen_ids = {m.get("id") for m in memories}
                for cm in code_memories:
                    if cm.get("id") not in seen_ids:
                        memories.append(cm)

                # Full-text search code chunks in Postgres
                # Search with original query + CamelCase/snake_case variants
                search_terms = self._extract_code_search_terms(body)
                code_results = await self._memory.search_code(search_terms, limit=20)
                for cr in code_results:
                    meta = cr.get("metadata", {})
                    doc_type = meta.get("doc_type", "")
                    score = 0.8 if doc_type in ("business-logic", "api-spec") else 0.5
                    memories.append({
                        "memory": cr["payload"].get("text", "")[:500],
                        "score": score,
                        "metadata": meta,
                    })

            # Step 3: sender relationship context
            sender_id = event.get("sender_id", "")
            sender_context: list[dict] = []
            if sender_id:
                sender_context = await self._memory.get_related(
                    sender_id,
                    agent_id=mode,
                )
                sender_context = sender_context[:SENDER_CONTEXT_LIMIT]

            sender_known = bool(sender_context)

            # Step 3b: check if we have conversation history in this room
            # Only reply in rooms where Khanh has participated before
            room_id = event.get("room_id", "")
            has_history_in_room = True  # default True for DMs / unknown
            if room_id and mode == "outward":
                try:
                    has_history_in_room = await self._check_room_history(room_id)
                except Exception:
                    has_history_in_room = True  # fail-open

            # Step 3c: fetch recent room messages for outward conversation context
            room_messages: list[dict] = []
            if mode == "outward" and room_id:
                try:
                    room_messages = await self._memory.get_room_messages(
                        room_id, limit=30,
                    )
                except Exception:
                    pass  # fail-open: no room history is non-fatal

            # Step 4: build prompt (inject style examples for outward mode)
            messages = self._prompt_builder.build(
                mode=mode,
                intent=intent,
                memories=memories,
                sender_context=sender_context,
                event=event,
                style_examples=self._style_examples if mode == "outward" else None,
                chat_history=chat_history if mode == "inward" else None,
                room_messages=room_messages if mode == "outward" else None,
            )

            # Step 5: LLM call
            # Outward: structured JSON (confidence scoring needs it)
            # Inward: plain text (no JSON wrapper, just the answer)
            temperature = 0.3 if mode == "outward" else 0.5
            max_tokens = 4096
            llm_response: LLMResponse = await self._llm.generate(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                require_structured=(mode == "outward"),
            )

            # Step 6: confidence scoring
            confidence = self._scorer.score(
                llm_response=llm_response,
                memories=memories,
                event=event,
                has_deadline_risk=has_deadline_risk,
                sender_known=sender_known,
                intent=intent,
                has_history_in_room=has_history_in_room,
            )

            latency_ms = int((time.monotonic() - t0) * 1000)

            # Step 7: route based on mode and confidence
            result = await self._route(
                event=event,
                mode=mode,
                intent=intent,
                reply_text=llm_response.text,
                confidence=confidence,
                evidence=llm_response.evidence,
                latency_ms=latency_ms,
                tokens_used=llm_response.tokens_used,
            )

            # Step 8: log to episodic store
            await self._log_event(event, result)

            return result

        except Exception as exc:
            logger.exception("Pipeline error processing event: %s", exc)
            latency_ms = int((time.monotonic() - t0) * 1000)
            return AgentResult(
                mode="unknown",
                intent="unknown",
                reply_text="",
                confidence=0.0,
                action="error",
                error=str(exc),
                latency_ms=latency_ms,
            )

    # ------------------------------------------------------------------
    # Style examples
    # ------------------------------------------------------------------

    @staticmethod
    def _load_style_examples() -> list[dict]:
        """Load Khanh's sent messages as few-shot style examples."""
        style_path = Path(__file__).parent.parent.parent / "config" / "style_examples.jsonl"
        if not style_path.exists():
            return []
        examples = []
        try:
            with open(style_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        examples.append(json.loads(line))
        except Exception:
            pass
        return examples

    # ------------------------------------------------------------------
    # Room history check
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_code_search_terms(body: str) -> str:
        """Convert natural language query to code-relevant search terms.

        Extracts English keywords, generates CamelCase/snake_case variants,
        and combines with the original query for broader matching.
        """
        import re
        # Extract English words (likely code-relevant)
        english_words = re.findall(r"[a-zA-Z_]{3,}", body)
        # Also extract potential code terms by joining adjacent English words as CamelCase
        terms = set(english_words)
        # Add CamelCase combination: "money source" → "MoneySource"
        if len(english_words) >= 2:
            camel = "".join(w.capitalize() for w in english_words)
            terms.add(camel)
            # Also snake_case
            terms.add("_".join(w.lower() for w in english_words))
        # Add individual words
        for w in english_words:
            terms.add(w)
        # Combine with original body for Vietnamese context
        return " ".join(terms) + " " + body

    @staticmethod
    def _is_mentioned(body: str) -> bool:
        """Check if message @mentions Khanh (by name or @all)."""
        import re
        text = body.lower()
        # Common mention patterns: @khanh, @bui, @all, full name variants
        mention_patterns = [
            r"@khanh", r"@bui", r"@all",
            r"\bkhanh\b", r"\bbui quoc khanh\b",
        ]
        return any(re.search(p, text) for p in mention_patterns)

    @staticmethod
    def _is_group_chat(event: dict) -> bool:
        """Detect if event is from a group chat (not a 1:1 DM).

        Heuristics: room_name containing spaces/hyphens or multiple members
        suggests a group. DMs in Matrix typically have no display name or
        use the other person's name.
        """
        room_name = event.get("room_name", "")
        room_id = event.get("room_id", "")
        # Matrix group rooms typically have descriptive names
        # DMs have empty room_name or just the other user's name
        if room_name and (" " in room_name or "-" in room_name or "team" in room_name.lower()):
            return True
        # Matrix convention: DM room IDs are shorter; groups have longer IDs
        # But safest: if room_name is set and looks like a channel name, it's a group
        return bool(room_name)

    async def _check_room_history(self, room_id: str) -> bool:
        """Check if we have any prior participation in this room.

        Queries events table for agent replies or seeded history in this room.
        Uses metadata->>'room_id' for fast lookup.
        """
        events = await self._memory.query_events(
            source="agent", limit=200,
        )
        return any(
            (e.get("metadata", {}).get("room_id") == room_id
             or e.get("payload", {}).get("room_id") == room_id)
            for e in events
        )

    # ------------------------------------------------------------------
    # Routing logic
    # ------------------------------------------------------------------

    async def _route(
        self,
        event: dict,
        mode: str,
        intent: str,
        reply_text: str,
        confidence: float,
        evidence: list[str],
        latency_ms: int,
        tokens_used: int,
    ) -> AgentResult:
        """Decide whether to auto-send, draft, or return inward response."""

        # Inward mode: always return directly to caller (no Matrix send)
        if mode == "inward":
            return AgentResult(
                mode=mode,
                intent=intent,
                reply_text=reply_text,
                confidence=confidence,
                action="inward_response",
                latency_ms=latency_ms,
                tokens_used=tokens_used,
            )

        # Outward mode: check confidence threshold for this room
        room_id = event.get("room_id", "")

        # Check global autoreply toggle
        from services.dashboard.agent_relay import is_autoreply_enabled
        if self._scorer.should_auto_send(confidence, room_id) and is_autoreply_enabled():
            # Auto-send via Matrix
            try:
                matrix_event_id = await self._sender.send(
                    room_id=room_id,
                    text=reply_text,
                    thread_event_id=event.get("thread_event_id"),
                )
                return AgentResult(
                    mode=mode,
                    intent=intent,
                    reply_text=reply_text,
                    confidence=confidence,
                    action="auto_sent",
                    matrix_event_id=matrix_event_id,
                    latency_ms=latency_ms,
                    tokens_used=tokens_used,
                )
            except RuntimeError as exc:
                # Rate limit or send failure — fall through to draft queue
                logger.warning("Auto-send failed (%s), falling back to draft queue", exc)

        # Store as draft for human review
        draft_id = await self._drafts.add_draft(
            room_id=room_id,
            original_message=event.get("body", ""),
            draft_text=reply_text,
            confidence=confidence,
            evidence=evidence,
            room_name=event.get("room_name", ""),
            event_id=event.get("event_id"),
        )
        return AgentResult(
            mode=mode,
            intent=intent,
            reply_text=reply_text,
            confidence=confidence,
            action="drafted",
            draft_id=draft_id,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
        )

    # ------------------------------------------------------------------
    # Episodic logging
    # ------------------------------------------------------------------

    async def _log_event(self, event: dict, result: AgentResult) -> None:
        """Append agent action to the episodic store (audit trail)."""
        try:
            event_type = (
                EPISODIC_TYPE_AGENT_REPLY if result.action == "auto_sent"
                else EPISODIC_TYPE_DRAFT_QUEUED
            )
            await self._memory.add_event(
                source="agent",
                event_type=event_type,
                actor="agent",
                payload={
                    "mode": result.mode,
                    "intent": result.intent,
                    "reply_text": result.reply_text,
                    "confidence": result.confidence,
                    "action": result.action,
                    "draft_id": result.draft_id,
                    "matrix_event_id": result.matrix_event_id,
                    "room_id": event.get("room_id", ""),
                    "original_body": event.get("body", "")[:500],  # truncate for storage
                },
                metadata={
                    "latency_ms": result.latency_ms,
                    "tokens_used": result.tokens_used,
                },
            )
        except Exception as exc:
            # Logging failure must never break the pipeline
            logger.warning("Failed to log agent event to episodic store: %s", exc)

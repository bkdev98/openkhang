"""Main agent pipeline: event → classify → skill dispatch → log.

AgentPipeline is the single entry point for processing any incoming event.
It wires together Classifier, MemoryClient, PromptBuilder, LLMClient,
ConfidenceScorer, DraftQueue, MatrixSender, ToolRegistry, and SkillRegistry.

All processing logic lives in skills (outward_reply, inward_query,
send_as_owner). Pipeline is a thin orchestrator: classify → match → delegate.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..memory.client import MemoryClient
from ..memory.config import MemoryConfig
from .classifier import Classifier
from .confidence import ConfidenceScorer
from .draft_queue import DraftQueue
from .llm_client import LLMClient
from .matrix_sender import MatrixSender
from .prompt_builder import PromptBuilder
from .skill_registry import SkillContext, SkillRegistry

logger = logging.getLogger(__name__)

# Episodic event types for audit trail
EPISODIC_TYPE_AGENT_REPLY = "agent.reply.sent"
EPISODIC_TYPE_DRAFT_QUEUED = "agent.reply.drafted"


@dataclass
class AgentResult:
    """Result of processing one event through the pipeline."""

    mode: str                               # 'outward' | 'inward'
    intent: str                             # classified intent label
    reply_text: str                         # generated reply
    confidence: float                       # final confidence score (0.0–1.0)
    action: str                             # 'auto_sent' | 'drafted' | 'inward_response' | 'error' | 'skipped'
    draft_id: Optional[str] = None          # set when action == 'drafted'
    matrix_event_id: Optional[str] = None   # set when action == 'auto_sent'
    error: Optional[str] = None             # set when action == 'error'
    latency_ms: int = 0
    tokens_used: int = 0


class AgentPipeline:
    """Main orchestrator: event → classify → skill dispatch → log.

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
        self._tools = self._init_tools()
        self._skills_registry = self._init_skills()

    @classmethod
    def from_env(cls) -> "AgentPipeline":
        """Construct pipeline from environment variables."""
        config = MemoryConfig.from_env()
        memory_client = MemoryClient(config)
        llm_client = LLMClient(
            meridian_url=os.environ.get("MERIDIAN_URL", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
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
        self,
        event: "dict | CanonicalMessage",
        chat_history: list[dict] | None = None,
    ) -> AgentResult:
        """Process one incoming event through the full pipeline.

        Accepts either a plain dict (legacy callers) or a CanonicalMessage
        (new channel-adapter callers).
        """
        from .channel_adapter import CanonicalMessage

        if isinstance(event, CanonicalMessage):
            event = event.to_legacy_dict()

        import time
        t0 = time.monotonic()

        body = event.get("body", "").strip()
        if not body:
            return AgentResult(
                mode="unknown", intent="unknown", reply_text="",
                confidence=0.0, action="error", error="Empty event body",
            )

        try:
            mode = self._classifier.classify_mode(event)
            intent = self._classifier.classify_intent(body, mode)
            logger.debug("Event classified: mode=%s intent=%s", mode, intent)

            skill = self._skills_registry.match(mode, intent, body)
            if not skill:
                logger.error("No skill matched mode=%s intent=%s — this should not happen", mode, intent)
                return AgentResult(
                    mode=mode, intent=intent, reply_text="",
                    confidence=0.0, action="error",
                    error=f"No skill matched mode={mode} intent={intent}",
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )

            logger.debug("Dispatching to skill: %s", skill.name)
            context = SkillContext(
                classifier=self._classifier,
                scorer=self._scorer,
                prompt_builder=self._prompt_builder,
                style_examples=self._style_examples,
                chat_history=chat_history,
            )
            result = await skill.execute(event, self._tools, self._llm, context)

            await self._log_event(event, result)
            return result

        except Exception as exc:
            logger.exception("Pipeline error processing event: %s", exc)
            latency_ms = int((time.monotonic() - t0) * 1000)
            return AgentResult(
                mode="unknown", intent="unknown", reply_text="",
                confidence=0.0, action="error", error=str(exc),
                latency_ms=latency_ms,
            )

    # ------------------------------------------------------------------
    # Registry initialisation
    # ------------------------------------------------------------------

    def _init_tools(self) -> "ToolRegistry":
        """Initialize tool registry with all available tools."""
        from .tool_registry import ToolRegistry
        from .tools import (
            SearchKnowledgeTool,
            SearchCodeTool,
            GetSenderContextTool,
            GetRoomHistoryTool,
            SendMessageTool,
            LookupPersonTool,
            CreateDraftTool,
        )
        registry = ToolRegistry()
        registry.register(SearchKnowledgeTool(self._memory))
        registry.register(SearchCodeTool(self._memory))
        registry.register(GetSenderContextTool(self._memory))
        registry.register(GetRoomHistoryTool(self._memory))
        registry.register(SendMessageTool(self._sender))
        registry.register(LookupPersonTool())
        registry.register(CreateDraftTool(self._drafts))
        return registry

    def _init_skills(self) -> SkillRegistry:
        """Initialize skill registry. Registration order = priority (first match wins)."""
        from .skills import OutwardReplySkill, InwardQuerySkill, SendAsOwnerSkill

        registry = SkillRegistry()
        # SendAsOwnerSkill must come before InwardQuerySkill (more specific pattern)
        registry.register(SendAsOwnerSkill(self._memory))
        registry.register(OutwardReplySkill(self._memory, self._drafts, self._sender))
        registry.register(InwardQuerySkill(self._memory))
        return registry

    # ------------------------------------------------------------------
    # Style examples
    # ------------------------------------------------------------------

    @staticmethod
    def _load_style_examples() -> list[dict]:
        """Load owner's sent messages as few-shot style examples."""
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
    # Episodic logging (cross-cutting concern — stays in pipeline)
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
                    "original_body": event.get("body", "")[:500],
                },
                metadata={
                    "latency_ms": result.latency_ms,
                    "tokens_used": result.tokens_used,
                },
            )
        except Exception as exc:
            logger.warning("Failed to log agent event to episodic store: %s", exc)

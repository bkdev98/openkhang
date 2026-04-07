"""Outward reply skill — handles all outward-mode events.

Extracts the full outward path from pipeline.process_event():
group-chat filtering → RAG → code search → sender context →
room history → build prompt → LLM (structured) → score → route.

Behavior must be IDENTICAL to the original inline pipeline path.
"""
from __future__ import annotations

import logging
from typing import Any

from ..skill_registry import BaseSkill, SkillContext
from .skill_helpers import extract_code_search_terms

logger = logging.getLogger(__name__)

_RAG_LIMIT = 10
_SENDER_CONTEXT_LIMIT = 5
_CODE_KEYWORDS = frozenset([
    "code", "logic", "function", "class", "implement", "api", "endpoint",
    "bug", "fix", "error", "crash", "build", "pipeline", "method", "screen",
    "view", "model", "repository", "service", "compose", "enum", "value",
    "constant", "config", "source", "type", "field", "param", "variable",
    "string", "money", "payment", "transaction", "wallet",
])


class OutwardReplySkill(BaseSkill):
    """Process outward-mode events: group rules → RAG → LLM → route."""

    def __init__(self, memory_client: Any, draft_queue: Any, matrix_sender: Any) -> None:
        self._memory = memory_client
        self._drafts = draft_queue
        self._sender = matrix_sender

    @property
    def name(self) -> str:
        return "outward_reply"

    @property
    def description(self) -> str:
        return "Handle outward-mode messages: compose reply via RAG+LLM, auto-send or draft."

    @property
    def match_criteria(self) -> dict:
        return {"mode": "outward"}

    async def execute(self, event: dict, tools: Any, llm: Any, context: SkillContext) -> Any:
        import time
        from ..pipeline import AgentResult

        t0 = time.monotonic()
        body = event.get("body", "").strip()
        intent = context.classifier.classify_intent(body, "outward")
        has_deadline_risk = context.classifier.has_deadline_risk(body)

        # Group chat behavioral rules — use adapter-set flags from CanonicalMessage
        is_group = event.get("is_group", False) or self._is_group_chat(event)
        is_mentioned = event.get("is_mentioned", False) or self._is_mentioned(body)
        if is_group and not is_mentioned and intent in (
            "social", "humor", "greeting", "fyi"
        ):
            logger.info("OutwardReplySkill: skipping group chat %s intent=%s", event.get("room_name", ""), intent)
            return AgentResult(
                mode="outward", intent=intent, reply_text="",
                confidence=0.0, action="skipped",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )

        trace = context.trace

        # RAG + conditional code search — skip for social/greeting (no context needed)
        memories: list[dict] = []
        if intent not in ("social", "greeting"):
            memories = await self._memory.search(body, agent_id="outward", limit=_RAG_LIMIT)
            body_lower = body.lower()
            if intent in ("question", "request") or any(kw in body_lower for kw in _CODE_KEYWORDS):
                seen_ids = {m.get("id") for m in memories}
                for cm in await self._memory.search(body, agent_id="inward", limit=5):
                    if cm.get("id") not in seen_ids:
                        memories.append(cm)
                for cr in await self._memory.search_code(extract_code_search_terms(body), limit=20):
                    meta = cr.get("metadata", {})
                    score = 0.8 if meta.get("doc_type") in ("business-logic", "api-spec") else 0.5
                    memories.append({"memory": cr["payload"].get("text", "")[:500], "score": score, "metadata": meta})
        if trace:
            trace.record_rag(memories, label="rag_memories")

        sender_id = event.get("sender_id", "")
        sender_context: list[dict] = []
        if sender_id:
            sender_context = (await self._memory.get_related(sender_id, agent_id="outward"))[:_SENDER_CONTEXT_LIMIT]

        room_id = event.get("room_id", "")
        has_history_in_room = False  # default safe: draft if unknown
        if room_id:
            try:
                has_history_in_room = await self._memory.has_room_history(room_id)
            except Exception:
                pass  # fail-safe: defaults to False → draft

        # Prefer thread-specific context when message is in a thread
        thread_event_id = event.get("thread_event_id", "")
        room_messages: list[dict] = []
        if thread_event_id:
            try:
                room_messages = await self._memory.get_thread_messages(thread_event_id, limit=30)
            except Exception:
                pass
        # Fall back to room-level messages if no thread or thread is empty
        if not room_messages and room_id:
            try:
                room_messages = await self._memory.get_room_messages(room_id, limit=30)
            except Exception:
                pass

        if trace:
            trace.record_rag(sender_context, label="sender_context")
            if room_messages:
                trace.add_step("room_messages", count=len(room_messages))

        messages = context.prompt_builder.build(
            mode="outward", intent=intent, memories=memories,
            sender_context=sender_context, event=event,
            style_examples=context.style_examples or None,
            chat_history=None, room_messages=room_messages or None,
        )
        if trace:
            trace.record_prompt(messages)

        llm_response = await llm.generate(
            messages=messages, temperature=0.3, max_tokens=4096, require_structured=True,
        )
        if trace:
            trace.record_llm_call(
                model=llm_response.model_used, tokens=llm_response.tokens_used,
                latency_ms=llm_response.latency_ms, temperature=0.3,
                raw_response=llm_response.raw,
            )

        confidence = context.scorer.score(
            llm_response=llm_response, memories=memories, event=event,
            has_deadline_risk=has_deadline_risk, sender_known=bool(sender_context),
            intent=intent, has_history_in_room=has_history_in_room,
        )
        if trace:
            trace.record_confidence(confidence, breakdown={
                "llm_confidence": llm_response.confidence,
                "has_deadline_risk": has_deadline_risk,
                "sender_known": bool(sender_context),
                "has_history_in_room": has_history_in_room,
                "is_group": is_group,
                "is_mentioned": is_mentioned,
            })

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Route: auto-send or draft
        from services.dashboard.agent_relay import is_autoreply_enabled
        if context.scorer.should_auto_send(confidence, room_id) and is_autoreply_enabled():
            try:
                eid = await self._sender.send(
                    room_id=room_id, text=llm_response.text,
                    thread_event_id=event.get("thread_event_id"),
                )
                return AgentResult(
                    mode="outward", intent=intent, reply_text=llm_response.text,
                    confidence=confidence, action="auto_sent", matrix_event_id=eid,
                    latency_ms=latency_ms, tokens_used=llm_response.tokens_used,
                )
            except Exception as exc:
                logger.warning("OutwardReplySkill: auto-send failed (%s), falling back to draft", exc)

        draft_id = await self._drafts.add_draft(
            room_id=room_id, original_message=event.get("body", ""),
            draft_text=llm_response.text, confidence=confidence,
            evidence=llm_response.evidence, room_name=event.get("room_name", ""),
            event_id=event.get("event_id"),
        )
        return AgentResult(
            mode="outward", intent=intent, reply_text=llm_response.text,
            confidence=confidence, action="drafted", draft_id=draft_id,
            latency_ms=latency_ms, tokens_used=llm_response.tokens_used,
        )

    @staticmethod
    def _is_mentioned(body: str) -> bool:
        from ..mention_detector import detect_mention
        return detect_mention(body)

    @staticmethod
    def _is_group_chat(event: dict) -> bool:
        room_name = event.get("room_name", "")
        if room_name and (" " in room_name or "-" in room_name or "team" in room_name.lower()):
            return True
        return bool(room_name)

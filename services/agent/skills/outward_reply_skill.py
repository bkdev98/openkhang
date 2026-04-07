"""Outward reply skill — handles all outward-mode events.

Extracts the full outward path from pipeline.process_event():
group-chat filtering → RAG → code search → sender context →
room history → build prompt → LLM (structured) → score → route.

Behavior must be IDENTICAL to the original inline pipeline path.
"""
from __future__ import annotations

import logging
import re
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

        # Group chat behavioral rules
        if self._is_group_chat(event) and not self._is_mentioned(body) and intent in (
            "social", "humor", "greeting", "fyi"
        ):
            logger.info("OutwardReplySkill: skipping group chat %s intent=%s", event.get("room_name", ""), intent)
            return AgentResult(
                mode="outward", intent=intent, reply_text="",
                confidence=0.0, action="skipped",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )

        # RAG + conditional code search
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

        sender_id = event.get("sender_id", "")
        sender_context: list[dict] = []
        if sender_id:
            sender_context = (await self._memory.get_related(sender_id, agent_id="outward"))[:_SENDER_CONTEXT_LIMIT]

        room_id = event.get("room_id", "")
        has_history_in_room = True
        if room_id:
            try:
                events_log = await self._memory.query_events(source="agent", limit=200)
                has_history_in_room = any(
                    e.get("metadata", {}).get("room_id") == room_id or e.get("payload", {}).get("room_id") == room_id
                    for e in events_log
                )
            except Exception:
                pass  # fail-open

        room_messages: list[dict] = []
        if room_id:
            try:
                room_messages = await self._memory.get_room_messages(room_id, limit=30)
            except Exception:
                pass

        messages = context.prompt_builder.build(
            mode="outward", intent=intent, memories=memories,
            sender_context=sender_context, event=event,
            style_examples=context.style_examples or None,
            chat_history=None, room_messages=room_messages or None,
        )
        llm_response = await llm.generate(
            messages=messages, temperature=0.3, max_tokens=4096, require_structured=True,
        )
        confidence = context.scorer.score(
            llm_response=llm_response, memories=memories, event=event,
            has_deadline_risk=has_deadline_risk, sender_known=bool(sender_context),
            intent=intent, has_history_in_room=has_history_in_room,
        )
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
            except RuntimeError as exc:
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
        from ..matrix_channel_adapter import _get_mention_patterns
        text = body.lower()
        return any(re.search(p, text) for p in _get_mention_patterns())

    @staticmethod
    def _is_group_chat(event: dict) -> bool:
        room_name = event.get("room_name", "")
        if room_name and (" " in room_name or "-" in room_name or "team" in room_name.lower()):
            return True
        return bool(room_name)

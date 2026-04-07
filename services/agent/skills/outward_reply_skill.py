"""Outward reply skill — handles all outward-mode events.

Extracts the full outward path from pipeline.process_event():
router-driven skip → RAG → code search → sender context →
room history → build prompt → LLM (structured) → score → route.

Skip decision prefers LLM router result (should_respond flag); falls back to
legacy group-chat heuristics when router_result is None (regex fallback path).
"""
from __future__ import annotations

import logging
from typing import Any

from ..skill_registry import BaseSkill, SkillContext

logger = logging.getLogger(__name__)


class OutwardReplySkill(BaseSkill):
    """Process outward-mode events: router skip → RAG → LLM → route."""

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

        # Use LLM router decision if available, else fall back to legacy group heuristics
        router_result = context.router_result
        if router_result and not router_result.should_respond:
            logger.info(
                "OutwardReplySkill: router says skip (reason: %s)", router_result.reasoning
            )
            return AgentResult(
                mode="outward", intent=intent, reply_text="",
                confidence=0.0, action="skipped",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        elif router_result is None:
            # Regex fallback path: apply legacy group-chat skip heuristic
            is_group = event.get("is_group", False) or self._is_group_chat(event)
            is_mentioned = event.get("is_mentioned", False) or self._is_mentioned(body)
            if is_group and not is_mentioned and intent in ("social", "humor", "greeting", "fyi"):
                logger.info(
                    "OutwardReplySkill: legacy skip group chat %s intent=%s",
                    event.get("room_name", ""), intent,
                )
                return AgentResult(
                    mode="outward", intent=intent, reply_text="",
                    confidence=0.0, action="skipped",
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )

        trace = context.trace

        # Use pre-fetched context bundle from pipeline; fall back to empty on None
        bundle = context.context_bundle
        memories: list[dict] = (bundle.memories + bundle.code_results) if bundle else []
        sender_context: list[dict] = bundle.sender_context if bundle else []
        # Room messages: prefer thread over room
        room_messages: list[dict] = (
            (bundle.thread_messages or bundle.room_messages) if bundle else []
        )

        # has_room_history is a lightweight boolean check — not replaced by bundle
        room_id = event.get("room_id", "")
        has_history_in_room = False  # default safe: draft if unknown
        if room_id:
            try:
                has_history_in_room = await self._memory.has_room_history(room_id)
            except Exception:
                pass  # fail-safe: defaults to False → draft

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

        from ..agent_loop import AgentLoop, ModeConfig

        loop = AgentLoop()
        loop_result = await loop.run(
            config=ModeConfig.outward(),
            messages=messages,
            llm_client=llm,
        )
        if trace:
            trace.record_llm_call(
                model=loop_result.model_used, tokens=loop_result.tokens_used,
                latency_ms=loop_result.latency_ms, temperature=0.3,
                raw_response=loop_result.raw,
            )

        # Derive priority and is_group for the scorer; fall back gracefully
        priority = router_result.priority if router_result else "normal"
        is_group = event.get("is_group", False)

        confidence = context.scorer.score(
            llm_response=loop_result, memories=memories, event=event,
            has_deadline_risk=has_deadline_risk, sender_known=bool(sender_context),
            intent=intent, has_history_in_room=has_history_in_room,
            priority=priority, is_group=is_group,
        )
        if trace:
            trace.record_confidence(confidence, breakdown={
                "llm_confidence": loop_result.confidence,
                "has_deadline_risk": has_deadline_risk,
                "sender_known": bool(sender_context),
                "has_history_in_room": has_history_in_room,
                "is_group": is_group,
                "priority": priority,
            })

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Route: auto-send or draft
        from services.dashboard.agent_relay import is_autoreply_enabled
        if context.scorer.should_auto_send(confidence, room_id) and is_autoreply_enabled():
            try:
                eid = await self._sender.send(
                    room_id=room_id, text=loop_result.text,
                    thread_event_id=event.get("thread_event_id"),
                )
                return AgentResult(
                    mode="outward", intent=intent, reply_text=loop_result.text,
                    confidence=confidence, action="auto_sent", matrix_event_id=eid,
                    latency_ms=latency_ms, tokens_used=loop_result.tokens_used,
                )
            except Exception as exc:
                logger.warning("OutwardReplySkill: auto-send failed (%s), falling back to draft", exc)

        draft_id = await self._drafts.add_draft(
            room_id=room_id, original_message=event.get("body", ""),
            draft_text=loop_result.text, confidence=confidence,
            evidence=loop_result.evidence, room_name=event.get("room_name", ""),
            event_id=event.get("event_id"),
        )
        return AgentResult(
            mode="outward", intent=intent, reply_text=loop_result.text,
            confidence=confidence, action="drafted", draft_id=draft_id,
            latency_ms=latency_ms, tokens_used=loop_result.tokens_used,
        )

    @staticmethod
    def _is_mentioned(body: str) -> bool:
        """Fallback mention detection used only when router_result is None."""
        from ..mention_detector import detect_mention
        return detect_mention(body)

    @staticmethod
    def _is_group_chat(event: dict) -> bool:
        """Fallback group detection used only when router_result is None."""
        room_name = event.get("room_name", "")
        if room_name and (" " in room_name or "-" in room_name or "team" in room_name.lower()):
            return True
        return bool(room_name)

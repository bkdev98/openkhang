"""Inward query skill — handles inward-mode questions from the owner.

Primary path: Claude Agent SDK — LLM dynamically decides which tools to call
(search_knowledge, search_code, etc.) via the SDK's built-in agent loop.

Fallback path: direct RAG search → build prompt → LLM (plain text).
The fallback is triggered when the SDK runner raises an unexpected error.

Outward mode is NOT touched by this skill.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..skill_registry import BaseSkill, SkillContext
from .skill_helpers import extract_code_search_terms

logger = logging.getLogger(__name__)

_RAG_LIMIT = 10
_SENDER_CONTEXT_LIMIT = 5


class InwardQuerySkill(BaseSkill):
    """Answer inward-mode questions using Claude Agent SDK (tool-calling loop).

    The SDK agent receives all safe inward tools via MCP and decides which to call.
    Falls back to direct RAG + LLM when the SDK runner fails.
    """

    def __init__(self, memory_client: Any, sdk_runner: Any = None) -> None:
        self._memory = memory_client
        self._sdk_runner = sdk_runner

    @property
    def name(self) -> str:
        return "inward_query"

    @property
    def description(self) -> str:
        return "Answer the owner's questions using Claude Agent SDK with memory and code search."

    @property
    def match_criteria(self) -> dict:
        # Matches all remaining inward events (send_as_owner has higher priority)
        return {"mode": "inward"}

    async def execute(self, event: dict, tools: Any, llm: Any, context: SkillContext) -> Any:
        from ..pipeline import AgentResult

        t0 = time.monotonic()
        body = event.get("body", "").strip()
        intent = context.classifier.classify_intent(body, "inward")
        trace = context.trace

        # Pre-seed with sender context (from pre-fetched bundle)
        bundle = context.context_bundle
        sender_context: list[dict] = bundle.sender_context if bundle else []
        if trace:
            trace.record_rag(sender_context, label="sender_context")

        try:
            if not self._sdk_runner:
                raise RuntimeError("SDKAgentRunner not configured")

            # Build user message via prompt builder
            user_message = context.prompt_builder.build_user_message(event, intent, "inward")

            # Extract session_id from event (set by dashboard cookie)
            session_id = event.get("session_id", "default")

            # Trace callback
            def on_tool_call(name, inp, result, success):
                if trace:
                    trace.record_tool_call(name, inp, result, success)

            loop_result = await self._sdk_runner.query(
                user_message=user_message,
                session_id=session_id,
                event=event,
                on_tool_call=on_tool_call,
            )

            if trace:
                trace.record_llm_call(
                    model=loop_result.model_used,
                    tokens=loop_result.tokens_used,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    temperature=0.5,
                )
                trace.add_step(
                    "sdk_agent_summary",
                    iterations=loop_result.iterations,
                    total_tool_calls=len(loop_result.tool_calls),
                )

            return AgentResult(
                mode="inward",
                intent=intent,
                reply_text=loop_result.text,
                confidence=0.5,  # inward mode doesn't score confidence
                action="inward_response",
                latency_ms=int((time.monotonic() - t0) * 1000),
                tokens_used=loop_result.tokens_used,
            )
        except Exception as exc:
            logger.warning(
                "SDK agent failed for inward query, falling back to direct RAG: %s", exc
            )
            return await self._fallback_direct(event, llm, context, intent, t0)

    async def _fallback_direct(
        self,
        event: dict,
        llm: Any,
        context: SkillContext,
        intent: str,
        t0: float,
    ) -> Any:
        """Fallback: RAG search → build prompt → plain LLM call.

        Triggered only when the SDK runner raises an unhandled error.
        """
        from ..pipeline import AgentResult

        body = event.get("body", "").strip()
        # Use pre-fetched memories from bundle when available; fall back to direct gather
        bundle = context.context_bundle
        if bundle and bundle.memories:
            memories = bundle.memories + bundle.code_results
        else:
            memories = await self._gather_memories(body)

        sender_context: list[dict] = bundle.sender_context if bundle else []

        messages = context.prompt_builder.build(
            mode="inward", intent=intent, memories=memories,
            sender_context=sender_context, event=event,
            style_examples=None, chat_history=context.chat_history, room_messages=None,
        )

        llm_response = await llm.generate(
            messages=messages, temperature=0.5, max_tokens=4096, require_structured=False,
        )

        return AgentResult(
            mode="inward",
            intent=intent,
            reply_text=llm_response.text,
            confidence=llm_response.confidence,
            action="inward_response",
            latency_ms=int((time.monotonic() - t0) * 1000),
            tokens_used=llm_response.tokens_used,
        )

    async def _gather_memories(self, body: str) -> list[dict]:
        """RAG + code search — used only by the fallback path."""
        memories = await self._memory.search(body, agent_id="inward", limit=_RAG_LIMIT)
        for cr in await self._memory.search_code(extract_code_search_terms(body), limit=20):
            meta = cr.get("metadata", {})
            score = 0.8 if meta.get("doc_type") in ("business-logic", "api-spec") else 0.5
            memories.append({"memory": cr["payload"].get("text", "")[:500], "score": score, "metadata": meta})
        return memories

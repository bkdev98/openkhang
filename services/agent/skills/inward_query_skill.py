"""Inward query skill — handles inward-mode questions from the owner.

Primary path: tool-calling loop (ReAct) — LLM dynamically decides which
tools to call (search_knowledge, search_code, etc.) before returning a reply.

Fallback path: direct RAG search → build prompt → LLM (plain text).
The fallback is triggered when tool-calling raises an unexpected error.

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

# Tools excluded from inward tool-calling loop:
# - create_draft: internal routing, not user-facing
# - send_message: only SendAsOwnerSkill may send (prevents prompt injection auto-sending)
_EXCLUDED_INWARD_TOOLS = {"create_draft", "send_message"}


class InwardQuerySkill(BaseSkill):
    """Answer inward-mode questions using LLM tool-calling (ReAct loop).

    The LLM receives all safe inward tools and decides which to call.
    Falls back to direct RAG + LLM when tool-calling fails.
    """

    def __init__(self, memory_client: Any) -> None:
        self._memory = memory_client

    @property
    def name(self) -> str:
        return "inward_query"

    @property
    def description(self) -> str:
        return "Answer the owner's questions using tool-calling loop (ReAct) with memory and code search."

    @property
    def match_criteria(self) -> dict:
        # Matches all remaining inward events (send_as_owner has higher priority)
        return {"mode": "inward"}

    async def execute(self, event: dict, tools: Any, llm: Any, context: SkillContext) -> Any:
        from ..pipeline import AgentResult
        from ..tool_calling_loop import run_tool_calling_loop

        t0 = time.monotonic()
        body = event.get("body", "").strip()
        intent = context.classifier.classify_intent(body, "inward")

        # Build prompt with empty memories — LLM will search via tools
        messages = context.prompt_builder.build(
            mode="inward", intent=intent, memories=[],
            sender_context=[], event=event,
            style_examples=None, chat_history=context.chat_history, room_messages=None,
        )

        # Expose all safe inward tools (exclude routing-only tools)
        tool_defs = [
            t for t in tools.list_descriptions()
            if t["name"] not in _EXCLUDED_INWARD_TOOLS
        ]

        try:
            result = await run_tool_calling_loop(
                llm_client=llm,
                messages=messages,
                tools=tool_defs,
                tool_executor=tools.execute,
                temperature=0.5,
                max_tokens=4096,
            )
            return AgentResult(
                mode="inward",
                intent=intent,
                reply_text=result.text,
                confidence=0.5,  # inward mode doesn't score confidence
                action="inward_response",
                latency_ms=int((time.monotonic() - t0) * 1000),
                tokens_used=result.tokens_used,
            )
        except Exception as exc:
            logger.warning(
                "Tool-calling loop failed for inward query, falling back to direct RAG: %s", exc
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

        Mirrors the original InwardQuerySkill behaviour before Phase 4.
        Triggered only when the tool-calling loop raises an unhandled error.
        """
        from ..pipeline import AgentResult

        body = event.get("body", "").strip()
        memories = await self._gather_memories(body)

        sender_id = event.get("sender_id", "")
        sender_context: list[dict] = []
        if sender_id:
            sender_context = (
                await self._memory.get_related(sender_id, agent_id="inward")
            )[:_SENDER_CONTEXT_LIMIT]

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

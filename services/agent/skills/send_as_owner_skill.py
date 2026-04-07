"""Send-as-owner skill — executes inward instructions to message a colleague.

Enriches the instruction with DM room context, composes via LLM,
then delivers using lookup_person + send_message tools.

Must be registered BEFORE InwardQuerySkill (more specific pattern wins).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..skill_registry import BaseSkill, SkillContext

logger = logging.getLogger(__name__)

# Extracts target name: "say hi to Dương" → "Dương"
_TARGET_RE = re.compile(
    r"(?:to|cho|tới|với)\s+(.+?)(?:\s+(?:that|rằng|là|:)|\s*$)",
    re.IGNORECASE,
)


class SendAsOwnerSkill(BaseSkill):
    """Compose and send a message to a colleague on the owner's behalf."""

    def __init__(self, memory_client: Any) -> None:
        self._memory = memory_client

    @property
    def name(self) -> str:
        return "send_as_owner"

    @property
    def description(self) -> str:
        return "Execute send-message instructions: look up recipient, compose via LLM, send via Matrix."

    @property
    def match_criteria(self) -> dict:
        return {
            "mode": "inward",
            "body_pattern": r"\b(say|send|tell|message|dm|nhắn|gửi|chat)\b.+\b(to|cho|tới|với)\b",
        }

    async def execute(self, event: dict, tools: Any, llm: Any, context: SkillContext) -> Any:
        import time
        from ..pipeline import AgentResult

        t0 = time.monotonic()
        body = event.get("body", "").strip()
        intent = context.classifier.classify_intent(body, "inward")

        # Enrich instruction with DM room context for better LLM composition
        enriched_event = {**event, "body": await self._enrich_with_context(body)}

        memories = await self._memory.search(body, agent_id="inward", limit=5)
        messages = context.prompt_builder.build(
            mode="inward", intent=intent, memories=memories,
            sender_context=[], event=enriched_event,
            style_examples=None, chat_history=context.chat_history, room_messages=None,
        )

        llm_response = await llm.generate(
            messages=messages, temperature=0.5, max_tokens=4096, require_structured=False,
        )

        reply_text = llm_response.text or ""
        action_result: dict | None = None
        if reply_text:
            action_result = await self._execute_send(body, reply_text, tools)

        result = AgentResult(
            mode="inward", intent=intent, reply_text=reply_text,
            confidence=llm_response.confidence, action="inward_response",
            latency_ms=int((time.monotonic() - t0) * 1000),
            tokens_used=llm_response.tokens_used,
        )
        result._send_action_result = action_result or {}  # type: ignore[attr-defined]
        return result

    async def _enrich_with_context(self, instruction: str) -> str:
        """Prepend recent DM messages for the target person to the instruction."""
        from ..room_lookup import find_room_by_person

        match = _TARGET_RE.search(instruction)
        if not match:
            return instruction
        target_name = match.group(1).strip().rstrip(".,!?")
        room = await find_room_by_person(target_name)
        if not room:
            return instruction

        try:
            room_messages = await self._memory.get_room_messages(room["room_id"], limit=5)
        except Exception:
            return instruction

        # Convert room messages to the format expected below
        rows = [
            {"sender": m.get("sender", ""), "body": m.get("body", "")}
            for m in reversed(room_messages)  # get_room_messages is chronological, we want newest first
        ]

        if not rows:
            return f"{instruction}\n\n[Target: {room['display_name']}. No recent conversation history.]"

        lines = [f"\n\n[Target: {room['display_name']}]", "[Recent conversation (newest first):]"]
        for r in rows:
            sender = "You" if "claude" in (r["sender"] or "") else room["display_name"].split(" - ")[0]
            lines.append(f"  {sender}: {(r['body'] or '')[:100]}")
        lines.append("[Use appropriate form of address based on this context.]")
        return instruction + "\n".join(lines)

    async def _execute_send(self, instruction: str, llm_reply: str, tools: Any) -> dict:
        """Resolve recipient and send via tool registry."""
        match = _TARGET_RE.search(instruction)
        if not match:
            return {"success": False, "error": "Could not parse target person from instruction"}

        target_name = match.group(1).strip().rstrip(".,!?")
        lookup = await tools.execute("lookup_person", name=target_name)
        if not lookup.success or not lookup.data:
            return {"success": False, "error": f"Could not find a DM room for '{target_name}'"}

        room = lookup.data
        message = _extract_composed_message(llm_reply) or llm_reply.strip()
        send = await tools.execute("send_message", room_id=room["room_id"], text=message)
        if send.success:
            logger.info("SendAsOwnerSkill: sent to %s (%s)", room.get("display_name"), room["room_id"])
            return {"success": True, "sent_to": room.get("display_name"),
                    "room_id": room["room_id"], "message": message, "event_id": send.data}
        return {"success": False, "error": send.error}


def _extract_composed_message(llm_reply: str) -> str | None:
    """Extract the actual message from LLM response (strip preamble/quotes)."""
    quote_match = re.search(r'["""](.+?)["""]', llm_reply, re.DOTALL)
    if quote_match:
        return quote_match.group(1).strip()
    prefix_match = re.search(r"(?:message|sending|sent|gửi|nhắn):\s*(.+)", llm_reply, re.IGNORECASE | re.DOTALL)
    if prefix_match:
        return prefix_match.group(1).strip()
    return None

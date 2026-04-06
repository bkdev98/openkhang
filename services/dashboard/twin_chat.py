"""Inward-mode chat adapter: routes questions through AgentPipeline, executes actions.

Supports action instructions like "say hi to Dương" — looks up the person's
DM room via Matrix API and sends the message.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Patterns that indicate a send-message instruction
_SEND_PATTERNS = re.compile(
    r"\b(say|send|tell|message|dm|nhắn|gửi|chat)\b.+\b(to|cho|tới|với)\b",
    re.IGNORECASE,
)

# Extract target person name: "say hi to Dương" → "Dương"
_TARGET_RE = re.compile(
    r"(?:to|cho|tới|với)\s+(.+?)(?:\s+(?:that|rằng|là|:)|\s*$)",
    re.IGNORECASE,
)


async def ask_twin(question: str) -> dict[str, Any]:
    """Process an inward-mode question through the agent pipeline.

    If the question is an action instruction (send message, etc.),
    executes the action after getting the LLM's composed message.
    """
    # Check if this is a send-message instruction
    is_send_action = bool(_SEND_PATTERNS.search(question))

    try:
        from ..agent.pipeline import AgentPipeline

        pipeline = AgentPipeline.from_env()
        await pipeline.connect()
        try:
            result = await pipeline.process_event({
                "body": question,
                "source": "dashboard",
                "sender_id": "dashboard_user",
                "mode_hint": "inward",
            })

            reply_text = result.reply_text or ""
            action_result = None

            # If this was a send instruction and we got a reply, try to execute
            if is_send_action and reply_text:
                action_result = await _execute_send_action(question, reply_text, pipeline)

            return {
                "reply_text": reply_text,
                "confidence": result.confidence,
                "latency_ms": result.latency_ms,
                "error": result.error,
                "action_executed": action_result,
            }
        finally:
            await pipeline.close()
    except Exception as exc:
        logger.error("ask_twin failed: %s", exc)
        return {
            "reply_text": "",
            "confidence": 0.0,
            "latency_ms": 0,
            "error": str(exc),
        }


async def _execute_send_action(
    instruction: str, llm_reply: str, pipeline: Any
) -> dict[str, Any] | None:
    """Try to send a message based on the instruction.

    Extracts target person, looks up their DM room, sends the message.
    """
    from ..agent.room_lookup import find_room_by_person

    # Extract target person name from instruction
    target_match = _TARGET_RE.search(instruction)
    if not target_match:
        return {"success": False, "error": "Could not parse target person from instruction"}

    target_name = target_match.group(1).strip().rstrip(".,!?")

    # Look up the person's DM room
    room = await find_room_by_person(target_name)
    if not room:
        return {
            "success": False,
            "error": f"Could not find a DM room for '{target_name}'",
        }

    # Extract the message to send — LLM should output just the message
    message_to_send = _extract_composed_message(llm_reply)
    if not message_to_send:
        # LLM likely returned just the message directly (ideal case)
        # Strip any leading "Here's..." preamble
        clean = llm_reply.strip()
        # If it's short and doesn't look like an explanation, use it as-is
        if len(clean) < 500 and "?" not in clean[-5:]:
            message_to_send = clean
        else:
            return {"success": False, "error": "Could not extract message to send from LLM response"}

    # Send via Matrix
    try:
        event_id = await pipeline._sender.send(
            room_id=room["room_id"],
            text=message_to_send,
        )
        logger.info(
            "twin_chat: sent message to %s (%s) event=%s",
            room["display_name"], room["room_id"], event_id,
        )
        return {
            "success": True,
            "sent_to": room["display_name"],
            "room_id": room["room_id"],
            "message": message_to_send,
            "event_id": event_id,
        }
    except Exception as exc:
        logger.error("twin_chat: send failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _extract_composed_message(llm_reply: str) -> str | None:
    """Extract the composed message from LLM response.

    The LLM might say "Here's the message I'll send: ..." or
    wrap it in quotes. Try to extract just the message part.
    """
    # Look for quoted message
    quote_match = re.search(r'["""](.+?)["""]', llm_reply, re.DOTALL)
    if quote_match:
        return quote_match.group(1).strip()

    # Look for "Message:" or "Sending:" prefix
    prefix_match = re.search(
        r"(?:message|sending|sent|gửi|nhắn):\s*(.+)",
        llm_reply,
        re.IGNORECASE | re.DOTALL,
    )
    if prefix_match:
        return prefix_match.group(1).strip()

    return None

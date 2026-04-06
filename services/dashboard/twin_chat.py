"""Inward-mode chat adapter: routes questions through AgentPipeline, executes actions.

Supports action instructions like "say hi to Dương" — looks up the person's
DM room via Matrix API and sends the message.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..memory.working import WorkingMemory

logger = logging.getLogger(__name__)

# Shared working memory instance for inward chat sessions (no TTL — persists until restart)
_working_memory = WorkingMemory(ttl_seconds=0)

# Max conversation turns to keep per session (1 turn = user + assistant)
_MAX_HISTORY_TURNS = 10

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


async def ask_twin(question: str, session_id: str = "default") -> dict[str, Any]:
    """Process an inward-mode question through the agent pipeline.

    Maintains conversation history per session_id using WorkingMemory.
    If the question is an action instruction (send message, etc.),
    executes the action after getting the LLM's composed message.
    """
    # Check if this is a send-message instruction
    is_send_action = bool(_SEND_PATTERNS.search(question))

    # Retrieve prior conversation turns for this session
    chat_history: list[dict] = _working_memory.get_context(session_id, "chat_history") or []

    try:
        from ..agent.pipeline import AgentPipeline

        pipeline = AgentPipeline.from_env()
        await pipeline.connect()
        try:
            # If send action, enrich question with target person context
            enriched_question = question
            if is_send_action:
                enriched_question = await _enrich_with_context(question)

            result = await pipeline.process_event(
                {
                    "body": enriched_question,
                    "source": "dashboard",
                    "sender_id": "dashboard_user",
                    "mode_hint": "inward",
                },
                chat_history=chat_history,
            )

            reply_text = result.reply_text or ""
            action_result = None

            # If this was a send instruction and we got a reply, try to execute
            if is_send_action and reply_text:
                action_result = await _execute_send_action(question, reply_text, pipeline)

            # Store this turn in session history
            if reply_text:
                chat_history.append({"role": "user", "content": question})
                chat_history.append({"role": "assistant", "content": reply_text})
                # Trim to max turns (each turn = 2 messages)
                if len(chat_history) > _MAX_HISTORY_TURNS * 2:
                    chat_history = chat_history[-_MAX_HISTORY_TURNS * 2:]
                _working_memory.set_context(session_id, "chat_history", chat_history)

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
        message_to_send = llm_reply.strip()

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


async def _enrich_with_context(instruction: str) -> str:
    """Add conversation context for the target person to the instruction.

    Looks up the person, fetches recent messages from their DM room,
    and appends context so the LLM can use correct xưng hô and topic.
    """
    from ..agent.room_lookup import find_room_by_person

    target_match = _TARGET_RE.search(instruction)
    if not target_match:
        return instruction

    target_name = target_match.group(1).strip().rstrip(".,!?")
    room = await find_room_by_person(target_name)
    if not room:
        return instruction

    # Fetch recent messages from this room for context
    import asyncpg
    import os
    db_url = os.getenv(
        "OPENKHANG_DATABASE_URL",
        "postgresql://openkhang:openkhang@localhost:5433/openkhang",
    )
    try:
        conn = await asyncpg.connect(db_url)
        rows = await conn.fetch(
            """
            SELECT payload->>'sender' as sender, payload->>'body' as body
            FROM events
            WHERE source = 'chat'
              AND (metadata->>'room_id' = $1 OR payload->>'room_id' = $1)
            ORDER BY created_at DESC
            LIMIT 5
            """,
            room["room_id"],
        )
        await conn.close()
    except Exception:
        return instruction

    if not rows:
        return f"{instruction}\n\n[Target: {room['display_name']}. No recent conversation history.]"

    # Build context block
    context_lines = [f"\n\n[Target: {room['display_name']}]"]
    context_lines.append("[Recent conversation in this DM (newest first):]")
    for r in rows:
        sender = "You" if "claude" in (r["sender"] or "") else room["display_name"].split(" - ")[0]
        body = (r["body"] or "")[:100]
        context_lines.append(f"  {sender}: {body}")
    context_lines.append("[Use appropriate xưng hô based on this context.]")

    return instruction + "\n".join(context_lines)


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

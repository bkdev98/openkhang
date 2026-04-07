"""Inward-mode chat adapter: routes questions through AgentPipeline.

Send-as-owner action detection and execution is now handled by
SendAsOwnerSkill inside the pipeline. This module is a thin adapter
that manages session history and calls process_event().
"""

from __future__ import annotations

import logging
from typing import Any

from ..memory.working import WorkingMemory

logger = logging.getLogger(__name__)

# Shared working memory instance for inward chat sessions (no TTL — persists until restart)
_working_memory = WorkingMemory(ttl_seconds=0)

# Max conversation turns to keep per session (1 turn = user + assistant)
_MAX_HISTORY_TURNS = 10


async def ask_twin(question: str, session_id: str = "default") -> dict[str, Any]:
    """Process an inward-mode question through the agent pipeline.

    Maintains conversation history per session_id using WorkingMemory.
    Send-message actions (e.g. "say hi to Dương") are handled automatically
    by SendAsOwnerSkill inside the pipeline.
    """
    chat_history: list[dict] = _working_memory.get_context(session_id, "chat_history") or []

    try:
        from ..agent.pipeline import AgentPipeline
        from ..agent.dashboard_channel_adapter import DashboardChannelAdapter

        _dashboard_adapter = DashboardChannelAdapter()
        pipeline = AgentPipeline.from_env()
        await pipeline.connect()
        try:
            msg = await _dashboard_adapter.normalize_inbound(question, session_id)
            result = await pipeline.process_event(msg.to_legacy_dict(), chat_history=chat_history)

            reply_text = result.reply_text or ""

            # Store this turn in session history
            if reply_text:
                chat_history.append({"role": "user", "content": question})
                chat_history.append({"role": "assistant", "content": reply_text})
                # Trim to max turns (each turn = 2 messages)
                if len(chat_history) > _MAX_HISTORY_TURNS * 2:
                    chat_history = chat_history[-_MAX_HISTORY_TURNS * 2:]
                _working_memory.set_context(session_id, "chat_history", chat_history)

            # Expose send action result if skill attached it
            action_executed = getattr(result, "_send_action_result", None)

            return {
                "reply_text": reply_text,
                "confidence": result.confidence,
                "latency_ms": result.latency_ms,
                "error": result.error,
                "action_executed": action_executed,
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

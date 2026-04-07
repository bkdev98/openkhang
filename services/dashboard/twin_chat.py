"""Inward-mode chat adapter: routes questions through AgentPipeline.

Send-as-owner action detection and execution is now handled by
SendAsOwnerSkill inside the pipeline. This module is a thin adapter
that calls process_event().

The SDKAgentRunner is a module-level singleton so sessions persist
across requests (the pipeline is recreated per-request, but the
runner holds SDK client sessions that must survive).

A lightweight WorkingMemory is kept for dashboard UI display of chat
history — the SDK manages its own internal session state for context.
"""

from __future__ import annotations

import logging
from typing import Any

from ..memory.working import WorkingMemory

logger = logging.getLogger(__name__)

# Module-level singleton — persists across requests for session continuity
_sdk_runner: Any = None

# UI-only history for dashboard display (SDK manages real session context)
_working_memory = WorkingMemory(ttl_seconds=0)
_MAX_HISTORY_TURNS = 10


def _get_sdk_runner() -> Any:
    """Lazy-init the shared SDKAgentRunner singleton."""
    global _sdk_runner
    if _sdk_runner is not None:
        return _sdk_runner

    from ..agent.pipeline import AgentPipeline
    from ..agent.sdk_tool_adapter import create_mcp_from_registry
    from ..agent.sdk_agent_runner import SDKAgentRunner
    from ..agent.prompt_builder import PromptBuilder
    from ..agent.tool_registry import ToolRegistry

    # Build a temporary pipeline just to get the tool registry and prompt
    pipeline = AgentPipeline.from_env()
    tools = pipeline._tools
    prompt_builder = pipeline._prompt_builder

    mcp_server = create_mcp_from_registry(tools, blacklist={"send_message"})
    system_prompt = prompt_builder.build_inward_system(
        memories=[], sender_context=[], tool_registry=tools,
    )
    _sdk_runner = SDKAgentRunner(
        mcp_server=mcp_server,
        system_prompt=system_prompt,
        memory_client=pipeline._memory,
    )
    return _sdk_runner


async def ask_twin(question: str, session_id: str = "default") -> dict[str, Any]:
    """Process an inward-mode question through the agent pipeline.

    Session history is managed natively by the SDK agent runner —
    each session_id maps to a persistent ClaudeSDKClient with full
    conversation context.
    """
    try:
        from ..agent.pipeline import AgentPipeline
        from ..agent.dashboard_channel_adapter import DashboardChannelAdapter

        sdk_runner = _get_sdk_runner()

        _dashboard_adapter = DashboardChannelAdapter()
        pipeline = AgentPipeline.from_env()
        # Inject the shared SDK runner so sessions persist
        pipeline._sdk_runner = sdk_runner
        await pipeline.connect()
        try:
            msg = await _dashboard_adapter.normalize_inbound(question, session_id)
            event_dict = msg.to_legacy_dict()
            # Pass session_id through the event so SDKAgentRunner can use it
            event_dict["session_id"] = session_id
            result = await pipeline.process_event(event_dict)

            reply_text = result.reply_text or ""

            # Track history for dashboard UI display
            if reply_text:
                chat_history = _working_memory.get_context(session_id, "chat_history") or []
                chat_history.append({"role": "user", "content": question})
                chat_history.append({"role": "assistant", "content": reply_text})
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

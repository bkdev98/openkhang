"""SDK-powered agent runner for inward mode.

Replaces the custom ReAct loop (tool_calling_loop.py) with the Claude Agent
SDK's built-in agent loop.  Manages per-session SDK clients, injects RAG
context via hooks, and wires tracing through PostToolUse hooks.

Usage:
    runner = SDKAgentRunner(mcp_server, system_prompt, memory_client)
    result = await runner.query(user_message, session_id, event, on_tool_call=...)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    HookMatcher,
)

from .agent_loop import AgentLoopResult

logger = logging.getLogger(__name__)

# Defaults matching the old ModeConfig.inward()
_MAX_TURNS = 10
_TIMEOUT_SECONDS = 120
_SESSION_TTL_SECONDS = 30 * 60  # 30 minutes idle before cleanup


@dataclass
class _SessionEntry:
    """Tracks a live SDK client session."""

    client: ClaudeSDKClient
    sdk_session_id: str | None = None
    last_active: float = 0.0
    tool_calls: list[dict] = field(default_factory=list)


class SDKAgentRunner:
    """Manages SDK sessions and executes inward-mode queries.

    One SDKAgentRunner instance is shared across all inward requests.
    Each dashboard session_id gets its own ClaudeSDKClient for multi-turn.
    """

    def __init__(
        self,
        mcp_server: Any,
        system_prompt: str,
        memory_client: Any,
    ) -> None:
        self._mcp_server = mcp_server
        self._system_prompt = system_prompt
        self._memory = memory_client
        self._sessions: dict[str, _SessionEntry] = {}

    async def query(
        self,
        user_message: str,
        session_id: str,
        event: dict | None = None,
        on_tool_call: Callable | None = None,
    ) -> AgentLoopResult:
        """Run a query through the SDK agent loop.

        Args:
            user_message: The user's question/instruction.
            session_id: Dashboard session ID for multi-turn context.
            event: Original event dict (for sender context extraction).
            on_tool_call: Optional callback(tool_name, tool_input, result, success)
                          for trace recording.

        Returns:
            AgentLoopResult compatible with the rest of the pipeline.
        """
        t0 = time.monotonic()
        tool_records: list[dict] = []

        # Build hooks for this request
        hooks = self._build_hooks(
            user_message=user_message,
            event=event or {},
            tool_records=tool_records,
            on_tool_call=on_tool_call,
        )

        try:
            entry = await self._get_or_create_session(session_id, hooks)
            entry.last_active = time.monotonic()
            entry.tool_calls = tool_records

            # Send query and collect response
            result_text = ""
            tokens_used = 0
            model_used = ""
            num_turns = 0

            await asyncio.wait_for(
                self._execute_query(entry, user_message),
                timeout=_TIMEOUT_SECONDS,
            )

            # Extract results from the collected messages
            result_text = entry._last_result_text
            tokens_used = entry._last_tokens_used
            model_used = entry._last_model_used
            num_turns = entry._last_num_turns

            latency_ms = int((time.monotonic() - t0) * 1000)

            # Convert tool_records to AgentLoopResult-compatible format
            from .agent_loop import ToolCallRecord
            formatted_tool_calls = [
                ToolCallRecord(
                    tool_name=tc.get("tool_name", ""),
                    tool_input=tc.get("tool_input", {}),
                    result=tc.get("result", ""),
                    success=tc.get("success", True),
                )
                for tc in tool_records
            ]

            return AgentLoopResult(
                text=result_text,
                tokens_used=tokens_used,
                model_used=model_used,
                tool_calls=formatted_tool_calls,
                iterations=num_turns,
                latency_ms=latency_ms,
            )

        except asyncio.TimeoutError:
            logger.warning("SDKAgentRunner: timed out after %ds", _TIMEOUT_SECONDS)
            return AgentLoopResult(
                text="I ran out of time processing this request. Please try a simpler question.",
                iterations=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as exc:
            logger.error("SDKAgentRunner: query failed: %s", exc)
            # Remove broken session so next query starts fresh
            self._sessions.pop(session_id, None)
            raise

    async def _execute_query(self, entry: _SessionEntry, user_message: str) -> None:
        """Send query to SDK client and collect the response."""
        client = entry.client

        await client.query(user_message)

        result_text = ""
        tokens_used = 0
        model_used = ""
        num_turns = 0

        async for message in client.receive_response():
            msg_type = type(message).__name__

            if msg_type == "AssistantMessage":
                # Extract text from content blocks
                for block in getattr(message, "content", []):
                    block_type = getattr(block, "type", "")
                    if block_type == "text":
                        result_text = getattr(block, "text", "")

            elif msg_type == "ResultMessage":
                result_text = getattr(message, "result", result_text) or result_text
                tokens_used = getattr(message, "total_cost_usd", 0)  # SDK reports cost
                num_turns = getattr(message, "num_turns", 0)
                model_used = getattr(message, "model", "")

            elif msg_type == "SystemMessage":
                subtype = getattr(message, "subtype", "")
                if subtype == "init":
                    data = getattr(message, "data", {})
                    entry.sdk_session_id = data.get("session_id")

        # Store results on entry for caller to read
        entry._last_result_text = result_text
        entry._last_tokens_used = tokens_used
        entry._last_model_used = model_used
        entry._last_num_turns = num_turns

    async def _get_or_create_session(
        self,
        session_id: str,
        hooks: dict,
    ) -> _SessionEntry:
        """Get existing session or create a new SDK client."""
        # Cleanup stale sessions
        self._cleanup_stale_sessions()

        if session_id in self._sessions:
            return self._sessions[session_id]

        options = ClaudeAgentOptions(
            tools=[],  # no filesystem built-ins
            mcp_servers={"openkhang": self._mcp_server},
            allowed_tools=["mcp__openkhang__*"],
            system_prompt=self._system_prompt,
            max_turns=_MAX_TURNS,
            permission_mode="bypassPermissions",
            hooks=hooks,
        )

        client = ClaudeSDKClient(options=options)
        await client.connect()

        entry = _SessionEntry(client=client, last_active=time.monotonic())
        self._sessions[session_id] = entry
        logger.info("SDKAgentRunner: created new session '%s'", session_id)
        return entry

    def _build_hooks(
        self,
        user_message: str,
        event: dict,
        tool_records: list[dict],
        on_tool_call: Callable | None,
    ) -> dict:
        """Build SDK hooks for RAG injection and tool call tracing."""
        memory_client = self._memory
        sender_id = event.get("sender_id", "")

        # --- UserPromptSubmit: inject RAG context per turn ---
        async def rag_injection_hook(input_data, tool_use_id, context):
            user_input = input_data.get("user_input", "") or user_message
            try:
                rag_hits = await memory_client.search(
                    user_input, agent_id="inward", limit=10,
                )
                sender_ctx = []
                if sender_id:
                    sender_ctx = (
                        await memory_client.get_related(sender_id, agent_id="inward")
                    )[:5]

                context_block = _format_context_block(rag_hits, sender_ctx)
                if context_block:
                    return {"systemMessage": context_block}
            except Exception as exc:
                logger.warning("SDKAgentRunner: RAG injection failed: %s", exc)
            return {}

        # --- PostToolUse: record tool calls for tracing ---
        async def trace_tool_hook(input_data, tool_use_id, context):
            tool_name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input", {})
            tool_result = input_data.get("tool_result", "")
            is_error = input_data.get("is_error", False)

            # Strip MCP prefix for clean tool names
            clean_name = tool_name
            if clean_name.startswith("mcp__openkhang__"):
                clean_name = clean_name[len("mcp__openkhang__"):]

            record = {
                "tool_name": clean_name,
                "tool_input": tool_input,
                "result": tool_result,
                "success": not is_error,
            }
            tool_records.append(record)

            if on_tool_call:
                try:
                    on_tool_call(clean_name, tool_input, tool_result, not is_error)
                except Exception:
                    pass  # tracing must not break the agent loop

            return {}

        return {
            "UserPromptSubmit": [
                HookMatcher(hooks=[rag_injection_hook]),
            ],
            "PostToolUse": [
                HookMatcher(hooks=[trace_tool_hook]),
            ],
        }

    def _cleanup_stale_sessions(self) -> None:
        """Remove sessions idle longer than TTL."""
        now = time.monotonic()
        stale = [
            sid for sid, entry in self._sessions.items()
            if now - entry.last_active > _SESSION_TTL_SECONDS
        ]
        for sid in stale:
            entry = self._sessions.pop(sid)
            logger.info("SDKAgentRunner: cleaned up stale session '%s'", sid)
            # Best-effort disconnect
            try:
                asyncio.create_task(entry.client.disconnect())
            except Exception:
                pass

    async def close_session(self, session_id: str) -> None:
        """Explicitly close a session (e.g., on dashboard tab close)."""
        entry = self._sessions.pop(session_id, None)
        if entry:
            try:
                await entry.client.disconnect()
            except Exception:
                pass
            logger.info("SDKAgentRunner: closed session '%s'", session_id)

    async def close_all(self) -> None:
        """Close all sessions (shutdown)."""
        for sid in list(self._sessions):
            await self.close_session(sid)


def _format_context_block(
    rag_hits: list[dict],
    sender_context: list[dict],
) -> str:
    """Format RAG results and sender context as a context block for injection."""
    parts: list[str] = []

    if rag_hits:
        lines = ["[Relevant knowledge for this turn]"]
        for hit in rag_hits[:10]:
            mem_text = hit.get("memory") or hit.get("text") or str(hit)
            score = hit.get("score", 0.0)
            lines.append(f"- [{score:.2f}] {mem_text}")
        parts.append("\n".join(lines))

    if sender_context:
        lines = ["[About the person asking]"]
        for ctx in sender_context[:5]:
            mem_text = ctx.get("memory") or ctx.get("text") or str(ctx)
            lines.append(f"- {mem_text}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)

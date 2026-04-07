"""Bridge between openkhang ToolRegistry and Claude Agent SDK MCP server.

Dynamically wraps all registered BaseTool instances as SDK-compatible MCP
tools so the SDK agent loop can call them natively. Zero changes needed to
existing tool implementations in services/agent/tools/.

Usage:
    from .sdk_tool_adapter import create_mcp_from_registry
    mcp_server = create_mcp_from_registry(tool_registry, blacklist={"send_message"})
"""
from __future__ import annotations

import json
import logging
from typing import Any

from claude_agent_sdk import tool as sdk_tool, create_sdk_mcp_server

from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

# SDK MCP server name — tools are exposed as mcp__openkhang__<tool_name>
MCP_SERVER_NAME = "openkhang"
MCP_SERVER_VERSION = "1.0.0"


def create_mcp_from_registry(
    registry: ToolRegistry,
    blacklist: set[str] | frozenset[str] = frozenset(),
) -> Any:
    """Create an in-process SDK MCP server from all tools in the registry.

    Args:
        registry: ToolRegistry with registered BaseTool instances.
        blacklist: Tool names to exclude (e.g. {"send_message"} for inward mode).

    Returns:
        An SDK MCP server object suitable for ClaudeAgentOptions.mcp_servers.
    """
    sdk_tools = []

    for base_tool in registry.list_tools():
        if base_tool.name in blacklist:
            logger.debug("sdk_tool_adapter: skipping blacklisted tool '%s'", base_tool.name)
            continue

        sdk_tools.append(_wrap_tool(base_tool))

    logger.info(
        "sdk_tool_adapter: created MCP server with %d tools (blacklisted %d)",
        len(sdk_tools), len(blacklist),
    )

    return create_sdk_mcp_server(
        name=MCP_SERVER_NAME,
        version=MCP_SERVER_VERSION,
        tools=sdk_tools,
    )


def _wrap_tool(base_tool: Any) -> Any:
    """Wrap a single BaseTool as an SDK @tool definition.

    The SDK tool handler receives args as a dict, calls the underlying
    BaseTool.execute(**args), and returns the result in SDK-expected format.
    """
    name = base_tool.name
    description = base_tool.description
    input_schema = base_tool.parameters

    # Capture base_tool in closure
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await base_tool.execute(**args)
        except Exception as exc:
            # BaseTool.execute shouldn't raise (ToolRegistry catches),
            # but handle it defensively for direct calls
            logger.error("sdk_tool_adapter: tool '%s' raised: %s", name, exc)
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "is_error": True,
            }

        # BaseTool.execute returns raw data (not ToolResult) — ToolResult
        # wrapping happens in ToolRegistry.execute(). Here we get raw output.
        text = _serialize_result(result)
        return {"content": [{"type": "text", "text": text}]}

    return sdk_tool(name, description, input_schema)(handler)


def _serialize_result(data: Any) -> str:
    """Serialize tool output to a string for the SDK agent.

    JSON for structured data (dict/list), str() for everything else.
    """
    if data is None:
        return "OK (no data returned)"
    if isinstance(data, str):
        return data
    if isinstance(data, (dict, list)):
        try:
            return json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(data)
    return str(data)

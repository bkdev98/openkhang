"""Tool registry for the openkhang agent.

BaseTool defines the interface; ToolRegistry manages registration and execution.
Tools are thin wrappers around existing service methods.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool
    data: Any = None
    error: str | None = None


class BaseTool(ABC):
    """Abstract base for agent tools."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict: ...  # JSON Schema format

    @abstractmethod
    async def execute(self, **kwargs) -> Any: ...

    def to_claude_tool(self) -> dict:
        """Generate Claude tool_use compatible tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class ToolRegistry:
    """Registry for agent tools. Manages discovery, listing, and execution."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool. Overwrites any existing tool with the same name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Return tool by name, or None if not found."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def list_descriptions(self) -> list[dict]:
        """Return Claude tool_use compatible definitions for all tools."""
        return [t.to_claude_tool() for t in self._tools.values()]

    async def execute(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name. Returns ToolResult (never raises)."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, error=f"Tool '{name}' not found")
        try:
            data = await tool.execute(**kwargs)
            return ToolResult(success=True, data=data)
        except Exception as exc:
            logger.error("Tool '%s' failed: %s", name, exc)
            return ToolResult(success=False, error=str(exc))

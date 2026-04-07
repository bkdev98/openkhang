"""Retrieve context about a message sender from memory."""
from __future__ import annotations

from ..tool_registry import BaseTool


class GetSenderContextTool(BaseTool):
    """Fetch stored memories related to a sender entity."""

    def __init__(self, memory_client) -> None:
        self._memory = memory_client

    @property
    def name(self) -> str:
        return "get_sender_context"

    @property
    def description(self) -> str:
        return (
            "Get stored context about a person (prior interactions, role, relationship). "
            "Use to personalize replies."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "sender_id": {
                    "type": "string",
                    "description": "Sender identifier",
                },
                "agent_id": {
                    "type": "string",
                    "default": "outward",
                },
            },
            "required": ["sender_id"],
        }

    async def execute(self, **kwargs) -> list[dict]:
        return await self._memory.get_related(
            kwargs["sender_id"],
            agent_id=kwargs.get("agent_id", "outward"),
        )

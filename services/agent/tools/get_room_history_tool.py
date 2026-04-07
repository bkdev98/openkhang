"""Fetch recent messages from a chat room for conversation context."""
from __future__ import annotations

from ..tool_registry import BaseTool


class GetRoomHistoryTool(BaseTool):
    """Fetch recent room messages from the episodic store."""

    def __init__(self, memory_client) -> None:
        self._memory = memory_client

    @property
    def name(self) -> str:
        return "get_room_history"

    @property
    def description(self) -> str:
        return "Get recent messages from a chat room to understand conversation context."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "room_id": {
                    "type": "string",
                    "description": "Matrix room ID",
                },
                "limit": {
                    "type": "integer",
                    "default": 30,
                },
            },
            "required": ["room_id"],
        }

    async def execute(self, **kwargs) -> list[dict]:
        return await self._memory.get_room_messages(
            kwargs["room_id"],
            limit=kwargs.get("limit", 30),
        )

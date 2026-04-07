"""Fetch messages from a specific thread for conversation context."""
from __future__ import annotations

from ..tool_registry import BaseTool


class GetThreadMessagesTool(BaseTool):
    """Fetch messages in a Matrix thread by thread_event_id."""

    def __init__(self, memory_client) -> None:
        self._memory = memory_client

    @property
    def name(self) -> str:
        return "get_thread_messages"

    @property
    def description(self) -> str:
        return (
            "Get messages from a specific thread (by thread_event_id) "
            "to understand the conversation context within that thread."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "thread_event_id": {
                    "type": "string",
                    "description": "Matrix event ID of the thread root",
                },
                "limit": {
                    "type": "integer",
                    "default": 30,
                },
            },
            "required": ["thread_event_id"],
        }

    async def execute(self, **kwargs) -> list[dict]:
        return await self._memory.get_thread_messages(
            kwargs["thread_event_id"],
            limit=kwargs.get("limit", 30),
        )

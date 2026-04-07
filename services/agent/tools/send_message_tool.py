"""Send a message to a Matrix room (via existing MatrixSender)."""
from __future__ import annotations

from ..tool_registry import BaseTool


class SendMessageTool(BaseTool):
    """Sends a text message to a Matrix room via MatrixSender."""

    def __init__(self, matrix_sender) -> None:
        self._sender = matrix_sender

    @property
    def name(self) -> str:
        return "send_message"

    @property
    def description(self) -> str:
        return (
            "Send a message to a chat room. "
            "Use for sending replies or initiating conversations."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "room_id": {
                    "type": "string",
                    "description": "Target room ID",
                },
                "text": {
                    "type": "string",
                    "description": "Message text to send",
                },
                "thread_event_id": {
                    "type": "string",
                    "description": "Thread to reply in (optional)",
                },
            },
            "required": ["room_id", "text"],
        }

    async def execute(self, **kwargs) -> str:
        return await self._sender.send(
            room_id=kwargs["room_id"],
            text=kwargs["text"],
            thread_event_id=kwargs.get("thread_event_id"),
        )

"""Create a draft reply for human review before sending."""
from __future__ import annotations

from ..tool_registry import BaseTool


class CreateDraftTool(BaseTool):
    """Queue a draft reply to the DraftQueue for human review."""

    def __init__(self, draft_queue) -> None:
        self._drafts = draft_queue

    @property
    def name(self) -> str:
        return "create_draft"

    @property
    def description(self) -> str:
        return (
            "Queue a draft reply for human review. "
            "Used when confidence is not high enough for auto-send."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "room_id": {"type": "string"},
                "original_message": {"type": "string"},
                "draft_text": {"type": "string"},
                "confidence": {"type": "number"},
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "room_name": {"type": "string", "default": ""},
                "event_id": {"type": "string"},
            },
            "required": ["room_id", "original_message", "draft_text", "confidence"],
        }

    async def execute(self, **kwargs) -> str:
        return await self._drafts.add_draft(
            room_id=kwargs["room_id"],
            original_message=kwargs["original_message"],
            draft_text=kwargs["draft_text"],
            confidence=kwargs["confidence"],
            evidence=kwargs.get("evidence", []),
            room_name=kwargs.get("room_name", ""),
            event_id=kwargs.get("event_id"),
        )

"""Approve, reject, or edit a pending draft reply, and send if approved."""
from __future__ import annotations

import logging

from ..tool_registry import BaseTool

logger = logging.getLogger(__name__)


class ManageDraftTool(BaseTool):
    """Approve/reject/edit drafts and auto-send via MatrixSender when approved."""

    def __init__(self, draft_queue, matrix_sender) -> None:
        self._drafts = draft_queue
        self._sender = matrix_sender

    @property
    def name(self) -> str:
        return "manage_draft"

    @property
    def description(self) -> str:
        return (
            "Approve, reject, or edit a pending draft reply. "
            "Use list_drafts first to find the draft ID. "
            "Approving a draft sends it via Matrix immediately."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "UUID of the draft to manage (from list_drafts)",
                },
                "action": {
                    "type": "string",
                    "description": "Action to take: approve | reject | edit",
                    "enum": ["approve", "reject", "edit"],
                },
                "edited_text": {
                    "type": "string",
                    "description": "Replacement text when action is 'edit'",
                },
            },
            "required": ["draft_id", "action"],
        }

    async def execute(self, **kwargs) -> dict:
        draft_id: str = kwargs["draft_id"]
        action: str = kwargs["action"]
        edited_text: str | None = kwargs.get("edited_text")

        if action == "reject":
            draft = await self._drafts.reject(draft_id)
            if draft is None:
                return {"ok": False, "error": f"Draft {draft_id} not found or not pending"}
            return {"ok": True, "action": "rejected", "draft_id": draft_id}

        if action == "approve":
            draft = await self._drafts.approve(draft_id)
            if draft is None:
                return {"ok": False, "error": f"Draft {draft_id} not found or not pending"}
            return await self._send_draft(draft)

        if action == "edit":
            if not edited_text:
                return {"ok": False, "error": "edited_text is required for action='edit'"}
            draft = await self._drafts.edit_and_approve(draft_id, edited_text)
            if draft is None:
                return {"ok": False, "error": f"Draft {draft_id} not found or not pending"}
            return await self._send_draft(draft)

        return {"ok": False, "error": f"Unknown action: {action}"}

    async def _send_draft(self, draft: dict) -> dict:
        """Send approved draft via Matrix and return result."""
        room_id = draft.get("room_id", "")
        text = draft.get("draft_text", "")
        draft_id = str(draft.get("id", ""))

        if not room_id or not text:
            return {"ok": False, "error": "Draft missing room_id or draft_text", "draft_id": draft_id}

        try:
            matrix_event_id = await self._sender.send(room_id=room_id, text=text)
            logger.info("Draft %s sent to room %s event=%s", draft_id, room_id, matrix_event_id)
            return {
                "ok": True,
                "action": "sent",
                "draft_id": draft_id,
                "room_id": room_id,
                "matrix_event_id": matrix_event_id,
            }
        except Exception as exc:
            logger.error("Failed to send draft %s: %s", draft_id, exc)
            return {"ok": False, "error": f"Send failed: {exc}", "draft_id": draft_id}

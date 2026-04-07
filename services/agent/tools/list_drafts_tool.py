"""List pending or recent draft replies from the DraftQueue."""
from __future__ import annotations

from datetime import timezone

from ..tool_registry import BaseTool


class ListDraftsTool(BaseTool):
    """Query draft_replies table by status and return summarised results."""

    def __init__(self, draft_queue) -> None:
        self._drafts = draft_queue

    @property
    def name(self) -> str:
        return "list_drafts"

    @property
    def description(self) -> str:
        return (
            "List pending draft replies awaiting review. "
            "Returns room name, original message, draft text, confidence, and status."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: pending | approved | rejected | edited",
                    "default": "pending",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return",
                    "default": 10,
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> list[dict]:
        status = kwargs.get("status", "pending")
        limit = int(kwargs.get("limit", 10))

        if status == "pending":
            rows = await self._drafts.get_pending(limit=limit)
        else:
            # Query non-pending statuses directly via the pool
            pool = self._drafts._pool
            if pool is None:
                return [{"error": "DraftQueue not connected"}]
            rows = await pool.fetch(
                """
                SELECT id, room_name, original_message, draft_text,
                       confidence, status, created_at
                FROM draft_replies
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                status,
                limit,
            )
            rows = [dict(r) for r in rows]

        return [_format_draft(r) for r in rows]


def _format_draft(row: dict) -> dict:
    created_at = row.get("created_at")
    if created_at and hasattr(created_at, "isoformat"):
        # Make timezone-aware for consistent formatting
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        created_str = created_at.isoformat()
    else:
        created_str = str(created_at) if created_at else ""

    original = row.get("original_message", "") or ""
    draft = row.get("draft_text", "") or ""

    return {
        "id": str(row.get("id", "")),
        "room_name": row.get("room_name", "") or "",
        "original_message": original[:100] + ("…" if len(original) > 100 else ""),
        "draft_text": draft[:200] + ("…" if len(draft) > 200 else ""),
        "confidence": row.get("confidence", 0.0),
        "status": row.get("status", ""),
        "created_at": created_str,
    }

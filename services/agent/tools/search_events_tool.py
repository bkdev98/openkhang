"""Query the episodic event store for activity analytics."""
from __future__ import annotations

from datetime import datetime, timezone

from ..tool_registry import BaseTool


class SearchEventsTool(BaseTool):
    """Search the events table for activity analytics via raw SQL."""

    def __init__(self, draft_queue) -> None:
        # Reuse DraftQueue's pool — same Postgres database
        self._drafts = draft_queue

    @property
    def name(self) -> str:
        return "search_events"

    @property
    def description(self) -> str:
        return (
            "Query the episodic event log for activity analytics. "
            "Search by source, event type, actor, or time range. "
            "Useful for 'how many messages today', 'what happened this week', "
            "'show recent agent actions'."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Filter by source: chat | agent | code | jira | gitlab",
                },
                "event_type": {
                    "type": "string",
                    "description": (
                        "Filter by event type e.g. message.received | "
                        "agent.reply.drafted | agent.reply.sent"
                    ),
                },
                "since_hours": {
                    "type": "integer",
                    "description": "Look back N hours (default 24)",
                    "default": 24,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20)",
                    "default": 20,
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> list[dict]:
        pool = self._drafts._pool
        if pool is None:
            return [{"error": "Database pool not connected"}]

        source: str | None = kwargs.get("source") or None
        event_type: str | None = kwargs.get("event_type") or None
        since_hours = int(kwargs.get("since_hours", 24))
        limit = int(kwargs.get("limit", 20))

        rows = await pool.fetch(
            """
            SELECT id, source, event_type, actor,
                   payload->>'body' AS body,
                   payload->>'room_name' AS room_name,
                   created_at
            FROM events
            WHERE ($1::text IS NULL OR source = $1)
              AND ($2::text IS NULL OR event_type = $2)
              AND created_at >= now() - interval '1 hour' * $3
            ORDER BY created_at DESC
            LIMIT $4
            """,
            source,
            event_type,
            since_hours,
            limit,
        )

        now = datetime.now(timezone.utc)
        return [_format_event(dict(r), now) for r in rows]


def _format_event(row: dict, now: datetime) -> dict:
    body = row.get("body") or ""
    created_at = row.get("created_at")

    # Relative time string
    if created_at:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        delta = now - created_at
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            relative = f"{total_seconds}s ago"
        elif total_seconds < 3600:
            relative = f"{total_seconds // 60}m ago"
        elif total_seconds < 86400:
            relative = f"{total_seconds // 3600}h ago"
        else:
            relative = f"{total_seconds // 86400}d ago"
    else:
        relative = ""

    return {
        "id": str(row.get("id", "")),
        "source": row.get("source", ""),
        "event_type": row.get("event_type", ""),
        "actor": row.get("actor", ""),
        "body": body[:150] + ("…" if len(body) > 150 else ""),
        "room_name": row.get("room_name") or "",
        "created_at": relative,
    }

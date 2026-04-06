"""Dashboard backend service adapters: drafts, stats, activity feed, twin chat.

Health checking is delegated to health_checker module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg

from .health_checker import get_all_health
from .twin_chat import ask_twin as _ask_twin

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "OPENKHANG_DATABASE_URL",
    "postgresql://openkhang:openkhang@localhost:5433/openkhang",
)


class DashboardServices:
    """Adapters connecting dashboard routes to backend services."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Open Postgres connection pool."""
        self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    async def close(self) -> None:
        """Close Postgres connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def get_health(self) -> list[dict[str, Any]]:
        """Delegate to health_checker for Docker + Ollama + Postgres."""
        return await get_all_health(self._pool)

    # ------------------------------------------------------------------
    # Drafts
    # ------------------------------------------------------------------

    async def get_drafts(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return pending draft replies from draft_replies table."""
        self._require_pool()
        try:
            rows = await self._pool.fetch(  # type: ignore[union-attr]
                """
                SELECT id, room_id, room_name, original_message, draft_text,
                       confidence, evidence, created_at
                FROM draft_replies
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT $1
                """,
                limit,
            )
            result = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("evidence"), str):
                    try:
                        d["evidence"] = json.loads(d["evidence"])
                    except json.JSONDecodeError:
                        d["evidence"] = []
                if d.get("created_at"):
                    d["created_at_str"] = d["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                d["confidence_pct"] = int(d.get("confidence", 0) * 100)
                d["id_short"] = str(d["id"])[:8]
                d["id"] = str(d["id"])
                result.append(d)
            return result
        except Exception as exc:
            logger.error("get_drafts failed: %s", exc)
            return []

    async def approve_draft(self, draft_id: str) -> bool:
        """Mark draft as approved and send via Matrix. Returns True on success."""
        # Fetch draft details before transitioning
        row = await self._pool.fetchrow(  # type: ignore[union-attr]
            "SELECT room_id, draft_text FROM draft_replies WHERE id = $1 AND status = 'pending'",
            UUID(draft_id),
        )
        if not row:
            return False
        ok = await self._transition(draft_id, "approved", "approve")
        if ok:
            await self._send_matrix_message(row["room_id"], row["draft_text"])
        return ok

    async def reject_draft(self, draft_id: str) -> bool:
        """Mark draft as rejected. Returns True on success."""
        return await self._transition(draft_id, "rejected", "reject")

    async def edit_draft(self, draft_id: str, edited_text: str) -> bool:
        """Edit draft text and mark as approved. Returns True on success."""
        self._require_pool()
        try:
            result = await self._pool.execute(  # type: ignore[union-attr]
                """
                UPDATE draft_replies
                SET status = 'edited', draft_text = $2,
                    reviewed_at = $3, reviewer_action = 'edit'
                WHERE id = $1 AND status = 'pending'
                """,
                UUID(draft_id),
                edited_text,
                datetime.now(timezone.utc),
            )
            ok = result == "UPDATE 1"
            if ok:
                row = await self._pool.fetchrow(  # type: ignore[union-attr]
                    "SELECT room_id FROM draft_replies WHERE id = $1",
                    UUID(draft_id),
                )
                if row:
                    await self._send_matrix_message(row["room_id"], edited_text)
            return ok
        except Exception as exc:
            logger.error("edit_draft %s failed: %s", draft_id, exc)
            return False

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        """Return draft/event counts for the stats bar."""
        self._require_pool()
        try:
            row = await self._pool.fetchrow(  # type: ignore[union-attr]
                """
                SELECT
                    (SELECT COUNT(*) FROM draft_replies WHERE status = 'pending')
                        AS pending_drafts,
                    (SELECT COUNT(*) FROM events)
                        AS total_events,
                    (SELECT COUNT(*) FROM events
                     WHERE created_at >= NOW() - INTERVAL '24 hours')
                        AS events_today,
                    (SELECT COUNT(*) FROM draft_replies
                     WHERE status IN ('approved','edited')
                     AND reviewed_at >= NOW() - INTERVAL '24 hours')
                        AS approved_today
                """
            )
            return dict(row) if row else {}
        except Exception as exc:
            logger.error("get_stats failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Activity feed
    # ------------------------------------------------------------------

    async def get_recent_events(
        self,
        since: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch recent episodic events for the activity feed."""
        self._require_pool()
        try:
            if since:
                # asyncpg needs datetime, not ISO string
                from datetime import datetime, timezone
                if isinstance(since, str):
                    since_dt = datetime.fromisoformat(since)
                else:
                    since_dt = since
                rows = await self._pool.fetch(  # type: ignore[union-attr]
                    """
                    SELECT id, source, event_type, actor, payload, created_at
                    FROM events
                    WHERE created_at > $1
                    ORDER BY created_at DESC LIMIT $2
                    """,
                    since_dt,
                    limit,
                )
            else:
                rows = await self._pool.fetch(  # type: ignore[union-attr]
                    """
                    SELECT id, source, event_type, actor, payload, created_at
                    FROM events
                    ORDER BY created_at DESC LIMIT $1
                    """,
                    limit,
                )
            return [self._normalise_event(dict(r)) for r in rows]
        except Exception as exc:
            logger.error("get_recent_events failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Inward chat
    # ------------------------------------------------------------------

    async def ask_twin(self, question: str, session_id: str = "default") -> dict[str, Any]:
        """Delegate to twin_chat module (keeps heavy pipeline import isolated)."""
        return await _ask_twin(question, session_id=session_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _send_matrix_message(self, room_id: str, text: str) -> bool:
        """Send a message to a Matrix room via Synapse API."""
        import urllib.request
        import uuid as _uuid

        hs = os.getenv("MATRIX_HOMESERVER", "http://localhost:8008")
        token = os.getenv("MATRIX_ACCESS_TOKEN", "")
        if not token or not room_id:
            logger.warning("_send_matrix_message: missing token or room_id")
            return False

        txn_id = str(_uuid.uuid4())
        enc_room = urllib.parse.quote(room_id)
        url = f"{hs}/_matrix/client/v3/rooms/{enc_room}/send/m.room.message/{txn_id}"
        body = json.dumps({"msgtype": "m.text", "body": text}).encode()

        req = urllib.request.Request(url, data=body, method="PUT")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=10)
            )
            logger.info("Sent message to %s: %s", room_id, text[:60])
            return True
        except Exception as exc:
            logger.error("Matrix send failed for %s: %s", room_id, exc)
            return False

    async def _transition(self, draft_id: str, status: str, action: str) -> bool:
        self._require_pool()
        try:
            result = await self._pool.execute(  # type: ignore[union-attr]
                """
                UPDATE draft_replies
                SET status = $2, reviewed_at = $3, reviewer_action = $4
                WHERE id = $1 AND status = 'pending'
                """,
                UUID(draft_id),
                status,
                datetime.now(timezone.utc),
                action,
            )
            return result == "UPDATE 1"
        except Exception as exc:
            logger.error("_transition %s→%s failed: %s", draft_id, status, exc)
            return False

    def _normalise_event(self, d: dict[str, Any]) -> dict[str, Any]:
        d["id"] = str(d["id"])
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        if isinstance(d.get("payload"), str):
            try:
                d["payload"] = json.loads(d["payload"])
            except json.JSONDecodeError:
                pass
        return d

    def _require_pool(self) -> None:
        if self._pool is None:
            raise RuntimeError(
                "DashboardServices.connect() was not called. "
                "Call `await svc.connect()` before using."
            )

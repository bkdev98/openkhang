"""Draft reply queue backed by Postgres draft_replies table.

Status lifecycle: pending → approved | rejected | edited
On approved/edited: caller is responsible for sending via MatrixSender.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

# Valid status transitions
VALID_STATUSES = {"pending", "approved", "rejected", "edited"}


class DraftQueue:
    """CRUD operations on the draft_replies Postgres table.

    Usage:
        queue = DraftQueue(database_url)
        await queue.connect()
        draft_id = await queue.add_draft(...)
        drafts = await queue.get_pending()
        await queue.approve(draft_id)
        await queue.close()
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Create connection pool. Must be called before any operation."""
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=1,
            max_size=5,
        )

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def add_draft(
        self,
        room_id: str,
        original_message: str,
        draft_text: str,
        confidence: float,
        evidence: list[str],
        room_name: str = "",
        event_id: Optional[str] = None,
    ) -> str:
        """Insert a new pending draft reply.

        Args:
            room_id: Matrix room ID.
            original_message: The incoming message text being replied to.
            draft_text: The generated reply text.
            confidence: Confidence score 0.0–1.0.
            evidence: List of evidence strings from LLM.
            room_name: Human-readable room name (optional).
            event_id: UUID of the episodic event row (optional FK).

        Returns:
            UUID string of the created draft row.
        """
        self._require_pool()
        row = await self._pool.fetchrow(  # type: ignore[union-attr]
            """
            INSERT INTO draft_replies
                (event_id, room_id, room_name, original_message, draft_text,
                 confidence, evidence, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
            RETURNING id
            """,
            UUID(event_id) if event_id else None,
            room_id,
            room_name,
            original_message,
            draft_text,
            confidence,
            json.dumps(evidence),
        )
        draft_id = str(row["id"])
        logger.debug("Draft created id=%s room=%s confidence=%.2f", draft_id, room_id, confidence)
        return draft_id

    async def get_pending(self, room_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Return pending drafts, optionally filtered by room.

        Args:
            room_id: If provided, return only drafts for this room.
            limit: Maximum rows to return.

        Returns:
            List of draft dicts with all columns.
        """
        self._require_pool()
        if room_id:
            rows = await self._pool.fetch(  # type: ignore[union-attr]
                """
                SELECT * FROM draft_replies
                WHERE status = 'pending' AND room_id = $1
                ORDER BY created_at ASC
                LIMIT $2
                """,
                room_id,
                limit,
            )
        else:
            rows = await self._pool.fetch(  # type: ignore[union-attr]
                """
                SELECT * FROM draft_replies
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    async def approve(self, draft_id: str) -> Optional[dict]:
        """Mark a draft as approved and return it.

        Returns:
            The draft dict, or None if not found / already processed.
        """
        return await self._transition(draft_id, "approved", reviewer_action="approve")

    async def reject(self, draft_id: str) -> Optional[dict]:
        """Mark a draft as rejected (discarded, not sent).

        Returns:
            The draft dict, or None if not found.
        """
        return await self._transition(draft_id, "rejected", reviewer_action="reject")

    async def edit_and_approve(self, draft_id: str, edited_text: str) -> Optional[dict]:
        """Replace draft text with edited version and mark approved.

        Args:
            draft_id: UUID of the draft to edit.
            edited_text: The corrected reply text to send.

        Returns:
            Updated draft dict, or None if not found.
        """
        self._require_pool()
        now = datetime.now(timezone.utc)
        row = await self._pool.fetchrow(  # type: ignore[union-attr]
            """
            UPDATE draft_replies
            SET status = 'edited',
                draft_text = $2,
                reviewed_at = $3,
                reviewer_action = 'edit'
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            UUID(draft_id),
            edited_text,
            now,
        )
        if row is None:
            logger.warning("edit_and_approve: draft %s not found or not pending", draft_id)
            return None
        return dict(row)

    async def get_by_id(self, draft_id: str) -> Optional[dict]:
        """Fetch a single draft by UUID."""
        self._require_pool()
        row = await self._pool.fetchrow(  # type: ignore[union-attr]
            "SELECT * FROM draft_replies WHERE id = $1",
            UUID(draft_id),
        )
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _transition(
        self, draft_id: str, new_status: str, reviewer_action: str
    ) -> Optional[dict]:
        """Generic status transition for pending drafts."""
        self._require_pool()
        now = datetime.now(timezone.utc)
        row = await self._pool.fetchrow(  # type: ignore[union-attr]
            """
            UPDATE draft_replies
            SET status = $2,
                reviewed_at = $3,
                reviewer_action = $4
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            UUID(draft_id),
            new_status,
            now,
            reviewer_action,
        )
        if row is None:
            logger.warning("transition to %s: draft %s not found or not pending", new_status, draft_id)
            return None
        logger.debug("Draft %s → %s", draft_id, new_status)
        return dict(row)

    def _require_pool(self) -> None:
        if self._pool is None:
            raise RuntimeError(
                "DraftQueue.connect() was not called. "
                "Call `await queue.connect()` before using."
            )

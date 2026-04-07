"""Episodic memory: append-only Postgres event log.

Events are immutable once written. Query by source, type, or time range.
Uses asyncpg for non-blocking I/O.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import asyncpg


class EpisodicStore:
    """Append-only event log backed by Postgres.

    The `events` table is created by schema.sql on first DB start.
    This class only performs INSERT and SELECT — never UPDATE or DELETE.
    """

    def __init__(self, database_url: str) -> None:
        self._dsn = database_url
        self._pool: Optional[asyncpg.Pool] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open connection pool. Call once before using the store."""
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=1,
            max_size=5,
            command_timeout=10,
        )

    async def close(self) -> None:
        """Close connection pool gracefully."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def add_event(
        self,
        source: str,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
        metadata: Optional[dict[str, Any]] = None,
        event_id: Optional[str] = None,
    ) -> str:
        """Append a new event. Returns the UUID of the inserted row.

        Args:
            source:     Origin system — 'chat' | 'jira' | 'gitlab' | 'confluence'
            event_type: Fine-grained type, e.g. 'message.received'
            actor:      User/bot who triggered the event
            payload:    Raw event data (stored as JSONB)
            metadata:   Optional extra fields (tags, room info, etc.)
            event_id:   Supply a deterministic UUID to enable idempotent inserts.
                        If the ID already exists the insert is skipped and the
                        existing ID is returned.
        """
        if self._pool is None:
            raise RuntimeError("EpisodicStore.connect() was not called")

        meta = metadata or {}
        payload_json = json.dumps(payload)
        meta_json = json.dumps(meta)

        async with self._pool.acquire() as conn:
            if event_id:
                # Idempotent path: skip on conflict
                row = await conn.fetchrow(
                    """
                    INSERT INTO events (id, source, event_type, actor, payload, metadata)
                    VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    RETURNING id
                    """,
                    event_id,
                    source,
                    event_type,
                    actor,
                    payload_json,
                    meta_json,
                )
                # If ON CONFLICT fired, row is None — fetch the existing id
                if row is None:
                    existing = await conn.fetchrow(
                        "SELECT id FROM events WHERE id = $1::uuid", event_id
                    )
                    return str(existing["id"])
                return str(row["id"])
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO events (source, event_type, actor, payload, metadata)
                    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                    RETURNING id
                    """,
                    source,
                    event_type,
                    actor,
                    payload_json,
                    meta_json,
                )
                return str(row["id"])

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def query_events(
        self,
        source: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query events with optional filters.

        Args:
            source:     Filter by source system (exact match)
            event_type: Filter by event type (prefix match with LIKE)
            since:      ISO-8601 timestamp; return events created after this
            limit:      Max rows to return (capped at 500)
        """
        if self._pool is None:
            raise RuntimeError("EpisodicStore.connect() was not called")

        limit = min(limit, 500)
        conditions: list[str] = []
        params: list[Any] = []

        if source:
            params.append(source)
            conditions.append(f"source = ${len(params)}")

        if event_type:
            params.append(f"{event_type}%")
            conditions.append(f"event_type LIKE ${len(params)}")

        if since:
            params.append(since)
            conditions.append(f"created_at > ${len(params)}::timestamptz")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, source, event_type, actor, payload, metadata, created_at
                FROM events
                {where}
                ORDER BY created_at DESC
                LIMIT ${len(params)}
                """,
                *params,
            )

        return [
            {
                "id": str(r["id"]),
                "source": r["source"],
                "event_type": r["event_type"],
                "actor": r["actor"],
                "payload": json.loads(r["payload"]),
                "metadata": json.loads(r["metadata"]),
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

    async def has_room_history(self, room_id: str) -> bool:
        """Check if the agent has ever sent a reply in this room. Single-row query."""
        if self._pool is None:
            raise RuntimeError("EpisodicStore.connect() was not called")
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                """
                SELECT 1 FROM events
                WHERE source = 'agent'
                  AND (metadata->>'room_id' = $1 OR payload->>'room_id' = $1)
                LIMIT 1
                """,
                room_id,
            )
            return row is not None

    async def get_thread_messages(
        self,
        thread_event_id: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Fetch messages in a specific thread (chronological order).

        Thread messages share the same thread_event_id in payload.
        The thread root message itself doesn't carry a thread_event_id,
        so it won't appear here — only replies within the thread.
        """
        if self._pool is None:
            raise RuntimeError("EpisodicStore.connect() was not called")

        limit = min(limit, 100)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload, metadata, created_at
                FROM events
                WHERE source = 'chat'
                  AND payload->>'thread_event_id' = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                thread_event_id,
                limit,
            )

        # Return in chronological order (oldest first)
        return [
            {
                "sender": json.loads(r["payload"]).get("sender", json.loads(r["payload"]).get("sender_id", "")),
                "body": json.loads(r["payload"]).get("body", ""),
                "created_at": r["created_at"].isoformat(),
            }
            for r in reversed(rows)
            if json.loads(r["payload"]).get("body", "").strip()
        ]

    async def get_room_messages(
        self,
        room_id: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Fetch recent chat messages for a specific room.

        Searches both metadata->>'room_id' and payload->>'room_id'.
        Returns messages in chronological order (oldest first).
        """
        if self._pool is None:
            raise RuntimeError("EpisodicStore.connect() was not called")

        limit = min(limit, 100)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload, metadata, created_at
                FROM events
                WHERE source = 'chat'
                  AND (metadata->>'room_id' = $1 OR payload->>'room_id' = $1)
                ORDER BY created_at DESC
                LIMIT $2
                """,
                room_id,
                limit,
            )

        # Return in chronological order (oldest first)
        return [
            {
                "sender": json.loads(r["payload"]).get("sender", json.loads(r["payload"]).get("sender_id", "")),
                "body": json.loads(r["payload"]).get("body", ""),
                "created_at": r["created_at"].isoformat(),
            }
            for r in reversed(rows)
            if json.loads(r["payload"]).get("body", "").strip()
        ]

    async def search_code(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search across indexed code chunks using ILIKE.

        Uses OR logic — any keyword match counts. Results ranked by match count.
        Also searches file paths and chunk labels in metadata.
        """
        if self._pool is None:
            raise RuntimeError("EpisodicStore.connect() was not called")

        # Split query into meaningful keywords (3+ chars), skip Vietnamese stop words
        stop_words = {"của", "cho", "trong", "với", "this", "that", "what", "whats", "the"}
        keywords = [w for w in query.lower().split() if len(w) >= 3 and w not in stop_words]
        if not keywords:
            return []

        # Build OR conditions — any keyword match counts
        # Score = number of matching keywords (computed in SQL)
        match_exprs = []
        params: list[Any] = []
        for i, kw in enumerate(keywords):
            param_idx = i + 1
            params.append(f"%{kw}%")
            match_exprs.append(
                f"(CASE WHEN payload->>'text' ILIKE ${param_idx} "
                f"OR metadata->>'file_path' ILIKE ${param_idx} "
                f"OR metadata->>'chunk_label' ILIKE ${param_idx} "
                f"THEN 1 ELSE 0 END)"
            )

        score_expr = " + ".join(match_exprs)
        # At least 1 keyword must match
        or_conditions = " OR ".join(
            f"(payload->>'text' ILIKE ${i+1} OR metadata->>'file_path' ILIKE ${i+1})"
            for i in range(len(keywords))
        )
        params.append(min(limit, 50))

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, payload, metadata, ({score_expr}) as match_score
                FROM events
                WHERE source = 'code' AND ({or_conditions})
                ORDER BY match_score DESC, created_at DESC
                LIMIT ${len(params)}
                """,
                *params,
            )

        return [
            {
                "id": str(r["id"]),
                "payload": json.loads(r["payload"]),
                "metadata": json.loads(r["metadata"]),
            }
            for r in rows
        ]

    async def count_events(
        self,
        source: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> int:
        """Return total event count, optionally filtered by source/type."""
        if self._pool is None:
            raise RuntimeError("EpisodicStore.connect() was not called")

        conditions: list[str] = []
        params: list[Any] = []

        if source:
            params.append(source)
            conditions.append(f"source = ${len(params)}")
        if event_type:
            params.append(f"{event_type}%")
            conditions.append(f"event_type LIKE ${len(params)}")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT COUNT(*) AS n FROM events {where}", *params)
        return row["n"]

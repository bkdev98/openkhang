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

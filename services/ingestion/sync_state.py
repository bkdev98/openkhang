"""Sync state tracker — persists last-synced timestamps per source in Postgres.

Table: sync_state(source VARCHAR PK, last_synced_at TIMESTAMPTZ, item_count INT)

The schema is appended to services/memory/schema.sql and created at first use
via ensure_table().
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import asyncpg


class SyncStateStore:
    """Tracks ingestion sync state per source in Postgres.

    Usage:
        store = SyncStateStore(database_url)
        await store.connect()
        last = await store.get_last_synced("jira")
        await store.update_synced("jira", datetime.now(tz=timezone.utc), count=42)
        await store.close()
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS sync_state (
            source          VARCHAR(50)  PRIMARY KEY,
            last_synced_at  TIMESTAMPTZ  DEFAULT NOW(),
            item_count      INTEGER      DEFAULT 0
        );
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Open connection pool and ensure the sync_state table exists."""
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=3)
        async with self._pool.acquire() as conn:
            await conn.execute(self._CREATE_TABLE)

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def get_last_synced(self, source: str) -> Optional[datetime]:
        """Return the last synced timestamp for a source, or None if never synced.

        Args:
            source: Source identifier (e.g. "jira", "gitlab", "confluence", "chat").

        Returns:
            Timezone-aware datetime or None.
        """
        self._require_pool()
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            row = await conn.fetchrow(
                "SELECT last_synced_at FROM sync_state WHERE source = $1",
                source,
            )
        if row is None:
            return None
        ts: datetime = row["last_synced_at"]
        # asyncpg returns timezone-aware datetimes from TIMESTAMPTZ
        return ts

    async def update_synced(
        self,
        source: str,
        timestamp: datetime,
        count: int = 0,
    ) -> None:
        """Upsert the sync state for a source.

        Args:
            source:    Source identifier.
            timestamp: The timestamp to record as last_synced_at.
            count:     Number of items ingested in this run (added to total).
        """
        self._require_pool()
        # Ensure timestamp is timezone-aware
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            await conn.execute(
                """
                INSERT INTO sync_state (source, last_synced_at, item_count)
                VALUES ($1, $2, $3)
                ON CONFLICT (source) DO UPDATE
                    SET last_synced_at = EXCLUDED.last_synced_at,
                        item_count     = sync_state.item_count + EXCLUDED.item_count
                """,
                source,
                timestamp,
                count,
            )

    async def get_all(self) -> list[dict]:
        """Return all sync state rows as a list of dicts."""
        self._require_pool()
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            rows = await conn.fetch("SELECT source, last_synced_at, item_count FROM sync_state")
        return [dict(r) for r in rows]

    def _require_pool(self) -> None:
        if self._pool is None:
            raise RuntimeError(
                "SyncStateStore.connect() was not called. "
                "Call `await store.connect()` before using."
            )

"""Asyncio-based ingestion scheduler.

Runs each ingestor on a configurable interval as background tasks.
Chat is driven by Redis pub/sub (realtime); others poll on a timer.

Usage:
    scheduler = IngestionScheduler(memory_client, sync_store)
    await scheduler.start()
    # ... runs indefinitely until cancelled
    await scheduler.stop()
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.memory.client import MemoryClient
    from .sync_state import SyncStateStore

# Default poll intervals in seconds
_DEFAULT_INTERVALS: dict[str, int] = {
    "jira": 5 * 60,        # 5 minutes
    "gitlab": 5 * 60,      # 5 minutes
    "confluence": 60 * 60, # 1 hour
    "chat": 0,             # realtime via Redis — no polling
}


class IngestionScheduler:
    """Runs ingestors on configurable intervals as asyncio background tasks.

    Each source runs in its own task loop. Errors in one source do not
    affect others. Sync state is persisted so restarts resume from the
    last successful sync point.

    Args:
        memory_client: Connected MemoryClient instance.
        sync_store:    Connected SyncStateStore instance.
        intervals:     Override default poll intervals (seconds per source).
        redis_url:     Redis URL for chat realtime listener (optional).
    """

    def __init__(
        self,
        memory_client: "MemoryClient",
        sync_store: "SyncStateStore",
        intervals: dict[str, int] | None = None,
        redis_url: str | None = None,
    ) -> None:
        self._memory = memory_client
        self._sync = sync_store
        self._intervals = {**_DEFAULT_INTERVALS, **(intervals or {})}
        self._redis_url = redis_url or os.getenv("OPENKHANG_REDIS_URL", "redis://localhost:6379")
        self._tasks: list[asyncio.Task] = []  # type: ignore[type-arg]
        self._running = False

    async def start(self) -> None:
        """Start all background ingestion tasks."""
        if self._running:
            return
        self._running = True

        # Lazy imports to avoid circular deps at module load
        from .jira import JiraIngestor
        from .gitlab import GitLabIngestor
        from .confluence import ConfluenceIngestor
        from .chat import ChatIngestor

        ingestors: dict[str, Any] = {
            "jira": JiraIngestor(self._memory),
            "gitlab": GitLabIngestor(self._memory),
            "confluence": ConfluenceIngestor(self._memory),
            "chat": ChatIngestor(self._memory),
        }

        for source, ingestor in ingestors.items():
            interval = self._intervals.get(source, 300)
            if source == "chat":
                # Chat is driven by Redis events, not polling
                task = asyncio.create_task(
                    self._redis_chat_listener(ingestor),
                    name=f"ingest-chat-realtime",
                )
            else:
                task = asyncio.create_task(
                    self._poll_loop(source, ingestor, interval),
                    name=f"ingest-{source}",
                )
            self._tasks.append(task)

        print(f"[scheduler] started {len(self._tasks)} ingestion tasks")

    async def stop(self) -> None:
        """Cancel all background tasks and wait for them to finish."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        print("[scheduler] all ingestion tasks stopped")

    async def run_once(self, source: str) -> None:
        """Manually trigger a single ingestion run for a source.

        Useful for testing or manual backfills.

        Args:
            source: One of "jira", "gitlab", "confluence", "chat".
        """
        from .jira import JiraIngestor
        from .gitlab import GitLabIngestor
        from .confluence import ConfluenceIngestor
        from .chat import ChatIngestor

        ingestor_map = {
            "jira": JiraIngestor,
            "gitlab": GitLabIngestor,
            "confluence": ConfluenceIngestor,
            "chat": ChatIngestor,
        }
        cls = ingestor_map.get(source)
        if not cls:
            print(f"[scheduler] unknown source: {source}")
            return

        ingestor = cls(self._memory)
        since = await self._sync.get_last_synced(source)
        result = await ingestor.ingest(since=since)
        print(f"[scheduler] {result}")
        await self._sync.update_synced(
            source, datetime.now(tz=timezone.utc), count=result.ingested
        )

    # ------------------------------------------------------------------
    # Internal task loops
    # ------------------------------------------------------------------

    async def _poll_loop(self, source: str, ingestor: Any, interval: int) -> None:
        """Poll a source on a fixed interval.

        Args:
            source:   Source identifier for sync state lookup.
            ingestor: Connected ingestor instance.
            interval: Seconds between runs.
        """
        print(f"[scheduler] {source} poll loop started (interval={interval}s)")
        while self._running:
            try:
                since = await self._sync.get_last_synced(source)
                result = await ingestor.ingest(since=since)
                print(f"[scheduler] {result}")
                if result.ingested > 0 or result.total > 0:
                    await self._sync.update_synced(
                        source,
                        datetime.now(tz=timezone.utc),
                        count=result.ingested,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[scheduler] {source} poll error: {exc}")

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

        print(f"[scheduler] {source} poll loop stopped")

    async def _redis_chat_listener(self, chat_ingestor: Any) -> None:
        """Subscribe to Redis openkhang:events and trigger chat ingest on new messages.

        Falls back gracefully if Redis is unavailable — logs a warning and
        switches to a 60-second polling interval as backup.
        """
        try:
            import redis.asyncio as aioredis  # type: ignore[import]
        except ImportError:
            print("[scheduler] redis package not available — falling back to chat polling")
            await self._poll_loop("chat", chat_ingestor, interval=60)
            return

        print("[scheduler] chat realtime listener starting (Redis pub/sub)")
        backoff = 5

        while self._running:
            try:
                client = aioredis.from_url(self._redis_url, decode_responses=True)
                pubsub = client.pubsub()
                await pubsub.subscribe("openkhang:events")
                print("[scheduler] subscribed to openkhang:events")
                backoff = 5  # reset on successful connect

                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message.get("type") != "message":
                        continue

                    try:
                        import json
                        payload = json.loads(message.get("data", "{}"))
                        if payload.get("type") == "chat_message":
                            # Trigger a fresh chat ingest (reads from inbox file)
                            since = await self._sync.get_last_synced("chat")
                            result = await chat_ingestor.ingest(since=since)
                            if result.ingested > 0:
                                await self._sync.update_synced(
                                    "chat",
                                    datetime.now(tz=timezone.utc),
                                    count=result.ingested,
                                )
                    except Exception as exc:
                        print(f"[scheduler] chat event processing error: {exc}")

                await pubsub.unsubscribe("openkhang:events")
                await client.aclose()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[scheduler] Redis connection error: {exc} — retrying in {backoff}s")
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    break
                backoff = min(backoff * 2, 120)

        print("[scheduler] chat realtime listener stopped")

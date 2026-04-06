"""Unified memory client: Mem0 semantic layer + episodic event log.

Usage:
    config = MemoryConfig.from_env()
    client = MemoryClient(config)
    await client.connect()

    mem_id = await client.add_memory("Khanh prefers async code", {"source": "chat"})
    results = await client.search("code style preferences")
    await client.close()
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from mem0 import Memory

from .config import MemoryConfig
from .episodic import EpisodicStore
from .working import WorkingMemory


class MemoryClient:
    """Unified memory client wrapping Mem0 + episodic store.

    Three layers:
    - Semantic: Mem0 with pgvector backend + bge-m3 embeddings (OpenRouter API)
    - Episodic: Postgres append-only event log (raw events, immutable)
    - Working:  In-memory session context with 30-min TTL expiry

    Mem0 operations are synchronous (Mem0 library is sync); they are
    run in a thread-pool executor so callers can await them without
    blocking the event loop.
    """

    def __init__(self, config: MemoryConfig) -> None:
        self._config = config
        self._mem0: Optional[Memory] = None
        self._episodic = EpisodicStore(config.database_url)
        self._working = WorkingMemory()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Initialise all backends. Must be called before any other method."""
        # Mem0 init is blocking — offload to thread pool
        loop = asyncio.get_running_loop()
        mem0_config = self._config.as_mem0_config()
        self._mem0 = await loop.run_in_executor(
            None, lambda: Memory.from_config(mem0_config)
        )
        await self._episodic.connect()

    async def close(self) -> None:
        """Flush working memory and close all connections."""
        self._working.purge_expired()
        await self._episodic.close()

    # ------------------------------------------------------------------
    # Semantic memory (Mem0)
    # ------------------------------------------------------------------

    async def add_memory(
        self,
        content: str,
        metadata: dict[str, Any],
        agent_id: str = "default",
    ) -> str:
        """Add a text fact to Mem0 semantic memory.

        Args:
            content:  Natural-language text to remember.
            metadata: Arbitrary key-value tags stored alongside the memory.
            agent_id: Scoping key — use 'outward' / 'inward' / 'default'.

        Returns:
            Mem0 memory ID string.
        """
        self._require_mem0()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._mem0.add(  # type: ignore[union-attr]
                content,
                agent_id=agent_id,
                metadata=metadata,
            ),
        )
        # Mem0 v1.1 returns {"results": [{"id": ...}]}
        try:
            return result["results"][0]["id"]
        except (KeyError, IndexError, TypeError):
            return str(result)

    async def search(
        self,
        query: str,
        agent_id: str = "default",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic search across memories for this agent.

        Returns a list of dicts with keys: id, memory, score, metadata.
        """
        self._require_mem0()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._mem0.search(  # type: ignore[union-attr]
                query,
                agent_id=agent_id,
                limit=limit,
            ),
        )
        # Normalise across Mem0 response shapes
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        if isinstance(result, list):
            return result
        return []

    async def get_related(
        self,
        entity: str,
        agent_id: str = "default",
    ) -> list[dict[str, Any]]:
        """Return memories related to a named entity.

        Falls back to a semantic search when graph mode is not enabled,
        so callers don't need to know whether graph is configured.
        """
        self._require_mem0()
        loop = asyncio.get_running_loop()

        # Try graph traversal first (available when graph store is configured)
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._mem0.get_all(  # type: ignore[union-attr]
                    agent_id=agent_id,
                    filters={"entity": entity},
                ),
            )
            if result:
                return result if isinstance(result, list) else result.get("results", [])
        except Exception:
            pass  # Graph not configured or query failed — fall through to search

        return await self.search(entity, agent_id=agent_id)

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by its Mem0 ID. Returns True on success."""
        self._require_mem0()
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self._mem0.delete(memory_id),  # type: ignore[union-attr]
            )
            return True
        except Exception:
            return False

    async def get_all_memories(
        self,
        agent_id: str = "default",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve all memories for an agent (unfiltered)."""
        self._require_mem0()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._mem0.get_all(agent_id=agent_id),  # type: ignore[union-attr]
        )
        items = result if isinstance(result, list) else result.get("results", [])
        return items[:limit]

    # ------------------------------------------------------------------
    # Episodic store
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
        """Append a raw event to the episodic log. Idempotent when event_id supplied."""
        return await self._episodic.add_event(
            source=source,
            event_type=event_type,
            actor=actor,
            payload=payload,
            metadata=metadata,
            event_id=event_id,
        )

    async def query_events(
        self,
        source: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query episodic events with optional filters.

        Args:
            source:     Exact source system match ('chat', 'jira', etc.)
            event_type: Prefix match (e.g. 'message' matches 'message.received')
            since:      ISO-8601 timestamp string — return events after this time
            limit:      Max rows (hard-capped at 500 in EpisodicStore)
        """
        return await self._episodic.query_events(
            source=source,
            event_type=event_type,
            since=since,
            limit=limit,
        )

    async def get_room_messages(
        self,
        room_id: str,
        limit: int = 30,
    ) -> list[dict]:
        """Fetch recent chat messages for a room (chronological order)."""
        return await self._episodic.get_room_messages(room_id, limit=limit)

    async def search_code(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across indexed code chunks."""
        return await self._episodic.search_code(query, limit=limit)

    # ------------------------------------------------------------------
    # Working memory
    # ------------------------------------------------------------------

    def set_context(self, session_id: str, key: str, value: Any) -> None:
        """Set a value in the active session context."""
        self._working.set_context(session_id, key, value)

    def get_context(self, session_id: str, key: Optional[str] = None) -> Any:
        """Get a value (or full context dict) from the active session."""
        return self._working.get_context(session_id, key)

    def clear_session(self, session_id: str) -> None:
        """Discard all context for a session."""
        self._working.clear_session(session_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_mem0(self) -> None:
        if self._mem0 is None:
            raise RuntimeError(
                "MemoryClient.connect() was not called. "
                "Call `await client.connect()` before using semantic memory."
            )

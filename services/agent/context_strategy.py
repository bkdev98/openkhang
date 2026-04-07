"""Centralized context strategy — pre-fetches the right data per intent in parallel.

Replaces ad-hoc context gathering scattered across OutwardReplySkill and InwardQuerySkill.
Each intent maps to a set of fetch keys; all fetches run via asyncio.gather.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Declarative: which context to fetch per intent
CONTEXT_STRATEGIES: dict[str, list[str]] = {
    "social":      [],
    "fyi":         ["sender"],
    "question":    ["rag", "code", "sender", "room"],
    "request":     ["rag", "sender", "room", "thread"],
    "instruction": ["rag", "sender"],
    "query":       ["rag", "code"],
}

# Default strategy for unknown intents
DEFAULT_STRATEGY = ["rag", "sender"]

RAG_LIMIT = 10
CODE_LIMIT = 20
SENDER_LIMIT = 5
ROOM_MSG_LIMIT = 30


@dataclass
class ContextBundle:
    """Pre-fetched context for a single event processing cycle."""
    memories: list[dict] = field(default_factory=list)
    code_results: list[dict] = field(default_factory=list)
    sender_context: list[dict] = field(default_factory=list)
    room_messages: list[dict] = field(default_factory=list)
    thread_messages: list[dict] = field(default_factory=list)


class ContextStrategy:
    """Resolves context requirements per intent and fetches in parallel."""

    def __init__(self, memory_client: Any) -> None:
        self._memory = memory_client

    async def resolve(self, intent: str, mode: str, event: dict) -> ContextBundle:
        """Fetch all required context for this intent in parallel.

        Args:
            intent: Classified intent (question, request, fyi, social, etc.)
            mode: 'outward' or 'inward'
            event: Legacy event dict with body, sender_id, room_id, thread_event_id, etc.

        Returns:
            ContextBundle with all pre-fetched data.
        """
        strategy = CONTEXT_STRATEGIES.get(intent, DEFAULT_STRATEGY)
        if not strategy:
            return ContextBundle()  # social: no context needed

        bundle = ContextBundle()
        body = event.get("body", "").strip()
        sender_id = event.get("sender_id", "")
        room_id = event.get("room_id", "")
        thread_event_id = event.get("thread_event_id", "")
        agent_id = "outward" if mode == "outward" else "inward"

        # Build list of async fetchers
        fetchers = []
        fetch_keys = []

        if "rag" in strategy and body:
            fetchers.append(self._fetch_rag(body, agent_id, mode, intent))
            fetch_keys.append("rag")

        if "code" in strategy and body:
            fetchers.append(self._fetch_code(body))
            fetch_keys.append("code")

        if "sender" in strategy and sender_id:
            fetchers.append(self._fetch_sender(sender_id, agent_id))
            fetch_keys.append("sender")

        if "room" in strategy and room_id:
            fetchers.append(self._fetch_room(room_id, thread_event_id))
            fetch_keys.append("room")

        if "thread" in strategy and thread_event_id:
            fetchers.append(self._fetch_thread(thread_event_id))
            fetch_keys.append("thread")

        if not fetchers:
            return bundle

        # Parallel fetch — partial failures are OK
        results = await asyncio.gather(*fetchers, return_exceptions=True)

        for key, result in zip(fetch_keys, results):
            if isinstance(result, Exception):
                logger.warning("Context fetch '%s' failed: %s", key, result)
                continue
            if key == "rag":
                bundle.memories = result or []
            elif key == "code":
                bundle.code_results = result or []
            elif key == "sender":
                bundle.sender_context = result or []
            elif key == "room":
                bundle.room_messages = result or []
            elif key == "thread":
                bundle.thread_messages = result or []

        return bundle

    # --- Individual fetchers ---

    async def _fetch_rag(self, body: str, agent_id: str, mode: str, intent: str) -> list[dict]:
        """Fetch RAG memories. For outward questions/requests, also search inward agent."""
        memories = await self._memory.search(body, agent_id=agent_id, limit=RAG_LIMIT)
        # Cross-agent augmentation for work questions in outward mode
        if mode == "outward" and intent in ("question", "request"):
            seen_ids = {m.get("id") for m in memories}
            for m in await self._memory.search(body, agent_id="inward", limit=5):
                if m.get("id") not in seen_ids:
                    memories.append(m)
        return memories

    async def _fetch_code(self, body: str) -> list[dict]:
        """Fetch code search results."""
        from .skills.skill_helpers import extract_code_search_terms
        results = await self._memory.search_code(extract_code_search_terms(body), limit=CODE_LIMIT)
        formatted = []
        for cr in results:
            meta = cr.get("metadata", {})
            score = 0.8 if meta.get("doc_type") in ("business-logic", "api-spec") else 0.5
            formatted.append({
                "memory": cr["payload"].get("text", "")[:500],
                "score": score,
                "metadata": meta,
            })
        return formatted

    async def _fetch_sender(self, sender_id: str, agent_id: str) -> list[dict]:
        """Fetch sender context (prior interactions)."""
        return (await self._memory.get_related(sender_id, agent_id=agent_id))[:SENDER_LIMIT]

    async def _fetch_room(self, room_id: str, thread_event_id: str) -> list[dict]:
        """Fetch room-level messages only. Thread messages are handled by _fetch_thread."""
        try:
            return await self._memory.get_room_messages(room_id, limit=ROOM_MSG_LIMIT)
        except Exception:
            return []

    async def _fetch_thread(self, thread_event_id: str) -> list[dict]:
        """Fetch thread-specific messages."""
        try:
            return await self._memory.get_thread_messages(thread_event_id, limit=ROOM_MSG_LIMIT)
        except Exception:
            return []

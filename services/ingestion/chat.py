"""Chat thread ingestor — reads gchat-inbox.jsonl and ingests by thread.

Groups Matrix messages by thread_event_id (or room_id when no thread),
stores each thread as one semantic memory chunk, and logs each raw
message to the episodic event store.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import BaseIngestor, Chunk, Document, IngestResult
from .chunker import chunk_by_thread
from .entity import extract_and_store_entities

if TYPE_CHECKING:
    from services.memory.client import MemoryClient

# Default inbox location (relative to project root)
DEFAULT_INBOX = Path(".claude/gchat-inbox.jsonl")


class ChatIngestor(BaseIngestor):
    """Ingest chat messages from gchat-inbox.jsonl grouped into threads.

    Each thread becomes one Document (and one Chunk). Individual messages
    are also written to the episodic event log for time-range queries.
    """

    def __init__(
        self,
        memory_client: "MemoryClient",
        inbox_path: Path | None = None,
    ) -> None:
        super().__init__(memory_client)
        self._inbox = inbox_path or DEFAULT_INBOX

    async def fetch_new(self, since: datetime | None = None) -> list[Document]:
        """Read JSONL inbox and group messages into thread Documents.

        Args:
            since: Only include messages with timestamp > since (Unix ms compared).
                   When None, all messages in the file are returned.

        Returns:
            One Document per thread (or room when no thread ID exists).
        """
        if not self._inbox.exists():
            print(f"[chat] inbox not found: {self._inbox}")
            return []

        since_ms = int(since.timestamp() * 1000) if since else None

        # Group messages by thread_event_id, falling back to room_id
        threads: dict[str, list[dict[str, Any]]] = defaultdict(list)
        thread_meta: dict[str, dict[str, Any]] = {}

        with self._inbox.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                ts = msg.get("timestamp", 0)
                if since_ms and ts <= since_ms:
                    continue

                thread_id = msg.get("thread_event_id") or msg.get("room_id", "unknown")
                threads[thread_id].append(msg)

                # Capture thread-level metadata from first message
                if thread_id not in thread_meta:
                    thread_meta[thread_id] = {
                        "room_id": msg.get("room_id", ""),
                        "room_name": msg.get("room_name", ""),
                        "thread_event_id": msg.get("thread_event_id", ""),
                    }

        docs: list[Document] = []
        for thread_id, messages in threads.items():
            if not messages:
                continue

            meta = thread_meta.get(thread_id, {})
            participants = list({m.get("sender_id", "") for m in messages if m.get("sender_id")})
            timestamps = [m.get("time", "") for m in messages if m.get("time")]

            doc_meta: dict[str, Any] = {
                "room_id": meta.get("room_id", ""),
                "room_name": meta.get("room_name", ""),
                "participants": sorted(participants),
                "message_count": len(messages),
            }
            if timestamps:
                doc_meta["timestamp_start"] = min(timestamps)
                doc_meta["timestamp_end"] = max(timestamps)

            # Build content as a readable transcript
            lines = [
                f"{m.get('sender_id', 'unknown')}: {m.get('body', '').strip()}"
                for m in messages
                if m.get("body", "").strip()
            ]
            content = "\n".join(lines)
            if not content:
                continue

            room_name = meta.get("room_name") or meta.get("room_id", "unknown room")
            docs.append(
                Document(
                    source="chat",
                    doc_id=thread_id,
                    title=f"Thread in {room_name}",
                    content=content,
                    metadata=doc_meta,
                )
            )

        return docs

    def chunk(self, doc: Document) -> list[Chunk]:
        """Return the entire thread as one chunk with participant metadata."""
        if not doc.content.strip():
            return []
        # Re-parse content lines back into message-like dicts for chunk_by_thread
        lines = doc.content.splitlines()
        messages = []
        for line in lines:
            if ": " in line:
                sender, _, body = line.partition(": ")
                messages.append({"sender_id": sender.strip(), "body": body.strip()})

        chunks = chunk_by_thread(messages)
        # Attach document-level metadata
        for c in chunks:
            c.metadata.update({
                "room_id": doc.metadata.get("room_id", ""),
                "room_name": doc.metadata.get("room_name", ""),
                "participants": doc.metadata.get("participants", []),
                "timestamp_start": doc.metadata.get("timestamp_start", ""),
                "timestamp_end": doc.metadata.get("timestamp_end", ""),
            })
        return chunks

    async def ingest(self, since: datetime | None = None) -> IngestResult:
        """Full ingest: semantic memory + episodic log + entity extraction."""
        result = IngestResult(source="chat", total=0, ingested=0, skipped=0, errors=0)

        if not self._inbox.exists():
            print(f"[chat] inbox not found: {self._inbox}")
            return result

        since_ms = int(since.timestamp() * 1000) if since else None

        # Collect raw messages for episodic log
        raw_messages: list[dict[str, Any]] = []
        with self._inbox.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ts = msg.get("timestamp", 0)
                if since_ms and ts <= since_ms:
                    continue
                raw_messages.append(msg)

        result.total = len(raw_messages)

        # Write each message to episodic log
        for msg in raw_messages:
            raw_eid = msg.get("event_id", "")
            pg_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, raw_eid)) if raw_eid else None
            try:
                await self.memory.add_event(
                    source="chat",
                    event_type="message.received",
                    actor=msg.get("sender", "unknown"),
                    payload=msg,
                    metadata={
                        "room_id": msg.get("room_id", ""),
                        "room_name": msg.get("room_name", ""),
                        "timestamp": msg.get("timestamp"),
                        "matrix_event_id": raw_eid,
                    },
                    event_id=pg_uuid,
                )
            except Exception as exc:
                print(f"[chat] episodic log error for event {raw_eid}: {exc}")

        # Group into threads and ingest as semantic chunks
        try:
            docs = await self.fetch_new(since=since)
        except Exception as exc:
            print(f"[chat] fetch_new failed: {exc}")
            result.errors += 1
            return result

        for doc in docs:
            try:
                chunks = self.chunk(doc)
                if not chunks:
                    result.skipped += 1
                    continue

                for chunk in chunks:
                    meta: dict[str, Any] = {
                        "source": "chat",
                        "doc_id": doc.doc_id,
                        "title": doc.title,
                        **chunk.metadata,
                    }
                    await self.memory.add_memory(
                        content=chunk.text,
                        metadata=meta,
                        agent_id="inward",
                    )
                    # Extract person entities from participants
                    await extract_and_store_entities(
                        self.memory,
                        text=chunk.text,
                        metadata=chunk.metadata,
                        context_label=doc.title,
                    )

                result.ingested += 1
            except Exception as exc:
                print(f"[chat] error on thread {doc.doc_id}: {exc}")
                result.errors += 1

        return result

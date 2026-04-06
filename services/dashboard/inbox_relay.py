"""Tail gchat-inbox.jsonl and relay new messages to the events table.

Runs as an asyncio background task inside the dashboard process.
Watches the JSONL file for new lines and inserts them into Postgres,
making them immediately visible in the SSE activity feed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

# Derive deterministic UUID from Matrix event_id for idempotency
def _event_uuid(event_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, event_id))


async def tail_inbox(pool: asyncpg.Pool, inbox_path: str | None = None) -> None:
    """Continuously tail the inbox JSONL and insert new events into Postgres.

    Seeks to end of file on startup so only NEW messages are relayed.
    Polls every 1 second for new lines.
    """
    path = Path(inbox_path or os.getenv("INBOX_PATH", ".claude/gchat-inbox.jsonl"))
    if not path.exists():
        logger.warning("inbox_relay: %s not found, waiting for it...", path)
        while not path.exists():
            await asyncio.sleep(10)

    logger.info("inbox_relay: tailing %s", path)

    with open(path, "r", encoding="utf-8") as fh:
        # Seek to end — only process new lines
        fh.seek(0, 2)

        while True:
            line = fh.readline()
            if not line:
                await asyncio.sleep(1)
                continue

            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_id = msg.get("event_id", "")
            body = msg.get("body", "")
            if not body:
                continue

            pg_uuid = _event_uuid(event_id) if event_id else str(uuid.uuid4())

            try:
                await pool.execute(
                    """
                    INSERT INTO events (id, source, event_type, actor, payload, metadata)
                    VALUES ($1::uuid, 'chat', 'message.received', $2, $3::jsonb, $4::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    pg_uuid,
                    msg.get("sender", "unknown"),
                    json.dumps(msg),
                    json.dumps({
                        "room_id": msg.get("room_id", ""),
                        "room_name": msg.get("room_name", ""),
                        "matrix_event_id": event_id,
                    }),
                )
            except Exception as exc:
                logger.warning("inbox_relay: insert failed: %s", exc)

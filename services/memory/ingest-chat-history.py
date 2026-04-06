#!/usr/bin/env python3
"""One-shot script: ingest .claude/gchat-inbox.jsonl into episodic + semantic memory.

Usage:
    python3 services/memory/ingest-chat-history.py [--dry-run] [--limit N]

Options:
    --dry-run   Parse and validate lines without writing to DB
    --limit N   Stop after N messages (useful for testing)

The script is idempotent: each line's Matrix event_id is used as the
Postgres event UUID, so re-running skips already-ingested rows.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

from services.memory.client import MemoryClient
from services.memory.config import MemoryConfig

# Path relative to project root
INBOX_PATH = Path(".claude/gchat-inbox.jsonl")
BATCH_SIZE = 100


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest gchat-inbox.jsonl into memory")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, no writes")
    parser.add_argument("--limit", type=int, default=0, help="Max messages (0 = all)")
    parser.add_argument(
        "--inbox",
        type=Path,
        default=INBOX_PATH,
        help=f"Path to jsonl file (default: {INBOX_PATH})",
    )
    return parser.parse_args()


def _read_lines(path: Path, limit: int) -> list[dict]:
    """Read and parse JSONL file. Skips malformed lines with a warning."""
    lines: list[dict] = []
    skipped = 0
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                print(f"  [WARN] line {lineno}: skipping malformed JSON — {exc}", file=sys.stderr)
                skipped += 1
            if limit and len(lines) >= limit:
                break
    if skipped:
        print(f"  [WARN] {skipped} malformed lines skipped")
    return lines


def _extract_fields(record: dict) -> dict:
    """Normalise a gchat-inbox.jsonl record into flat fields for storage.

    The JSONL format (from matrix-listener.py parse_message) has top-level
    fields: body, sender, sender_id, room_id, room_name, event_id, timestamp, time.
    """
    body = record.get("body", "")
    sender = record.get("sender", record.get("sender_id", "unknown"))
    room_id = record.get("room_id", "")
    room_name = record.get("room_name", "")
    event_id = record.get("event_id", "")
    timestamp = record.get("timestamp")  # unix ms

    return {
        "event_id": event_id,
        "sender": sender,
        "room_id": room_id,
        "room_name": room_name,
        "body": body,
        "timestamp": timestamp,
        "raw": record,
    }


async def ingest(args: argparse.Namespace) -> None:
    inbox: Path = args.inbox
    if not inbox.exists():
        print(f"[ERROR] Inbox file not found: {inbox}", file=sys.stderr)
        sys.exit(1)

    records = _read_lines(inbox, args.limit)
    total = len(records)
    print(f"Loaded {total} records from {inbox}")

    if args.dry_run:
        print("[dry-run] Validation passed. No writes performed.")
        return

    config = MemoryConfig.from_env()
    client = MemoryClient(config)
    await client.connect()

    ingested = 0
    skipped = 0
    errors = 0

    try:
        for i, record in enumerate(records):
            fields = _extract_fields(record)
            body = fields["body"].strip()

            # Skip system/empty messages
            if not body:
                skipped += 1
                continue

            try:
                # --- Episodic layer ---
                # Matrix event_ids (like $abc123:localhost) aren't UUIDs,
                # so we derive a deterministic UUID via uuid5 for idempotency.
                raw_eid = fields["event_id"]
                pg_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, raw_eid)) if raw_eid else None

                await client.add_event(
                    source="chat",
                    event_type="message.received",
                    actor=fields["sender"],
                    payload=fields["raw"],
                    metadata={
                        "room_id": fields["room_id"],
                        "room_name": fields["room_name"],
                        "timestamp": fields["timestamp"],
                        "matrix_event_id": raw_eid,
                    },
                    event_id=pg_uuid,
                )

                # --- Semantic layer ---
                await client.add_memory(
                    content=body,
                    metadata={
                        "source": "chat",
                        "sender": fields["sender"],
                        "room_id": fields["room_id"],
                        "event_id": fields["event_id"],
                    },
                    agent_id="inward",
                )

                ingested += 1

            except Exception as exc:
                errors += 1
                print(f"  [ERROR] record {i}: {exc}", file=sys.stderr)

            # Progress report every BATCH_SIZE messages
            if (i + 1) % BATCH_SIZE == 0:
                print(f"  Progress: {i + 1}/{total}  ingested={ingested}  skipped={skipped}  errors={errors}")

    finally:
        await client.close()

    print(
        f"\nDone. total={total}  ingested={ingested}  skipped={skipped}  errors={errors}"
    )


def main() -> None:
    args = _parse_args()
    asyncio.run(ingest(args))


if __name__ == "__main__":
    main()

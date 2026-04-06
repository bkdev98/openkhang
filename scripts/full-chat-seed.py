#!/usr/bin/env python3
"""Full chat history seed — paginate ALL messages from ALL rooms.

Fetches both Khanh's own messages (style examples) AND others' messages
(conversation context), storing everything in semantic memory with
per-person addressing patterns.

Usage:
    services/.venv/bin/python3 scripts/full-chat-seed.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from services.memory.config import MemoryConfig
from services.memory.client import MemoryClient


def matrix_api(method: str, path: str, hs: str, token: str, timeout: int = 15) -> dict:
    url = f"{hs}/_matrix/client/v3{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_all_room_messages(hs: str, token: str, room_id: str, max_pages: int = 20) -> list[dict]:
    """Paginate through all messages in a room (newest first)."""
    enc = urllib.parse.quote(room_id)
    all_events = []
    from_token = ""

    for page in range(max_pages):
        url = f"/rooms/{enc}/messages?dir=b&limit=100"
        if from_token:
            url += f"&from={urllib.parse.quote(from_token)}"

        try:
            resp = matrix_api("GET", url, hs=hs, token=token)
        except Exception as e:
            print(f"    [WARN] Page {page} failed: {e}")
            break

        chunk = resp.get("chunk", [])
        if not chunk:
            break

        for event in chunk:
            if event.get("type") == "m.room.message":
                all_events.append(event)

        from_token = resp.get("end", "")
        if not from_token or len(chunk) < 100:
            break  # no more pages

    return all_events


def get_room_name(hs: str, token: str, room_id: str) -> str:
    enc = urllib.parse.quote(room_id)
    try:
        resp = matrix_api("GET", f"/rooms/{enc}/state/m.room.name", hs=hs, token=token)
        return resp.get("name", "")
    except Exception:
        return ""


def extract_addressing_patterns(own_messages: list[dict]) -> dict[str, list[str]]:
    """Analyze how Khanh addresses different people.

    Returns: {person_id: [addressing_terms_used]}
    E.g. {"TRẦN ĐÌNH CHƯƠNG": ["anh", "a"], "NGUYỄN TẤN KHANG": ["Khang"]}
    """
    import re
    patterns = defaultdict(list)

    for msg in own_messages:
        body = msg.get("content", {}).get("body", "")
        # Look for @mentions with titles
        mentions = re.findall(r"@([^-\n]+?)(?:\s*-\s*ITC)", body)
        for name in mentions:
            name = name.strip()
            # Check what comes before the @mention
            idx = body.find(f"@{name}")
            if idx > 0:
                prefix = body[:idx].strip().split()[-1] if body[:idx].strip() else ""
                if prefix.lower() in ("anh", "chị", "chi", "a", "c", "em", "bạn", "bro"):
                    patterns[name].append(prefix.lower())

        # Also check for standalone addressing at start of message
        first_word = body.split()[0].lower() if body.split() else ""
        if first_word in ("anh", "chị", "chi", "em", "dạ", "bạn"):
            patterns["_default_tone"].append(first_word)

    return dict(patterns)


async def main():
    hs = os.getenv("MATRIX_HOMESERVER", "http://localhost:8008")
    token = os.getenv("MATRIX_ACCESS_TOKEN", "")

    # Find own puppet prefix
    own_prefix = ""
    state_file = Path(".claude/gchat-autopilot.local.md")
    if state_file.exists():
        for line in state_file.read_text().splitlines():
            if line.startswith("sender_id:"):
                uid = line.split(":", 1)[1].strip().strip('"').replace("users/", "")
                own_prefix = f"@googlechat_{uid}:"
                break
    if not own_prefix:
        own_prefix = "@googlechat_"

    config = MemoryConfig.from_env()
    client = MemoryClient(config)
    await client.connect()

    # Get all rooms
    rooms_resp = matrix_api("GET", "/joined_rooms", hs=hs, token=token)
    room_ids = rooms_resp.get("joined_rooms", [])

    print(f"Scanning {len(room_ids)} rooms for full history...\n")

    all_own_messages = []
    all_conversations = []  # (room_name, sender, body) tuples for context
    addressing = defaultdict(list)

    for i, rid in enumerate(room_ids):
        rname = get_room_name(hs, token, rid)
        label = rname or rid[:30]
        print(f"[{i+1}/{len(room_ids)}] {label}...", end=" ", flush=True)

        events = fetch_all_room_messages(hs, token, rid)
        print(f"{len(events)} messages")

        own_in_room = 0
        for event in events:
            sender = event.get("sender", "")
            body = event.get("content", {}).get("body", "")
            if not body or len(body) < 2:
                continue

            is_own = sender.startswith(own_prefix)

            if is_own:
                all_own_messages.append({
                    "body": body,
                    "room_id": rid,
                    "room_name": rname,
                    "sender": sender,
                    "timestamp": event.get("origin_server_ts", 0),
                    "event_id": event.get("event_id", ""),
                    "raw_content": event.get("content", {}),
                })
                own_in_room += 1

            # Store conversation pairs for context
            all_conversations.append({
                "room_name": rname,
                "sender": sender,
                "body": body,
                "is_own": is_own,
                "timestamp": event.get("origin_server_ts", 0),
            })

        if own_in_room:
            print(f"    → {own_in_room} of your messages")

    # ── Save style examples ──
    print(f"\n{'='*50}")
    print(f"Your sent messages: {len(all_own_messages)}")

    style_path = Path("config/style_examples.jsonl")
    with open(style_path, "w") as f:
        for msg in all_own_messages:
            f.write(json.dumps({
                "body": msg["body"],
                "room_name": msg["room_name"],
                "room_id": msg["room_id"],
            }, ensure_ascii=False) + "\n")
    print(f"Style examples saved to {style_path}")

    # ── Extract addressing patterns ──
    addr = extract_addressing_patterns(all_own_messages)
    if addr:
        addr_path = Path("config/addressing_patterns.json")
        with open(addr_path, "w") as f:
            json.dump(addr, f, ensure_ascii=False, indent=2)
        print(f"Addressing patterns saved to {addr_path}")
        for person, terms in addr.items():
            if person != "_default_tone":
                print(f"  {person}: {', '.join(set(terms))}")
        if "_default_tone" in addr:
            print(f"  Default tone: {', '.join(set(addr['_default_tone']))}")

    # ── Store in semantic memory ──
    print(f"\nStoring {len(all_own_messages)} style memories + conversation context...")

    stored = 0
    # Store own messages as style memories
    for msg in all_own_messages:
        try:
            await client.add_memory(
                content=f"[Khanh said in {msg['room_name'] or 'chat'}]: {msg['body']}",
                metadata={"source": "chat_own", "room_id": msg["room_id"]},
                agent_id="outward",
            )
            stored += 1
            if stored % 50 == 0:
                print(f"  Stored {stored}/{len(all_own_messages)}...")
        except Exception as e:
            print(f"  [ERR] {e}")
            # Don't stop on errors — Mem0 API can be slow
            continue

    # Store conversation summaries per room (grouped context)
    rooms_with_convos = defaultdict(list)
    for conv in all_conversations:
        rooms_with_convos[conv["room_name"] or "unnamed"].append(conv)

    room_summaries = 0
    for rname, convos in rooms_with_convos.items():
        # Create a summary of who's in this room and what's discussed
        senders = set(c["sender"].split(":")[0].replace("@googlechat_", "") for c in convos)
        topics = " | ".join(c["body"][:50] for c in convos[:5])
        summary = f"Room '{rname}' has {len(convos)} messages from {len(senders)} people. Recent topics: {topics}"

        try:
            await client.add_memory(
                content=summary,
                metadata={"source": "chat_room_summary", "room_name": rname},
                agent_id="inward",
            )
            room_summaries += 1
        except Exception:
            continue

    await client.close()

    print(f"\n{'='*50}")
    print(f"Full seed complete:")
    print(f"  Style memories:   {stored}")
    print(f"  Room summaries:   {room_summaries}")
    print(f"  Addressing rules: {len(addr)} patterns")
    print(f"  Total messages:   {len(all_conversations)}")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())

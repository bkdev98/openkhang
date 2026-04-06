#!/usr/bin/env python3
"""Comprehensive knowledge seeder for the digital twin.

Seeds ALL knowledge sources into the memory layer:
1. Khanh's own sent messages from Matrix history (style examples)
2. Jira tickets (current sprint + recent)
3. GitLab MRs (open + recent merged)
4. Chat history threads (already in episodic, this adds semantic grouping)

Usage:
    services/.venv/bin/python3 scripts/seed-knowledge.py [--source all|chat|jira|gitlab]
    services/.venv/bin/python3 scripts/seed-knowledge.py --source chat  # only chat history
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from services.memory.config import MemoryConfig
from services.memory.client import MemoryClient


# ── Matrix helpers ──────────────────────────────────────────────────

def matrix_api(method: str, path: str, hs: str, token: str, timeout: int = 15) -> dict:
    url = f"{hs}/_matrix/client/v3{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_own_messages(hs: str, token: str, own_puppet_prefix: str, limit_per_room: int = 100) -> list[dict]:
    """Fetch Khanh's own sent messages from Matrix room history."""
    rooms = matrix_api("GET", "/joined_rooms", hs=hs, token=token)
    room_ids = rooms.get("joined_rooms", [])
    print(f"  Scanning {len(room_ids)} rooms for your sent messages...")

    own_messages = []
    for rid in room_ids:
        enc = urllib.parse.quote(rid)
        try:
            resp = matrix_api(
                "GET",
                f"/rooms/{enc}/messages?dir=b&limit={limit_per_room}",
                hs=hs, token=token,
            )
        except Exception as e:
            print(f"  [WARN] Failed to read {rid[:30]}: {e}")
            continue

        # Get room name
        room_name = ""
        try:
            name_resp = matrix_api("GET", f"/rooms/{enc}/state/m.room.name", hs=hs, token=token)
            room_name = name_resp.get("name", "")
        except Exception:
            pass

        for event in resp.get("chunk", []):
            sender = event.get("sender", "")
            if not sender.startswith(own_puppet_prefix):
                continue
            if event.get("type") != "m.room.message":
                continue

            body = event.get("content", {}).get("body", "")
            if not body or len(body) < 3:
                continue

            own_messages.append({
                "body": body,
                "room_id": rid,
                "room_name": room_name,
                "sender": sender,
                "timestamp": event.get("origin_server_ts", 0),
                "event_id": event.get("event_id", ""),
            })

    return own_messages


# ── Jira helper ─────────────────────────────────────────────────────

def fetch_jira_tickets() -> list[dict]:
    """Fetch current sprint + recent tickets via jira-cli."""
    project = os.getenv("JIRA_PROJECT", "VR")
    jql = f'project = {project} AND (sprint in openSprints() OR updated >= "-14d")'

    try:
        result = subprocess.run(
            ["jira", "issue", "list", "--jql", jql, "--plain", "--no-headers",
             "--columns", "KEY,SUMMARY,STATUS,ASSIGNEE,PRIORITY"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        print("  [WARN] jira CLI not found, skipping")
        return []

    tickets = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            tickets.append({
                "key": parts[0].strip(),
                "summary": parts[1].strip() if len(parts) > 1 else "",
                "status": parts[2].strip() if len(parts) > 2 else "",
                "assignee": parts[3].strip() if len(parts) > 3 else "",
                "priority": parts[4].strip() if len(parts) > 4 else "",
            })
    return tickets


# ── GitLab helper ───────────────────────────────────────────────────

def fetch_gitlab_mrs() -> list[dict]:
    """Fetch open + recent MRs via glab."""
    try:
        result = subprocess.run(
            ["glab", "mr", "list", "-F", "json", "--per-page", "30"],
            capture_output=True, text=True, timeout=30,
        )
        mrs = json.loads(result.stdout) if result.stdout.strip() else []
    except (FileNotFoundError, json.JSONDecodeError):
        print("  [WARN] glab CLI not found or failed, skipping")
        return []

    return [
        {
            "iid": mr.get("iid"),
            "title": mr.get("title", ""),
            "state": mr.get("state", ""),
            "author": mr.get("author", {}).get("username", ""),
            "branch": mr.get("source_branch", ""),
            "target": mr.get("target_branch", ""),
            "description": (mr.get("description", "") or "")[:500],
        }
        for mr in mrs
    ]


# ── Main seeder ─────────────────────────────────────────────────────

async def seed_chat_style(client: MemoryClient) -> int:
    """Seed Khanh's own messages as style examples + episodic history."""
    hs = os.getenv("MATRIX_HOMESERVER", "http://localhost:8008")
    token = os.getenv("MATRIX_ACCESS_TOKEN", "")

    # Find Khanh's puppet prefix from config
    state_file = Path(".claude/gchat-autopilot.local.md")
    own_prefix = ""
    if state_file.exists():
        for line in state_file.read_text().splitlines():
            if line.startswith("sender_id:"):
                uid = line.split(":", 1)[1].strip().strip('"').replace("users/", "")
                own_prefix = f"@googlechat_{uid}:"
                break

    if not own_prefix:
        print("  [WARN] Could not determine own puppet prefix from gchat-autopilot.local.md")
        print("  Falling back to scanning all googlechat_ senders")
        own_prefix = "@googlechat_"

    messages = fetch_own_messages(hs, token, own_prefix)
    print(f"  Found {len(messages)} of your sent messages")

    # Save as style examples
    style_file = Path("config/style_examples.jsonl")
    with open(style_file, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    print(f"  Saved to {style_file}")

    # Also store in semantic memory for RAG
    stored = 0
    for msg in messages:
        try:
            await client.add_memory(
                content=f"[Khanh said in {msg['room_name'] or 'chat'}]: {msg['body']}",
                metadata={"source": "chat_own", "room_id": msg["room_id"]},
                agent_id="outward",
            )
            stored += 1
            if stored % 20 == 0:
                print(f"  Stored {stored}/{len(messages)} style memories...")
        except Exception as e:
            print(f"  [ERR] {e}")

    return stored


async def seed_jira(client: MemoryClient) -> int:
    """Seed Jira tickets into semantic memory."""
    tickets = fetch_jira_tickets()
    print(f"  Found {len(tickets)} Jira tickets")

    stored = 0
    for t in tickets:
        content = f"Jira {t['key']}: {t['summary']} (Status: {t['status']}, Assignee: {t['assignee']})"
        try:
            await client.add_memory(
                content=content,
                metadata={"source": "jira", "key": t["key"], "status": t["status"]},
                agent_id="inward",
            )
            stored += 1
        except Exception as e:
            print(f"  [ERR] {t['key']}: {e}")

    return stored


async def seed_gitlab(client: MemoryClient) -> int:
    """Seed GitLab MRs into semantic memory."""
    mrs = fetch_gitlab_mrs()
    print(f"  Found {len(mrs)} GitLab MRs")

    stored = 0
    for mr in mrs:
        content = f"GitLab MR !{mr['iid']}: {mr['title']} ({mr['state']}, branch: {mr['branch']} → {mr['target']})"
        if mr["description"]:
            content += f"\nDescription: {mr['description'][:300]}"
        try:
            await client.add_memory(
                content=content,
                metadata={"source": "gitlab", "iid": mr["iid"], "state": mr["state"]},
                agent_id="inward",
            )
            stored += 1
        except Exception as e:
            print(f"  [ERR] MR !{mr['iid']}: {e}")

    return stored


async def main():
    parser = argparse.ArgumentParser(description="Seed knowledge into digital twin memory")
    parser.add_argument("--source", choices=["all", "chat", "jira", "gitlab"], default="all")
    args = parser.parse_args()

    config = MemoryConfig.from_env()
    client = MemoryClient(config)
    await client.connect()

    print("=" * 50)
    print("openkhang Knowledge Seeder")
    print("=" * 50)

    totals = {}

    if args.source in ("all", "chat"):
        print("\n[1/3] Seeding chat style (your sent messages)...")
        totals["chat_style"] = await seed_chat_style(client)

    if args.source in ("all", "jira"):
        print("\n[2/3] Seeding Jira tickets...")
        totals["jira"] = await seed_jira(client)

    if args.source in ("all", "gitlab"):
        print("\n[3/3] Seeding GitLab MRs...")
        totals["gitlab"] = await seed_gitlab(client)

    await client.close()

    print("\n" + "=" * 50)
    print("Seeding complete:")
    for source, count in totals.items():
        print(f"  {source}: {count} items")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())

---
name: chat-autopilot
description: >-
  This skill provides core knowledge for the Google Chat autopilot plugin.
  It should be activated when any other gchat-autopilot skill or agent runs,
  or when the user asks about "chat autopilot", "message categories",
  "auto-reply rules", "chat priority", or "gchat settings".
version: 1.0.0
---

# Google Chat Autopilot — Core Knowledge

Google Chat autopilot monitors DMs and spaces in real-time via mautrix-googlechat bridge (Matrix protocol). It categorizes messages using AI, auto-replies to routine ones, and queues complex messages for human review.

## Architecture

```
Google Chat ←──real-time──→ mautrix-googlechat bridge
                                     │
                                     ▼
                              Synapse (Matrix homeserver)
                                     │
                                     ▼
                         /chat-scan (Matrix sync API)
                              │
                              ▼
                   chat-categorizer agent → classify + draft replies
                              │
                   ├─ FYI/Social → Matrix send API (auto-reply)
                   └─ Urgent/Action → queue draft → /chat-reply
```

### How It Works

1. The mautrix bridge connects to Google Chat using browser cookies (no API keys needed)
2. Each Google Chat space/DM becomes a Matrix room on the local Synapse server
3. Messages flow in real-time between Google Chat and Matrix
4. `/chat-scan` calls the Matrix `/sync` endpoint — long-polls for new events
5. Replies sent via Matrix API are delivered to Google Chat instantly through the bridge

### Key Advantages

- **Real-time** — messages arrive via push, not polling
- **No API permissions** — uses browser cookies, no Google Workspace admin needed
- **Structured data** — messages are native JSON (Matrix events), no DOM parsing
- **Reliable** — protocol-level, no browser/DOM fragility
- **Threads, reactions, read receipts** — all supported natively

## Prerequisites

- Docker + Docker Compose (for Synapse + PostgreSQL + bridge)
- Google Chat browser cookies (one-time extraction)
- See `references/mautrix-setup.md` for full setup guide

## Message Categories

| Category | Trigger signals | Auto-reply? | Action |
|----------|----------------|-------------|--------|
| **Urgent** | deadlines, blockers, incidents, "ASAP", "down", "broken" | No | Draft reply, surface immediately |
| **Action needed** | requests, reviews, approvals, questions directed at user | No | Draft reply, add to action queue |
| **FYI** | announcements, updates, newsletters, broadcasts | Yes | Auto-reply acknowledgment |
| **Social** | greetings, casual chat, emojis-only, "thanks" | Yes | Auto-reply or react with emoji |

## Matrix API Quick Reference

All calls use `curl` with `$MATRIX_HOMESERVER` and `Bearer $MATRIX_ACCESS_TOKEN` from `.env`.

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Get new messages | `/sync?since=$TOKEN&timeout=30000` | GET |
| List rooms | `/joined_rooms` | GET |
| Get room name | `/rooms/$ROOM_ID/state/m.room.name` | GET |
| Send message | `/rooms/$ROOM_ID/send/m.room.message/$TXN` | PUT |
| Reply in thread | Same as send, with `m.relates_to.rel_type: m.thread` | PUT |
| React with emoji | `/rooms/$ROOM_ID/send/m.reaction/$TXN` | PUT |
| Mark as read | `/rooms/$ROOM_ID/receipt/m.read/$EVENT_ID` | POST |
| Fetch history | `/rooms/$ROOM_ID/messages?dir=b&limit=20` | GET |

See `references/matrix-api.md` for full patterns with examples.

## State File

All state persists in `.claude/gchat-autopilot.local.md` with YAML frontmatter:

```yaml
---
account: user@company.com
matrix_since_token: "s12345_67890"  # sync token for incremental updates
room_map:                            # Matrix room ID → Google Chat space name
  "!abc:localhost": "[QLCT] The worker"
  "!def:localhost": "[Redeem-promotion] PO-Dev-Qc"
  "!ghi:localhost": "PHAN THÙY DƯƠNG"  # DM
tone_profile: |
  Language: Vietnamese + English mix
  Style: casual-professional, concise
  Examples: ["Noted, sẽ check sau nha", "Ok anh, em handle"]
monitored_rooms: all  # or list of Matrix room IDs
blacklisted_rooms:    # completely ignored — no messages collected
  - "!wvj:localhost"  # Group Cơm
mention_only_rooms:   # only messages @mentioning you are collected
  - "!TGy:localhost"  # [ABC] [Tech] MoMo App Platform
pending_drafts:
  - room_id: "!abc:localhost"
    event_id: "$eventXYZ"
    thread_event_id: "$threadRoot"  # null if not threaded
    sender: "PHAN THÙY DƯƠNG"
    message_preview: "Can you review the PR?"
    category: action_needed
    draft_reply: "Sure, will review within the hour"
    timestamp: "2026-03-25T00:05:00+07:00"
---
```

## Bridged User Format

- Google Chat users become: `@googlechat_USERID:localhost`
- Display names mirror Google Chat names
- Your own messages come from your puppet: `@googlechat_YOURID:localhost`
- Skip events from your own puppet when scanning

## Tone Learning

On first run, fetch recent messages from a few rooms via `/rooms/$ROOM_ID/messages` and filter for messages from your own puppet to learn tone patterns.

## Additional Resources

### Reference Files

- **`references/mautrix-setup.md`** — Full setup guide for Synapse + bridge + PostgreSQL
- **`references/matrix-api.md`** — Matrix API patterns with curl examples

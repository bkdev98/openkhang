---
name: chat-autopilot
description: >-
  This skill provides core knowledge for the Google Chat autopilot plugin.
  It should be activated when any other gchat-autopilot skill or agent runs,
  or when the user asks about "chat autopilot", "message categories",
  "auto-reply rules", "chat priority", or "gchat settings".
version: 0.1.0
---

# Google Chat Autopilot — Core Knowledge

Google Chat autopilot monitors DMs and @mentions via `gog chat` CLI, categorizes messages using AI, auto-replies to routine ones, and queues complex messages for human review.

## Architecture

```
/loop 5m /chat-scan
       │
       ▼
  gog chat spaces ls → list monitored spaces
  gog chat messages ls → fetch new messages per space
       │
       ▼
  chat-categorizer agent → classify + draft replies
       │
       ├─ FYI/Social → auto-send reply via gog chat messages send
       └─ Urgent/Action → queue draft in state file → /chat-reply
```

## Message Categories

| Category | Trigger signals | Auto-reply? | Action |
|----------|----------------|-------------|--------|
| **Urgent** | deadlines, blockers, incidents, "ASAP", "down", "broken" | No | Draft reply, surface immediately |
| **Action needed** | requests, reviews, approvals, questions directed at user | No | Draft reply, add to action queue |
| **FYI** | announcements, updates, newsletters, broadcasts | Yes | Auto-reply acknowledgment |
| **Social** | greetings, casual chat, emojis-only, "thanks" | Yes | Auto-reply or react with emoji |

## State File

All state persists in `.claude/gchat-autopilot.local.md` with YAML frontmatter:

```yaml
---
account: user@company.com
last_scan: "2026-03-24T00:00:00+07:00"
tone_profile: |
  Language: Vietnamese + English mix
  Style: casual-professional, concise
  Examples: ["Noted, sẽ check sau nha", "Ok anh, em handle"]
monitored_spaces: all  # or list of space IDs
scan_history:
  spaces/AAAA: "2026-03-24T00:00:00+07:00"
  spaces/BBBB: "2026-03-24T00:00:00+07:00"
pending_drafts:
  - space: spaces/AAAA
    thread: spaces/AAAA/threads/XXXX
    message_preview: "Can you review the PR?"
    category: action_needed
    draft_reply: "Sure, will review within the hour"
    timestamp: "2026-03-24T00:05:00+07:00"
---
```

## gogcli Commands Reference

```bash
# List all spaces (DMs + groups)
gog chat spaces ls -a USER@COMPANY.COM -j --results-only

# List messages in a space (newest first)
gog chat messages ls SPACE_NAME -a USER@COMPANY.COM -j --results-only

# Send a message to a space
gog chat messages send SPACE_NAME -a USER@COMPANY.COM --text "reply text"

# Reply to a thread
gog chat messages send SPACE_NAME -a USER@COMPANY.COM --text "reply" --thread THREAD_NAME

# React to a message
gog chat messages react MESSAGE_NAME EMOJI -a USER@COMPANY.COM
```

## Tone Learning

On first run, fetch 20 recent messages sent BY the user to learn:
- Primary language(s) used
- Formality level (casual/professional/mixed)
- Common phrases and patterns
- Average message length
- Use of Vietnamese diacritics vs shorthand

Store extracted tone profile in state file for consistent auto-replies.

## Additional Resources

### Reference Files

- **`references/categorization-rules.md`** — Detailed categorization heuristics and edge cases

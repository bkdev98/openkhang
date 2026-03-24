---
name: chat-autopilot
description: >-
  This skill provides core knowledge for the Google Chat autopilot plugin.
  It should be activated when any other gchat-autopilot skill or agent runs,
  or when the user asks about "chat autopilot", "message categories",
  "auto-reply rules", "chat priority", or "gchat settings".
version: 0.3.0
---

# Google Chat Autopilot — Core Knowledge

Google Chat autopilot monitors DMs and spaces by reading the Google Chat web UI via Chrome DevTools MCP. It categorizes messages using AI, auto-replies to routine ones, and queues complex messages for human review.

## Architecture

```
/loop 5m /chat-scan
       │
       ▼
  list_pages → find/open Google Chat tab in Chrome
  navigate to chat.google.com/app/home
       │
       ▼
  take_snapshot → read home feed (all recent messages in one view)
  ┌─────────────────────────────────────────────────────┐
  │ Home feed shows: space name, sender, time, preview, │
  │ unread badge, thread context — across ALL spaces     │
  │ No need to click into each space individually!       │
  └─────────────────────────────────────────────────────┘
       │
       ▼
  parse listitem elements → extract messages
  filter: unread only, skip own messages, skip non-monitored
       │
       ▼
  chat-categorizer agent → classify + draft replies
       │
       ├─ FYI/Social → click item → fill reply input → press_key Enter
       └─ Urgent/Action → queue draft in state file → /chat-reply
```

### Additional Views
- **"Chưa đọc" toggle** — filter home feed to unread only
- **"Lượt đề cập" shortcut** — view only @mentions (with unread count)
- **Click into space** — only needed for full thread context or sending replies

## Prerequisites

- Chrome running with DevTools protocol enabled
- Google Chat open and logged in at `https://chat.google.com`
- Chrome DevTools MCP server connected

## Message Categories

| Category | Trigger signals | Auto-reply? | Action |
|----------|----------------|-------------|--------|
| **Urgent** | deadlines, blockers, incidents, "ASAP", "down", "broken" | No | Draft reply, surface immediately |
| **Action needed** | requests, reviews, approvals, questions directed at user | No | Draft reply, add to action queue |
| **FYI** | announcements, updates, newsletters, broadcasts | Yes | Auto-reply acknowledgment |
| **Social** | greetings, casual chat, emojis-only, "thanks" | Yes | Auto-reply or react with emoji |

## Chrome DevTools MCP Tools Reference

### Navigation & Page Management
```
list_pages          → find Google Chat tab among open tabs
new_page            → open https://chat.google.com if no tab exists
select_page         → switch to the Chat tab
navigate_page       → go to a specific Chat URL (space, DM, thread)
```

### Reading Content
```
take_snapshot       → get a11y tree of current page (sidebar, messages, etc.)
evaluate_script     → run JS to extract structured data from the DOM
take_screenshot     → visual capture for debugging layout issues
```

### Interacting
```
click               → click a space in sidebar, a thread, or a button
fill                → type text into the message input field
press_key           → press Enter to send a message
```

### Key Patterns

**Find/open Google Chat tab:**
1. `list_pages` → look for a page with URL containing `chat.google.com`
2. If found: `select_page` with that pageId
3. If not found: `new_page` with url `https://chat.google.com`

**Navigate to a specific space:**
- Use `navigate_page` with URL: `https://chat.google.com/room/SPACE_ID`
- Or for DMs: click the DM entry in the sidebar snapshot

**Extract messages from current view:**
- Use `evaluate_script` with JS that queries message elements from the DOM
- Returns structured data: sender, text, timestamp, thread ID

**Send a reply:**
1. `take_snapshot` → find the message input element (uid)
2. `click` the input to focus it
3. `fill` with the reply text
4. `press_key` with key `Enter` to send

## State File

All state persists in `.claude/gchat-autopilot.local.md` with YAML frontmatter:

```yaml
---
account: user@company.com
sender_id: "users/123456"
chat_tab_url: "https://chat.google.com"
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

## Tone Learning

On first run, navigate through a few spaces and use `evaluate_script` to extract the user's own recent messages to learn:
- Primary language(s) used
- Formality level (casual/professional/mixed)
- Common phrases and patterns
- Average message length
- Use of Vietnamese diacritics vs shorthand

Store extracted tone profile in state file for consistent auto-replies.

## Additional Resources

### Reference Files

- **`references/categorization-rules.md`** — Detailed categorization heuristics and edge cases
- **`references/chrome-extraction.md`** — JS extraction patterns for Google Chat DOM

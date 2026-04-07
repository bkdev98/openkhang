# Phase 4: Chat Page

**Priority:** High
**Status:** Complete

## Overview

Replace basic textarea with a proper conversation UI: message bubbles, history, typing indicator, markdown rendering.

## Related Code Files

**Modify:**
- `services/dashboard/app.py` — update `/api/chat` to return JSON, add `/api/chat/history` endpoint
- `services/dashboard/twin_chat.py` — persist conversation history, add history retrieval

**Create:**
- `services/dashboard/templates/pages/chat.html` — full chat interface
- `services/dashboard/templates/partials/chat_bubble.html` — single message bubble
- `services/dashboard/templates/partials/typing_indicator.html` — animated dots

## Implementation Steps

1. Update twin_chat.py: store conversation in a dict keyed by session_id (max 100 messages), add `get_history(session_id)` method
2. Add `/api/chat/history` endpoint: returns rendered chat bubbles for session
3. Create chat_bubble.html: user bubble (right-aligned, amber tint) vs twin bubble (left, raised surface), metadata (confidence, latency)
4. Create chat.html: scrollable conversation area + input bar at bottom
5. Chat submit: HTMX POST to `/api/chat`, append user bubble immediately (optimistic), then append twin reply
6. Auto-scroll to bottom on new message (vanilla JS)
7. Typing indicator: show after submit, hide on response
8. Add markdown rendering via marked.js CDN (lightweight, ~8kb)
9. Clear history button: POST to `/api/chat/clear`
10. Cmd+Enter keyboard shortcut for send

## Todo

- [x] Update twin_chat.py with conversation persistence + get_history()
- [x] Add /api/chat/history and /api/chat/clear endpoints
- [x] Create chat_bubble.html partial
- [x] Create typing_indicator.html partial
- [x] Create chat.html page with conversation UI
- [x] Add markdown rendering (marked.js)
- [x] Auto-scroll + keyboard shortcuts
- [x] Verify session persistence across page navigation

## Success Criteria

- Chat shows conversation history with proper bubbles
- Messages persist across page navigation (same session)
- Typing indicator shows while twin thinks
- Twin replies render markdown
- Cmd+Enter sends message
- Clear history works

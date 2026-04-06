#!/bin/bash
# Session start hook: start listener, check pending drafts, show inbox count
set -euo pipefail

STATE_FILE="$CLAUDE_PROJECT_DIR/.claude/gchat-autopilot.local.md"
PID_FILE="$CLAUDE_PROJECT_DIR/.claude/matrix-listener.pid"
INBOX_FILE="$CLAUDE_PROJECT_DIR/.claude/gchat-inbox.jsonl"

# Skip if no state file (plugin not set up yet)
if [ ! -f "$STATE_FILE" ]; then
  echo '{"systemMessage": "Google Chat autopilot not configured. Run /chat-auth to get started."}'
  exit 0
fi

messages=""

# Auto-start listener if not running
if [ ! -f "$PID_FILE" ] || ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  cd "$CLAUDE_PROJECT_DIR" && python3 scripts/matrix-listener.py --daemon 2>/dev/null
  messages="Chat listener started. "
fi

# Count unread inbox messages
if [ -f "$INBOX_FILE" ] && [ -s "$INBOX_FILE" ]; then
  inbox_count=$(wc -l < "$INBOX_FILE" | tr -d ' ')
  messages="${messages}📬 ${inbox_count} new messages in inbox. Run /chat-scan to process. "
fi

# Count pending drafts
pending_count=$(grep -c "^  - room_id:" "$STATE_FILE" 2>/dev/null || echo "0")
if [ "$pending_count" -gt 0 ]; then
  messages="${messages}📝 ${pending_count} pending draft replies. Run /chat-reply to review."
fi

if [ -n "$messages" ]; then
  echo "{\"systemMessage\": \"Google Chat: ${messages}\"}"
else
  echo '{"systemMessage": ""}'
fi

exit 0

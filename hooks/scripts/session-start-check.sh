#!/bin/bash
# Session start hook: check for pending chat drafts and remind user
set -euo pipefail

STATE_FILE="$CLAUDE_PROJECT_DIR/.claude/gchat-autopilot.local.md"

# Skip if no state file (plugin not set up yet)
if [ ! -f "$STATE_FILE" ]; then
  echo '{"systemMessage": "Google Chat autopilot not configured. Run /chat-scan --setup to get started."}'
  exit 0
fi

# Count pending drafts by looking for entries in pending_drafts section
pending_count=$(grep -c "^  - space:" "$STATE_FILE" 2>/dev/null || echo "0")

if [ "$pending_count" -gt 0 ]; then
  echo "{\"systemMessage\": \"Google Chat: $pending_count pending draft replies awaiting review. Run /chat-reply to review and send.\"}"
else
  echo '{"systemMessage": ""}'
fi

exit 0

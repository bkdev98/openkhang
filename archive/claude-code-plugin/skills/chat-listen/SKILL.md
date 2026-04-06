---
name: chat-listen
description: >-
  Start or stop the real-time Google Chat message listener. Use "/chat-listen"
  to start the background daemon that long-polls Matrix for incoming messages.
  Messages are written to .claude/gchat-inbox.jsonl for /chat-scan to process.
  Use "/chat-listen stop" to stop, "/chat-listen status" to check.
argument-hint: "[start|stop|status|tail]"
allowed-tools: ["Bash", "Read", "Write"]
version: 1.0.0
---

# Chat Listen

Real-time Google Chat message listener via Matrix sync long-polling.

## How It Works

The listener is a Python daemon (`scripts/matrix-listener.py`) that:
1. Long-polls the Matrix `/sync` endpoint with 30s timeout
2. The server holds the connection and returns **instantly** when new messages arrive
3. New messages are appended to `.claude/gchat-inbox.jsonl` as JSON lines
4. `/chat-scan` reads from this file instead of calling sync directly

This gives true real-time message delivery — no polling delay.

## Subcommands

### start (default)

Start the listener daemon in the background:

```bash
cd $CLAUDE_PROJECT_DIR
python3 scripts/matrix-listener.py --daemon
```

Display:
```
🎧 Listener started (PID 12345)
   Inbox: .claude/gchat-inbox.jsonl
   Log:   .claude/matrix-listener.log

Messages will appear in real-time. Run /chat-scan to process them.
```

### stop

Stop the background listener:

```bash
cd $CLAUDE_PROJECT_DIR
python3 scripts/matrix-listener.py --stop
```

### status

Check if the listener is running and show stats:

```bash
# Check PID
PID_FILE=".claude/matrix-listener.pid"
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "🟢 Listener running (PID $PID)"
  else
    echo "🔴 Listener not running (stale PID)"
  fi
else
  echo "🔴 Listener not running"
fi

# Show inbox stats
INBOX=".claude/gchat-inbox.jsonl"
if [ -f "$INBOX" ]; then
  TOTAL=$(wc -l < "$INBOX" | tr -d ' ')
  RECENT=$(tail -5 "$INBOX" | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        m = json.loads(line)
        print(f'  [{m[\"room_name\"][:30]}] {m[\"body\"][:60]}')
    except: pass
  ")
  echo "📬 Inbox: $TOTAL messages"
  echo "Recent:"
  echo "$RECENT"
fi
```

### tail

Show incoming messages in real-time (foreground mode):

```bash
cd $CLAUDE_PROJECT_DIR
python3 scripts/matrix-listener.py
```

This runs the listener in the foreground, printing each message as it arrives. Ctrl+C to stop.

## Inbox File Format

`.claude/gchat-inbox.jsonl` — one JSON object per line:

```json
{"room_id":"!abc:localhost","room_name":"[QLCT] The worker","event_id":"$xyz","sender":"@googlechat_123:localhost","sender_id":"123","body":"message text","formatted_body":"<p>message text</p>","msgtype":"m.text","thread_event_id":null,"timestamp":1774440000000,"time":"2026-03-26T12:00:00+00:00"}
```

Fields:
- `room_id` — Matrix room ID
- `room_name` — Google Chat space/DM name
- `event_id` — unique message ID (for replies/reactions)
- `sender` — full Matrix user ID of the bridged sender
- `sender_id` — Google Chat user ID (numeric)
- `body` — plain text message content
- `thread_event_id` — parent event ID if threaded reply, null otherwise
- `timestamp` — Unix timestamp in milliseconds
- `time` — ISO 8601 timestamp

## Integration with /chat-scan

When the listener is running, `/chat-scan` should:
1. Atomically rename `.claude/gchat-inbox.jsonl` to `.claude/gchat-inbox.processing.jsonl` (`mv` is atomic)
2. Read and process all messages from the renamed file
3. Delete the processing file when done

**Do not** truncate with `> inbox.jsonl` — the listener writes concurrently and messages between read and truncate would be lost. The atomic `mv` approach is safe because the listener will create a fresh inbox file on its next write.

This is much faster than calling the sync API directly — messages are already waiting in the file.

## Auto-Start

To start the listener automatically on session start, add to the SessionStart hook:

```bash
# Start listener if not already running
PID_FILE="$CLAUDE_PROJECT_DIR/.claude/matrix-listener.pid"
if [ ! -f "$PID_FILE" ] || ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  cd "$CLAUDE_PROJECT_DIR" && python3 scripts/matrix-listener.py --daemon
fi
```

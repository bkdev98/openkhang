#!/usr/bin/env python3
"""
Matrix real-time message listener for Google Chat bridge.

Long-polls the Matrix /sync endpoint and writes new messages to an inbox file.
Messages are appended as JSON lines for efficient reading by /chat-scan.

Usage:
    python3 scripts/matrix-listener.py              # Run in foreground
    python3 scripts/matrix-listener.py --daemon      # Run in background (writes PID file)
    python3 scripts/matrix-listener.py --stop        # Stop the background daemon

Environment (from .env):
    MATRIX_HOMESERVER   - Synapse URL (default: http://localhost:8008)
    MATRIX_ACCESS_TOKEN - Auth token for the Claude Matrix user
"""

import json
import os
import sys
import signal
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
STATE_DIR = PROJECT_DIR / ".claude"
INBOX_FILE = STATE_DIR / "gchat-inbox.jsonl"
SINCE_FILE = STATE_DIR / "gchat-sync-token.txt"
PID_FILE = STATE_DIR / "matrix-listener.pid"
ENV_FILE = PROJECT_DIR / ".env"

# Sync config
SYNC_TIMEOUT_MS = 30000   # 30s long-poll — server returns immediately on new events
RETRY_DELAY_S = 5          # delay between retries on error
MAX_TIMELINE_LIMIT = 50    # max messages per room per sync


def load_filter_config():
    """Load blacklisted_rooms and mention_only_rooms from state file."""
    state_file = STATE_DIR / "gchat-autopilot.local.md"
    blacklisted = set()
    mention_only = set()
    mention_names = []  # names/patterns to match for mention-only rooms

    if not state_file.exists():
        return blacklisted, mention_only, mention_names

    text = state_file.read_text()
    # Parse YAML-ish frontmatter between --- markers
    current_list = None
    sender_id = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "---":
            current_list = None
            continue
        if stripped.startswith("sender_id:"):
            sender_id = stripped.split(":", 1)[1].strip().strip('"').replace("users/", "")
        # Detect start of a list key (not indented, has colon)
        if not line.startswith(" ") and not line.startswith("\t"):
            if "blacklisted_rooms:" in stripped:
                current_list = "blacklist"
                continue
            elif "mention_only_rooms:" in stripped:
                current_list = "mention"
                continue
            elif ":" in stripped and not stripped.startswith("#") and not stripped.startswith("-"):
                current_list = None  # moved to a different top-level key
                continue
        # Indented list items belong to current_list
        if stripped.startswith("- ") and current_list:
            # Extract room ID from  - "!room:localhost"  # comment
            val = stripped[2:].strip().split("#")[0].strip().strip('"')
            if val.startswith("!"):
                if current_list == "blacklist":
                    blacklisted.add(val)
                elif current_list == "mention":
                    mention_only.add(val)

    # Build mention patterns: puppet ID, display name variants, email
    if sender_id:
        mention_names.append(f"@googlechat_{sender_id}:")

    # Also load account email for @-mention matching
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("account:"):
            email = stripped.split(":", 1)[1].strip()
            username = email.split("@")[0]
            mention_names.append(username)
            break

    # Load display name from bridge puppet (if available, fetch once from Matrix)
    # The bridge formats mentions as matrix.to links containing the puppet user ID,
    # so the puppet ID pattern above catches formatted_body mentions.
    # Also add common name variants for plain-text body matching.
    if sender_id:
        mention_names.append(f"googlechat_{sender_id}")

    return blacklisted, mention_only, mention_names


def load_env():
    """Load environment variables from .env file."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def matrix_api(method, path, body=None, hs=None, token=None, timeout=35):
    """Call the Matrix client API."""
    url = f"{hs}/_matrix/client/v3{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# Global cache: Matrix user ID → display name (populated from gchat-users.json + member events)
_user_display_names: dict[str, str] = {}
# Static lookup: Google Chat numeric ID → display name (loaded from config/gchat-users.json)
_gchat_users: dict[str, str] = {}


def _load_gchat_users() -> None:
    """Load the static Google Chat user directory for display name resolution.

    Maps numeric Google Chat user IDs to full display names.
    This is the primary source — covers all users including those in DMs
    where Matrix member events show 'Anonymous User'.
    """
    global _gchat_users
    lookup_path = PROJECT_DIR / "config" / "gchat-users.json"
    try:
        _gchat_users = json.loads(lookup_path.read_text(encoding="utf-8"))
        print(f"[listener] Loaded {len(_gchat_users)} users from gchat-users.json", flush=True)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[listener] gchat-users.json not found or invalid: {exc}", flush=True)
        _gchat_users = {}


def _clean_display_name(raw: str) -> str:
    """Strip '(Google Chat)' suffix from bridge display names.

    'BÙI QUỐC KHÁNH - ITC - App Dev - Senior - Mobile Engineer (Google Chat)' →
    'BÙI QUỐC KHÁNH - ITC - App Dev - Senior - Mobile Engineer'
    """
    if not raw:
        return ""
    if raw.endswith("(Google Chat)"):
        raw = raw[:-len("(Google Chat)")].rstrip()
    # Skip useless placeholder names
    if raw in ("Anonymous User", "Deleted User"):
        return ""
    return raw


def _short_name(display_name: str) -> str:
    """Extract just the person's name from the full Google Chat handle.

    'BÙI QUỐC KHÁNH - ITC - App Dev - Senior - Mobile Engineer' → 'BÙI QUỐC KHÁNH'
    """
    if " - " in display_name:
        return display_name.split(" - ")[0].strip()
    return display_name


def _cache_member(user_id: str, displayname: str) -> None:
    """Cache a user's display name, preferring real names over Anonymous."""
    clean = _clean_display_name(displayname)
    if clean and (user_id not in _user_display_names or not _user_display_names[user_id]):
        _user_display_names[user_id] = clean


def _resolve_sender_name(sender: str, room_id: str = "", hs: str = "", token: str = "") -> str:
    """Look up sender's display name. Checks: static directory → member cache → Matrix API.

    Returns short name (just the person's name without org/title) or empty string.
    """
    # Extract numeric Google Chat ID from Matrix user ID (@googlechat_12345:localhost → 12345)
    gchat_id = sender.split(":")[0].replace("@googlechat_", "").replace("@", "")
    # Primary: static user directory (covers all users including DMs with Anonymous)
    if gchat_id in _gchat_users:
        return _short_name(_gchat_users[gchat_id])
    # Fallback: member event cache
    dn = _user_display_names.get(sender, "")
    if dn:
        return _short_name(dn)
    # Last resort: query Matrix API for member state (and cache the result)
    if room_id and hs and token:
        try:
            enc_room = urllib.parse.quote(room_id)
            enc_sender = urllib.parse.quote(sender)
            result = matrix_api("GET", f"/rooms/{enc_room}/state/m.room.member/{enc_sender}", hs=hs, token=token)
            raw_dn = result.get("displayname", "")
            if raw_dn:
                _cache_member(sender, raw_dn)
                clean = _clean_display_name(raw_dn)
                if clean:
                    return _short_name(clean)
        except Exception:
            pass
    return ""


def parse_message(event, room_id, room_name, hs="", token=""):
    """Parse a Matrix event into a compact message dict."""
    content = event.get("content", {})
    sender = event.get("sender", "")
    ts = event.get("origin_server_ts", 0)

    # Extract display name from sender (bridge format: @googlechat_USERID:localhost)
    sender_local = sender.split(":")[0].replace("@googlechat_", "").replace("@", "")

    # Resolve human-readable sender name (static dir → cache → Matrix API)
    sender_display = _resolve_sender_name(sender, room_id, hs, token)

    # Check for thread
    relates = content.get("m.relates_to", {})
    thread_id = relates.get("event_id") if relates.get("rel_type") == "m.thread" else None

    return {
        "room_id": room_id,
        "room_name": room_name,
        "event_id": event.get("event_id", ""),
        "sender": sender,
        "sender_id": sender_local,
        "sender_display_name": sender_display,
        "body": content.get("body", ""),
        "formatted_body": content.get("formatted_body", ""),
        "msgtype": content.get("msgtype", ""),
        "thread_event_id": thread_id,
        "timestamp": ts,
        "time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat() if ts else "",
    }


def _redis_publish(messages, redis_url):
    """Publish messages to Redis openkhang:events channel (best-effort).

    Non-blocking: if Redis is unavailable or redis package missing,
    logs a warning and returns without raising.
    """
    try:
        import redis  # type: ignore[import]
    except ImportError:
        return  # redis package not installed — skip silently

    try:
        client = redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        for msg in messages:
            payload = json.dumps({"type": "chat_message", "payload": msg}, ensure_ascii=False)
            client.publish("openkhang:events", payload)
        client.close()
    except Exception as exc:
        print(f"[listener] Redis publish warning (non-fatal): {exc}", flush=True)


def append_to_inbox(messages, redis_url=None):
    """Append messages to the inbox JSONL file and publish to Redis."""
    if not messages:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(INBOX_FILE, "a") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    # Publish to Redis for realtime ingestion pipeline (non-breaking)
    if redis_url:
        _redis_publish(messages, redis_url)


def load_since_token():
    """Load the sync token from disk."""
    if SINCE_FILE.exists():
        return SINCE_FILE.read_text().strip()
    return None


def save_since_token(token):
    """Save the sync token to disk."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SINCE_FILE.write_text(token)


def sync_loop(hs, token, own_puppet_prefix, redis_url=None):
    """Main sync loop — long-polls Matrix for new events."""
    since = load_since_token()
    room_names = {}

    # Load static user directory for display name resolution
    _load_gchat_users()

    # Load room filtering config
    blacklisted, mention_only, mention_names = load_filter_config()
    if blacklisted:
        print(f"[listener] Blacklisted rooms: {len(blacklisted)}", flush=True)
    if mention_only:
        print(f"[listener] Mention-only rooms: {len(mention_only)}", flush=True)

    # Initial sync to get room names and since token
    if not since:
        print("[listener] Performing initial sync...", flush=True)
        try:
            params = f"timeout=5000&filter=%7B%22room%22%3A%7B%22timeline%22%3A%7B%22limit%22%3A1%7D%7D%7D"
            result = matrix_api("GET", f"/sync?{params}", hs=hs, token=token, timeout=10)
            since = result.get("next_batch", "")
            save_since_token(since)
            # Build display name cache from ALL member events, and resolve room names
            for rid in result.get("rooms", {}).get("join", {}):
                state_evts = result["rooms"]["join"][rid].get("state", {}).get("events", [])
                real_members = []  # non-bot, non-puppet members
                for e in state_evts:
                    if e.get("type") == "m.room.name":
                        room_names[rid] = e["content"].get("name", "")
                    elif e.get("type") == "m.room.member":
                        uid = e.get("state_key", "")
                        dn = e.get("content", {}).get("displayname", "")
                        if dn:
                            _cache_member(uid, dn)
                        # Track real members (not bots, not own puppet, not claude)
                        if (uid and "bot" not in uid.lower()
                                and not uid.startswith("@claude:")
                                and not (own_puppet and uid.startswith(own_puppet))):
                            clean = _clean_display_name(dn)
                            if clean:
                                real_members.append((uid, clean))
                # For rooms without m.room.name: use other member's name if it's a DM (2 real members)
                if not room_names.get(rid) and len(real_members) == 1:
                    room_names[rid] = _short_name(real_members[0][1])
            print(f"[listener] Initial sync done. {len(room_names)} rooms, {len(_user_display_names)} users cached. Token: {since[:30]}...", flush=True)
        except Exception as e:
            print(f"[listener] Initial sync failed: {e}", flush=True)
            return

    print(f"[listener] Listening for messages (long-poll {SYNC_TIMEOUT_MS}ms)...", flush=True)

    while True:
        try:
            params = f"since={since}&timeout={SYNC_TIMEOUT_MS}"
            params += f"&filter=%7B%22room%22%3A%7B%22timeline%22%3A%7B%22limit%22%3A{MAX_TIMELINE_LIMIT}%7D%7D%7D"
            result = matrix_api("GET", f"/sync?{params}", hs=hs, token=token, timeout=SYNC_TIMEOUT_MS // 1000 + 10)

            new_since = result.get("next_batch", since)
            if new_since != since:
                since = new_since
                save_since_token(since)

            # Process new messages
            new_messages = []
            joined_rooms = result.get("rooms", {}).get("join", {})

            for rid, rdata in joined_rooms.items():
                # Update caches from state events
                for e in rdata.get("state", {}).get("events", []):
                    if e.get("type") == "m.room.name":
                        room_names[rid] = e["content"].get("name", "")
                    elif e.get("type") == "m.room.member":
                        _cache_member(e.get("state_key", ""), e.get("content", {}).get("displayname", ""))

                # Skip blacklisted rooms entirely
                if rid in blacklisted:
                    continue

                rname = room_names.get(rid, "")
                is_mention_only = rid in mention_only

                # Process timeline events
                for event in rdata.get("timeline", {}).get("events", []):
                    if event.get("type") != "m.room.message":
                        continue
                    # Skip own messages (puppet + claude user)
                    sender = event.get("sender", "")
                    if own_puppet_prefix and sender.startswith(own_puppet_prefix):
                        continue
                    if sender.startswith("@claude:"):
                        continue
                    # Skip bot messages
                    if "googlechatbot" in sender:
                        continue

                    # For mention-only rooms, check if message mentions the user
                    if is_mention_only:
                        body = event.get("content", {}).get("body", "")
                        formatted = event.get("content", {}).get("formatted_body", "")
                        text_to_check = (body + " " + formatted).lower()
                        mentioned = any(name.lower() in text_to_check for name in mention_names if name)
                        if not mentioned:
                            continue

                    # Use room name, or sender's short name for unnamed DM rooms
                    effective_rname = rname
                    if not effective_rname:
                        effective_rname = _resolve_sender_name(sender, rid, hs, token)

                    msg = parse_message(event, rid, effective_rname, hs, token)
                    new_messages.append(msg)

            if new_messages:
                append_to_inbox(new_messages, redis_url=redis_url)
                for msg in new_messages:
                    name = msg["room_name"] or msg["room_id"]
                    body_preview = msg["body"][:80]
                    print(f"[{msg['time'][:19]}] [{name}] {body_preview}", flush=True)

            # Also auto-join any invited rooms
            invited = result.get("rooms", {}).get("invite", {})
            for rid in invited:
                try:
                    enc = urllib.parse.quote(rid)
                    matrix_api("POST", f"/join/{enc}", {}, hs=hs, token=token)
                    print(f"[listener] Auto-joined room {rid}", flush=True)
                except Exception:
                    pass

        except KeyboardInterrupt:
            print("\n[listener] Stopped by user.", flush=True)
            break
        except Exception as e:
            print(f"[listener] Sync error: {e}. Retrying in {RETRY_DELAY_S}s...", flush=True)
            time.sleep(RETRY_DELAY_S)


def daemonize():
    """Fork to background and write PID file."""
    pid = os.fork()
    if pid > 0:
        # Parent — write PID and exit
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(pid))
        print(f"[listener] Started in background (PID {pid})", flush=True)
        print(f"[listener] Inbox: {INBOX_FILE}", flush=True)
        print(f"[listener] Stop:  python3 {__file__} --stop", flush=True)
        sys.exit(0)

    # Child — detach
    os.setsid()
    # Redirect stdout/stderr to log with line buffering
    log_path = STATE_DIR / "matrix-listener.log"
    log_file = open(log_path, "a", buffering=1)  # line-buffered
    sys.stdout = log_file
    sys.stderr = log_file
    print(f"\n[{datetime.now().isoformat()}] Daemon started (PID {os.getpid()})", flush=True)


def stop_daemon():
    """Stop the background daemon."""
    if not PID_FILE.exists():
        print("[listener] No daemon running (no PID file)", flush=True)
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"[listener] Stopped daemon (PID {pid})", flush=True)
    except ProcessLookupError:
        print(f"[listener] Daemon already stopped (stale PID {pid})", flush=True)
    PID_FILE.unlink(missing_ok=True)


def main():
    if "--stop" in sys.argv:
        stop_daemon()
        return

    env = load_env()
    hs = env.get("MATRIX_HOMESERVER", "http://localhost:8008")
    token = env.get("MATRIX_ACCESS_TOKEN", "")

    if not token:
        print("[listener] ERROR: MATRIX_ACCESS_TOKEN not set in .env", flush=True)
        sys.exit(1)

    # Determine own puppet prefix to filter own messages
    # The bridge creates @googlechat_USERID:localhost for the user
    # Read sender_id from state file if available
    state_file = STATE_DIR / "gchat-autopilot.local.md"
    own_puppet = ""
    if state_file.exists():
        for line in state_file.read_text().splitlines():
            if line.startswith("sender_id:"):
                uid = line.split(":", 1)[1].strip().strip('"').replace("users/", "")
                own_puppet = f"@googlechat_{uid}:"
                break

    redis_url = env.get("OPENKHANG_REDIS_URL", "redis://localhost:6379")

    if "--daemon" in sys.argv:
        daemonize()

    sync_loop(hs, token, own_puppet, redis_url=redis_url)


if __name__ == "__main__":
    main()

---
name: chat-scan
description: >-
  Scan Google Chat for new messages. This skill should be invoked with
  "/chat-scan" to read the Google Chat web UI via Chrome DevTools MCP,
  detect unread messages across monitored spaces, categorize them,
  auto-reply to routine ones, and surface actionable items.
  Compatible with "/loop 5m /chat-scan" for continuous monitoring.
argument-hint: "[--setup] [--dry-run] [--mentions-only]"
allowed-tools: ["Read", "Write", "Edit", "Agent", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__list_pages", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__new_page", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__select_page", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__navigate_page", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_snapshot", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_screenshot", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__evaluate_script", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__click", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__fill", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__press_key", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__wait_for"]
version: 0.3.0
---

# Chat Scan

Scan Google Chat for new messages via Chrome DevTools MCP — no API permissions needed.

## Arguments

- `--setup` — Run first-time setup: verify Chrome tab, extract tone profile
- `--dry-run` — Scan and categorize but don't send any auto-replies
- `--mentions-only` — Only scan @mentions (faster, uses "Lượt đề cập" view)

## Key Insight: Home Feed

Google Chat's home page (`chat.google.com/app/home`) shows a **unified feed of all recent messages across all spaces and DMs** — with sender, time, space name, message preview, and unread indicators. This eliminates the need to click into each space individually.

The home feed also provides:
- **"Chưa đọc" toggle** — filters to only unread messages
- **"Lượt đề cập" shortcut** — shows only @mentions directed at you (with unread count)
- **Thread context** — shows both the original message and the latest reply in threads
- **Live updates** — the ARIA live region announces new messages in real-time

**One snapshot of the home feed = all recent messages.** Only click into a space when you need full thread context or to send a reply.

## Execution Flow

### 1. Connect to Google Chat Tab

Use `list_pages` to find an open tab with URL containing `chat.google.com`.

- **If found:** `select_page` with that pageId
- **If not found:** `new_page` with url `https://chat.google.com`
  - After page loads, `take_snapshot` to verify user is logged in
  - If login page detected: instruct user to log in manually, then re-run

If state file doesn't exist or `--setup` flag passed, run **First-Time Setup** (see below).

### 2. Load State

Read `.claude/gchat-autopilot.local.md` for account, last scan timestamp, tone profile, and monitored spaces.

### 3. Navigate to Home & Read Feed

Ensure we're on the home page. If not, `navigate_page` to `https://chat.google.com/app/home`.

**Option A — Full scan (default):**
1. `take_snapshot` of the home feed
2. The home feed shows all recent conversations as `listitem level="1"` elements
3. Each item contains: space/DM name, timestamp, sender name, message preview, and unread indicator ("Chưa đọc")
4. Thread items show "Chuỗi cuộc trò chuyện" with both original message and "Tin trả lời mới nhất" (latest reply)

**Option B — Unread only (recommended for efficiency):**
1. Find the "Chưa đọc" toggle switch in the home feed header
2. `click` to enable it — filters feed to only unread messages
3. `take_snapshot` to read the filtered feed
4. After processing, `click` the toggle again to disable the filter

**Option C — Mentions only (`--mentions-only`):**
1. `click` the "Lượt đề cập" shortcut in the sidebar (shows @mentions with unread count)
2. `take_snapshot` to read the mentions feed
3. Navigate back to home when done

### 4. Parse Messages from Snapshot

From the home feed snapshot, extract each message item:

```
For each listitem level="1":
  - Space/DM name: first StaticText (e.g., "[ABC] [Tech] MoMo App Platform")
  - Timestamp: StaticText with time pattern (e.g., "19 phút", "17:15", "Hôm qua")
  - Unread: presence of "Chưa đọc" StaticText
  - Sender: StaticText with full name pattern "NAME - DEPT - Role"
  - Message text: remaining StaticText content
  - Thread: "Chuỗi cuộc trò chuyện" indicates threaded, "Tin trả lời mới nhất" has latest reply
  - @mention: look for "Bạn:" prefix (your own messages) to skip, or @mentions of your name
```

**Filter rules:**
- Skip items where sender starts with "Bạn:" (your own messages)
- Skip items older than `last_scan` timestamp
- Skip spaces not in `monitored_spaces` whitelist (unless `monitored_spaces: all`)
- If `monitor_all_dms: true`, include all DM items regardless of whitelist

### 5. Categorize Messages

Spawn the `chat-categorizer` agent with the batch of new messages and the tone profile from state. The agent returns categorized messages with draft replies.

### 6. Execute Actions

For each categorized message:

- **FYI / Social** (auto-reply enabled, unless `--dry-run`):
  1. `click` the message item in the home feed to navigate to that space
  2. `take_snapshot` → find the message input element
  3. `click` the input to focus it
  4. `fill` with the auto-reply text
  5. `press_key` with key `Enter` to send
  6. `navigate_page` back to home feed for the next reply

- **Urgent / Action Needed**: Add to `pending_drafts` in state file with:
  - space name, thread context, message preview, sender, category, draft reply, timestamp

If `--dry-run`, skip sending and just display the categorization results.

### 7. Update State

Update `last_scan` timestamp in `.claude/gchat-autopilot.local.md`.

### 8. Display Summary

```
📬 Chat Scan Complete — 12 new messages

🔴 Urgent (1):
  • [Happy User] NGÔ THỊ HỒNG THẢO: "Giao dịch bị treo, cần chuyển tiền gấp"
    → Draft: "Đang check rồi nha"

🟡 Action Needed (3):
  • [DM] PHAN THÙY DƯƠNG: "card VR-198 sao r a"
    → Draft: "Để em check lại nha"
  • [Redeem-promotion] PHAN THÙY DƯƠNG: "@BÙI QUỐC KHÁNH discuss with BE về VR-209"
    → Draft: "Ok em, em check rồi reply nha"
  • [ACB After Payment] NGUYỄN NGỌC HẢI: "@tất cả AI Productivity mục tiêu"
    → Draft: "Noted anh, em xem qua rồi discuss chiều nha"

🟢 Auto-replied (6):
  • [Group Cơm] PHẠM THỊ HỒNG ĐÀO: "Hàng có sẵn" → 👍
  • [Trackify] NGUYỄN THANH HẢI: "Release note E2E Duration" → "Noted, cảm ơn!"
  ...

⚪ Skipped (2): bot messages, non-monitored spaces
```

## First-Time Setup

When no state file exists or `--setup` is passed:

1. **Connect to Chrome** — Find or open Google Chat tab (step 1 above)
2. **Verify login** — `take_snapshot` to confirm user is logged in (look for account button in header)
3. **Detect account** — Read account name from the header button (e.g., "Tài khoản Google: NAME (email)")
4. **Scan sidebar** — Extract all visible spaces from "Tin nhắn trực tiếp" (DMs) and "Không gian" (Spaces) sections
5. **Learn tone** — From the home feed, identify messages where sender is "Bạn:" (your messages), extract language/style patterns. If not enough samples, click into 2-3 spaces to see more of your messages.
6. **Create state file** — Write `.claude/gchat-autopilot.local.md` with:
   - account (from header), chat_tab_url, monitored_spaces, tone_profile
7. **Confirm** — Show extracted tone profile and space list, ask user to confirm or adjust

## Snapshot Structure Reference

The home feed snapshot follows this structure:

```
region "Trang chủ..."
  switch "Chưa đọc"              ← toggle for unread filter
  button "Chuỗi cuộc trò chuyện" ← thread view toggle
  button "Chia màn hình..."       ← split pane toggle
  generic
    listitem level="1"            ← each message/conversation
      StaticText "Space Name"
      StaticText "Timestamp"
      StaticText "Chưa đọc"      ← present if unread
      StaticText "Sender Name: "
      StaticText "Message preview..."
    listitem level="1"            ← next message
      ...
```

Sidebar shortcuts (for mentions):
```
generic "Lối tắt đến Lượt đề cập, N tin nhắn chưa đọc"
  StaticText "Lượt đề cập"
  StaticText "N"                  ← unread mention count
```

## Error Handling

- If Chrome not connected / MCP server not running: instruct user to check Chrome DevTools MCP setup
- If Google Chat tab not found: open one with `new_page`
- If not logged in: instruct user to log in and re-run
- If home feed is empty or loading: wait briefly with `wait_for`, retry snapshot
- If message input not found when replying: take screenshot for debugging, skip reply
- If DOM structure changed: fall back to `evaluate_script` for data extraction

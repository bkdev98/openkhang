---
name: chat-reply
description: >-
  This skill should be invoked with "/chat-reply" to review and send
  pending draft replies queued by chat-scan. Allows approving, editing,
  or rejecting each draft before sending via Chrome DevTools MCP.
argument-hint: "[--send-all] [--reject-all]"
allowed-tools: ["Read", "Write", "Edit", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__list_pages", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__select_page", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__navigate_page", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_snapshot", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__evaluate_script", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__click", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__fill", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__press_key", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__wait_for"]
version: 0.2.0
---

# Chat Reply

Review and send pending draft replies from the autopilot queue via Chrome DevTools.

## Arguments

- `--send-all` — Approve and send all pending drafts without review
- `--reject-all` — Clear all pending drafts without sending

## Execution Flow

### 1. Load Pending Drafts

Read `.claude/gchat-autopilot.local.md` and extract `pending_drafts` list.

If no pending drafts, display: "No pending replies. Run /chat-scan to check for new messages."

### 2. Present Drafts for Review

Display each draft with context:

```
📝 Pending Replies (3)

[1] 🔴 Urgent — DM with Alice (2 min ago)
    Message: "Server is returning 500s on /api/users"
    Draft:   "Looking into this now"
    → (a)pprove / (e)dit / (s)kip / (r)eject

[2] 🟡 Action — #backend, Bob (15 min ago)
    Message: "Can you review PR #142?"
    Draft:   "Will review shortly"
    → (a)pprove / (e)dit / (s)kip / (r)eject

[3] 🟡 Action — DM with Carol (1 hr ago)
    Message: "Need the API spec by Thursday"
    Draft:   "On it, will share tomorrow"
    → (a)pprove / (e)dit / (s)kip / (r)eject
```

### 3. Process User Decisions

For each draft, handle the user's choice:

- **Approve**: Send the reply via Chrome DevTools (see Send Flow below). Remove from pending_drafts.

- **Edit**: Ask user for revised text, then send the edited version. Remove from pending_drafts.

- **Skip**: Leave in queue for next review cycle.

- **Reject**: Remove from pending_drafts without sending.

### 4. Send Flow (via Chrome DevTools)

There are two distinct flows: **DM/space replies** (direct messages) and **thread replies** (replying inside a thread in a space).

#### 4a. DM / Space Direct Reply

1. **Navigate to the conversation:**
   - Click on the DM or space in the sidebar to open it
   - `take_snapshot` to confirm the conversation loaded

2. **Find the main message input:**
   - Look for a `textbox` element with aria-label "Đã bật lịch sử" (history enabled) in the `main` region
   - This is the primary chat input — it appears at the bottom of the conversation

3. **Type and send:**
   - `click` the textbox uid to focus it
   - `fill` the textbox uid with the reply text
   - `press_key` with key `Enter` to send

4. **Verify sent:**
   - The snapshot after pressing Enter should show your message with "Đang gửi..." (Sending...)
   - Check the ARIA live region (at the bottom of the page) for `StaticText "Đã gửi tin nhắn"` (Message sent)
   - The sidebar unread count should decrease (e.g., "9 tin nhắn chưa đọc" → "8 tin nhắn chưa đọc")

#### 4b. Thread Reply (Space with threaded messages)

Thread replies require special handling because the thread reply input is often **not directly clickable** via its uid.

1. **Navigate to the space:**
   - Click on the space in the sidebar to open it
   - `take_snapshot` — the space shows messages in thread view with reply count buttons

2. **Open the thread panel:**
   - Find the target thread's reply count button: `button "N tin nhắn trả lời , Câu trả lời cuối cùng TIMESTAMP"`
   - `click` on that button to open the thread panel on the right side
   - `take_snapshot` — you should see the thread panel with the original message, replies, and a reply input

3. **Focus the thread reply input (use evaluate_script — direct click often times out):**
   - The thread reply textbox has aria-label "Trả lời" but is often not interactive via `click`
   - Use `evaluate_script` to focus it:
     ```js
     () => {
       const replyAreas = document.querySelectorAll('[contenteditable="true"]');
       for (const area of replyAreas) {
         const placeholder = area.getAttribute('aria-label') || area.textContent;
         if (placeholder.includes('Trả lời') || area.closest('[aria-label*="Trả lời"]')) {
           area.focus();
           area.click();
           return 'Found and focused thread reply area';
         }
       }
       if (replyAreas.length > 1) {
         replyAreas[replyAreas.length - 1].focus();
         replyAreas[replyAreas.length - 1].click();
         return 'Focused last contenteditable area (count: ' + replyAreas.length + ')';
       }
       return 'No reply area found. Count: ' + replyAreas.length;
     }
     ```

4. **Get the new uid for the focused textbox:**
   - `take_snapshot` after focusing — the thread reply textbox now appears as `textbox "Trả lời" focusable focused multiline`
   - Note the **new uid** (it changes each time the thread panel opens)

5. **Type and send:**
   - `fill` with the new textbox uid and reply text
   - `press_key` with key `Enter` to send

6. **Verify sent:**
   - Use `evaluate_script` to check the ARIA live region:
     ```js
     () => {
       const liveRegion = document.querySelector('[aria-live="assertive"]');
       return liveRegion ? liveRegion.textContent.trim() : 'no live region';
     }
     ```
   - Should return `"Đã gửi tin nhắn"` (Message sent)

#### Key UI Element Reference

| Element | Selector in snapshot | Notes |
|---------|---------------------|-------|
| Main chat input | `textbox "Đã bật lịch sử"` | Always present in DM/space view |
| Thread reply count | `button "N tin nhắn trả lời , Câu trả lời cuối cùng ..."` | Click to open thread panel |
| Thread reply input | `textbox "Trả lời"` | Use evaluate_script to focus, then take_snapshot for uid |
| Send confirmation | ARIA live region `"Đã gửi tin nhắn"` | Appears after successful send |
| Unread indicator | `StaticText "Chưa đọc"` | Disappears after reading/replying |

### 5. Update State

Write updated `pending_drafts` back to `.claude/gchat-autopilot.local.md`.

### 6. Summary

```
✅ Sent: 2 replies
⏭️ Skipped: 1 (still in queue)
🗑️ Rejected: 0

Next scan in ~5 min (if /loop active)
```

## Batch Mode

With `--send-all`: skip review, send all drafts via Chrome DevTools, clear queue.
With `--reject-all`: skip review, clear all drafts without sending.

Both modes display a summary of what was sent/cleared.

## Error Handling

- If Chrome tab not found: instruct user to open Google Chat in Chrome
- If space navigation fails: skip that reply, keep in queue, warn user
- If message input not found: take screenshot for debugging, skip reply
- If send appears to fail: keep draft in queue, notify user

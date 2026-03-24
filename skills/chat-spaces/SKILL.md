---
name: chat-spaces
description: >-
  This skill should be invoked with "/chat-spaces" to list and manage
  which Google Chat spaces and DMs the autopilot monitors. Reads the
  sidebar from Google Chat via Chrome DevTools MCP to discover spaces.
argument-hint: "[list|add|remove|refresh]"
allowed-tools: ["Read", "Write", "Edit", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__list_pages", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__select_page", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_snapshot", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__evaluate_script", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__click", "mcp__plugin_chrome-devtools-mcp_chrome-devtools__navigate_page"]
version: 0.2.0
---

# Chat Spaces

Manage monitored Google Chat spaces for the autopilot.

## Subcommands

### list (default)

Read the Google Chat sidebar via Chrome DevTools and display all spaces with monitoring status.

1. `list_pages` → find and `select_page` for Google Chat tab
2. `take_snapshot` → read the sidebar to extract all visible spaces
3. Cross-reference with `monitored_spaces` in state file

Output format:
```
📋 Google Chat Spaces (12 total, monitoring: all)

DMs:
  ✅ Alice Chen — last scan: 2 min ago
  ✅ Bob Kim — last scan: 2 min ago
  ...

Groups:
  ✅ #backend — last scan: 2 min ago
  ✅ #general — last scan: 2 min ago
  ❌ #random — not monitored
  ...
```

### add <space-name>

Add a specific space to the monitoring list.

1. `take_snapshot` → find the space in the sidebar by name
2. Extract the space ID from the sidebar entry (via snapshot or `evaluate_script`)
3. Add to `monitored_spaces` in state file

Only relevant when `monitored_spaces` is a whitelist (not "all").

### remove <space-name>

Remove a space from monitoring.

1. Find the space ID matching the name
2. If `monitored_spaces: all`, switch to explicit whitelist excluding the removed space
3. Update state file

### refresh

Re-read the sidebar to discover new spaces (new DMs or groups created since last check).

1. `list_pages` → find and `select_page` for Google Chat tab
2. `take_snapshot` → extract all spaces from sidebar
3. If sidebar is scrollable, scroll down and snapshot again to find more spaces
4. Compare with state file, report any new/removed spaces
5. Optionally update `monitored_spaces` with new entries

## State Management

Read and update `monitored_spaces` in `.claude/gchat-autopilot.local.md`.

- `monitored_spaces: all` — monitor everything (default)
- `monitored_spaces: [spaces/AAAA, spaces/CCCC]` — whitelist mode

## Identifying Spaces

Google Chat spaces in the sidebar show:
- **Group spaces**: Name like "#backend" or "[Team] Project Name"
- **DMs**: Person's name, sometimes with avatar
- **Unread badge**: Number or dot indicating new messages

Space IDs can be extracted from:
- The URL when navigating to a space (`chat.google.com/room/SPACE_ID`)
- Data attributes in the DOM via `evaluate_script`
- The sidebar snapshot entries

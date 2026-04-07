# Phase 5: Drafts Page

**Priority:** High
**Status:** Complete

## Overview

Full draft management: tabs for Pending/Approved/Rejected, search, historical records with timestamps.

## Related Code Files

**Modify:**
- `services/dashboard/app.py` — update `/api/drafts` to accept `status` and `search` params
- `services/dashboard/dashboard_services.py` — update `get_drafts()` with status filter + search
- `services/dashboard/templates/partials/draft_card.html` — update styling to new theme, add read-only mode for history

**Create:**
- `services/dashboard/templates/pages/drafts.html` — tab bar + search + draft list

## Implementation Steps

1. Update `get_drafts()` in dashboard_services.py: accept `status` param (pending/approved/rejected/all), `search` param (ILIKE on room_name + draft_text), `limit` + `offset` for pagination
2. Update `/api/drafts` endpoint: accept query params `?status=pending&search=&limit=20&offset=0`
3. Update draft_card.html: new warm theme colors, confidence badge per design, read-only mode for approved/rejected (no action buttons, show reviewed_at timestamp)
4. Create drafts.html: tab bar (Pending/Approved/Rejected), search input (debounced 300ms via htmx), draft list area
5. Tabs use HTMX: `hx-get="/api/drafts?status=approved"` targeting draft list
6. Approve/reject animations: card slides out on action
7. Pending tab auto-refreshes via HTMX polling (10s)

## Todo

- [x] Update get_drafts() with status filter + search + pagination
- [x] Update /api/drafts endpoint with query params
- [x] Update draft_card.html to new theme + read-only mode
- [x] Create drafts.html page with tabs + search
- [x] Wire up tab switching via HTMX
- [x] Add search debounce
- [x] Verify approve/reject still works

## Success Criteria

- 3 tabs: Pending (default), Approved, Rejected
- Search filters drafts by room or text
- Approved/Rejected tabs show historical records with timestamps
- Approve/Reject/Edit actions work on pending tab
- Pending tab auto-refreshes

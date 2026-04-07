# Phase 2: Overview Page

**Priority:** High
**Status:** Complete

## Overview

Command center view: stat cards with sparklines, recent pending drafts (compact), live activity feed (last 10 events). All SSE/HTMX powered.

## Related Code Files

**Modify:**
- `services/dashboard/app.py` — new `/api/stats/hourly` endpoint for sparkline data
- `services/dashboard/dashboard_services.py` — add `get_hourly_stats()` method

**Create:**
- `services/dashboard/templates/pages/overview.html` — main overview layout
- `services/dashboard/templates/partials/stat_card.html` — stat with sparkline SVG

**Reuse from other phases:**
- `partials/draft_card.html` (compact mode)
- `partials/activity_card.html`

## Implementation Steps

1. Add `get_hourly_stats()` to dashboard_services.py — query events grouped by hour (last 24h)
2. Add `/api/stats/hourly` endpoint returning JSON array for sparkline
3. Create stat_card.html partial: number + label + trend + inline SVG sparkline
4. Create overview.html: 4 stat cards grid + recent drafts section + live activity section
5. Stats update via HTMX polling (10s) or SSE
6. Recent drafts: `hx-get="/api/drafts"` with `limit=3` param, compact view
7. Live activity: SSE connection, last 10 events, uses activity_card.html partial

## Todo

- [x] Add get_hourly_stats() to dashboard_services.py
- [x] Add /api/stats/hourly endpoint
- [x] Create stat_card.html partial with sparkline SVG
- [x] Create overview.html page
- [x] Wire up SSE for live activity section
- [x] Verify real-time stat updates

## Success Criteria

- 4 stat cards display correct counts with sparkline trends
- Stats auto-refresh without page reload
- Recent drafts show max 3 pending, with approve/reject actions
- Live activity streams new events in real-time

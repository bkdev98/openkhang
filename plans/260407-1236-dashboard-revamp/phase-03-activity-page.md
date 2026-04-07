# Phase 3: Activity Page

**Priority:** High
**Status:** Complete

## Overview

Full activity log with human-readable cards, source filters, time-ago formatting, collapsible details, infinite scroll.

## Related Code Files

**Modify:**
- `services/dashboard/app.py` — add `/api/feed/history` for paginated older events, source filter param
- `services/dashboard/dashboard_services.py` — add source filter to `get_recent_events()`

**Create:**
- `services/dashboard/templates/pages/activity.html` — filter pills + SSE feed + scroll loader
- `services/dashboard/templates/partials/activity_card.html` — single event card with icon, time-ago, expandable

## Implementation Steps

1. Create activity_card.html: source icon (Lucide), source name (colored), actor, time-ago, summary line, collapsible details
2. Add event summary extraction logic: parse event_type + payload to generate human-readable summary
3. Create activity.html: source filter pills (All/Chat/Jira/GitLab/Confluence/Agent), SSE feed area
4. Add `/api/feed/history?before={ts}&source={src}&limit=20` for pagination
5. Infinite scroll: `hx-trigger="intersect once"` on sentinel element at bottom
6. SSE for new events: reuse existing `/api/feed`, format client-side with activity_card template
7. Time-ago formatting: JS function for "2m ago", "1h ago", "yesterday 14:30"

## Todo

- [x] Create activity_card.html partial
- [x] Implement event summary extraction (human-readable from payload)
- [x] Create activity.html page with filters
- [x] Add /api/feed/history endpoint with pagination + source filter
- [x] Implement infinite scroll with HTMX intersect
- [x] Add time-ago JS formatter
- [x] Wire SSE for live events

## Success Criteria

- Events display as readable cards with source icons and colors
- Source filter pills toggle correctly
- Infinite scroll loads older events
- New events appear via SSE in real-time
- Collapsible details show raw payload

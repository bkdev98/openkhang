# Dashboard Revamp Plan

**Date:** 2026-04-07
**Branch:** main
**Status:** Complete

## Overview

Complete redesign of the openkhang dashboard from a 3-column grid to a sidebar-nav multi-page app with warm terminal aesthetic. Fixes stats accuracy, unreadable activity feed, basic chat, and adds settings, memory browse, and knowledge drop features.

## Design Reference

- Design doc: `plans/reports/ui-ux-260407-1217-dashboard-revamp-design.md`
- HTMX patterns: `plans/reports/researcher-260407-1217-htmx-dashboard-patterns.md`

## Design Decisions (Unresolved → Resolved)

1. Chat history: 100 messages per session, pagination via HTMX
2. Settings: write directly to YAML config files (KISS)
3. Knowledge drop: 5MB limit, text/pdf/md only
4. Memory deletion: hard delete from Mem0
5. Sparkline: new `/api/stats/hourly` endpoint for 24h event counts

## Phases

| # | Phase | Status | Key Files |
|---|-------|--------|-----------|
| 1 | Base layout + sidebar + routing | ✓ Complete | base.html, app.py, style.css |
| 2 | Overview page (stats, recent drafts, live feed) | ✓ Complete | pages/overview.html, partials/* |
| 3 | Activity page (readable cards, filters) | ✓ Complete | pages/activity.html, partials/activity_card.html |
| 4 | Chat page (conversation UI) | ✓ Complete | pages/chat.html, partials/chat_bubble.html, twin_chat.py |
| 5 | Drafts page (tabs, history, search) | ✓ Complete | pages/drafts.html, dashboard_services.py |
| 6 | Memory + Knowledge drop page | ✓ Complete | pages/memory.html, memory_services.py |
| 7 | Settings page | ✓ Complete | pages/settings.html, settings_services.py |

## Completion Summary

All 7 phases completed successfully. Dashboard redesigned with sidebar navigation, 6 new pages, and warm terminal aesthetic. New architecture:

**Files Modified/Created:**
- `app.py` — Refactored to 280 LOC, added 33 routes, page rendering with HTMX support
- `api_routes.py` — NEW, extracted API logic (150 LOC)
- `dashboard_services.py` — Enhanced to 355 LOC with hourly stats, memory ops
- `templates/base.html` — Complete rewrite: sidebar + main content shell
- `templates/pages/` — 6 new pages (overview, activity, chat, drafts, memory, settings)
- `templates/partials/` — 5 new partials (stat_card, activity_card, chat_bubble, draft_card, sidebar)
- `templates/static/style.css` — New warm terminal theme, sidebar styles, animations

**Total Dashboard LOC:** ~2,500 (was ~2,000)
**Total Routes:** 33 (was ~10)
**Features Added:** Sidebar nav, 6 pages, memory search, settings, chat UI, real-time updates via SSE/HTMX

## Dependencies

- Phase 1 ✓ Base layout completed (foundation for all pages)
- Phases 2-7 ✓ All independent pages completed
- Reused partials across pages for consistency

## Tech Stack

FastAPI + HTMX 1.9 + Jinja2 + Tailwind CSS (CDN) + Lucide Icons + Inter font. No JS frameworks.

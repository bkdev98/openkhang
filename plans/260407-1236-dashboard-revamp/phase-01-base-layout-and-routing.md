# Phase 1: Base Layout, Sidebar, and HTMX Routing

**Priority:** Critical (blocks all other phases)
**Status:** Complete

## Overview

Replace the 3-column grid with sidebar navigation + main content area. Implement HTMX page routing so sidebar nav loads page partials without full page reloads.

## Key Insights

- Use `hx-get` + `hx-target="#main-content"` + `hx-push-url` for SPA-like navigation
- Server checks `HX-Request` header: return partial for HTMX, full page for direct URL access
- Sidebar collapses to icons on tablet, hidden with hamburger on mobile
- Health status + auto-reply toggle move to sidebar footer

## Related Code Files

**Modify:**
- `services/dashboard/templates/base.html` — complete rewrite: sidebar + main content shell
- `services/dashboard/templates/static/style.css` — new theme, animations, sidebar styles
- `services/dashboard/app.py` — add page routes, detect HX-Request for partial rendering

**Create:**
- `services/dashboard/templates/partials/sidebar.html` — nav items + health footer
- `services/dashboard/templates/pages/overview.html` — placeholder (Phase 2 fills in)

**Delete (after migration):**
- `services/dashboard/templates/index.html` — replaced by pages/overview.html

## Implementation Steps

1. Update `base.html`:
   - Add Google Fonts (Inter) + Lucide Icons CDN links
   - New Tailwind config with warm charcoal palette (ok-void, ok-srf, ok-raised, etc.)
   - Sidebar HTML structure: logo, nav items with icons, health footer, auto-reply toggle
   - Main content area: `<main id="main-content">` with page header slot
   - HTMX routing: nav links use `hx-get="/pages/{name}"` targeting `#main-content`
   - `hx-push-url="true"` on nav links for browser history
   - Active nav item highlighting via HTMX `hx-on::after-swap`

2. Update `style.css`:
   - Replace all ok-bg/ok-card/ok-accent/ok-blue/ok-border colors
   - Sidebar styles: width, collapsed state, transitions
   - Page transition animation (fade + translateY)
   - Updated scrollbar, feed-item, draft-card animations
   - Skeleton shimmer loading state
   - Reduced motion media query

3. Update `app.py`:
   - Add helper to detect HTMX requests: `request.headers.get("HX-Request")`
   - New route pattern: `GET /pages/{page_name}` returns partial or full page
   - Keep existing API routes unchanged
   - `GET /` redirects or renders overview

4. Create `partials/sidebar.html`:
   - Nav items with Lucide icons + labels + badge slots
   - Health status section (HTMX polled every 30s)
   - Auto-reply toggle button

5. Create placeholder `pages/overview.html`:
   - Simple "Overview" heading + loading placeholders
   - Will be filled in Phase 2

## Todo

- [x] Rewrite base.html with sidebar + main content layout
- [x] New Tailwind config with warm palette
- [x] Create sidebar.html partial with nav + health + auto-reply
- [x] Add HTMX page routing in app.py
- [x] Create pages/overview.html placeholder
- [x] Update style.css with new theme
- [x] Verify direct URL access works (full page) and HTMX nav works (partial)
- [x] Remove old index.html

## Success Criteria

- Sidebar renders with all 6 nav items and health footer
- Clicking nav items loads page content without full reload
- Browser back/forward works
- Direct URL access (e.g., /pages/chat) renders full page
- Auto-reply toggle works from sidebar
- Mobile responsive: sidebar collapses/hides appropriately

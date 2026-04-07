# openkhang Dashboard Revamp -- Design Document

**Date:** 2026-04-07
**Author:** UI/UX Designer
**Status:** Design Phase

---

## 1. Design Philosophy

**"Your terminal, evolved."** The openkhang dashboard is a personal command center that feels like an advanced terminal emulator crossed with a modern IDE -- warm, dense, intimate. It rejects the cold corporate SaaS aesthetic in favor of something a developer would build *for themselves*: information-dense but never cluttered, dark but never depressing, technical but never hostile. Think: the love child of Warp terminal, Linear, and a cozy late-night coding session.

Three guiding words: **Dense. Warm. Alive.**

---

## 2. Color Palette

Moving away from generic cold navy. The new palette uses warm charcoal bases with amber/green accents -- evoking a terminal that runs in a room with warm lighting.

### Core Tokens

| Token | Hex | Usage |
|-------|-----|-------|
| `--ok-void` | `#0C0C0F` | Page background (near-OLED black with warm undertone) |
| `--ok-surface` | `#141419` | Primary surface / cards |
| `--ok-surface-raised` | `#1C1C24` | Elevated cards, modals, dropdowns |
| `--ok-surface-hover` | `#24242E` | Hover states on surfaces |
| `--ok-border` | `#2A2A36` | Subtle borders, dividers |
| `--ok-border-focus` | `#3D3D4A` | Focus ring borders |

### Text

| Token | Hex | Usage |
|-------|-----|-------|
| `--ok-text` | `#E8E4DE` | Primary text (warm off-white, not harsh #FFF) |
| `--ok-text-secondary` | `#9B9690` | Secondary / muted text |
| `--ok-text-ghost` | `#5C5853` | Timestamps, IDs, tertiary info |

### Accents

| Token | Hex | Usage |
|-------|-----|-------|
| `--ok-amber` | `#E5A84B` | Primary accent -- CTAs, active nav, highlights |
| `--ok-amber-dim` | `#A07832` | Amber hover / pressed states |
| `--ok-green` | `#4ADE80` | Success states, approved, health OK |
| `--ok-green-dim` | `#166534` | Green backgrounds (badges) |
| `--ok-red` | `#F87171` | Error, rejected, destructive actions |
| `--ok-red-dim` | `#7F1D1D` | Red backgrounds (badges) |
| `--ok-cyan` | `#67E8F9` | Informational, links, secondary accent |
| `--ok-purple` | `#C084FC` | Labels, tags, categories |

### Source Colors (Activity Feed)

| Source | Color | Hex |
|--------|-------|-----|
| Google Chat | Amber | `#E5A84B` |
| Jira | Blue | `#60A5FA` |
| GitLab | Orange | `#FB923C` |
| Confluence | Cyan | `#67E8F9` |
| Agent | Purple | `#C084FC` |
| System | Ghost | `#5C5853` |

### Tailwind Config

```js
tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'ok-void':    '#0C0C0F',
        'ok-srf':     '#141419',
        'ok-raised':  '#1C1C24',
        'ok-hover':   '#24242E',
        'ok-border':  '#2A2A36',
        'ok-bfocus':  '#3D3D4A',
        'ok-text':    '#E8E4DE',
        'ok-muted':   '#9B9690',
        'ok-ghost':   '#5C5853',
        'ok-amber':   '#E5A84B',
        'ok-green':   '#4ADE80',
        'ok-red':     '#F87171',
        'ok-cyan':    '#67E8F9',
        'ok-purple':  '#C084FC',
      }
    }
  }
}
```

---

## 3. Typography

### Font Pairing: JetBrains Mono + Inter

- **JetBrains Mono** (monospace) -- headings, stats, code, IDs, timestamps. Already in use; keep it.
- **Inter** (sans-serif) -- body text, descriptions, form labels, chat messages. Excellent readability at small sizes, strong Vietnamese diacritical support.

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

### Type Scale

| Element | Font | Size | Weight | Line Height |
|---------|------|------|--------|-------------|
| Page title | JetBrains Mono | 18px | 600 | 1.3 |
| Section heading | JetBrains Mono | 14px | 500 | 1.3 |
| Nav item | Inter | 13px | 500 | 1.0 |
| Body text | Inter | 13px | 400 | 1.6 |
| Stat number | JetBrains Mono | 28px | 600 | 1.0 |
| Stat label | Inter | 11px | 400 | 1.3 |
| Badge / tag | Inter | 11px | 500 | 1.0 |
| Timestamp | JetBrains Mono | 11px | 400 | 1.0 |
| Code / ID | JetBrains Mono | 12px | 400 | 1.4 |

### Tailwind Config

```js
fontFamily: {
  mono: ['JetBrains Mono', 'monospace'],
  sans: ['Inter', 'system-ui', 'sans-serif'],
}
```

---

## 4. Layout Architecture

### Sidebar + Content Pattern

Replace the 3-column grid with a persistent left sidebar (240px collapsed to 56px on mobile) + scrollable main content area.

```
+--------+----------------------------------------------+
| SIDE   |  MAIN CONTENT                                |
| BAR    |                                              |
|        |                                              |
| [logo] |  +------ PAGE HEADER -----+                  |
|        |  | Page Title    [actions] |                  |
| [nav]  |  +-------------------------+                  |
| Ovrvw  |                                              |
| Chat   |  +------ CONTENT AREA ----+                  |
| Drafts |  |                        |                  |
| Actvty |  |  (varies by page)      |                  |
| Memory |  |                        |                  |
| Settng |  |                        |                  |
|        |  +------------------------+                  |
|        |                                              |
|--------|                                              |
|[health]|                                              |
|[status]|                                              |
+--------+----------------------------------------------+
```

### Sidebar Detail

```
+--240px---+
|           |
| openkhang |  <-- JetBrains Mono 16px, amber
| v0.2.0   |  <-- ghost text
|           |
| NAVIGATE  |  <-- section label, ghost, uppercase 10px
|           |
| > Overview|  <-- active: amber text + left border
|   Chat    |
|   Drafts  |  <-- badge count: pending drafts
|   Activity|
|   Memory  |
|   Settings|
|           |
|           |
|  -------- |  <-- divider
|  HEALTH   |  <-- section label
|  * Agent     OK |
|  * Memory    OK |
|  * Redis     OK |
|  * Bridge    OK |
|           |
|  Auto-reply|
|  [=== ON] |  <-- toggle switch, amber when ON
+----------+
```

### Main Content Area

- Max width: `1200px` (centered if viewport > sidebar + 1200px)
- Horizontal padding: `24px` (desktop), `16px` (tablet), `12px` (mobile)
- Content adapts per page (details in Section 7)

### Responsive Breakpoints

| Breakpoint | Sidebar | Content |
|------------|---------|---------|
| >= 1024px | Full 240px, expanded | Fluid main area |
| 768-1023px | Collapsed 56px (icons only) | Fluid, more space |
| < 768px | Hidden, hamburger menu overlay | Full width |

---

## 5. Component Design

### 5.1 Nav Item

```
+--240px-------------------+
| [icon]  Label        (3) |   <-- icon 16px, label Inter 13px 500, badge optional
+--240px-------------------+
```

- Default: `ok-muted` text, transparent bg
- Hover: `ok-text` text, `ok-hover` bg
- Active: `ok-amber` text, 2px left border amber, `ok-surface-raised` bg
- Badge: pill shape, `ok-amber` bg, `ok-void` text, for unread/pending counts

### 5.2 Stat Card (Overview)

```
+---------------------------+
|  [sparkline ~~~~~~~~]     |  <-- 40px tall SVG sparkline, amber stroke
|  47                       |  <-- JetBrains Mono 28px 600, ok-text
|  events today      +12%   |  <-- Inter 11px, ok-muted + ok-green for trend
+---------------------------+
```

- Background: `ok-surface`
- Border: 1px `ok-border`
- Border-radius: 8px
- Padding: 16px
- Sparkline: inline SVG, 24-point data, amber stroke (#E5A84B), 1.5px line, no fill
- Trend indicator: green up arrow for positive, red down for negative, ghost for neutral
- **SSE-powered**: counter animates (CSS `font-variant-numeric: tabular-nums`) on update

### 5.3 Activity Card

```
+-----------------------------------------------+
| [icon] google_chat    khanh.bui    2m ago     |  <-- source icon + color, actor, time-ago
| New message in #mobile-team                   |  <-- event summary, Inter 13px
| [v expand details]                            |  <-- collapsible raw JSON, ghost text
+-----------------------------------------------+
```

- Source icon: 14px inline SVG, colored per source (see Source Colors above)
- Source name: JetBrains Mono 11px, source color
- Actor: Inter 12px, `ok-muted`
- Time-ago: JetBrains Mono 11px, `ok-ghost`, right-aligned
- Summary: Inter 13px, `ok-text`, single line truncated
- Expandable details: click to reveal full payload in `<pre>` block, `ok-surface` bg
- Divider: 1px `ok-border` between cards (not card borders -- cleaner)
- Entry animation: `translateY(-8px) -> 0` + `opacity 0 -> 1`, 200ms ease-out

### 5.4 Chat Bubble

**Inward chat** (ask the twin) redesigned as a proper conversation window.

```
+-----------------------------------------------+
|  YOU                              10:32 AM     |
|  +------------------------------------------+ |
|  | How's the KMP migration going?           | |
|  +------------------------------------------+ |
|                                                |
|                     TWIN                10:32  |
|  +------------------------------------------+ |
|  | Based on your recent Jira tickets...     | |
|  | The migration is blocked on API 34...    | |
|  |                                          | |
|  | conf: 89%  |  latency: 340ms             | |
|  +------------------------------------------+ |
|                                                |
|  +--input-----------------------------------+ |
|  | Ask anything...                     [->] | |
|  +------------------------------------------+ |
+-----------------------------------------------+
```

- **Your messages**: right-aligned, `ok-amber` bg (opacity 15%), left-aligned text
- **Twin replies**: left-aligned, `ok-surface-raised` bg
- Bubble border-radius: 12px (with 4px on the "tail" corner)
- Message text: Inter 13px, `ok-text`
- Metadata (conf/latency): JetBrains Mono 11px, `ok-ghost`
- Markdown rendering in replies (via a small marked.js or similar CDN lib, ~8kb)
- **Typing indicator**: three dots pulsing animation (amber)
- Input: single-line `<input>` expanding to `<textarea>` on newline, `ok-surface` bg, amber border on focus
- Send button: amber circle with arrow icon, or Cmd+Enter shortcut
- Scrollable conversation history (last 50 messages in viewport, HTMX loads older)

### 5.5 Draft Card

```
+-----------------------------------------------+
|  #mobile-team              87%        2m ago  |  <-- room, confidence pill, time-ago
|  ------------------------------------------- |
|  "Can you review the PR for the new..."      |  <-- original message, italic, muted
|  ------------------------------------------- |
|  [editable draft text area]                   |  <-- textarea, mono 12px
|  ------------------------------------------- |
|  [Approve]  [Edit & Send]  [Reject]          |  <-- action buttons
+-----------------------------------------------+
```

- Confidence badge colors:
  - >= 80%: `ok-green` text on `ok-green-dim` bg
  - 50-79%: `ok-amber` text on `ok-amber/15%` bg
  - < 50%: `ok-red` text on `ok-red-dim` bg
- Approve button: `ok-green` outline, fills on hover
- Reject button: `ok-red` outline, fills on hover
- Edit & Send: `ok-amber` outline, fills on hover
- Card bg: `ok-surface`, 8px radius
- On approve/reject: card animates out (slide + fade, 300ms)

### 5.6 Settings Form

```
+-----------------------------------------------+
|  PERSONA                                      |  <-- section, JetBrains Mono 14px
|  ------------------------------------------- |
|  Display Name    [Khanh Bui                 ] |
|  Tone            [Professional, concise     ] |
|  Language         Vietnamese / English         |
|  ------------------------------------------- |
|                                                |
|  CONFIDENCE                                    |
|  ------------------------------------------- |
|  Default Threshold  [====|=========] 0.75     |  <-- range slider, amber
|  Per-room overrides...                        |
|  ------------------------------------------- |
|                                                |
|  INTEGRATIONS                                  |
|  ------------------------------------------- |
|  Jira     [https://jira.example.com  ] [Test]|
|  GitLab   [https://gitlab.example.com] [Test]|
|  ------------------------------------------- |
|                                                |
|  [Save Changes]                               |  <-- amber button
+-----------------------------------------------+
```

- Form inputs: `ok-surface` bg, `ok-border` border, `ok-bfocus` on focus, 6px radius
- Labels: Inter 12px, `ok-muted`, above input
- Section headers: JetBrains Mono 14px 500, `ok-text`
- Range slider: custom-styled, amber thumb, `ok-border` track
- "Test" buttons: small, `ok-cyan` outline, triggers connection check
- Save: amber fill, `ok-void` text, full width at bottom of section

### 5.7 Memory Card

```
+-----------------------------------------------+
|  [type: episodic]       2026-04-06 14:30      |  <-- type badge, timestamp
|  ------------------------------------------- |
|  "Khanh prefers short replies in group chats  |  <-- memory text, Inter 13px
|   and detailed replies in DMs."               |
|  ------------------------------------------- |
|  Source: google_chat / DM        [Delete]     |  <-- metadata + delete
+-----------------------------------------------+
```

- Type badges: `semantic` = cyan, `episodic` = purple, `working` = amber
- Memory text: Inter 13px, `ok-text`, max 3 lines then truncate with "show more"
- Delete button: `ok-ghost` text, turns `ok-red` on hover, requires confirmation
- Search bar at top: JetBrains Mono input, amber focus ring, magnifying glass icon

---

## 6. Micro-interactions

### Transitions

| Element | Trigger | Animation |
|---------|---------|-----------|
| Nav item | hover | bg-color 150ms ease |
| Nav item | active switch | left-border slide-in 200ms |
| Page content | page switch | fade-in 150ms + translateY(4px -> 0) |
| Stat counter | SSE update | number morphs (CSS `transition: all 300ms`) |
| Activity card | new event | slideDown 200ms + fadeIn |
| Draft card | approve/reject | slideOut 300ms + fadeOut |
| Chat bubble | new message | fadeIn 200ms + translateY(8px -> 0) |
| Typing indicator | toggle | 3 dots pulse (scale 0.6 -> 1), staggered 100ms |
| Toggle switch | click | thumb slides 200ms ease, bg-color 200ms |
| Sparkline | hover | tooltip appears with exact value |
| Health dot | status change | scale pulse 0.8 -> 1.2 -> 1.0, 400ms |

### Hover States

- Cards: `box-shadow: 0 0 0 1px var(--ok-bfocus)` (subtle glow border)
- Buttons: slight brightness increase (`filter: brightness(1.1)`)
- Links/clickable text: underline appears, color shifts to `ok-amber`

### Loading States

- HTMX requests: skeleton shimmer (linear-gradient animation on placeholder elements)
- Chat thinking: animated ellipsis with amber color
- Page transitions: subtle progress bar at top (2px, amber, left-to-right)

### Focus States

- All interactive elements: 2px `ok-amber` outline with 2px offset (accessibility)
- Tab navigation fully supported

### Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 7. Page Breakdown

### 7.1 Overview (Default Page)

The command center view. Dense, at-a-glance status of everything.

```
+-----------------------------------------------+
|  OVERVIEW                                      |
|                                                |
|  +------+ +------+ +------+ +------+          |
|  | Pend | | Evts | | Appr | | Totl |          |
|  |  3   | |  47  | |  12  | | 2.4k |          |
|  | ~drft| | ~tday| | ~tday| | ~evnt|          |
|  +------+ +------+ +------+ +------+          |
|                                                |
|  RECENT DRAFTS (3 pending)     [View All ->]  |
|  +--------------------------------------------+|
|  | [draft card 1]                             ||
|  | [draft card 2]                             ||
|  | [draft card 3]                             ||
|  +--------------------------------------------+|
|                                                |
|  LIVE ACTIVITY                  [View All ->] |
|  +--------------------------------------------+|
|  | [activity card 1]                          ||
|  | [activity card 2]                          ||
|  | [activity card 3]                          ||
|  | [activity card 4]                          ||
|  | [activity card 5]                          ||
|  +--------------------------------------------+|
+-----------------------------------------------+
```

- 4 stat cards in a row (responsive: 2x2 on tablet, stacked on mobile)
- Recent drafts: max 3, only pending, compact view (no edit textarea -- just approve/reject)
- Live activity: SSE feed, last 10 events, auto-scroll
- Quick actions embedded where relevant

### 7.2 Chat

Full conversation interface with the twin (inward mode).

```
+-----------------------------------------------+
|  CHAT                         [Clear History] |
|                                                |
|  +-- conversation scroll area ---------------+|
|  |                                            ||
|  |  [bubble: your message]                    ||
|  |  [bubble: twin reply]                      ||
|  |  [bubble: your message]                    ||
|  |  [bubble: twin reply with markdown]        ||
|  |  ...                                       ||
|  |                                            ||
|  +--------------------------------------------+|
|                                                |
|  +-- input area -----------------------------+|
|  | [text input]                        [Send]||
|  +--------------------------------------------+|
+-----------------------------------------------+
```

- Conversation persists in session (stored server-side, loaded on page visit)
- Markdown rendered in twin replies
- Keyboard shortcut: Cmd+Enter to send
- HTMX post, response replaces/appends in conversation area
- "Thinking..." indicator while waiting

### 7.3 Drafts

Full draft management with tabs.

```
+-----------------------------------------------+
|  DRAFTS                                        |
|                                                |
|  [Pending (3)]  [Approved]  [Rejected]        |  <-- tab bar
|                                                |
|  +-- search bar ----------------------------+ |
|  | [Search drafts...]                        | |
|  +-------------------------------------------+ |
|                                                |
|  +-- draft list -----------------------------+|
|  | [full draft card 1 with edit textarea]     ||
|  | [full draft card 2 with edit textarea]     ||
|  | [full draft card 3 with edit textarea]     ||
|  +--------------------------------------------+|
+-----------------------------------------------+
```

- Tabs: Pending (default, SSE auto-refresh), Approved (history), Rejected (history)
- Each tab loads via HTMX (`hx-get="/api/drafts?status=pending"`)
- Search filters by room name or draft text content
- Approved/Rejected tabs show read-only cards with timestamp of action
- Sort: newest first (default), toggle to oldest first

### 7.4 Activity

Full activity log with filtering.

```
+-----------------------------------------------+
|  ACTIVITY                                      |
|                                                |
|  [All] [Chat] [Jira] [GitLab] [Confluence]   |  <-- source filters
|                                                |
|  +-- feed (SSE-powered) --------------------+ |
|  | [activity card]                           | |
|  | [activity card]                           | |
|  | [activity card]                           | |
|  | [activity card]                           | |
|  | ... infinite scroll via HTMX             | |
|  +-------------------------------------------+ |
+-----------------------------------------------+
```

- Source filter pills: colored per source, toggle on/off
- SSE for new events, HTMX `hx-get` for loading older events on scroll
- Time-ago formatting: "2m ago", "1h ago", "yesterday 14:30"
- Collapsible details on each card (click to expand raw payload)

### 7.5 Memory

Browse and search Mem0 memories.

```
+-----------------------------------------------+
|  MEMORY                                        |
|                                                |
|  +-- search bar ----------------------------+ |
|  | [Search memories...]                      | |
|  +-------------------------------------------+ |
|                                                |
|  [All] [Semantic] [Episodic] [Working]        |  <-- type filter
|                                                |
|  +-- results --------------------------------+|
|  | [memory card 1]                            ||
|  | [memory card 2]                            ||
|  | [memory card 3]                            ||
|  +--------------------------------------------+|
|                                                |
|  KNOWLEDGE DROP                                |
|  +-------------------------------------------+|
|  | Paste text or drop a file to ingest       ||
|  | [textarea / drop zone]                    ||
|  | Source label: [__________]                ||
|  | [Ingest]                                  ||
|  +-------------------------------------------+|
+-----------------------------------------------+
```

- Search: HTMX `hx-get="/api/memory/search?q=..."`, debounced 300ms
- Type filter pills (cyan, purple, amber per type)
- Memory cards: text preview, source, timestamp, delete button
- Knowledge Drop section at bottom: textarea or file drop zone, source label input, ingest button
- File drop: highlights drop zone with amber dashed border, shows file name on drop

### 7.6 Settings

System configuration.

```
+-----------------------------------------------+
|  SETTINGS                                      |
|                                                |
|  PERSONA                                       |
|  [form fields: name, tone, language, etc.]    |
|                                                |
|  CONFIDENCE                                    |
|  [default threshold slider]                    |
|  [per-room override table]                    |
|                                                |
|  PROJECTS                                      |
|  [repo list with add/remove]                  |
|                                                |
|  INTEGRATIONS                                  |
|  [jira/gitlab/confluence URL + token fields]  |
|  [connection test buttons]                    |
|                                                |
|  AUTO-REPLY                                    |
|  [toggle + description of behavior]           |
|                                                |
|  [Save All Changes]                           |
+-----------------------------------------------+
```

- All settings load from config YAML files
- Save writes to config files (API endpoint)
- Connection test buttons show inline success/error status
- Auto-reply toggle: large, prominent, amber when ON

---

## 8. Iconography

Use **Lucide Icons** (CDN, MIT license, 1000+ icons, 24x24 default).

```html
<script src="https://unpkg.com/lucide@latest"></script>
```

Key icon mapping:

| Element | Icon | Lucide Name |
|---------|------|-------------|
| Overview | grid layout | `layout-dashboard` |
| Chat | message circle | `message-circle` |
| Drafts | file edit | `file-edit` |
| Activity | activity pulse | `activity` |
| Memory | brain | `brain` |
| Settings | sliders | `sliders-horizontal` |
| Google Chat | message square | `message-square` |
| Jira | ticket | `ticket` |
| GitLab | git merge | `git-merge-queue` |
| Confluence | book open | `book-open` |
| Health OK | circle check | `circle-check` |
| Health Error | circle x | `circle-x` |
| Expand | chevron down | `chevron-down` |
| Send | arrow up | `arrow-up` |
| Delete | trash 2 | `trash-2` |
| Search | search | `search` |

---

## 9. Service Health (Sidebar Footer)

Health moves from a full panel to a compact sidebar footer. Always visible, never takes prime real estate.

```
+--sidebar-bottom----------+
|  SYSTEM                   |
|  * Agent      OK          |  <-- green dot
|  * Memory     OK          |
|  * Redis      ERR         |  <-- red dot, text turns red
|  * Bridge     OK          |
|                           |
|  Auto-reply  [==|==] ON  |  <-- toggle, amber
+---------------------------+
```

- Status dots: 6px circles, `ok-green` or `ok-red`
- Service name: JetBrains Mono 11px
- Status text: same 11px, green or red per status
- Polled every 30s via HTMX (`hx-get="/api/health"`)
- On error: subtle red glow on the sidebar section (box-shadow)

---

## 10. HTMX / SSE Integration Notes

### Page Routing via HTMX

- Sidebar nav clicks use `hx-get="/pages/overview"` (or chat, drafts, etc.)
- Target: `#main-content` (the content area right of sidebar)
- Swap: `innerHTML` with fade transition via `hx-swap="innerHTML transition:true"`
- URL updates via `hx-push-url="true"` for browser back/forward support
- Each "page" is a Jinja2 partial loaded into the main content slot

### SSE Channels

| Channel | Endpoint | Powers |
|---------|----------|--------|
| Activity feed | `/api/feed` | Live events on Overview + Activity pages |
| Stats | `/api/stats/stream` | Real-time stat counter updates |
| Drafts | `/api/drafts/stream` | New draft notifications + badge count |

### Polling Fallbacks

- Health: 30s polling (low frequency, fine without SSE)
- Memory search: on-demand (user-triggered)
- Settings: load once, save on action

---

## 11. Accessibility Checklist

- [x] Color contrast >= 4.5:1 for text (verified: `#E8E4DE` on `#0C0C0F` = 15.2:1)
- [x] Color contrast >= 3:1 for large text and UI components
- [x] Focus indicators on all interactive elements (2px amber outline)
- [x] Keyboard navigation: Tab through all nav items, form fields, buttons
- [x] ARIA labels on icon-only buttons and nav items
- [x] `prefers-reduced-motion` respected
- [x] Touch targets >= 44x44px on mobile
- [x] Semantic HTML: `<nav>`, `<main>`, `<article>`, `<aside>`, `<button>`
- [x] Screen reader: all icons have `aria-hidden="true"` + adjacent text labels
- [x] Vietnamese diacritical marks render correctly (Inter + JetBrains Mono both support)

---

## 12. File / Template Structure (Proposed)

```
services/dashboard/templates/
  base.html                    # Shell: sidebar + #main-content slot
  pages/
    overview.html              # Stats + recent drafts + live feed
    chat.html                  # Full conversation interface
    drafts.html                # Tabs: pending/approved/rejected
    activity.html              # Full filterable feed
    memory.html                # Search + browse + knowledge drop
    settings.html              # All config forms
  partials/
    sidebar.html               # Nav + health footer
    stat_card.html             # Single stat with sparkline
    activity_card.html         # Single activity event
    chat_bubble.html           # Single message bubble
    draft_card.html            # Single draft with actions
    memory_card.html           # Single memory entry
    health_status.html         # Sidebar health section
    typing_indicator.html      # Chat typing dots
```

---

## Unresolved Questions

1. **Chat history persistence** -- How many messages to keep server-side per session? Propose 100 with pagination.
2. **Settings write-back** -- Should settings API write directly to YAML config files, or use a DB table with config sync?
3. **Knowledge ingestion** -- Max file size for knowledge drop? Propose 5MB limit, text/pdf/markdown only.
4. **Memory deletion** -- Soft delete (mark as hidden) or hard delete from Mem0?
5. **Sparkline data source** -- Need a new API endpoint for hourly event counts (last 24h). Does this exist?

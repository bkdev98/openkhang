---
phase: 5
title: Dashboard
status: Pending
priority: P2
effort: 6h
depends_on: [3]
---

# Phase 5: Dashboard

## Context Links

- Phase 3: [Dual-Mode Agent](phase-03-dual-mode-agent.md) — draft queue, agent results
- Phase 4: [Workflow Engine](phase-04-workflow-engine.md) — approval queue, audit log
- Existing status skill: `skills/openkhang-status/SKILL.md`

## Overview

FastAPI + HTMX + TailwindCSS web dashboard with SSE real-time updates. Replaces the CLI-only `/openkhang-status` with a persistent UI for draft review, workflow approvals, activity feed, and service health monitoring.

## Key Insights

- HTMX: server-rendered HTML fragments over SSE — no JavaScript framework, minimal complexity
- TailwindCSS via CDN (no build step) — KISS
- SSE for real-time: agent results, new drafts, workflow state changes, service health
- Docker socket access for container health monitoring
- Dashboard IS the primary inward-mode interface for the digital twin

## Requirements

### Functional
- F1: Activity feed — real-time SSE stream of all events (chat, jira, gitlab, agent actions)
- F2: Draft review queue — view pending drafts, approve/edit/reject, see confidence + evidence
- F3: Workflow approvals — view pending T3 actions, approve/reject with context
- F4: Service health — Docker container status (Synapse, bridge, Postgres, Redis, agent)
- F5: Entity graph — visual map of linked items (tickets ↔ MRs ↔ chats ↔ pages)
- F6: Inward mode chat — text input to ask the twin questions, get reports
- F7: Confidence tuning — adjust per-space thresholds, view graduation status

### Non-Functional
- NF1: Page load <1s, SSE events <100ms latency
- NF2: Works on localhost only (no public exposure needed)
- NF3: Mobile-responsive (sometimes check from phone on same network)
- NF4: No JavaScript build step — HTMX + Tailwind CDN only

## Architecture

```
Browser ──HTTP──→ FastAPI (Uvicorn)
    │                  │
    │              ┌───┴───┐
    │              │Routes  │
    │              │        │
    │   ┌─────────┼────────┼──────────┐
    │   │         │        │          │
    │   ▼         ▼        ▼          ▼
    │  /feed    /drafts  /workflows  /health
    │  (SSE)   (CRUD)   (approvals) (Docker)
    │                                  │
    │                           Docker socket
    │
    └──SSE──→ Redis pub/sub channels
              openkhang:agent_results
              openkhang:workflow_updates
              openkhang:events
```

### Data Flow

1. **Activity Feed**: Redis `openkhang:events` → SSE → `<div id="feed">` (HTMX swap append)
2. **Draft Review**: `GET /drafts` → Postgres draft_replies → HTML table. Approve button → `POST /drafts/{id}/approve` → Matrix send → SSE update
3. **Workflow Approvals**: `GET /approvals` → Postgres approval_queue → HTML cards. Action → `POST /approvals/{id}/approve` → workflow engine resumes
4. **Service Health**: `GET /health` → Docker socket → container status JSON → HTML badges. Polled every 30s via HTMX `hx-trigger="every 30s"`
5. **Inward Chat**: `POST /chat` with message → agent pipeline (inward mode) → SSE response stream

## Related Code Files

### Create
- `services/dashboard/__init__.py`
- `services/dashboard/app.py` — FastAPI app factory + routes
- `services/dashboard/routes/feed.py` — Activity feed SSE endpoint
- `services/dashboard/routes/drafts.py` — Draft review CRUD
- `services/dashboard/routes/approvals.py` — Workflow approval endpoints
- `services/dashboard/routes/health.py` — Docker container health
- `services/dashboard/routes/chat.py` — Inward mode chat endpoint
- `services/dashboard/routes/settings.py` — Confidence thresholds, persona config
- `services/dashboard/sse.py` — SSE helper (Redis sub → EventSourceResponse)
- `services/dashboard/templates/base.html` — Layout with Tailwind CDN + HTMX
- `services/dashboard/templates/index.html` — Main dashboard page
- `services/dashboard/templates/partials/feed_item.html` — Single feed item fragment
- `services/dashboard/templates/partials/draft_card.html` — Draft review card
- `services/dashboard/templates/partials/approval_card.html` — Approval card
- `services/dashboard/templates/partials/health_badge.html` — Service health badge
- `services/dashboard/Dockerfile` — Dashboard service container

### Modify
- `docker-compose.yml` — Add dashboard service, expose port 8080

### No Deletes

## Implementation Steps

1. **FastAPI App Skeleton**
   - Create app factory with Jinja2 templates, static files
   - Mount routes: `/`, `/feed`, `/drafts`, `/approvals`, `/health`, `/chat`, `/settings`
   - CORS middleware (localhost only)
   - Lifespan: connect Redis, connect Postgres on startup

2. **Base Template**
   ```html
   <!-- Tailwind CDN + HTMX CDN, no build step -->
   <script src="https://unpkg.com/htmx.org@2"></script>
   <script src="https://unpkg.com/htmx-ext-sse@2"></script>
   <script src="https://cdn.tailwindcss.com"></script>
   ```
   - Sidebar nav: Feed | Drafts | Approvals | Health | Chat | Settings
   - Dark mode default (developer preference)
   - Status bar: connection indicator, pending counts

3. **Activity Feed (SSE)**
   - FastAPI SSE endpoint using `sse-starlette`
   - Subscribe to Redis channels: `openkhang:events`, `openkhang:agent_results`
   - Format events as HTML fragments (server-rendered)
   - HTMX: `hx-ext="sse" sse-connect="/feed/stream" sse-swap="message"` on feed container
   - Each item: timestamp, source icon, summary, expandable details

4. **Draft Review Queue**
   - `GET /drafts` — list pending drafts from Postgres, render as cards
   - Each card: original message, draft reply, confidence score bar, evidence citations
   - Actions: Approve (send as-is), Edit (textarea → send edited), Reject (discard)
   - `POST /drafts/{id}/approve` → call Matrix sender → mark reviewed
   - `POST /drafts/{id}/edit` → update text → call Matrix sender → mark reviewed
   - `POST /drafts/{id}/reject` → mark rejected
   - HTMX: actions swap the card with result status (no page reload)

5. **Workflow Approvals**
   - `GET /approvals` — list pending T3 approvals from Postgres
   - Each card: workflow name, action type, parameters, context summary
   - Actions: Approve / Reject
   - On approve: publish to Redis → workflow engine picks up → resumes state machine
   - HTMX: same swap pattern as drafts

6. **Service Health**
   - Mount Docker socket: `/var/run/docker.sock` into dashboard container
   - Use `docker` Python SDK to list containers, get status
   - Filter to openkhang-related containers (by label or name prefix)
   - Display: container name, status (running/stopped/error), uptime, restart count
   - Poll every 30s via HTMX `hx-trigger="every 30s"` on health section

7. **Inward Mode Chat**
   - Simple chat interface: input box + message history
   - `POST /chat` → agent pipeline (inward mode) → stream response via SSE
   - Display: user message (right-aligned), twin response (left-aligned)
   - Support markdown rendering in responses (use marked.js CDN)

8. **Settings Page**
   - View/edit persona.yaml (read-only display, edit via form)
   - Per-space confidence thresholds: slider per space, save to config
   - Graduation status: spaces with auto-reply enabled, approval rate history
   - Agent mode toggle: enable/disable outward mode globally (kill switch)

9. **Dockerfile**
   - Python 3.11 slim base
   - Install: fastapi, uvicorn, jinja2, sse-starlette, redis, asyncpg, docker
   - Expose port 8080
   - CMD: `uvicorn services.dashboard.app:create_app --host 0.0.0.0 --port 8080`

10. **Write Tests**
    - Unit: route handlers with mocked DB/Redis
    - Integration: draft approve flow end-to-end
    - SSE: verify event stream format

## TODO

- [ ] Create FastAPI app skeleton with Jinja2
- [ ] Create base template (Tailwind + HTMX, dark mode)
- [ ] Implement activity feed SSE endpoint
- [ ] Implement draft review queue (list + approve/edit/reject)
- [ ] Implement workflow approval endpoints
- [ ] Implement service health via Docker socket
- [ ] Implement inward mode chat interface
- [ ] Implement settings page
- [ ] Create Dockerfile for dashboard service
- [ ] Add to docker-compose.yml
- [ ] Write tests

## Success Criteria

1. Dashboard loads at `http://localhost:8080` in <1s
2. Activity feed shows real-time events as they arrive via SSE
3. Draft review: approve sends message via Matrix, card updates without page reload
4. Service health shows all Docker containers with correct status
5. Inward chat: "what did I work on today?" returns accurate summary from memory
6. Kill switch: toggling outward mode OFF immediately stops all auto-replies

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| HTMX SSE connection drops | Medium | Low | Auto-reconnect built into htmx-ext-sse, show indicator |
| Docker socket security | Low | Medium | Read-only mount, localhost-only access, no public exposure |
| Template rendering slow with large feed | Low | Low | Paginate feed, limit to last 100 items, virtual scroll |
| Tailwind CDN unavailable offline | Low | Low | Pin version, add fallback local copy |

## Security Considerations

- Dashboard runs on localhost only — no auth required (single-user system)
- Docker socket mounted read-only
- No secrets in templates or client-side code
- CSP headers to prevent XSS (HTMX is safe by default — no eval)
- If ever exposed beyond localhost: add basic auth middleware

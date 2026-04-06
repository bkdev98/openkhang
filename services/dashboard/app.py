"""FastAPI dashboard app: routes, SSE activity feed, HTMX endpoints.

Run with:
    uvicorn services.dashboard.app:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .dashboard_services import DashboardServices
from .inbox_relay import tail_inbox

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = TEMPLATES_DIR / "static"

# Shared service instance (initialised in lifespan)
_svc: DashboardServices | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise and tear down shared services."""
    global _svc
    _svc = DashboardServices()
    relay_task = None
    try:
        await _svc.connect()
        logger.info("Dashboard services connected")
        # Start inbox relay to feed new chat messages into events table
        if _svc._pool:
            relay_task = asyncio.create_task(tail_inbox(_svc._pool))
            logger.info("Inbox relay started")
    except Exception as exc:
        logger.warning("Dashboard services connect failed (running degraded): %s", exc)
    yield
    if relay_task:
        relay_task.cancel()
    if _svc:
        await _svc.close()


app = FastAPI(title="openkhang Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def svc() -> DashboardServices:
    """Return initialised services or raise if not ready."""
    if _svc is None:
        raise RuntimeError("Services not initialised")
    return _svc


# ------------------------------------------------------------------
# Main page
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render main dashboard page."""
    return templates.TemplateResponse(request, "index.html")


# ------------------------------------------------------------------
# SSE: real-time activity feed
# ------------------------------------------------------------------

@app.get("/api/feed")
async def activity_feed(request: Request):
    """Server-Sent Events stream of episodic events (polls every 2s)."""
    async def event_generator():
        last_ts: str | None = None
        # Send initial batch
        try:
            events = await svc().get_recent_events(limit=15)
            for event in reversed(events):
                last_ts = event.get("created_at")
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        # Poll for new events
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(2)
            try:
                new_events = await svc().get_recent_events(since=last_ts, limit=10)
                for event in reversed(new_events):
                    last_ts = event.get("created_at")
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as exc:
                logger.warning("SSE poll error: %s", exc)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------
# Drafts: HTMX partial
# ------------------------------------------------------------------

@app.get("/api/drafts", response_class=HTMLResponse)
async def list_drafts(request: Request):
    """Return rendered drafts list partial for HTMX."""
    try:
        drafts = await svc().get_drafts()
    except Exception as exc:
        logger.error("list_drafts error: %s", exc)
        drafts = []
    return templates.TemplateResponse(request, "partials/drafts_list.html", {"drafts": drafts})


@app.post("/api/drafts/{draft_id}/approve", response_class=HTMLResponse)
async def approve_draft(request: Request, draft_id: str):
    """Approve a pending draft reply."""
    ok = await svc().approve_draft(draft_id)
    if not ok:
        return HTMLResponse(
            '<p class="text-red-400 text-xs">Failed to approve (not found or already processed)</p>',
            status_code=400,
        )
    # Re-render drafts list after action
    drafts = await svc().get_drafts()
    return templates.TemplateResponse(request, "partials/drafts_list.html", {"drafts": drafts})


@app.post("/api/drafts/{draft_id}/reject", response_class=HTMLResponse)
async def reject_draft(request: Request, draft_id: str):
    """Reject a pending draft reply."""
    ok = await svc().reject_draft(draft_id)
    if not ok:
        return HTMLResponse(
            '<p class="text-red-400 text-xs">Failed to reject (not found or already processed)</p>',
            status_code=400,
        )
    drafts = await svc().get_drafts()
    return templates.TemplateResponse(request, "partials/drafts_list.html", {"drafts": drafts})


@app.post("/api/drafts/{draft_id}/edit", response_class=HTMLResponse)
async def edit_draft(request: Request, draft_id: str, edited_text: str = Form(...)):
    """Edit draft text and mark approved."""
    ok = await svc().edit_draft(draft_id, edited_text)
    if not ok:
        return HTMLResponse(
            '<p class="text-red-400 text-xs">Failed to edit (not found or already processed)</p>',
            status_code=400,
        )
    drafts = await svc().get_drafts()
    return templates.TemplateResponse(request, "partials/drafts_list.html", {"drafts": drafts})


# ------------------------------------------------------------------
# Health panel: HTMX partial
# ------------------------------------------------------------------

@app.get("/api/health", response_class=HTMLResponse)
async def health_panel(request: Request):
    """Return rendered health panel partial for HTMX."""
    try:
        services = await svc().get_health()
    except Exception as exc:
        logger.error("health_panel error: %s", exc)
        services = []
    return templates.TemplateResponse(request, "partials/health_panel.html", {"services": services})


# ------------------------------------------------------------------
# Stats bar: HTMX partial
# ------------------------------------------------------------------

@app.get("/api/stats", response_class=HTMLResponse)
async def stats_bar(request: Request):
    """Return rendered stats bar partial for HTMX."""
    try:
        stats = await svc().get_stats()
    except Exception as exc:
        logger.error("stats_bar error: %s", exc)
        stats = {}
    return templates.TemplateResponse(request, "partials/stats_bar.html", {"stats": stats})


# ------------------------------------------------------------------
# Inward chat: ask the twin
# ------------------------------------------------------------------

@app.post("/api/chat", response_class=HTMLResponse)
async def chat(request: Request, question: str = Form(...)):
    """Process inward-mode question through agent pipeline."""
    question = question.strip()
    if not question:
        return HTMLResponse('<p class="text-yellow-400 text-sm">Please enter a question.</p>')
    try:
        result = await svc().ask_twin(question)
    except Exception as exc:
        return HTMLResponse(
            f'<p class="text-red-400 text-sm">Error: {exc}</p>',
            status_code=500,
        )
    return templates.TemplateResponse(request, "partials/chat_input.html", {"result": result, "question": question})

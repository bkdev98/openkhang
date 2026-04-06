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
from .agent_relay import run_agent_relay

logger = logging.getLogger(__name__)

# Suppress noisy Mem0 "Invalid JSON response" warnings from Gemini extraction
class _Mem0JsonFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Invalid JSON response" not in record.getMessage()

for _name in ("mem0", "mem0.memory.main", "mem0.client.main"):
    logging.getLogger(_name).addFilter(_Mem0JsonFilter())

# Suppress google-genai deprecation warning
import warnings
warnings.filterwarnings("ignore", message=".*Inheritance class AiohttpClientSession.*")

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
    agent_task = None
    telegram_task = None
    telegram_poll_task = None
    scheduler = None
    try:
        await _svc.connect()
        logger.info("Dashboard services connected")
        if _svc._pool:
            # Tail JSONL → events table
            relay_task = asyncio.create_task(tail_inbox(_svc._pool))
            logger.info("Inbox relay started")
            # Process new chat events through agent pipeline → draft replies
            agent_task = asyncio.create_task(run_agent_relay(_svc._pool))
            logger.info("Agent relay started")
            # Start continuous knowledge ingestion (Jira 5min, GitLab 5min, Confluence 1hr)
            try:
                from services.memory.config import MemoryConfig
                from services.memory.client import MemoryClient
                from services.ingestion.scheduler import IngestionScheduler
                from services.ingestion.sync_state import SyncStateStore

                config = MemoryConfig.from_env()
                memory = MemoryClient(config)
                await memory.connect()
                sync_store = SyncStateStore(config.database_url)
                await sync_store.connect()
                scheduler = IngestionScheduler(memory, sync_store)
                await scheduler.start()
                logger.info("Ingestion scheduler started (Jira/GitLab/Confluence)")
            except Exception as exc:
                logger.warning("Ingestion scheduler failed to start: %s", exc)
            # Telegram bot (opt-in via TELEGRAM_BOT_TOKEN)
            try:
                from services.telegram.bot import init_bot, set_pool, bot as tg_bot, dp as tg_dp
                result = init_bot()
                if result:
                    set_pool(_svc._pool)
                    from services.telegram.bot import bot as tg_bot, dp as tg_dp
                    from services.telegram.notifier import run_notifier
                    telegram_task = asyncio.create_task(run_notifier(_svc._pool))
                    # Start polling for commands (no webhook needed for local dev)
                    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "")
                    if webhook_url:
                        await tg_bot.set_webhook(webhook_url + "/telegram/webhook")
                        logger.info("Telegram webhook set: %s", webhook_url)
                    else:
                        # Polling mode: process incoming commands via long-polling
                        async def _poll_telegram():
                            await tg_dp.start_polling(tg_bot, handle_signals=False)
                        telegram_poll_task = asyncio.create_task(_poll_telegram())
                        logger.info("Telegram bot polling started")
                    logger.info("Telegram bot + notifier started")
            except Exception as exc:
                logger.warning("Telegram bot failed to start: %s", exc)
    except Exception as exc:
        logger.warning("Dashboard services connect failed (running degraded): %s", exc)
    yield
    if relay_task:
        relay_task.cancel()
    if agent_task:
        agent_task.cancel()
    if telegram_task:
        telegram_task.cancel()
    if telegram_poll_task:
        telegram_poll_task.cancel()
    if scheduler:
        await scheduler.stop()
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
# Auto-reply toggle
# ------------------------------------------------------------------

@app.get("/api/autoreply")
async def get_autoreply():
    """Return current auto-reply status."""
    from .agent_relay import is_autoreply_enabled
    return {"enabled": is_autoreply_enabled()}


@app.post("/api/autoreply/toggle", response_class=HTMLResponse)
async def toggle_autoreply():
    """Toggle auto-reply mode and return updated status badge."""
    from .agent_relay import is_autoreply_enabled, set_autoreply
    new_state = not is_autoreply_enabled()
    set_autoreply(new_state)
    label = "ON" if new_state else "OFF"
    color = "green" if new_state else "red"
    return HTMLResponse(
        f'<span class="px-2 py-1 rounded text-xs font-bold bg-{color}-600 text-white">'
        f'Auto-reply: {label}</span>'
    )


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
# Telegram webhook
# ------------------------------------------------------------------

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram updates via webhook."""
    from services.telegram.bot import bot as tg_bot, dp as tg_dp
    if not tg_bot or not tg_dp:
        return {"ok": False, "error": "bot not initialized"}
    from aiogram.types import Update
    update = Update.model_validate(await request.json(), context={"bot": tg_bot})
    await tg_dp.feed_update(tg_bot, update)
    return {"ok": True}


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

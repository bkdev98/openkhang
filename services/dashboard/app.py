"""FastAPI dashboard app: sidebar-nav multi-page layout with HTMX routing.

Run with:
    uvicorn services.dashboard.app:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .dashboard_services import DashboardServices
from .inbox_relay import tail_inbox
from .agent_relay import run_agent_relay

logger = logging.getLogger(__name__)

# Suppress noisy Mem0 "Invalid JSON response" warnings
class _Mem0JsonFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Invalid JSON response" not in record.getMessage()

for _name in ("mem0", "mem0.memory.main", "mem0.client.main"):
    logging.getLogger(_name).addFilter(_Mem0JsonFilter())

import warnings
warnings.filterwarnings("ignore", message=".*Inheritance class AiohttpClientSession.*")

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = TEMPLATES_DIR / "static"
PAGES = {"overview", "chat", "drafts", "activity", "memory", "settings"}

# Shared service instance (initialised in lifespan)
_svc: DashboardServices | None = None


async def _start_meridian() -> asyncio.subprocess.Process | None:
    """Auto-start Meridian proxy if configured and not already running."""
    import shutil
    meridian_url = os.getenv("MERIDIAN_URL", "")
    if not meridian_url:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{meridian_url.rstrip('/')}/v1/models")
            if resp.status_code == 200:
                logger.info("Meridian already running at %s", meridian_url)
                return None
    except Exception:
        pass
    meridian_bin = shutil.which("meridian")
    if not meridian_bin:
        logger.warning("Meridian not found — install with: npm install -g @rynfar/meridian")
        return None
    proc = await asyncio.create_subprocess_exec(
        meridian_bin, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.sleep(3)
    if proc.returncode is not None:
        logger.error("Meridian failed to start (exit %d)", proc.returncode)
        return None
    logger.info("Meridian auto-started (pid=%d) at %s", proc.pid, meridian_url)
    return proc


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise and tear down shared services."""
    global _svc
    _svc = DashboardServices()
    meridian_proc = None
    relay_task = agent_task = telegram_task = telegram_poll_task = None
    scheduler = None
    try:
        meridian_proc = await _start_meridian()
        await _svc.connect()
        logger.info("Dashboard services connected")
        if _svc._pool:
            relay_task = asyncio.create_task(tail_inbox(_svc._pool))
            agent_task = asyncio.create_task(run_agent_relay(_svc._pool))
            logger.info("Inbox + agent relays started")
            # Ingestion scheduler
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
                logger.info("Ingestion scheduler started")
            except Exception as exc:
                logger.warning("Ingestion scheduler failed: %s", exc)
            # Telegram bot (opt-in)
            try:
                from services.telegram.bot import init_bot, set_pool, bot as tg_bot, dp as tg_dp
                from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
                if init_bot():
                    set_pool(_svc._pool)
                    from services.telegram.bot import bot as tg_bot, dp as tg_dp
                    from services.telegram.notifier import run_notifier
                    ok_cmds = [
                        BotCommand(command="ok_status", description="Service health"),
                        BotCommand(command="ok_events", description="Recent events"),
                        BotCommand(command="ok_drafts", description="Pending drafts"),
                        BotCommand(command="ok_autoreply", description="Toggle auto-reply"),
                    ]
                    await tg_bot.set_my_commands(ok_cmds, scope=BotCommandScopeAllPrivateChats())
                    telegram_task = asyncio.create_task(run_notifier(_svc._pool))
                    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "")
                    if webhook_url:
                        await tg_bot.set_webhook(webhook_url + "/telegram/webhook")
                    else:
                        await tg_bot.delete_webhook(drop_pending_updates=True)
                        logging.getLogger("aiogram.dispatcher").setLevel(logging.ERROR)
                        telegram_poll_task = asyncio.create_task(
                            tg_dp.start_polling(tg_bot, handle_signals=False, polling_timeout=10)
                        )
                    logger.info("Telegram bot started")
            except Exception as exc:
                logger.warning("Telegram bot failed: %s", exc)
    except Exception as exc:
        logger.warning("Dashboard connect failed (degraded): %s", exc)
    yield
    for task in (relay_task, agent_task, telegram_task, telegram_poll_task):
        if task:
            task.cancel()
    if telegram_poll_task:
        try:
            from services.telegram.bot import bot as tg_bot
            if tg_bot:
                await tg_bot.session.close()
        except Exception:
            pass
    if scheduler:
        await scheduler.stop()
    if meridian_proc and meridian_proc.returncode is None:
        meridian_proc.terminate()
    if _svc:
        await _svc.close()


# -- App setup --

app = FastAPI(title="openkhang Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Mount API routes
from .api_routes import router as api_router
app.include_router(api_router)


def svc() -> DashboardServices:
    """Return initialised services or raise if not ready."""
    if _svc is None:
        raise RuntimeError("Services not initialised")
    return _svc


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


# -- Page routing --

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if _is_htmx(request):
        return templates.TemplateResponse(request, "pages/overview.html")
    return RedirectResponse(url="/pages/overview", status_code=302)


@app.get("/pages/{page_name}", response_class=HTMLResponse)
async def render_page(request: Request, page_name: str):
    """Render page: partial for HTMX, full page for direct URL access."""
    if page_name not in PAGES:
        page_name = "overview"
    template_path = f"pages/{page_name}.html"
    if _is_htmx(request):
        return templates.TemplateResponse(request, template_path)
    return templates.TemplateResponse(request, "base.html", {"page_content": template_path})


# -- Telegram webhook --

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    from services.telegram.bot import bot as tg_bot, dp as tg_dp
    if not tg_bot or not tg_dp:
        return {"ok": False, "error": "bot not initialized"}
    from aiogram.types import Update
    update = Update.model_validate(await request.json(), context={"bot": tg_bot})
    await tg_dp.feed_update(tg_bot, update)
    return {"ok": True}

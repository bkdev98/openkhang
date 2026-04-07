"""Dashboard API routes: drafts, stats, health, chat, memory, settings, feed.

All routes are mounted under the main FastAPI app via APIRouter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/api")


def _get_svc():
    """Import svc() from app module to avoid circular imports."""
    from .app import svc
    return svc()


def _escape(s: Any) -> str:
    """HTML-escape a string (handles None)."""
    if s is None:
        return ""
    s = str(s)
    return (
        s.replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;")
    )


# ------------------------------------------------------------------
# SSE: real-time activity feed
# ------------------------------------------------------------------

def _render_event_card(ev: dict, compact: bool = False) -> str:
    """Render an event as an HTML activity card (server-side)."""
    src = ev.get("source", "system")
    src_class = f"source-{src}"
    icon_map = {"chat": "message-square", "jira": "ticket", "gitlab": "git-merge",
                "confluence": "book-open", "agent": "cpu"}
    icon = icon_map.get(src, "circle")
    actor = _escape(ev.get("actor", ""))
    etype = ev.get("event_type", "")
    ts = ev.get("created_at", "")

    # Extract human-readable summary from payload
    summary = etype
    payload = ev.get("payload")
    if isinstance(payload, dict):
        if payload.get("body"):
            summary = str(payload["body"])[:80]
        elif payload.get("message"):
            summary = str(payload["message"])[:80]
        elif payload.get("reply_text"):
            summary = "Draft: " + str(payload["reply_text"])[:60]
    summary = _escape(summary)

    pad = "px-3 py-2" if compact else "px-4 py-3"
    actor_html = f'<span class="text-[11px] text-ok-muted">{actor}</span>' if actor else ""
    details = "" if compact else (
        f'<details class="mt-1"><summary class="text-[10px] text-ok-ghost cursor-pointer hover:text-ok-muted">details</summary>'
        f'<pre class="text-[10px] text-ok-ghost mt-1 overflow-x-auto max-h-32 bg-ok-void rounded p-2">'
        f'{_escape(json.dumps(payload, default=str)[:500] if payload else "")}</pre></details>'
    )
    return (
        f'<div class="activity-card flex items-start gap-3 {pad} rounded-lg bg-ok-srf border border-ok-border card-hover" data-source="{_escape(src)}">'
        f'<i data-lucide="{icon}" class="w-4 h-4 mt-0.5 flex-shrink-0 {src_class}"></i>'
        f'<div class="flex-1 min-w-0">'
        f'<div class="flex items-center justify-between gap-2">'
        f'<div class="flex items-center gap-2">'
        f'<span class="font-mono text-[11px] font-medium {src_class}">{_escape(src)}</span>'
        f'{actor_html}</div>'
        f'<span class="font-mono text-[11px] text-ok-ghost flex-shrink-0">{_escape(ts[:19]) if ts else ""}</span>'
        f'</div>'
        f'<p class="text-xs text-ok-text mt-1 truncate">{summary}</p>'
        f'{details}'
        f'</div></div>'
    )


@router.get("/feed")
async def activity_feed(request: Request, compact: int = 0):
    """Server-Sent Events stream — returns pre-rendered HTML cards."""
    svc = _get_svc()
    is_compact = compact == 1

    async def event_generator():
        last_ts: str | None = None
        try:
            events = await svc.get_recent_events(limit=15)
            for event in reversed(events):
                last_ts = event.get("created_at")
                html = _render_event_card(event, compact=is_compact)
                yield f"data: {html}\n\n"
        except Exception as exc:
            yield f"data: <p class=\"text-ok-red text-xs\">{_escape(str(exc))}</p>\n\n"
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(2)
            try:
                new_events = await svc.get_recent_events(since=last_ts, limit=10)
                for event in reversed(new_events):
                    last_ts = event.get("created_at")
                    html = _render_event_card(event, compact=is_compact)
                    yield f"data: {html}\n\n"
            except Exception as exc:
                logger.warning("SSE poll error: %s", exc)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/feed/history", response_class=HTMLResponse)
async def feed_history(request: Request, before: str = "", source: str = "", limit: int = 20):
    """Return older activity events as rendered HTML cards for infinite scroll."""
    try:
        # Use 'before' timestamp for pagination if provided
        events = await _get_svc().get_events_before(before=before, source=source, limit=limit)
    except Exception:
        events = []
    icon_map = {"chat": "message-square", "jira": "ticket", "gitlab": "git-merge",
                "confluence": "book-open", "agent": "cpu"}
    cards = ""
    for ev in events:
        src = ev.get("source", "system")
        icon = icon_map.get(src, "circle")
        actor = ev.get("actor", "")
        summary = ev.get("event_type", "")
        ts = ev.get("created_at", "")
        actor_html = f'<span class="text-[11px] text-ok-muted">{_escape(actor)}</span>' if actor else ""
        cards += (
            f'<div class="activity-card flex items-start gap-3 px-4 py-3 rounded-lg bg-ok-srf border border-ok-border card-hover" data-source="{src}">'
            f'<i data-lucide="{icon}" class="w-4 h-4 mt-0.5 flex-shrink-0 source-{src}"></i>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="flex items-center justify-between gap-2">'
            f'<div class="flex items-center gap-2">'
            f'<span class="font-mono text-[11px] font-medium source-{src}">{_escape(src)}</span>'
            f'{actor_html}</div>'
            f'<span class="font-mono text-[11px] text-ok-ghost flex-shrink-0">{ts[:19] if ts else ""}</span>'
            f'</div><p class="text-xs text-ok-text mt-1">{_escape(summary)}</p>'
            f'</div></div>'
        )
    return HTMLResponse(cards)


# ------------------------------------------------------------------
# Drafts
# ------------------------------------------------------------------

@router.get("/drafts", response_class=HTMLResponse)
async def list_drafts(request: Request, status: str = "pending", search: str = "",
                      limit: int = 20, compact: int = 0):
    """Return rendered drafts list partial for HTMX."""
    try:
        drafts = await _get_svc().get_drafts(status=status, search=search, limit=limit)
        if status != "pending":
            for d in drafts:
                d["readonly"] = True
    except Exception as exc:
        logger.error("list_drafts error: %s", exc)
        drafts = []
    return templates.TemplateResponse(
        request, "partials/drafts_list.html",
        {"drafts": drafts, "status_label": status},
    )


@router.post("/drafts/{draft_id}/approve", response_class=HTMLResponse)
async def approve_draft(request: Request, draft_id: str):
    """Approve a pending draft reply."""
    s = _get_svc()
    ok = await s.approve_draft(draft_id)
    if not ok:
        return HTMLResponse('<p class="text-ok-red text-xs">Failed to approve</p>', status_code=400)
    drafts = await s.get_drafts()
    return templates.TemplateResponse(request, "partials/drafts_list.html", {"drafts": drafts})


@router.post("/drafts/{draft_id}/reject", response_class=HTMLResponse)
async def reject_draft(request: Request, draft_id: str):
    """Reject a pending draft reply."""
    s = _get_svc()
    ok = await s.reject_draft(draft_id)
    if not ok:
        return HTMLResponse('<p class="text-ok-red text-xs">Failed to reject</p>', status_code=400)
    drafts = await s.get_drafts()
    return templates.TemplateResponse(request, "partials/drafts_list.html", {"drafts": drafts})


@router.post("/drafts/{draft_id}/edit", response_class=HTMLResponse)
async def edit_draft(request: Request, draft_id: str, edited_text: str = Form(...)):
    """Edit draft text and mark approved."""
    s = _get_svc()
    ok = await s.edit_draft(draft_id, edited_text)
    if not ok:
        return HTMLResponse('<p class="text-ok-red text-xs">Failed to edit</p>', status_code=400)
    drafts = await s.get_drafts()
    return templates.TemplateResponse(request, "partials/drafts_list.html", {"drafts": drafts})


# ------------------------------------------------------------------
# Auto-reply toggle
# ------------------------------------------------------------------

@router.get("/autoreply")
async def get_autoreply():
    from .agent_relay import is_autoreply_enabled
    return {"enabled": is_autoreply_enabled()}


@router.get("/autoreply/toggle-state", response_class=HTMLResponse)
async def autoreply_state():
    """Return current toggle button reflecting actual state."""
    from .agent_relay import is_autoreply_enabled
    on = is_autoreply_enabled()
    on_class = "on" if on else ""
    label = "ON" if on else "OFF"
    return HTMLResponse(
        f'<button id="autoreply-toggle" hx-post="/api/autoreply/toggle" hx-target="#autoreply-toggle" '
        f'hx-swap="outerHTML" class="toggle-btn {on_class}">'
        f'<span class="toggle-thumb"></span><span class="toggle-label">{label}</span></button>'
    )


@router.post("/autoreply/toggle", response_class=HTMLResponse)
async def toggle_autoreply():
    from .agent_relay import is_autoreply_enabled, set_autoreply
    new_state = not is_autoreply_enabled()
    set_autoreply(new_state)
    on_class = "on" if new_state else ""
    label = "ON" if new_state else "OFF"
    return HTMLResponse(
        f'<button id="autoreply-toggle" hx-post="/api/autoreply/toggle" hx-target="#autoreply-toggle" '
        f'hx-swap="outerHTML" class="toggle-btn {on_class}">'
        f'<span class="toggle-thumb"></span><span class="toggle-label">{label}</span></button>'
    )


# ------------------------------------------------------------------
# Health + Stats
# ------------------------------------------------------------------

@router.get("/health", response_class=HTMLResponse)
async def health_panel(request: Request):
    try:
        services = await _get_svc().get_health()
    except Exception as exc:
        logger.error("health_panel error: %s", exc)
        services = []
    return templates.TemplateResponse(request, "partials/health_panel.html", {"services": services})


@router.get("/health/compact", response_class=HTMLResponse)
async def health_compact(request: Request):
    try:
        services = await _get_svc().get_health()
    except Exception as exc:
        logger.error("health_compact error: %s", exc)
        services = []
    return templates.TemplateResponse(request, "partials/health_panel.html", {"services": services})


@router.get("/stats", response_class=HTMLResponse)
async def stats_bar(request: Request):
    try:
        stats = await _get_svc().get_stats()
    except Exception as exc:
        logger.error("stats_bar error: %s", exc)
        stats = {}
    return templates.TemplateResponse(request, "partials/stats_bar.html", {"stats": stats})


# ------------------------------------------------------------------
# Chat (inward mode)
# ------------------------------------------------------------------

@router.post("/chat")
async def chat(request: Request, question: str = Form(...)):
    """Process inward-mode question, return JSON for JS-based chat UI."""
    import uuid
    question = question.strip()
    if not question:
        return JSONResponse({"error": "Please enter a question."})
    session_id = request.cookies.get("twin_session_id", "")
    if not session_id:
        session_id = str(uuid.uuid4())
    try:
        result = await _get_svc().ask_twin(question, session_id=session_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    response = JSONResponse(result)
    response.set_cookie("twin_session_id", session_id, httponly=True, samesite="lax")
    return response


@router.get("/chat/history", response_class=HTMLResponse)
async def chat_history(request: Request):
    """Return rendered chat history for current session."""
    session_id = request.cookies.get("twin_session_id", "")
    empty_html = (
        '<div class="text-center py-12">'
        '<p class="text-ok-ghost text-sm">Start a conversation with your twin</p>'
        '<p class="text-ok-ghost text-xs mt-1">Ask about your context, preferences, or tasks</p>'
        '</div>'
    )
    if not session_id:
        return HTMLResponse(empty_html)
    from .twin_chat import _working_memory
    history = _working_memory.get_context(session_id, "chat_history") or []
    if not history:
        return HTMLResponse(empty_html)
    html = ""
    for msg in history:
        if msg["role"] == "user":
            html += (
                '<div class="chat-bubble flex justify-end">'
                '<div class="max-w-[80%] bg-ok-amber/15 border border-ok-amber/20 rounded-xl rounded-br px-4 py-3">'
                f'<p class="text-sm text-ok-text whitespace-pre-wrap">{_escape(msg["content"])}</p>'
                '</div></div>'
            )
        else:
            html += (
                '<div class="chat-bubble flex justify-start">'
                '<div class="max-w-[80%] bg-ok-raised border border-ok-border rounded-xl rounded-bl px-4 py-3">'
                f'<div class="text-sm text-ok-text prose-invert prose-sm">{_escape(msg["content"])}</div>'
                '</div></div>'
            )
    return HTMLResponse(html)


@router.post("/chat/clear", response_class=HTMLResponse)
async def chat_clear(request: Request):
    session_id = request.cookies.get("twin_session_id", "")
    if session_id:
        from .twin_chat import _working_memory
        _working_memory.set_context(session_id, "chat_history", [])
    return HTMLResponse(
        '<div class="text-center py-12">'
        '<p class="text-ok-ghost text-sm">Conversation cleared</p>'
        '</div>'
    )


# ------------------------------------------------------------------
# Memory search & knowledge ingestion
# ------------------------------------------------------------------

@router.get("/memory/search", response_class=HTMLResponse)
async def memory_search(request: Request, q: str = "", type: str = ""):
    if not q and not type:
        q = "recent"  # Default: show latest memories
    try:
        results = await _get_svc().search_memories(query=q or "recent", limit=20)
        if not results:
            return HTMLResponse('<p class="text-ok-ghost text-xs text-center py-8">No memories found</p>')
        html = ""
        for mem in results:
            src_type = mem.get("_source_type", "semantic")
            mem_id = mem.get("id", "")
            meta = mem.get("metadata", {}) if isinstance(mem.get("metadata"), dict) else {}
            source = meta.get("source", "unknown")

            # Badge
            badge_colors = {"semantic": "bg-ok-cyan/20 text-ok-cyan", "episodic": "bg-ok-purple/20 text-ok-purple"}
            badge_cls = badge_colors.get(src_type, "bg-ok-amber/20 text-ok-amber")
            badge = f'<span class="text-[10px] px-1.5 py-0.5 rounded {badge_cls}">{_escape(src_type)}</span>'

            if src_type == "episodic":
                # Code/knowledge result — show file path + text
                file_path = mem.get("file_path", "")
                chunk_label = mem.get("chunk_label", "")
                text = mem.get("text", "")[:400]
                header = ""
                if file_path:
                    short_path = file_path.split("/")[-1] if "/" in file_path else file_path
                    header = (
                        f'<div class="font-mono text-[11px] text-ok-amber truncate" title="{_escape(file_path)}">{_escape(file_path)}</div>'
                    )
                if chunk_label:
                    header += f'<div class="font-mono text-[11px] text-ok-muted">{_escape(chunk_label)}</div>'
                html += (
                    '<div class="bg-ok-srf border border-ok-border rounded-lg p-4 card-hover flex flex-col gap-1.5">'
                    f'<div class="flex items-center gap-2">{badge}'
                    f'<span class="text-[10px] text-ok-ghost">{_escape(source)}</span></div>'
                    f'{header}'
                    f'<pre class="text-[11px] text-ok-text whitespace-pre-wrap font-mono max-h-24 overflow-y-auto">{_escape(text)}</pre>'
                    '</div>'
                )
            else:
                # Mem0 semantic memory
                text = mem.get("memory", mem.get("text", ""))[:300]
                delete_btn = ""
                if mem_id:
                    delete_btn = (
                        f'<button hx-delete="/api/memory/{mem_id}" hx-target="closest div.bg-ok-srf" hx-swap="outerHTML" '
                        f'hx-confirm="Delete this memory?" class="text-[10px] text-ok-ghost hover:text-ok-red transition-colors">'
                        'delete</button>'
                    )
                html += (
                    '<div class="bg-ok-srf border border-ok-border rounded-lg p-4 card-hover flex flex-col gap-2">'
                    f'<div class="flex items-center gap-2">{badge}'
                    f'<span class="text-[10px] text-ok-ghost">{_escape(source)}</span></div>'
                    f'<p class="text-xs text-ok-text">{_escape(text)}</p>'
                    f'<div class="flex justify-end">{delete_btn}</div>'
                    '</div>'
                )
        return HTMLResponse(html)
    except Exception as exc:
        logger.error("memory_search error: %s", exc)
        return HTMLResponse(f'<p class="text-ok-red text-xs text-center py-4">Error: {exc}</p>')


@router.delete("/memory/{memory_id}", response_class=HTMLResponse)
async def memory_delete(memory_id: str):
    try:
        await _get_svc().delete_memory(memory_id)
        return HTMLResponse("")
    except Exception as exc:
        return HTMLResponse(f'<p class="text-ok-red text-xs">Delete failed: {exc}</p>')


@router.post("/memory/ingest", response_class=HTMLResponse)
async def memory_ingest(text: str = Form(""), source_label: str = Form("manual"),
                        file: UploadFile | None = File(None)):
    content = text.strip()
    if file and file.filename:
        file_bytes = await file.read()
        if len(file_bytes) > 5 * 1024 * 1024:
            return HTMLResponse('<p class="text-ok-red text-xs">File too large (max 5MB)</p>')
        content = file_bytes.decode("utf-8", errors="replace")
        if not source_label or source_label == "manual":
            source_label = file.filename
    if not content:
        return HTMLResponse('<p class="text-ok-amber text-xs">Please provide text or a file</p>')
    try:
        await _get_svc().ingest_knowledge(content, source_label)
        return HTMLResponse('<p class="text-ok-green text-xs">Knowledge ingested successfully</p>')
    except Exception as exc:
        return HTMLResponse(f'<p class="text-ok-red text-xs">Ingestion failed: {exc}</p>')


# ------------------------------------------------------------------
# Request traces
# ------------------------------------------------------------------

@router.get("/traces", response_class=HTMLResponse)
async def list_traces(request: Request, mode: str = "", action: str = "",
                      limit: int = 50, before: str = ""):
    """Return rendered trace list for HTMX."""
    limit = min(max(1, limit), 200)
    try:
        traces = await _get_svc().get_traces(mode=mode, action=action, limit=limit, before=before)
    except Exception as exc:
        logger.error("list_traces error: %s", exc)
        traces = []
    if not traces:
        return HTMLResponse('<p class="text-ok-ghost text-xs text-center py-8">No traces found</p>')
    html = ""
    for t in traces:
        mode_badge = _trace_mode_badge(t.get("mode", ""))
        action_badge = _trace_action_badge(t.get("action", ""))
        intent = _escape(t.get("intent", ""))
        skill = _escape(t.get("skill_name", ""))
        latency = t.get("latency_ms", 0)
        tokens = t.get("tokens_used", 0)
        conf_pct = t.get("confidence_pct", 0)
        ts = _escape(t.get("created_at_str", ""))
        tid = t.get("id", "")
        body_preview = _escape((t.get("input_body") or "")[:80])
        error = t.get("error", "")
        error_html = f'<span class="text-ok-red text-[10px]">{_escape(error[:60])}</span>' if error else ""

        html += (
            f'<div class="trace-row bg-ok-srf border border-ok-border rounded-lg px-4 py-3 card-hover cursor-pointer"'
            f' hx-get="/api/traces/{tid}" hx-target="#trace-detail" hx-swap="innerHTML">'
            f'<div class="flex items-center justify-between gap-2 mb-1">'
            f'<div class="flex items-center gap-2">'
            f'{mode_badge}{action_badge}'
            f'<span class="font-mono text-[11px] text-ok-muted">{intent}</span>'
            f'<span class="font-mono text-[11px] text-ok-ghost">{skill}</span>'
            f'</div>'
            f'<span class="font-mono text-[11px] text-ok-ghost flex-shrink-0">{ts}</span>'
            f'</div>'
            f'<p class="text-xs text-ok-text truncate">{body_preview}</p>'
            f'<div class="flex items-center gap-3 mt-1">'
            f'<span class="text-[10px] text-ok-muted">{latency}ms</span>'
            f'<span class="text-[10px] text-ok-muted">{tokens} tok</span>'
            f'<span class="text-[10px] text-ok-amber">{conf_pct}%</span>'
            f'{error_html}'
            f'</div></div>'
        )
    return HTMLResponse(html)


@router.get("/traces/{trace_id}", response_class=HTMLResponse)
async def trace_detail(request: Request, trace_id: str):
    """Return rendered trace detail with expandable steps."""
    try:
        t = await _get_svc().get_trace_detail(trace_id)
    except Exception as exc:
        logger.error("trace_detail error: %s", exc)
        return HTMLResponse(f'<p class="text-ok-red text-xs">Error loading trace</p>')
    if not t:
        return HTMLResponse('<p class="text-ok-ghost text-xs">Trace not found</p>')

    mode_badge = _trace_mode_badge(t.get("mode", ""))
    action_badge = _trace_action_badge(t.get("action", ""))

    # Header
    html = (
        f'<div class="flex items-center justify-between mb-4">'
        f'<div class="flex items-center gap-2">'
        f'<button hx-get="/api/traces" hx-target="#trace-list" hx-swap="innerHTML"'
        f' onclick="document.getElementById(\'trace-detail\').innerHTML=\'\'"'
        f' class="text-ok-ghost hover:text-ok-text text-xs">&larr; back</button>'
        f'{mode_badge}{action_badge}'
        f'<span class="font-mono text-[11px] text-ok-muted">{_escape(t.get("intent", ""))}</span>'
        f'</div>'
        f'<span class="font-mono text-[11px] text-ok-ghost">{_escape(t.get("created_at_str", ""))}</span>'
        f'</div>'
    )

    # Summary bar
    html += (
        f'<div class="flex items-center gap-4 mb-4 text-xs text-ok-muted">'
        f'<span>Skill: <b class="text-ok-text">{_escape(t.get("skill_name", ""))}</b></span>'
        f'<span>Latency: <b class="text-ok-amber">{t.get("latency_ms", 0)}ms</b></span>'
        f'<span>Tokens: <b class="text-ok-text">{t.get("tokens_used", 0)}</b></span>'
        f'<span>Confidence: <b class="text-ok-amber">{t.get("confidence_pct", 0)}%</b></span>'
        f'<span>Channel: <b class="text-ok-text">{_escape(t.get("channel", ""))}</b></span>'
        f'</div>'
    )

    # Input
    html += (
        f'<div class="mb-3">'
        f'<span class="text-[10px] text-ok-ghost uppercase tracking-wider">Input</span>'
        f'<p class="text-xs text-ok-text mt-1 bg-ok-raised rounded p-3 whitespace-pre-wrap">{_escape(t.get("input_body", ""))}</p>'
        f'</div>'
    )

    if t.get("error"):
        html += (
            f'<div class="mb-3 bg-ok-reddim/20 border border-ok-red/30 rounded p-3">'
            f'<span class="text-[10px] text-ok-red uppercase">Error</span>'
            f'<p class="text-xs text-ok-red mt-1">{_escape(t["error"])}</p>'
            f'</div>'
        )

    # Steps
    steps = t.get("steps", [])
    if steps:
        html += '<div class="flex flex-col gap-2">'
        html += '<span class="text-[10px] text-ok-ghost uppercase tracking-wider">Pipeline Steps</span>'
        for i, step in enumerate(steps):
            step_name = _escape(step.get("name", ""))
            step_data = step.get("data", {})
            icon = _step_icon(step_name)
            color = _step_color(step_name)

            # Format step data as readable content
            data_html = _render_step_data(step_name, step_data)

            html += (
                f'<details class="bg-ok-raised border border-ok-border rounded-lg">'
                f'<summary class="px-4 py-2.5 cursor-pointer hover:bg-ok-hover flex items-center gap-2">'
                f'<span class="font-mono text-[11px] font-medium {color}">{i+1}. {icon} {step_name}</span>'
                f'</summary>'
                f'<div class="px-4 py-3 border-t border-ok-border">{data_html}</div>'
                f'</details>'
            )
        html += '</div>'

    return HTMLResponse(html)


def _trace_mode_badge(mode: str) -> str:
    colors = {"outward": "bg-ok-cyan/20 text-ok-cyan", "inward": "bg-ok-purple/20 text-ok-purple"}
    cls = colors.get(mode, "bg-ok-amber/20 text-ok-amber")
    return f'<span class="text-[10px] px-1.5 py-0.5 rounded font-mono {cls}">{_escape(mode)}</span>'


def _trace_action_badge(action: str) -> str:
    colors = {
        "auto_sent": "bg-ok-green/20 text-ok-green",
        "drafted": "bg-ok-amber/20 text-ok-amber",
        "inward_response": "bg-ok-purple/20 text-ok-purple",
        "skipped": "bg-ok-ghost/20 text-ok-ghost",
        "error": "bg-ok-red/20 text-ok-red",
    }
    cls = colors.get(action, "bg-ok-ghost/20 text-ok-ghost")
    return f'<span class="text-[10px] px-1.5 py-0.5 rounded font-mono {cls}">{_escape(action)}</span>'


def _step_icon(name: str) -> str:
    icons = {
        "classification": "&#x1F3AF;", "rag_memories": "&#x1F50D;", "sender_context": "&#x1F464;",
        "room_messages": "&#x1F4AC;", "prompt": "&#x1F4DD;", "llm_call": "&#x1F916;",
        "tool_call": "&#x1F527;", "tool_loop_summary": "&#x1F504;", "confidence": "&#x1F4CA;",
        "result": "&#x2705;", "skill_matched": "&#x1F3AF;",
    }
    return icons.get(name, "&#x25CF;")


def _step_color(name: str) -> str:
    colors = {
        "classification": "text-ok-cyan", "rag_memories": "text-ok-amber", "sender_context": "text-ok-amber",
        "prompt": "text-ok-purple", "llm_call": "text-ok-green", "tool_call": "text-ok-cyan",
        "confidence": "text-ok-amber", "result": "text-ok-green", "error": "text-ok-red",
    }
    return colors.get(name, "text-ok-muted")


def _render_step_data(name: str, data: dict) -> str:
    """Render step data as human-readable HTML."""
    if name == "prompt":
        messages = data.get("messages", [])
        html = f'<span class="text-[10px] text-ok-ghost">{data.get("message_count", 0)} messages</span>'
        for msg in messages:
            role = _escape(msg.get("role", ""))
            content = _escape(msg.get("content", ""))
            role_cls = "text-ok-cyan" if role == "system" else ("text-ok-amber" if role == "user" else "text-ok-green")
            html += (
                f'<div class="mt-2">'
                f'<span class="text-[10px] font-mono font-medium {role_cls} uppercase">{role}</span>'
                f'<pre class="text-[11px] text-ok-text whitespace-pre-wrap font-mono mt-1 '
                f'max-h-48 overflow-y-auto bg-ok-void rounded p-2">{content}</pre>'
                f'</div>'
            )
        return html

    if name in ("rag_memories", "sender_context"):
        results = data.get("results", [])
        count = data.get("count", len(results))
        html = f'<span class="text-[10px] text-ok-ghost">{count} results</span>'
        for r in results:
            score = r.get("score", 0)
            mem = _escape(r.get("memory", ""))
            html += (
                f'<div class="flex gap-2 mt-1">'
                f'<span class="text-[10px] text-ok-amber font-mono flex-shrink-0">[{score:.2f}]</span>'
                f'<span class="text-[11px] text-ok-text">{mem}</span>'
                f'</div>'
            )
        return html

    if name == "llm_call":
        return (
            f'<div class="grid grid-cols-2 gap-2 text-[11px]">'
            f'<span class="text-ok-muted">Model:</span><span class="text-ok-text font-mono">{_escape(str(data.get("model", "")))}</span>'
            f'<span class="text-ok-muted">Tokens:</span><span class="text-ok-text">{data.get("tokens", 0)}</span>'
            f'<span class="text-ok-muted">Latency:</span><span class="text-ok-amber">{data.get("latency_ms", 0)}ms</span>'
            f'<span class="text-ok-muted">Temperature:</span><span class="text-ok-text">{data.get("temperature", 0)}</span>'
            f'</div>'
            f'{"<pre class=\"text-[11px] text-ok-text whitespace-pre-wrap font-mono mt-2 max-h-32 overflow-y-auto bg-ok-void rounded p-2\">" + _escape(data.get("response_preview", "")) + "</pre>" if data.get("response_preview") else ""}'
        )

    if name == "tool_call":
        return (
            f'<div class="text-[11px]">'
            f'<span class="text-ok-muted">Tool:</span> <span class="text-ok-cyan font-mono">{_escape(str(data.get("tool_name", "")))}</span>'
            f' <span class="{"text-ok-green" if data.get("success") else "text-ok-red"}">{"ok" if data.get("success") else "failed"}</span>'
            f'<pre class="text-[11px] text-ok-text whitespace-pre-wrap font-mono mt-1 max-h-20 overflow-y-auto bg-ok-void rounded p-2">'
            f'Input: {_escape(json.dumps(data.get("tool_input", {}), default=str)[:500])}\n'
            f'Result: {_escape(str(data.get("result", ""))[:500])}</pre>'
            f'</div>'
        )

    if name == "confidence":
        breakdown = data.get("breakdown", {})
        html = f'<span class="text-ok-amber font-mono text-sm font-semibold">{data.get("score", 0):.3f}</span>'
        if breakdown:
            html += '<div class="grid grid-cols-2 gap-1 mt-2 text-[11px]">'
            for k, v in breakdown.items():
                html += f'<span class="text-ok-muted">{_escape(k)}:</span><span class="text-ok-text">{_escape(str(v))}</span>'
            html += '</div>'
        return html

    # Default: render as JSON
    return (
        f'<pre class="text-[11px] text-ok-text whitespace-pre-wrap font-mono '
        f'max-h-32 overflow-y-auto bg-ok-void rounded p-2">'
        f'{_escape(json.dumps(data, indent=2, default=str)[:1000])}</pre>'
    )


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

@router.get("/settings/persona", response_class=HTMLResponse)
async def get_persona_settings(request: Request):
    try:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "persona.yaml"
        data = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
        data = data or {}
        name, tone, language = data.get("name", ""), data.get("tone", ""), data.get("language", "")
        field = (
            '<input type="text" name="{name}" value="{val}" '
            'class="bg-ok-srf border border-ok-border rounded-lg px-4 py-2.5 text-sm text-ok-text '
            'focus:outline-none focus:border-ok-amber">'
        )
        return HTMLResponse(
            f'<label class="text-xs text-ok-muted">Display Name</label>{field.format(name="name", val=_escape(name))}'
            f'<label class="text-xs text-ok-muted">Tone / Style</label>{field.format(name="tone", val=_escape(tone))}'
            f'<label class="text-xs text-ok-muted">Language</label>{field.format(name="language", val=_escape(language))}'
        )
    except Exception as exc:
        return HTMLResponse(f'<p class="text-ok-red text-xs">Error loading persona: {exc}</p>')


@router.post("/settings/persona", response_class=HTMLResponse)
async def save_persona_settings(name: str = Form(""), tone: str = Form(""), language: str = Form("")):
    try:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "persona.yaml"
        data = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
        data = data or {}
        data["name"] = name
        data["tone"] = tone
        data["language"] = language
        config_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
        return HTMLResponse('<span class="text-ok-green text-xs">Saved</span>')
    except Exception as exc:
        return HTMLResponse(f'<span class="text-ok-red text-xs">Error: {exc}</span>')


@router.get("/settings/confidence", response_class=HTMLResponse)
async def get_confidence_settings(request: Request):
    try:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "confidence_thresholds.yaml"
        data = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
        threshold = (data or {}).get("default", 0.75)
        return HTMLResponse(
            f'<label class="text-xs text-ok-muted">Default Threshold</label>'
            f'<div class="flex items-center gap-3">'
            f'<input type="range" name="default" min="0" max="1" step="0.05" value="{threshold}" '
            f'class="flex-1 accent-ok-amber" oninput="this.nextElementSibling.textContent=this.value">'
            f'<span class="font-mono text-sm text-ok-amber w-10">{threshold}</span></div>'
        )
    except Exception as exc:
        return HTMLResponse(f'<p class="text-ok-red text-xs">Error: {exc}</p>')


@router.post("/settings/confidence", response_class=HTMLResponse)
async def save_confidence_settings(default: float = Form(0.75)):
    try:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "confidence_thresholds.yaml"
        data = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
        data = data or {}
        data["default"] = float(default)
        config_path.write_text(yaml.dump(data, default_flow_style=False))
        return HTMLResponse('<span class="text-ok-green text-xs">Saved</span>')
    except Exception as exc:
        return HTMLResponse(f'<span class="text-ok-red text-xs">Error: {exc}</span>')


@router.get("/settings/projects", response_class=HTMLResponse)
async def get_projects_settings(request: Request):
    try:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "projects.yaml"
        data = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
        projects = (data or {}).get("projects", [])
        html = ""
        for proj in projects:
            name = proj.get("name", "unknown") if isinstance(proj, dict) else str(proj)
            path = proj.get("path", "") if isinstance(proj, dict) else ""
            html += (
                '<div class="bg-ok-srf border border-ok-border rounded-lg p-3 flex items-center justify-between">'
                f'<div><span class="font-mono text-sm text-ok-text">{_escape(name)}</span>'
                f'<span class="text-[11px] text-ok-ghost ml-2">{_escape(path)}</span></div></div>'
            )
        return HTMLResponse(html or '<p class="text-ok-ghost text-xs">No projects configured</p>')
    except Exception as exc:
        return HTMLResponse(f'<p class="text-ok-red text-xs">Error: {exc}</p>')


@router.post("/settings/integrations", response_class=HTMLResponse)
async def save_integrations_settings(
    jira_url: str = Form(""), gitlab_url: str = Form(""), confluence_url: str = Form(""),
):
    """Save integration URLs (note: env vars are read-only, this is informational)."""
    return HTMLResponse('<span class="text-ok-amber text-xs">Integration URLs are configured via .env file</span>')


@router.get("/settings/integrations", response_class=HTMLResponse)
async def get_integrations_settings(request: Request):
    jira_url = os.getenv("JIRA_BASE_URL", "")
    gitlab_url = os.getenv("GITLAB_URL", "")
    confluence_url = os.getenv("CONFLUENCE_BASE_URL", "")
    field = (
        '<input type="text" name="{name}" value="{val}" placeholder="{ph}" '
        'class="bg-ok-srf border border-ok-border rounded-lg px-4 py-2.5 text-sm text-ok-text '
        'focus:outline-none focus:border-ok-amber">'
    )
    return HTMLResponse(
        '<div class="grid grid-cols-1 gap-3">'
        f'<label class="text-xs text-ok-muted">Jira URL</label>'
        f'{field.format(name="jira_url", val=_escape(jira_url), ph="https://jira.example.com")}'
        f'<label class="text-xs text-ok-muted">GitLab URL</label>'
        f'{field.format(name="gitlab_url", val=_escape(gitlab_url), ph="https://gitlab.example.com")}'
        f'<label class="text-xs text-ok-muted">Confluence URL</label>'
        f'{field.format(name="confluence_url", val=_escape(confluence_url), ph="https://confluence.example.com")}'
        '</div>'
    )

"""Telegram bot: command handlers, inline keyboards, inward chat relay.

Commands use /ok prefix to avoid conflicts with other bots.
Single user — all handlers check chat_id == TELEGRAM_CHAT_ID.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.filters import Command
from aiogram.enums import ParseMode

import asyncpg

logger = logging.getLogger(__name__)

# Env config
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Bot + dispatcher (initialised lazily — only if token is set)
bot: Bot | None = None
dp: Dispatcher | None = None
router = Router()

# DB pool injected from dashboard lifespan
_pool: asyncpg.Pool | None = None


def init_bot() -> tuple[Bot, Dispatcher] | None:
    """Create bot and dispatcher if token is configured."""
    global bot, dp
    if not BOT_TOKEN:
        logger.info("telegram: TELEGRAM_BOT_TOKEN not set, bot disabled")
        return None
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    logger.info("telegram: bot initialized (chat_id=%s)", CHAT_ID)
    return bot, dp


def set_pool(pool: asyncpg.Pool) -> None:
    """Inject DB pool from dashboard lifespan."""
    global _pool
    _pool = pool


def _authorized(msg_or_cb: Message | CallbackQuery) -> bool:
    """Check sender matches configured chat ID."""
    if not CHAT_ID:
        return True  # No restriction if CHAT_ID not set
    chat_id = str(msg_or_cb.chat.id) if hasattr(msg_or_cb, "chat") else str(msg_or_cb.message.chat.id)
    return chat_id == CHAT_ID


# ------------------------------------------------------------------
# Notification helpers (called by notifier.py)
# ------------------------------------------------------------------

def _draft_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    """Inline keyboard for approve/reject/edit a draft."""
    prefix = draft_id[:8]
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Approve", callback_data=f"approve:{prefix}"),
        InlineKeyboardButton(text="Reject", callback_data=f"reject:{prefix}"),
    ]])


async def send_draft_notification(data: dict) -> None:
    """Push draft notification with inline keyboard."""
    if not bot or not CHAT_ID:
        return
    room = data.get("room_name", "unknown")
    sender = data.get("sender", "?")
    body = data.get("body", "")[:150]
    reply = data.get("reply_text", "")[:300]
    draft_id = data.get("draft_id", "")
    conf = data.get("confidence", 0)

    text = (
        f"<b>Draft reply</b> ({conf:.0%} confidence)\n"
        f"<b>Room:</b> {_esc(room)}\n"
        f"<b>From:</b> {_esc(sender)}\n"
        f"<b>Message:</b> {_esc(body)}\n\n"
        f"<b>Draft:</b>\n{_esc(reply)}"
    )
    kb = _draft_keyboard(draft_id) if draft_id else None
    await bot.send_message(chat_id=int(CHAT_ID), text=text, reply_markup=kb)


async def send_auto_reply_notification(data: dict) -> None:
    """Push notification when agent auto-replied, with conversation context."""
    if not bot or not CHAT_ID:
        return
    room = data.get("room_name", "unknown")
    sender = data.get("sender", "?")
    body = data.get("body", "")[:200]
    reply = data.get("reply_text", "")[:300]
    conf = data.get("confidence", 0)

    text = (
        f"<b>Auto-replied</b> ({conf:.0%}) in {_esc(room)}\n"
        f"<b>From:</b> {_esc(sender)}\n"
        f"<b>Message:</b> {_esc(body)}\n\n"
        f"<b>Reply sent:</b>\n{_esc(reply)}"
    )
    await bot.send_message(chat_id=int(CHAT_ID), text=text)


async def send_workflow_notification(data: dict) -> None:
    """Push notification for workflow action."""
    if not bot or not CHAT_ID:
        return
    wf_name = data.get("workflow_name", "unknown")
    action_type = data.get("action_type", "?")
    state = data.get("state", "?")
    output = data.get("output", "")[:200]

    text = (
        f"<b>Workflow:</b> {_esc(wf_name)}\n"
        f"<b>Action:</b> {_esc(action_type)} (state: {_esc(state)})\n"
    )
    if output:
        text += f"\n{_esc(output)}"
    await bot.send_message(chat_id=int(CHAT_ID), text=text)


async def send_text(text: str) -> None:
    """Send a plain text message."""
    if not bot or not CHAT_ID:
        return
    await bot.send_message(chat_id=int(CHAT_ID), text=text)


# ------------------------------------------------------------------
# Command handlers (all prefixed with /ok)
# ------------------------------------------------------------------

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not _authorized(message):
        return
    from services.dashboard.agent_relay import is_autoreply_enabled
    mode = "ON" if is_autoreply_enabled() else "OFF"
    await message.answer(
        f"<b>openkhang twin</b> (autoreply: {mode})\n\n"
        "Commands:\n"
        "/ok_status — service health\n"
        "/ok_events — recent events\n"
        "/ok_drafts — pending drafts\n"
        "/ok_autoreply — toggle auto-reply on/off\n\n"
        "Or just type a message for inward chat."
    )


@router.message(Command("ok_autoreply"))
async def cmd_autoreply(message: Message) -> None:
    """Toggle auto-reply mode on/off."""
    if not _authorized(message):
        return
    from services.dashboard.agent_relay import is_autoreply_enabled, set_autoreply
    new_state = not is_autoreply_enabled()
    set_autoreply(new_state)
    status = "ON — will auto-send high-confidence replies" if new_state else "OFF — all replies go to draft for review"
    await message.answer(f"<b>Auto-reply:</b> {status}")


@router.message(Command("ok_status"))
async def cmd_status(message: Message) -> None:
    """Return service health status."""
    if not _authorized(message):
        return
    if not _pool:
        await message.answer("DB pool not available")
        return

    from services.dashboard.health_checker import get_all_health
    services = await get_all_health(_pool)
    lines = ["<b>Service Health</b>\n"]
    for s in services:
        icon = "+" if s.get("healthy") else "-"
        name = s.get("name", "?")
        detail = s.get("detail", "")
        lines.append(f"  {icon} {name}: {detail}")
    await message.answer("\n".join(lines))


@router.message(Command("ok_events"))
async def cmd_events(message: Message) -> None:
    """Return recent 10 events summary."""
    if not _authorized(message):
        return
    if not _pool:
        await message.answer("DB pool not available")
        return

    rows = await _pool.fetch(
        """
        SELECT source, event_type, actor, created_at,
               substring(payload::text, 1, 80) as preview
        FROM events
        ORDER BY created_at DESC
        LIMIT 10
        """
    )
    if not rows:
        await message.answer("No events found.")
        return

    lines = ["<b>Recent Events</b>\n"]
    for r in rows:
        ts = r["created_at"].strftime("%H:%M") if r["created_at"] else "?"
        lines.append(f"  {ts} [{r['source']}] {r['event_type']} — {r['preview'][:60]}")
    await message.answer("\n".join(lines))


@router.message(Command("ok_drafts"))
async def cmd_drafts(message: Message) -> None:
    """List pending drafts with approve/reject buttons."""
    if not _authorized(message):
        return
    if not _pool:
        await message.answer("DB pool not available")
        return

    rows = await _pool.fetch(
        """
        SELECT id, room_name, original_message, draft_text, confidence
        FROM draft_replies
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT 10
        """
    )
    if not rows:
        await message.answer("No pending drafts.")
        return

    for r in rows:
        draft_id = str(r["id"])
        room = r["room_name"] or "?"
        original = (r["original_message"] or "")[:100]
        draft = (r["draft_text"] or "")[:300]
        conf = r["confidence"] or 0

        text = (
            f"<b>Draft</b> ({conf:.0%})\n"
            f"<b>Room:</b> {_esc(room)}\n"
            f"<b>Message:</b> {_esc(original)}\n\n"
            f"<b>Reply:</b>\n{_esc(draft)}"
        )
        await message.answer(text, reply_markup=_draft_keyboard(draft_id))


# ------------------------------------------------------------------
# Callback handlers (inline keyboard actions)
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(callback: CallbackQuery) -> None:
    """Approve a draft via inline button."""
    if not _authorized(callback):
        return
    draft_prefix = callback.data.split(":")[1]
    draft_id = await _resolve_draft_id(draft_prefix)
    if not draft_id:
        await callback.answer("Draft not found", show_alert=True)
        return

    await _pool.execute(
        "UPDATE draft_replies SET status = 'approved' WHERE id = $1",
        draft_id,
    )
    await callback.message.edit_text(
        callback.message.text + "\n\n<b>APPROVED</b>",
        reply_markup=None,
    )
    await callback.answer("Approved")


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(callback: CallbackQuery) -> None:
    """Reject a draft via inline button."""
    if not _authorized(callback):
        return
    draft_prefix = callback.data.split(":")[1]
    draft_id = await _resolve_draft_id(draft_prefix)
    if not draft_id:
        await callback.answer("Draft not found", show_alert=True)
        return

    await _pool.execute(
        "UPDATE draft_replies SET status = 'rejected' WHERE id = $1",
        draft_id,
    )
    await callback.message.edit_text(
        callback.message.text + "\n\n<b>REJECTED</b>",
        reply_markup=None,
    )
    await callback.answer("Rejected")


# ------------------------------------------------------------------
# Inward chat (any text without command prefix)
# ------------------------------------------------------------------

@router.message()
async def inward_chat(message: Message) -> None:
    """Route free-text messages through agent pipeline (inward mode)."""
    if not _authorized(message):
        return
    if not message.text:
        return

    # Send "thinking" indicator
    thinking_msg = await message.answer("Thinking...")

    try:
        from services.dashboard.twin_chat import ask_twin
        result = await ask_twin(message.text)
        reply = result.get("reply", "No response.")
        await thinking_msg.edit_text(reply)
    except Exception as exc:
        logger.error("telegram: inward chat error: %s", exc)
        await thinking_msg.edit_text(f"Error: {exc}")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

async def _resolve_draft_id(prefix: str) -> Any:
    """Resolve 8-char UUID prefix to full draft ID."""
    if not _pool:
        return None
    row = await _pool.fetchrow(
        "SELECT id FROM draft_replies WHERE id::text LIKE $1 AND status = 'pending'",
        f"{prefix}%",
    )
    return row["id"] if row else None


def _esc(text: str) -> str:
    """Escape HTML special characters for Telegram."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

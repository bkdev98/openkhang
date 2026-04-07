"""Telegram inline keyboard callbacks for draft approval workflow.

Handles approve, reject, edit, and detail actions from inline keyboards
attached to draft notification messages.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

router = Router()

# Edit state: maps chat_id → {draft_id} when waiting for edited text
_pending_edits: dict[int, dict] = {}


def is_editing(chat_id: int) -> bool:
    """Check if chat is in edit mode."""
    return chat_id in _pending_edits


def pop_edit(chat_id: int) -> dict | None:
    """Pop and return edit state for chat_id, or None."""
    return _pending_edits.pop(chat_id, None)


@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(callback: CallbackQuery) -> None:
    """Approve a draft via inline button and send the message to Matrix."""
    from .bot import _authorized, _pool, _resolve_draft_id, _send_approved_to_matrix

    if not _authorized(callback):
        return
    draft_prefix = callback.data.split(":")[1]
    draft_id = await _resolve_draft_id(draft_prefix)
    if not draft_id:
        await callback.answer("Draft not found", show_alert=True)
        return

    row = await _pool.fetchrow(
        "SELECT room_id, draft_text FROM draft_replies WHERE id = $1 AND status = 'pending'",
        draft_id,
    )
    if not row:
        await callback.answer("Draft already processed", show_alert=True)
        return

    await _pool.execute(
        "UPDATE draft_replies SET status = 'approved', reviewed_at = NOW(), reviewer_action = 'approve' WHERE id = $1",
        draft_id,
    )

    sent = await _send_approved_to_matrix(row["room_id"], row["draft_text"])
    status_label = "APPROVED & SENT" if sent else "APPROVED (send failed)"

    await callback.message.edit_text(
        callback.message.text + f"\n\n<b>{status_label}</b>",
        reply_markup=None,
    )
    await callback.answer("Approved" if sent else "Approved but send failed")


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(callback: CallbackQuery) -> None:
    """Reject a draft via inline button."""
    from .bot import _authorized, _pool, _resolve_draft_id

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


@router.callback_query(F.data.startswith("detail:"))
async def cb_detail(callback: CallbackQuery) -> None:
    """Show thread/conversation context for a draft to help review."""
    from .bot import _authorized, _pool, _resolve_draft_id, _friendly_name, _esc, bot

    if not _authorized(callback):
        return
    draft_prefix = callback.data.split(":")[1]
    draft_id = await _resolve_draft_id(draft_prefix)
    if not draft_id:
        await callback.answer("Draft not found", show_alert=True)
        return

    row = await _pool.fetchrow(
        """
        SELECT dr.room_id, dr.room_name, dr.original_message, dr.draft_text,
               e.payload->>'thread_event_id' as thread_event_id,
               e.payload->>'sender_display_name' as sender_display,
               e.payload->>'sender' as sender_raw
        FROM draft_replies dr
        LEFT JOIN events e ON dr.event_id = e.id
        WHERE dr.id = $1
        """,
        draft_id,
    )
    if not row:
        await callback.answer("Draft details not found", show_alert=True)
        return

    thread_id = row["thread_event_id"] or ""
    room_id = row["room_id"]
    sender = row["sender_display"] or _friendly_name(row["sender_raw"] or "")

    # Fetch thread messages if threaded, else room messages
    messages: list[dict] = []
    context_label = ""
    if thread_id:
        msgs = await _pool.fetch(
            """
            SELECT payload->>'sender_display_name' as sender,
                   payload->>'sender' as sender_raw,
                   payload->>'body' as body,
                   created_at
            FROM events
            WHERE source = 'chat' AND payload->>'thread_event_id' = $1
            ORDER BY created_at ASC
            LIMIT 20
            """,
            thread_id,
        )
        messages = [dict(m) for m in msgs]
        context_label = f"Thread ({len(messages)} messages)"
    else:
        msgs = await _pool.fetch(
            """
            SELECT payload->>'sender_display_name' as sender,
                   payload->>'sender' as sender_raw,
                   payload->>'body' as body,
                   created_at
            FROM events
            WHERE source = 'chat'
              AND (metadata->>'room_id' = $1 OR payload->>'room_id' = $1)
            ORDER BY created_at DESC
            LIMIT 10
            """,
            room_id,
        )
        messages = [dict(m) for m in reversed(msgs)]
        context_label = f"Recent room messages ({len(messages)})"

    if not messages:
        await callback.answer("No conversation context found", show_alert=True)
        return

    lines = [f"<b>{context_label}</b>\n"]
    for m in messages:
        s = m["sender"] or _friendly_name(m["sender_raw"] or "")
        s_short = s.split(" - ")[0].split()[-1] if s else "?"
        body = (m["body"] or "")[:150]
        ts = m["created_at"].strftime("%H:%M") if m["created_at"] else ""
        lines.append(f"<b>{ts}</b> {_esc(s_short)}: {_esc(body)}")

    lines.append(f"\n<b>Draft reply to {_esc(sender or 'unknown')}:</b>")
    lines.append(_esc((row["draft_text"] or "")[:500]))

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>(truncated)</i>"

    await bot.send_message(chat_id=callback.message.chat.id, text=text)
    await callback.answer()


@router.callback_query(F.data.startswith("edit:"))
async def cb_edit(callback: CallbackQuery) -> None:
    """Enter edit mode: next text message replaces the draft and sends it."""
    from .bot import _authorized, _pool, _resolve_draft_id, bot

    if not _authorized(callback):
        return
    draft_prefix = callback.data.split(":")[1]
    draft_id = await _resolve_draft_id(draft_prefix)
    if not draft_id:
        await callback.answer("Draft not found", show_alert=True)
        return

    chat_id = callback.message.chat.id
    _pending_edits[chat_id] = {"draft_id": draft_id}

    await bot.send_message(
        chat_id=chat_id,
        text="<b>Edit mode:</b> Send your edited reply text now.\nSend /cancel to abort.",
    )
    await callback.answer("Send edited text")


async def handle_edit_text(message: Message, draft_id: Any) -> None:
    """Process edited draft text: update DB, send to Matrix."""
    from .bot import _pool, _send_approved_to_matrix, _esc

    edited_text = message.text.strip()
    if not edited_text:
        await message.answer("Empty text — edit cancelled.")
        return

    row = await _pool.fetchrow(
        "SELECT room_id, status FROM draft_replies WHERE id = $1",
        draft_id,
    )
    if not row:
        await message.answer("Draft not found — may have been processed already.")
        return
    if row["status"] != "pending":
        await message.answer(f"Draft already {row['status']}.")
        return

    await _pool.execute(
        "UPDATE draft_replies SET status = 'edited', draft_text = $2, "
        "reviewed_at = NOW(), reviewer_action = 'edit' WHERE id = $1",
        draft_id, edited_text,
    )

    sent = await _send_approved_to_matrix(row["room_id"], edited_text)
    status = "EDITED & SENT" if sent else "EDITED (send failed)"
    await message.answer(f"<b>{status}</b>\n\n{_esc(edited_text[:500])}")

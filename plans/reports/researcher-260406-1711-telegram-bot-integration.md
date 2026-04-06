# Telegram Bot Integration: Architecture & Library Selection

**Date:** 2026-04-06 | **Status:** Complete | **Scope:** Framework selection, webhook pattern, rate limiting

## Executive Recommendation

**Use aiogram v3 (async) with webhook + FastAPI integration** for native fit with your existing stack. Pair with Redis pub/sub for bi-directional flow (agent→telegram push, telegram→agent inbound).

### Why aiogram over alternatives:

| Dimension | aiogram v3 | python-telegram-bot | Telethon |
|-----------|-----------|-------------------|---------|
| **Async-first** | ✓ Built for concurrency | Async retrofit (v20+) | MTProto protocol, overkill |
| **FastAPI integration** | ✓ Native webhook support | ✓ Works, less idiomatic | ✗ Designed for MTProto |
| **Production maturity** | ✓ Stable, active (2026) | ✓ 27k GH stars, battle-tested | ✓ But lower adoption for bots |
| **Webhook latency** | Best (3ms+ median) | Same | Slightly higher |
| **Learning curve** | Moderate | Low | Steep |
| **GH stars** | 1.8k | 27.7k | 10.9k |

**Verdict:** aiogram offers best coupling to your async Python stack + Redis. python-telegram-bot acceptable if you prefer zero learning curve, but requires middleware wrapping for pub/sub.

---

## Architecture Pattern

```
┌─────────────────────────────────────────────────────────┐
│ Telegram Users                                          │
└────────────┬────────────────────────────────────────────┘
             │
             ▼ (HTTP POST via Bot API)
┌─────────────────────────────────────────────────────────┐
│ FastAPI Webhook (port 8000, route: /telegram/webhook)  │
│                                                         │
│ ┌──────────────────────────────────────────────────┐   │
│ │ aiogram Router + Dispatcher                      │   │
│ │ • command handler (/status, /list_drafts)       │   │
│ │ • callback handler (approve_btn, reject_btn)    │   │
│ │ • message handler (user questions)              │   │
│ └──────────────────────────────────────────────────┘   │
└────┬─────────────────────────────────────────────────────┘
     │
     ├─────────────────────────────────────────────────┐
     │                                                 │
     ▼                                                 ▼
┌──────────────────────────┐        ┌────────────────────────┐
│ Redis Pub/Sub            │        │ Agent Pipeline         │
│                          │        │ (existing)             │
│ Channels:               │        │                        │
│ • telegram:inbound     │        │ • Process messages     │
│   (user questions)     │        │ • Generate drafts      │
│ • telegram:outbound    │◄───────│ • Status updates       │
│   (drafts, approvals)  │        │                        │
└──────────────────────────┘        └────────────────────────┘
```

**Flow:**
1. **Outbound (agent → Telegram)**: Agent publishes to `telegram:outbound` channel with draft/notification metadata. Bot subscriber sends `InlineKeyboardMarkup` with approve/reject buttons.
2. **Inbound (Telegram → agent)**: User sends `/status` or question → webhook handler → publish to `telegram:inbound` → agent processes and responds via `telegram:outbound`.
3. **Callback actions**: Button clicks trigger `callback_query` handler → update Postgres draft status → optional message edit to show "Approved ✓".

---

## Library Comparison Details

### aiogram v3
- **Async/await native**: Built for concurrent request handling (no event loop hacks).
- **Webhook support**: Official aiogram-fastapi-server package OR integrate directly into your FastAPI app.
- **Router pattern**: Clean separation of handlers (commands, messages, callbacks) — scales to 100+ commands.
- **Production bottleneck**: Slight overhead vs raw TDLib, but negligible for your use case (<1ms per message).

### python-telegram-bot v22
- **Maturity advantage**: 27k stars, exception docs, larger community.
- **Webhook retrofit**: Works, but requires `telegram.ext.Application` wrapper + explicit async context setup.
- **AIORateLimiter built-in**: Integrated rate limiting (20 msg/min per chat, 30 req/s global). aiogram lacks this — **you must add custom Redis-backed rate limiter**.

### Telethon
- **Eliminates HTTP middleman**: Speaks MTProto directly to Telegram servers. Advantage: better flood-limit handling, lower latency for bulk operations.
- **Downsides for your case**: Designed for user account automation. Bot mode exists but less polished. Overkill unless you need 1000+ msg/sec.

---

## Webhook vs Polling Trade-off

### Webhook (Recommended)
**Latency:** 190ms median (p95: 310ms) after switch from polling.
**Throughput:** Unlimited concurrent updates (Telegram load-balances across your servers).
**Setup:** Requires HTTPS + SSL cert. Use `ngrok` locally for dev, real cert in prod.
**Scaling:** Linear — add more FastAPI workers as QPS grows.

### Long-polling
**Latency:** 500ms median (p95: 1.1s).
**Throughput:** Blocks on single `getUpdates()` call — one poll per bot token.
**Setup:** Works behind NAT/firewall — no SSL needed.
**Scaling:** Hits Telegram API limits. Concurrent polls return HTTP 409 Conflict.

**Your choice:** Webhook. You already have FastAPI + HTTPS reverse proxy. Latency 3× better.

---

## Inline Keyboard Pattern (Approve/Reject)

```python
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Pattern: draft approval with context
kb = InlineKeyboardBuilder()
kb.add(InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_draft_{draft_id}"))
kb.add(InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_draft_{draft_id}"))

message = await bot.send_message(
    chat_id=user_id,
    text=f"Draft ready:\n{draft_preview}",
    reply_markup=kb.as_markup()
)

# Handler
@router.callback_query(lambda q: q.data.startswith("approve_draft_"))
async def approve_handler(query: CallbackQuery):
    draft_id = query.data.split("_")[2]
    
    # Update Postgres
    await db.update_draft(draft_id, status="approved")
    
    # Edit button to show checkmark (optional but smooth UX)
    await query.message.edit_text(f"✅ Approved")
    await query.answer()  # Dismiss loading spinner
```

**Key points:**
- `callback_data` max 64 bytes — use IDs, not full context.
- Call `query.answer()` to dismiss Telegram's "loading" indicator.
- Edit message text after action for visual feedback.
- Max 100 buttons per keyboard — not a constraint for your use case.

---

## Rate Limiting & Security

### Rate Limits (Telegram Hard Limits)
- **Per-chat:** 20 messages/60s
- **Per-bot:** 30 requests/1s (global)
- **Paid broadcast:** 1000 msg/s (requires Telegram Stars)

### Implementation (aiogram)
Telegram doesn't auto-throttle; HTTP 429 errors occur on overflow. **Add custom layer:**

```python
# Redis-backed rate limiter (pseudo-code)
async def check_rate_limit(user_id: int) -> bool:
    key = f"tg:user:{user_id}:msg_count"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)  # Reset window every 60s
    return count <= 20

# In message handler
if not await check_rate_limit(message.from_user.id):
    await message.reply("Rate limited. Try again in 60s.")
    return
```

### Security
1. **Webhook validation:** Telegram sends secret token in header. Verify it matches your bot token (or custom secret).
   ```python
   if request.headers.get("X-Telegram-Bot-API-Secret-Token") != WEBHOOK_SECRET:
       raise HTTPException(status_code=401)
   ```

2. **SQL injection:** Use parameterized queries for all Postgres operations (sqlalchemy does this by default).

3. **Callback data spoofing:** Sign callback_data with HMAC:
   ```python
   callback_data = f"approve_draft_{draft_id}_{hmac.new(SECRET, f'{draft_id}'.encode()).hexdigest()[:8]}"
   ```

---

## Integration Checklist

- [ ] Create `telegram/` service in `services/telegram/` (separate from dashboard).
- [ ] Webhook route: POST `/telegram/webhook` on FastAPI, validates signature.
- [ ] Subscribe to `telegram:outbound` Redis channel (agent publishes drafts).
- [ ] Publish `telegram:inbound` on user messages (agent consumes).
- [ ] Rate limiter: Redis-backed per-user counter, 20 msg/60s.
- [ ] Inline keyboards: `InlineKeyboardBuilder` for approve/reject, HMAC-signed callback_data.
- [ ] Error handling: HTTP 429 retry logic, Telegram API downtime graceful degradation.
- [ ] Logging: All user interactions → Postgres `telegram_events` table.
- [ ] Testing: Mock `aiogram.Bot` for unit tests, live webhook test with ngrok.

---

## Unresolved Questions

1. **Multi-user support?** Is this single-user (Khanh only) or multi-tenant? Affects user ID mapping & rate limiting scope.
2. **Command scope:** Which agent commands should be exposed? (/status, /list_drafts, /search, /execute_workflow?)
3. **Message retention:** How long to keep Telegram message history? Separate table or link to existing events table?
4. **Notification batching:** Should agent send 1 message per draft or batch 5 drafts into single message?

---

## Sources

- [python-telegram-bot vs aiogram comparison](https://piptrends.com/compare/python-telegram-bot-vs-aiogram)
- [aiogram webhook FastAPI integration](https://www.restack.io/p/fastapi-answer-aiogram-webhook)
- [FastAPI aiogram webhook template](https://github.com/QuvonchbekBobojonov/aiogram-webhook-template)
- [Webhook vs polling latency benchmarks](https://gramio.dev/updates/webhook)
- [Telegram webhook vs long-polling guide](https://hostman.com/tutorials/difference-between-polling-and-webhook-in-telegram-bots)
- [InlineKeyboardButton patterns](https://core.telegram.org/api/bots/buttons)
- [python-telegram-bot rate limiting](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits)
- [AIORateLimiter implementation](https://docs.python-telegram-bot.org/en/v22.0/telegram.ext.aioratelimiter.html)
- [Telegram Bot API rate limits](https://core.telegram.org/bots/faq)

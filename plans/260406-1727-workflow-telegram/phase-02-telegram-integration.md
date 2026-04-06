# Phase 2: Telegram Bot Integration

## Context Links
- Research report: `plans/reports/researcher-260406-1711-telegram-bot-integration.md`
- Dashboard app: `services/dashboard/app.py`
- Dashboard services: `services/dashboard/dashboard_services.py`
- Health checker: `services/dashboard/health_checker.py`
- Agent relay: `services/dashboard/agent_relay.py`
- Requirements: `services/requirements.txt`

## Overview
- **Priority**: P1
- **Status**: Pending
- **Effort**: 4.5h
- **Depends on**: Phase 1 (workflow actions publish to Redis)

Telegram bot for single user (Khanh). Push notifications on agent actions (auto-replies, drafts), draft approval via inline keyboards, system commands, and inward chat through agent pipeline.

## Key Design Decisions

1. **aiogram v3** — async-native, best FastAPI integration
2. **Webhook mode** — reuse existing FastAPI on :8000, route `POST /telegram/webhook`
3. **Single Redis channel** — subscribe to existing `openkhang:events` (no new channels)
4. **No rate limiter** — single user, low volume. YAGNI.
5. **No HMAC on callback_data** — single user, private bot. YAGNI.
6. **Polling fallback for dev** — when no `TELEGRAM_WEBHOOK_URL` set, use long-polling

## Data Flow

```
OUTBOUND (agent → Telegram):
  Redis openkhang:events
      │
      └─→ TelegramNotifier (asyncio task, subscribes to Redis)
              │
              ├─ source=agent, action=drafted → send draft notification + inline keyboard
              ├─ source=agent, action=auto_sent → send confirmation notification
              ├─ source=workflow, event_type=workflow.action → send workflow notification
              └─ source=workflow, needs_approval=true → send approval keyboard

INBOUND (Telegram → agent):
  Telegram webhook POST /telegram/webhook
      │
      └─→ aiogram Dispatcher
              │
              ├─ /status → query health_checker → reply
              ├─ /events → query recent events → reply
              ├─ /drafts → query pending drafts → reply with keyboards
              ├─ callback: approve:{id} → update draft_replies → edit message
              ├─ callback: reject:{id} → update draft_replies → edit message
              ├─ callback: edit:{id} → set state, prompt for text
              └─ text message → agent pipeline (inward mode) → reply
```

## Related Code Files

**Create:**
- `services/telegram/__init__.py` — empty
- `services/telegram/bot.py` — aiogram bot setup, command/callback handlers
- `services/telegram/notifier.py` — Redis subscriber → Telegram push

**Modify:**
- `services/dashboard/app.py` — add webhook route, start notifier task in lifespan
- `services/requirements.txt` — add `aiogram>=3.4.0`

**Read-only:**
- `services/dashboard/dashboard_services.py` — reuse `get_drafts()`, `approve_draft()`, etc.
- `services/dashboard/health_checker.py` — reuse `get_all_health()`

## Architecture

### services/telegram/bot.py (~180 lines)

Responsibilities:
- Initialize aiogram `Bot` and `Dispatcher`
- Register handlers via `Router`
- Provide `setup_webhook()` and `get_dispatcher()` for FastAPI integration
- Export `send_notification()` for the notifier to call

```python
# Key exports:
bot: Bot                          # aiogram Bot instance
dp: Dispatcher                    # aiogram Dispatcher
router: Router                    # handler router

async def setup_webhook(base_url: str) -> None
async def send_draft_notification(draft: dict) -> None
async def send_workflow_notification(action: dict) -> None
async def send_text(text: str) -> None
```

**Handler registration:**

| Handler | Trigger | Action |
|---------|---------|--------|
| `/start` | Command | Welcome message |
| `/status` | Command | Call `get_all_health(pool)`, format as text |
| `/events` | Command | Query last 10 events, format summary |
| `/drafts` | Command | Query pending drafts, send each with inline keyboard |
| `approve:{draft_id}` | Callback | Call `approve_draft()`, edit message to "Approved" |
| `reject:{draft_id}` | Callback | Call `reject_draft()`, edit message to "Rejected" |
| `edit:{draft_id}` | Callback | Set FSM state, ask for new text |
| Text (no command) | Message | Route through agent pipeline inward mode |

**Inline keyboard for drafts:**

```python
def draft_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Approve", callback_data=f"approve:{draft_id[:8]}")
    kb.button(text="Reject", callback_data=f"reject:{draft_id[:8]}")
    kb.button(text="Edit", callback_data=f"edit:{draft_id[:8]}")
    kb.adjust(3)
    return kb.as_markup()
```

**Note on draft_id**: callback_data max 64 bytes. Use first 8 chars of UUID + query DB with `LIKE` or store full ID mapping in memory dict.

### services/telegram/notifier.py (~100 lines)

Responsibilities:
- Subscribe to Redis `openkhang:events`
- Filter for events worth notifying (agent drafts, auto-replies, workflow actions)
- Call bot functions to send Telegram messages

```python
async def run_notifier(pool: asyncpg.Pool) -> None:
    """Long-running task: subscribe to Redis, push to Telegram."""
    redis_client = aioredis.from_url(redis_url)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("openkhang:events")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        data = json.loads(message["data"])

        # Agent drafted a reply
        if data.get("source") == "agent" and data.get("action") == "drafted":
            await send_draft_notification(data)

        # Agent auto-sent a reply
        elif data.get("source") == "agent" and data.get("action") == "auto_sent":
            await send_text(f"Auto-replied in {data.get('room_name', '?')}:\n{data.get('reply_text', '')[:200]}")

        # Workflow action
        elif data.get("source") == "workflow":
            await send_workflow_notification(data)
```

**Problem**: agent_relay currently does NOT publish pipeline results to Redis. Need to add Redis publish for agent results too (in Phase 1 scope or here).

**Solution**: Add Redis publish in agent_relay.py for pipeline results. Small addition — do it alongside workflow wiring in Phase 1.

### Modifications to services/dashboard/app.py

Add in lifespan:
```python
# After agent_task creation
telegram_task = None
if os.getenv("TELEGRAM_BOT_TOKEN"):
    from services.telegram.bot import setup_webhook, dp, bot
    from services.telegram.notifier import run_notifier

    # Set pool reference for handlers
    from services.telegram import bot as tg_bot_module
    tg_bot_module.set_pool(_svc._pool)

    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "")
    if webhook_url:
        await setup_webhook(webhook_url)
    telegram_task = asyncio.create_task(run_notifier(_svc._pool))
    logger.info("Telegram bot + notifier started")
```

Add webhook route:
```python
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    from services.telegram.bot import dp, bot
    from aiogram.types import Update
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}
```

### Addition to agent_relay.py (Phase 1 addendum)

Publish pipeline results to Redis so notifier can pick them up:

```python
# After pipeline.process_event() and logging
if result.action in ("drafted", "auto_sent"):
    await redis_client.publish(
        "openkhang:events",
        json.dumps({
            "source": "agent",
            "event_type": f"agent.{result.action}",
            "action": result.action,
            "room_name": event.get("room_name", ""),
            "sender": event.get("sender", ""),
            "body": event.get("body", "")[:200],
            "reply_text": result.reply_text[:500] if result.reply_text else "",
            "draft_id": result.draft_id,
            "confidence": result.confidence,
        }),
    )
```

## Implementation Steps

### Step 1: Add aiogram dependency
```bash
echo "aiogram>=3.4.0" >> services/requirements.txt
services/.venv/bin/pip install aiogram>=3.4.0
```

### Step 2: Create `services/telegram/__init__.py`
Empty file.

### Step 3: Create `services/telegram/bot.py`

1. Import aiogram Bot, Dispatcher, Router, types
2. Read `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from env
3. Create bot, dp, router instances
4. Implement `/start` — welcome message
5. Implement `/status` — call `get_all_health(pool)`, format checklist
6. Implement `/events` — query last 10 events from pool, format summary
7. Implement `/drafts` — query pending drafts, send each with inline keyboard
8. Implement callback handler for `approve:*`, `reject:*`, `edit:*`
9. Implement text handler — route through AgentPipeline inward mode
10. Export `setup_webhook()`, `send_draft_notification()`, `send_workflow_notification()`, `send_text()`
11. Export `set_pool()` to inject DB pool from lifespan

### Step 4: Create `services/telegram/notifier.py`

1. Subscribe to Redis `openkhang:events`
2. Filter for agent and workflow events
3. Call bot notification functions
4. Handle Redis disconnect with reconnect loop

### Step 5: Modify `services/dashboard/app.py`

1. Add Telegram bot init in lifespan (conditional on `TELEGRAM_BOT_TOKEN`)
2. Add webhook route `POST /telegram/webhook`
3. Add telegram_task cleanup in lifespan teardown

### Step 6: Add agent result publishing to agent_relay.py

1. Publish `drafted` and `auto_sent` results to Redis `openkhang:events`
2. This enables Telegram notifier to receive agent actions

### Step 7: Add env vars to `.env.example`
```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_WEBHOOK_URL=  # empty = polling mode for dev
```

## Todo List

- [ ] Add `aiogram>=3.4.0` to `services/requirements.txt`
- [ ] Create `services/telegram/__init__.py`
- [ ] Create `services/telegram/bot.py` with command handlers
- [ ] Implement `/status` command (health check)
- [ ] Implement `/events` command (recent events summary)
- [ ] Implement `/drafts` command (pending drafts with inline keyboards)
- [ ] Implement callback handlers (approve/reject/edit)
- [ ] Implement inward chat handler (text → agent pipeline → reply)
- [ ] Create `services/telegram/notifier.py` (Redis subscriber → push)
- [ ] Add webhook route to `services/dashboard/app.py`
- [ ] Add Telegram init to app lifespan (conditional)
- [ ] Add agent result Redis publishing to `agent_relay.py`
- [ ] Add env vars to `.env.example`
- [ ] Test: `/status` returns health info
- [ ] Test: draft notification arrives with inline keyboard
- [ ] Test: approve button updates draft in Postgres
- [ ] Test: free-text message gets agent reply

## Failure Modes

| Failure | Impact | Handling |
|---------|--------|----------|
| `TELEGRAM_BOT_TOKEN` not set | Bot disabled | Conditional init in lifespan, log info, skip |
| Telegram API unreachable | Notifications lost | Log warning, notifier continues listening |
| Webhook URL not reachable | Updates not received | Fallback: add polling mode option |
| Redis subscriber disconnects | Notifications stop | Reconnect loop with exponential backoff |
| Draft ID truncation collision | Wrong draft approved | Use 8-char prefix + DB LIKE query; collision probability negligible for single user |
| Agent pipeline slow on inward | Telegram timeout (no reply) | Send "Thinking..." immediately, edit with result |
| `app.py` lifespan grows too large | Maintenance burden | Accept for now; extract to `lifespan.py` if it crosses 100 lines |

## Security Considerations

- **Bot token**: env var only, never committed
- **Chat ID restriction**: All handlers check `message.chat.id == TELEGRAM_CHAT_ID` before processing
- **Webhook secret**: Use aiogram's built-in secret_token validation
- **No sensitive data in notifications**: Truncate message bodies, never include passwords/tokens

## Backwards Compatibility

- All Telegram code is additive — no existing behavior changes
- Bot is entirely opt-in via env var
- Dashboard continues to work identically without Telegram configured
- Existing Redis channel `openkhang:events` gains new message types (source=agent) — SSE feed may show them, which is fine

## Test Matrix

| Test | Type | What it validates |
|------|------|-------------------|
| Bot init without token | Unit | Graceful skip, no crash |
| `/status` handler | Integration | Health checker called, formatted response |
| `/drafts` handler | Integration | DB query, keyboard generation |
| Approve callback | Integration | Draft status updated in Postgres |
| Notifier receives agent draft | Integration | Redis → Telegram message sent |
| Notifier receives workflow action | Integration | Redis → Telegram message sent |
| Inward chat | E2E | Text → pipeline → reply in Telegram |
| Webhook signature validation | Unit | Invalid secret rejected with 401 |

## Next Steps

After both phases complete:
1. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to production `.env`
2. Set up ngrok or public URL for webhook
3. Run `@BotFather` `/setcommands` to register command menu
4. Monitor `audit_log` and Telegram for workflow triggers

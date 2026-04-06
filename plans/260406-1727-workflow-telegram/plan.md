---
title: "Workflow Wiring + Telegram Bot Integration"
description: "Wire orphaned workflow engine into agent_relay, add Telegram bot for notifications and draft approval"
status: pending
priority: P1
effort: 6h
branch: main
tags: [workflow, telegram, integration]
created: 2026-04-06
---

# Workflow Wiring + Telegram Bot Integration

## Overview

Two features to close the loop on the digital twin's automation and mobile access:

1. **Phase 1 (1.5h)**: Wire the existing (complete but orphaned) workflow engine into `agent_relay.py` so events trigger YAML-defined workflows after pipeline processing.
2. **Phase 2 (4.5h)**: Add Telegram bot via aiogram v3 for push notifications, draft approval via inline keyboards, and inward chat.

## Architecture

```
matrix-listener → Redis → events table
                              │
                    agent_relay.py (poll 3s)
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        AgentPipeline        WorkflowEngine     ← Phase 1
         (existing)          (existing, wired)
              │                     │
              ├─ auto_sent ─────────┼──→ Redis openkhang:events
              ├─ drafted ───────────┤
              └─ error              └──→ Postgres audit_log
                                        │
                              ┌─────────┘
                              ▼
                     TelegramNotifier           ← Phase 2
                     (Redis subscriber)
                              │
                              ▼
                     Telegram Bot API
                     (webhook on :8000)
                              │
                     ┌────────┴────────┐
                     ▼                 ▼
                Push notifications   Inbound commands
                (drafts, auto-replies)  (/status, /drafts, chat)
```

## Phases

| # | Phase | Status | Effort | Files Modified | Files Created |
|---|-------|--------|--------|----------------|---------------|
| 1 | [Workflow Wiring](phase-01-workflow-wiring.md) | Pending | 1.5h | `services/dashboard/agent_relay.py` | None |
| 2 | [Telegram Bot](phase-02-telegram-integration.md) | Pending | 4.5h | `services/dashboard/app.py`, `services/requirements.txt` | `services/telegram/bot.py`, `services/telegram/notifier.py`, `services/telegram/__init__.py` |

## Dependencies

- Phase 1 has no blockers (all workflow code exists)
- Phase 2 depends on Phase 1 (workflow actions should publish to Redis so Telegram notifier can pick them up)
- Phase 2 requires: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` in `.env`
- Phase 2 requires: ngrok or public URL for webhook in dev

## Risk Summary

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Workflow match on wrong event type | Medium | Medium | workflow trigger uses `chat_message` but events table has `message.received` — need mapping |
| Telegram webhook unreachable in dev | Low | High | Fallback to long-polling mode for local dev |
| Redis subscriber blocks event loop | Medium | Low | Use `asyncio.create_task` with proper cancellation |
| Rate limit from Telegram API | Low | Low | Single user, low volume; add Redis counter if needed later |

## Rollback

- **Phase 1**: Revert single file (`agent_relay.py`). Workflow engine stays dormant.
- **Phase 2**: Remove `services/telegram/`, revert `app.py` webhook route, remove `aiogram` from requirements. Zero impact on existing features.

## Success Criteria

- [ ] Phase 1: Workflow actions appear in `audit_log` table when bug-keyword chat message arrives
- [ ] Phase 1: Workflow actions published to Redis `openkhang:events` (visible in dashboard SSE)
- [ ] Phase 2: `/status` command returns service health in Telegram
- [ ] Phase 2: Draft notifications arrive with approve/reject inline keyboard
- [ ] Phase 2: Approve button marks draft as approved in Postgres and sends via Matrix
- [ ] Phase 2: Free-text message routed through agent pipeline and reply sent back

"""Redis subscriber that pushes agent events to Telegram.

Subscribes to openkhang:events and filters for agent drafts, auto-replies,
and workflow actions. Runs as a long-lived asyncio task.
"""

from __future__ import annotations

import json
import logging
import os

import asyncpg

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("OPENKHANG_REDIS_URL", "redis://localhost:6379")


async def run_notifier(pool: asyncpg.Pool) -> None:
    """Subscribe to Redis events, push relevant ones to Telegram.

    Reconnects automatically on Redis disconnect.
    """
    import redis.asyncio as aioredis
    from .bot import (
        send_draft_notification,
        send_auto_reply_notification,
        send_workflow_notification,
    )

    backoff = 1
    while True:
        try:
            client = aioredis.from_url(REDIS_URL)
            pubsub = client.pubsub()
            await pubsub.subscribe("openkhang:events")
            logger.info("telegram notifier: subscribed to openkhang:events")
            backoff = 1  # Reset on successful connect

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                source = data.get("source", "")
                action = data.get("action", "")
                event_type = data.get("event_type", "")

                # Agent drafted a reply — send with approval keyboard
                if source == "agent" and action == "drafted":
                    await send_draft_notification(data)

                # Agent auto-sent a reply — send confirmation
                elif source == "agent" and action == "auto_sent":
                    await send_auto_reply_notification(data)

                # Workflow action triggered
                elif source == "workflow" and event_type == "workflow.action":
                    await send_workflow_notification(data)

        except Exception as exc:
            logger.warning("telegram notifier: connection lost (%s), reconnecting in %ds", exc, backoff)
            import asyncio
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

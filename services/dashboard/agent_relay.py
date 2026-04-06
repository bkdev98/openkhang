"""Process new chat events through the agent pipeline.

Runs as an asyncio background task inside the dashboard process.
Watches the events table for new chat messages and feeds them through
the dual-mode agent, creating draft replies or auto-sending.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)

# Track last processed event to avoid re-processing
_last_processed: datetime | None = None


async def run_agent_relay(pool: asyncpg.Pool) -> None:
    """Poll events table for new chat messages, process through agent pipeline.

    Creates draft replies (or auto-sends if confidence is high enough).
    Runs continuously with 3s poll interval.
    """
    global _last_processed

    # Late import to avoid heavy deps at dashboard startup
    from services.agent.llm_client import LLMClient
    from services.agent.draft_queue import DraftQueue
    from services.agent.matrix_sender import MatrixSender
    from services.agent.pipeline import AgentPipeline
    from services.memory.config import MemoryConfig
    from services.memory.client import MemoryClient

    logger.info("agent_relay: initializing agent pipeline...")

    try:
        config = MemoryConfig.from_env()
        memory = MemoryClient(config)
        await memory.connect()

        llm = LLMClient(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        drafts = DraftQueue(config.database_url)
        await drafts.connect()
        sender = MatrixSender(
            homeserver=os.getenv("MATRIX_HOMESERVER", "http://localhost:8008"),
            access_token=os.getenv("MATRIX_ACCESS_TOKEN", ""),
        )

        pipeline = AgentPipeline(
            memory_client=memory,
            llm_client=llm,
            draft_queue=drafts,
            matrix_sender=sender,
        )
        logger.info("agent_relay: pipeline ready, polling for new chat events")
    except Exception as exc:
        logger.error("agent_relay: failed to initialize: %s", exc)
        return

    # Start from now — don't reprocess historical events
    _last_processed = datetime.now(timezone.utc)

    while True:
        await asyncio.sleep(3)

        try:
            rows = await pool.fetch(
                """
                SELECT id, source, event_type, actor, payload, metadata, created_at
                FROM events
                WHERE source = 'chat'
                  AND event_type = 'message.received'
                  AND created_at > $1
                ORDER BY created_at ASC
                LIMIT 5
                """,
                _last_processed,
            )

            for row in rows:
                _last_processed = row["created_at"]
                payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]

                body = payload.get("body", "")
                if not body or len(body) < 2:
                    continue

                # Skip own messages (prevent reply loop) and bot messages
                sender_id = payload.get("sender", "")
                own_user = os.getenv("MATRIX_USER", "@claude:localhost")
                if sender_id == own_user or sender_id.startswith("@claude:"):
                    continue
                if "bot" in sender_id.lower():
                    continue
                # Also skip if sender_id matches our googlechat puppet
                if "googlechat" in sender_id and os.getenv("MATRIX_USER", "") in sender_id:
                    continue

                sender_name = payload.get("sender_id", sender_id)
                event = {
                    "source": "matrix",
                    "body": body,
                    "sender": sender_name,
                    "sender_id": sender_name,  # pipeline reads sender_id
                    "room_id": payload.get("room_id", metadata.get("room_id", "")),
                    "room_name": payload.get("room_name", metadata.get("room_name", "")),
                    "event_id": str(row["id"]),
                    "thread_event_id": payload.get("thread_event_id", ""),
                }

                logger.info(
                    "agent_relay: processing [%s] %s — %s",
                    event["room_name"] or event["room_id"][:20],
                    event["sender"],
                    body[:60],
                )

                try:
                    result = await pipeline.process_event(event)
                    logger.info(
                        "agent_relay: %s conf=%.2f action=%s reply=%s",
                        result.mode,
                        result.confidence,
                        result.action,
                        result.reply_text[:60] if result.reply_text else "None",
                    )
                except Exception as exc:
                    logger.error("agent_relay: pipeline error: %s", exc)

        except Exception as exc:
            logger.error("agent_relay: poll error: %s", exc)

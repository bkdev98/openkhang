"""Process new chat events through the agent pipeline + workflow engine.

Runs as an asyncio background task inside the dashboard process.
Watches the events table for new chat messages, feeds them through
the dual-mode agent, then triggers matching workflows.
Publishes results to Redis for dashboard SSE and Telegram notifier.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)

# Track last processed event to avoid re-processing
_last_processed: datetime | None = None
# Dedup: track recently processed event IDs to prevent duplicate pipeline runs
_processed_event_ids: set[str] = set()
_MAX_PROCESSED_IDS = 500  # bounded to prevent unbounded memory growth

# Auto-reply toggle — when False, pipeline still runs but all replies go to draft (never auto-sends)
_autoreply_enabled: bool = False


def is_autoreply_enabled() -> bool:
    return _autoreply_enabled


def set_autoreply(enabled: bool) -> None:
    global _autoreply_enabled
    _autoreply_enabled = enabled
    logger.info("agent_relay: autoreply %s", "ENABLED" if enabled else "DISABLED")


async def run_agent_relay(pool: asyncpg.Pool) -> None:
    """Poll events table for new chat messages, process through agent + workflows.

    Creates draft replies (or auto-sends if confidence is high enough),
    then triggers any matching YAML workflows.
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
    from services.workflow import WorkflowEngine

    logger.info("agent_relay: initializing agent pipeline...")

    redis_client = None
    engine = None

    try:
        config = MemoryConfig.from_env()
        memory = MemoryClient(config)
        await memory.connect()

        llm = LLMClient(
            meridian_url=os.getenv("MERIDIAN_URL", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        )
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
        logger.info("agent_relay: pipeline ready")

        # Initialize workflow engine (graceful — relay works without it)
        try:
            engine = WorkflowEngine(
                memory_client=memory,
                agent_pipeline=pipeline,
                database_url=str(config.database_url),
                workflows_dir="config/workflows",
            )
            await engine.connect()
            await engine.load_workflows()
            logger.info("agent_relay: workflow engine ready (%d workflows)", len(engine._workflows))
        except Exception as exc:
            logger.warning("agent_relay: workflow engine init failed (continuing without): %s", exc)
            engine = None

        # Redis client for publishing events (notifier + dashboard SSE)
        try:
            import redis.asyncio as aioredis
            redis_url = os.getenv("OPENKHANG_REDIS_URL", "redis://localhost:6379")
            redis_client = aioredis.from_url(redis_url)
            await redis_client.ping()
            logger.info("agent_relay: redis publisher connected")
        except Exception as exc:
            logger.warning("agent_relay: redis publish init failed (continuing without): %s", exc)
            redis_client = None

    except Exception as exc:
        logger.error("agent_relay: failed to initialize: %s", exc)
        return

    # Start from now — don't reprocess historical events
    _last_processed = datetime.now(timezone.utc)

    # Debounce buffer: (sender, room_id) → list of (row, payload, metadata)
    # Holds messages for a short window to batch rapid-fire messages from same sender
    _debounce_buffer: dict[tuple[str, str], list[tuple[dict, dict, dict]]] = {}
    _debounce_deadline: dict[tuple[str, str], float] = {}
    _DEBOUNCE_SECONDS = 5.0  # wait this long after last message before processing

    try:
        while True:
            await asyncio.sleep(2)

            try:
                rows = await pool.fetch(
                    """
                    SELECT id, source, event_type, actor, payload, metadata, created_at
                    FROM events
                    WHERE source = 'chat'
                      AND event_type = 'message.received'
                      AND created_at >= $1
                    ORDER BY created_at ASC
                    LIMIT 10
                    """,
                    _last_processed,
                )

                # Collect new events into debounce buffer
                for row in rows:
                    _last_processed = row["created_at"]
                    event_db_id = str(row["id"])

                    # Dedup: skip if already processed
                    if event_db_id in _processed_event_ids:
                        continue
                    _processed_event_ids.add(event_db_id)
                    if len(_processed_event_ids) > _MAX_PROCESSED_IDS:
                        _processed_event_ids.clear()

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
                    if "googlechat" in sender_id and os.getenv("MATRIX_USER", "") in sender_id:
                        continue

                    room_id = payload.get("room_id", metadata.get("room_id", ""))
                    key = (sender_id, room_id)
                    _debounce_buffer.setdefault(key, []).append((dict(row), payload, metadata))
                    # Reset deadline: wait for more messages from this sender+room
                    _debounce_deadline[key] = _time.monotonic() + _DEBOUNCE_SECONDS

                # Process groups whose debounce deadline has passed
                now = _time.monotonic()
                ready_keys = [k for k, deadline in _debounce_deadline.items() if now >= deadline]

                for key in ready_keys:
                    entries = _debounce_buffer.pop(key, [])
                    _debounce_deadline.pop(key, None)
                    if not entries:
                        continue

                    # Use the LAST row as the primary event (most recent message)
                    last_row, last_payload, last_metadata = entries[-1]

                    # Combine bodies from all messages in the batch
                    if len(entries) > 1:
                        combined_body = "\n".join(e[1].get("body", "") for e in entries)
                        last_payload = {**last_payload, "body": combined_body}
                        logger.info(
                            "agent_relay: batched %d messages from %s in %s",
                            len(entries), key[0][:30], key[1][:20],
                        )

                    await _process_event(
                        last_row, last_payload, last_metadata,
                        pipeline, sender, drafts, engine, redis_client,
                    )

            except Exception as exc:
                logger.error("agent_relay: poll error: %s", exc)
    finally:
        if engine:
            try:
                await engine.close()
            except Exception:
                pass
        if redis_client:
            try:
                await redis_client.close()
            except Exception:
                pass


async def _process_event(
    row: dict,
    payload: dict,
    metadata: dict,
    pipeline,
    matrix_sender,
    drafts,
    engine,
    redis_client,
) -> None:
    """Process a single (possibly batched) event through the agent pipeline + workflows."""
    from services.agent.matrix_channel_adapter import MatrixChannelAdapter

    body = payload.get("body", "")
    matrix_adapter = MatrixChannelAdapter(
        matrix_sender=matrix_sender,
        draft_queue=drafts,
        confidence_scorer=pipeline._scorer,
    )
    msg = await matrix_adapter.normalize_inbound(row, payload, metadata)
    event = msg.to_legacy_dict()

    # Skip group messages where the owner is not mentioned — don't reply to unrelated threads
    if msg.is_group and not msg.is_mentioned:
        logger.info(
            "agent_relay: SKIPPED group [%s] — not mentioned. body=%s",
            event["room_name"] or event["room_id"][:20],
            body[:60],
        )
        return

    logger.info(
        "agent_relay: processing [%s] %s — %s",
        event["room_name"] or event["room_id"][:20],
        event.get("sender_display_name") or event["sender"],
        body[:60],
    )

    # --- Agent Pipeline ---
    try:
        result = await pipeline.process_event(event)
        logger.info(
            "agent_relay: %s conf=%.2f action=%s reply=%s",
            result.mode,
            result.confidence,
            result.action,
            result.reply_text[:60] if result.reply_text else "None",
        )

        # Publish agent result to Redis (for Telegram notifier + dashboard)
        if redis_client and result.action in ("drafted", "auto_sent"):
            await _publish_safe(redis_client, {
                "source": "agent",
                "event_type": f"agent.{result.action}",
                "action": result.action,
                "room_name": event.get("room_name", ""),
                "sender": event.get("sender", ""),
                "sender_display_name": event.get("sender_display_name", ""),
                "body": event.get("body", "")[:200],
                "reply_text": result.reply_text[:3000] if result.reply_text else "",
                "draft_id": result.draft_id or "",
                "confidence": result.confidence,
            })

    except Exception as exc:
        logger.error("agent_relay: pipeline error: %s", exc)
        return

    # --- Workflow Engine ---
    if engine:
        try:
            workflow_event = {
                **event,
                "type": "chat_message",
                "intent": result.intent,
                "action": result.action,
                "confidence": result.confidence,
            }
            actions = await engine.handle_event(workflow_event)
            for wa in actions:
                logger.info(
                    "agent_relay: workflow '%s' action=%s state=%s",
                    wa.workflow_name, wa.action_type, wa.state_name,
                )
                if redis_client:
                    await _publish_safe(redis_client, {
                        "source": "workflow",
                        "event_type": "workflow.action",
                        "workflow_name": wa.workflow_name,
                        "workflow_id": wa.workflow_id,
                        "action_type": wa.action_type,
                        "state": wa.state_name,
                        "success": wa.result.success,
                        "needs_approval": wa.result.needs_approval,
                        "output": wa.result.output,
                    })
        except Exception as exc:
            logger.error("agent_relay: workflow error: %s", exc)


async def _publish_safe(redis_client, data: dict) -> None:
    """Publish event to Redis, logging but never crashing on failure."""
    try:
        await redis_client.publish("openkhang:events", json.dumps(data, default=str))
    except Exception as exc:
        logger.warning("agent_relay: redis publish failed: %s", exc)

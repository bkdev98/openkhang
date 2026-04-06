"""Inward-mode chat adapter: routes dashboard questions through AgentPipeline."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def ask_twin(question: str) -> dict[str, Any]:
    """Process an inward-mode question through the agent pipeline.

    Late-imports AgentPipeline to avoid loading heavy ML deps at module init.

    Returns:
        dict with keys: reply_text, confidence, latency_ms, error
    """
    try:
        from ..agent.pipeline import AgentPipeline  # heavy dep — import on demand

        pipeline = AgentPipeline.from_env()
        await pipeline.connect()
        try:
            result = await pipeline.process_event({
                "body": question,
                "source": "dashboard",
                "sender_id": "dashboard_user",
                "mode_hint": "inward",
            })
            return {
                "reply_text": result.reply_text,
                "confidence": result.confidence,
                "latency_ms": result.latency_ms,
                "error": result.error,
            }
        finally:
            await pipeline.close()
    except Exception as exc:
        logger.error("ask_twin failed: %s", exc)
        return {
            "reply_text": "",
            "confidence": 0.0,
            "latency_ms": 0,
            "error": str(exc),
        }

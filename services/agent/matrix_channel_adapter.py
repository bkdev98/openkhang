"""Matrix channel adapter: normalize Matrix events and dispatch replies.

Extracts transport-specific logic from agent_relay.py and pipeline.py
into a single cohesive adapter for the Matrix protocol.

Responsibilities:
  - normalize_inbound: Postgres event row → CanonicalMessage
  - send_outbound: AgentResult → auto-send via MatrixSender or create draft
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .channel_adapter import CanonicalMessage, ChannelAdapter

if TYPE_CHECKING:
    from .confidence import ConfidenceScorer
    from .draft_queue import DraftQueue
    from .matrix_sender import MatrixSender
    from .pipeline import AgentResult

logger = logging.getLogger(__name__)

# @all is always a mention; owner-specific patterns derived from persona.yaml
_STATIC_MENTION_PATTERNS = [r"@all"]
_owner_mention_patterns: list[str] | None = None


def _get_mention_patterns() -> list[str]:
    """Build mention regex patterns from persona.yaml name. Cached after first call."""
    global _owner_mention_patterns
    if _owner_mention_patterns is not None:
        return _owner_mention_patterns

    import yaml
    from pathlib import Path
    persona_path = Path(__file__).parent.parent.parent / "config" / "persona.yaml"
    patterns = list(_STATIC_MENTION_PATTERNS)
    try:
        persona = yaml.safe_load(persona_path.read_text(encoding="utf-8")) or {}
        name = persona.get("name", "")
        if name:
            parts = name.lower().split()
            for part in parts:
                patterns.append(rf"@{part}")
                patterns.append(rf"\b{part}\b")
            if len(parts) > 1:
                patterns.append(rf"\b{' '.join(parts)}\b")
    except Exception:
        pass  # fail-open: no persona = no owner-specific mention patterns
    _owner_mention_patterns = patterns
    return _owner_mention_patterns


class MatrixChannelAdapter(ChannelAdapter):
    """Adapter for the Matrix chat protocol.

    Wraps MatrixSender, DraftQueue, and ConfidenceScorer to handle the full
    outbound routing decision (auto-send vs draft) that was previously spread
    across agent_relay.py and pipeline._route().
    """

    def __init__(
        self,
        matrix_sender: "MatrixSender",
        draft_queue: "DraftQueue",
        confidence_scorer: "ConfidenceScorer",
    ) -> None:
        self._sender = matrix_sender
        self._drafts = draft_queue
        self._scorer = confidence_scorer

    async def normalize_inbound(
        self,
        row: dict,
        payload: dict,
        metadata: dict,
    ) -> CanonicalMessage:
        """Convert a Postgres event row into a CanonicalMessage.

        Extracts body, sender, room identifiers from payload/metadata,
        and applies group-chat and mention heuristics.

        Args:
            row: Raw asyncpg Record dict (id, source, event_type, …).
            payload: Parsed JSON from row['payload'].
            metadata: Parsed JSON from row['metadata'].

        Returns:
            CanonicalMessage ready for AgentPipeline.process_event().
        """
        body = payload.get("body", "")
        sender_id = payload.get("sender_id", payload.get("sender", ""))
        room_id = payload.get("room_id", metadata.get("room_id", ""))
        room_name = payload.get("room_name", metadata.get("room_name", ""))
        thread_event_id = payload.get("thread_event_id", "")
        event_id = str(row.get("id", ""))

        is_group = _detect_group_chat(room_name)
        is_mentioned = _detect_mention(body)

        return CanonicalMessage(
            body=body,
            channel="matrix",
            sender_id=sender_id,
            room_id=room_id,
            room_name=room_name,
            thread_event_id=thread_event_id,
            event_id=event_id,
            is_group=is_group,
            is_mentioned=is_mentioned,
            raw={"row": dict(row), "payload": payload, "metadata": metadata},
        )

    async def send_outbound(
        self, result: "AgentResult", msg: CanonicalMessage
    ) -> str | None:
        """Route AgentResult back to Matrix: auto-send or create a draft.

        Mirrors the outward-mode routing in pipeline._route():
        1. Check confidence threshold and autoreply toggle.
        2. Auto-send via MatrixSender if above threshold.
        3. Fall back to draft queue on send failure or below threshold.

        Args:
            result: AgentResult from pipeline.
            msg: CanonicalMessage that produced the result.

        Returns:
            matrix_event_id on auto-send, draft_id on draft, None on skip.
        """
        from services.dashboard.agent_relay import is_autoreply_enabled

        room_id = msg.room_id

        if self._scorer.should_auto_send(result.confidence, room_id) and is_autoreply_enabled():
            try:
                matrix_event_id = await self._sender.send(
                    room_id=room_id,
                    text=result.reply_text,
                    thread_event_id=msg.thread_event_id or None,
                )
                logger.info(
                    "matrix_adapter: auto-sent to %s event=%s",
                    room_id,
                    matrix_event_id,
                )
                return matrix_event_id
            except RuntimeError as exc:
                logger.warning(
                    "matrix_adapter: auto-send failed (%s), falling back to draft", exc
                )

        # Store as draft for human review
        legacy = msg.to_legacy_dict()
        draft_id = await self._drafts.add_draft(
            room_id=room_id,
            original_message=legacy.get("body", ""),
            draft_text=result.reply_text,
            confidence=result.confidence,
            evidence=getattr(result, "evidence", []),
            room_name=msg.room_name,
            event_id=msg.event_id or None,
        )
        logger.info("matrix_adapter: draft created %s for room %s", draft_id, room_id)
        return draft_id


# ---------------------------------------------------------------------------
# Private helpers (extracted from pipeline.py static methods)
# ---------------------------------------------------------------------------

def _detect_group_chat(room_name: str) -> bool:
    """Detect if a room is a group chat based on its display name.

    Matrix DMs typically have an empty room_name or use the other
    person's name. Group rooms have descriptive names with spaces,
    hyphens, or keywords like 'team'.
    """
    if room_name and (
        " " in room_name
        or "-" in room_name
        or "team" in room_name.lower()
    ):
        return True
    return bool(room_name)


def _detect_mention(body: str) -> bool:
    """Check if a message body @mentions the owner by name or handle."""
    text = body.lower()
    return any(re.search(p, text) for p in _get_mention_patterns())

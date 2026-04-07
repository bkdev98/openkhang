"""Matrix channel adapter: normalize Matrix events and dispatch replies.

Extracts transport-specific logic from agent_relay.py and pipeline.py
into a single cohesive adapter for the Matrix protocol.

Responsibilities:
  - normalize_inbound: Postgres event row → CanonicalMessage
  - send_outbound: AgentResult → auto-send via MatrixSender or create draft
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .channel_adapter import CanonicalMessage, ChannelAdapter
from .mention_detector import detect_mention, get_mention_patterns

if TYPE_CHECKING:
    from .confidence import ConfidenceScorer
    from .draft_queue import DraftQueue
    from .matrix_sender import MatrixSender
    from .pipeline import AgentResult

logger = logging.getLogger(__name__)

# Re-export for backward compatibility (outward_reply_skill imports this)
_get_mention_patterns = get_mention_patterns


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

        # Extract member count from payload or metadata room state; fallback to name heuristic.
        # Matrix room member counts may be embedded in metadata under 'member_count' or
        # 'room_member_count' by the relay layer, or in payload for richer events.
        member_count = int(
            payload.get("member_count")
            or metadata.get("member_count")
            or metadata.get("room_member_count")
            or 0
        )
        # Group if explicit count > 2; otherwise fall back to room name heuristic
        is_group = member_count > 2 if member_count else _detect_group_chat(room_name)

        formatted_body = payload.get("formatted_body", "")
        is_mentioned = detect_mention(body, formatted_body)

        return CanonicalMessage(
            body=body,
            channel="matrix",
            sender_id=sender_id,
            room_id=room_id,
            room_name=room_name,
            sender_display_name=payload.get("sender_display_name", ""),
            thread_event_id=thread_event_id,
            event_id=event_id,
            is_group=is_group,
            is_mentioned=is_mentioned,
            member_count=member_count,
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



"""Dashboard channel adapter: normalize dashboard questions and return replies.

The dashboard is an inward-mode channel — questions come from the owner via the
web UI, and replies are returned directly (no Matrix send, no draft queue).

Responsibilities:
  - normalize_inbound: question string + session_id → CanonicalMessage
  - send_outbound: AgentResult → reply_text (returned to caller, not sent)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .channel_adapter import CanonicalMessage, ChannelAdapter

if TYPE_CHECKING:
    from .pipeline import AgentResult

logger = logging.getLogger(__name__)


class DashboardChannelAdapter(ChannelAdapter):
    """Adapter for the web dashboard (inward mode only).

    The dashboard always operates in inward mode: the owner asks questions,
    the pipeline generates a direct answer, and the answer is returned
    inline — no queuing, no Matrix dispatch.
    """

    async def normalize_inbound(
        self,
        question: str,
        session_id: str = "default",
    ) -> CanonicalMessage:
        """Convert a dashboard question into a CanonicalMessage.

        Mirrors the dict construction previously in twin_chat.py lines 61-66.
        The mode_hint 'inward' is preserved in raw for downstream consumers
        that inspect the original payload.

        Args:
            question: The question text from the dashboard UI.
            session_id: Caller's session identifier (unused internally but
                        preserved in raw for traceability).

        Returns:
            CanonicalMessage with channel='dashboard' and no room context.
        """
        return CanonicalMessage(
            body=question,
            channel="dashboard",
            sender_id="dashboard_user",
            raw={"mode_hint": "inward", "session_id": session_id},
        )

    async def send_outbound(
        self, result: "AgentResult", msg: CanonicalMessage
    ) -> str | None:
        """Return the reply text directly — no Matrix send for dashboard.

        The dashboard caller reads the reply from the AgentResult directly,
        so this method just surfaces reply_text as the return value.

        Args:
            result: AgentResult from pipeline.
            msg: CanonicalMessage that triggered the result (unused here).

        Returns:
            reply_text string, or None if the pipeline produced no reply.
        """
        if not result.reply_text:
            logger.debug("dashboard_adapter: empty reply_text from pipeline")
            return None
        return result.reply_text

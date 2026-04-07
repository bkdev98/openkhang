"""Telegram channel adapter stub.

Not yet implemented — placeholder to reserve the interface slot so
ResponseRouter can register a Telegram adapter without import errors.
Raises NotImplementedError on any call until a real implementation lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .channel_adapter import CanonicalMessage, ChannelAdapter

if TYPE_CHECKING:
    from .pipeline import AgentResult


class TelegramChannelAdapter(ChannelAdapter):
    """Stub adapter for Telegram. Not yet implemented."""

    async def normalize_inbound(self, *args, **kwargs) -> CanonicalMessage:
        raise NotImplementedError("Telegram adapter not yet implemented")

    async def send_outbound(
        self, result: "AgentResult", msg: CanonicalMessage
    ) -> str | None:
        raise NotImplementedError("Telegram adapter not yet implemented")

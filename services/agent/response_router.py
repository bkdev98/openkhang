"""ResponseRouter: dispatch AgentResult to the correct channel adapter.

Acts as a registry + dispatcher — callers register adapters by channel name
then call dispatch() to route a result through the appropriate adapter's
send_outbound() method.

Usage:
    router = ResponseRouter()
    router.register("matrix", matrix_adapter)
    router.register("dashboard", dashboard_adapter)

    reply = await router.dispatch(result, msg)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .channel_adapter import CanonicalMessage, ChannelAdapter

if TYPE_CHECKING:
    from .pipeline import AgentResult

logger = logging.getLogger(__name__)


class ResponseRouter:
    """Registry and dispatcher for channel adapters.

    Maintains a mapping of channel name → ChannelAdapter. When dispatch()
    is called, it looks up the adapter by msg.channel and delegates to
    adapter.send_outbound(). Unknown channels produce a warning and return
    None rather than raising, so a missing adapter is never fatal.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, channel: str, adapter: ChannelAdapter) -> None:
        """Register a ChannelAdapter for a given channel name.

        Re-registering the same channel replaces the previous adapter.

        Args:
            channel: Channel identifier string ('matrix', 'dashboard', etc.).
            adapter: ChannelAdapter instance to handle that channel.
        """
        if not isinstance(adapter, ChannelAdapter):
            raise TypeError(
                f"adapter must be a ChannelAdapter subclass, got {type(adapter).__name__}"
            )
        self._adapters[channel] = adapter
        logger.debug("response_router: registered adapter for channel '%s'", channel)

    def registered_channels(self) -> list[str]:
        """Return the list of currently registered channel names."""
        return list(self._adapters.keys())

    async def dispatch(
        self, result: "AgentResult", msg: CanonicalMessage
    ) -> str | None:
        """Route result to the appropriate channel adapter.

        Args:
            result: AgentResult from AgentPipeline.process_event().
            msg: CanonicalMessage carrying the channel identifier.

        Returns:
            Whatever the adapter's send_outbound() returns
            (event_id, draft_id, reply_text, or None).
        """
        adapter = self._adapters.get(msg.channel)
        if not adapter:
            logger.warning(
                "response_router: no adapter registered for channel '%s' — dropping result",
                msg.channel,
            )
            return None
        return await adapter.send_outbound(result, msg)

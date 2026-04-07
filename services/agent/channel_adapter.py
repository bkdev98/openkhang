"""Channel adapter abstraction for the digital twin agent.

Defines the CanonicalMessage dataclass and ChannelAdapter ABC that all
channel-specific adapters must implement. This layer decouples the agent
pipeline from transport-specific details (Matrix, Dashboard, Telegram, CLI).

Usage:
    msg = await adapter.normalize_inbound(...)
    result = await pipeline.process_event(msg)
    reply = await adapter.send_outbound(result, msg)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pipeline import AgentResult


@dataclass
class CanonicalMessage:
    """Transport-agnostic representation of an inbound message.

    All channel adapters normalize their raw payloads into this format
    before handing off to AgentPipeline. The ``raw`` field preserves the
    original payload for escape-hatch access when needed.
    """

    body: str
    channel: str              # 'matrix' | 'dashboard' | 'telegram' | 'cli'
    sender_id: str
    room_id: str = ""
    room_name: str = ""
    sender_display_name: str = ""   # resolved human-readable name from member events
    thread_event_id: str = ""
    event_id: str = ""
    is_group: bool = False
    is_mentioned: bool = False
    raw: dict = field(default_factory=dict)   # original payload for escape hatch

    def to_legacy_dict(self) -> dict:
        """Convert to raw dict format for backward compat with existing pipeline.

        The pipeline internally still works with plain dicts. This method
        bridges CanonicalMessage → dict so callers can pass either form
        to AgentPipeline.process_event().
        """
        return {
            "body": self.body,
            "source": self.channel if self.channel != "matrix" else "matrix",
            "room_id": self.room_id,
            "room_name": self.room_name,
            "sender_id": self.sender_id,
            "sender": self.sender_id,
            "sender_display_name": self.sender_display_name,
            "thread_event_id": self.thread_event_id,
            "event_id": self.event_id,
            "is_group": self.is_group,
            "is_mentioned": self.is_mentioned,
        }


class ChannelAdapter(ABC):
    """Abstract base class for channel-specific adapters.

    Each channel (Matrix, Dashboard, Telegram, CLI) implements this interface
    to handle inbound normalization and outbound dispatch independently from
    the agent pipeline business logic.
    """

    @abstractmethod
    async def normalize_inbound(self, *args, **kwargs) -> CanonicalMessage:
        """Convert a channel-native payload into a CanonicalMessage.

        Args:
            *args, **kwargs: Channel-specific arguments (row, payload, question, etc.)

        Returns:
            CanonicalMessage ready for AgentPipeline.process_event().
        """
        ...

    @abstractmethod
    async def send_outbound(self, result: "AgentResult", msg: CanonicalMessage) -> str | None:
        """Dispatch an AgentResult back through this channel.

        Args:
            result: The AgentResult from AgentPipeline.process_event().
            msg: The CanonicalMessage that triggered this result (for context).

        Returns:
            A string identifier (event_id, draft_id, reply_text) or None
            if no outbound action was taken.
        """
        ...

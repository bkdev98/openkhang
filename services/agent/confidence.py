"""Confidence scoring and auto-send threshold management.

Scores are 0.0-1.0. Higher = more confident the reply is safe to auto-send.
Default threshold is 0.85 (conservative). Per-room thresholds loaded from config.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from .llm_client import LLMResponse

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "confidence_thresholds.yaml"

# Confidence modifiers applied on top of LLM self-assessed score
MODIFIER_MANY_MEMORIES = +0.10     # 3+ relevant memories found
MODIFIER_DEADLINE_RISK = -0.20     # message asks about timeline/deadline
MODIFIER_UNKNOWN_SENDER = -0.15    # no prior interactions (reduced from -0.30)
MODIFIER_LANGUAGE_MISMATCH = -0.10 # message language differs from persona primary
MODIFIER_SOCIAL_INTENT = +0.25     # social messages (hi, thanks, emoji) are low-risk


class ConfidenceScorer:
    """Score LLM responses and decide whether to auto-send or queue as draft.

    Loads per-room thresholds from config/confidence_thresholds.yaml.
    Falls back to default_threshold (0.85) if file missing or room not listed.
    """

    def __init__(self) -> None:
        self._config = self._load_config()

    def score(
        self,
        llm_response: LLMResponse,
        memories: list[dict],
        event: dict,
        has_deadline_risk: bool = False,
        sender_known: bool = True,
        intent: str = "",
    ) -> float:
        """Compute final confidence score for a generated reply.

        Args:
            llm_response: Parsed LLM output including self-assessed confidence.
            memories: RAG results used in this reply.
            event: Original event dict (used for language check).
            has_deadline_risk: True if message contains deadline/timeline keywords.
            sender_known: False if no prior interactions exist for this sender.

        Returns:
            Clipped float in [0.0, 1.0].
        """
        base = llm_response.confidence

        # Bonus: many grounding memories available
        if len(memories) >= 3:
            base += MODIFIER_MANY_MEMORIES

        # Penalty: message asks about commitments/timelines
        if has_deadline_risk:
            base += MODIFIER_DEADLINE_RISK

        # Penalty: sender is unknown (higher risk of misrepresentation)
        if not sender_known:
            base += MODIFIER_UNKNOWN_SENDER

        # Bonus: social/greeting messages are low-risk and should auto-reply
        if intent in ("social", "fyi"):
            base += MODIFIER_SOCIAL_INTENT

        # Penalty: detected language mismatch (crude heuristic)
        if self._language_mismatch(event.get("body", "")):
            base += MODIFIER_LANGUAGE_MISMATCH

        return max(0.0, min(1.0, base))

    def should_auto_send(self, score: float, room_id: str) -> bool:
        """Return True if score meets the threshold for this room.

        Args:
            score: Confidence score from self.score().
            room_id: Matrix room ID — used to look up per-room threshold.

        Returns:
            True if reply should be sent automatically.
        """
        threshold = self._threshold_for_room(room_id)
        return score >= threshold

    def get_threshold(self, room_id: str) -> float:
        """Return the active threshold for a room (for logging/display)."""
        return self._threshold_for_room(room_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _threshold_for_room(self, room_id: str) -> float:
        """Look up per-room threshold, fall back to default."""
        graduated = self._config.get("graduated_spaces", {}) or {}
        if room_id and room_id in graduated:
            return float(graduated[room_id])
        return float(self._config.get("default_threshold", 0.85))

    def _language_mismatch(self, body: str) -> bool:
        """Very crude check: if body is all-ASCII with no Vietnamese chars,
        assume language mismatch is unlikely. Only flag when body contains
        a script that is clearly not Vietnamese or English.
        """
        # For now keep this conservative — only flag CJK scripts
        for ch in (body or ""):
            cp = ord(ch)
            # CJK Unified Ideographs (Chinese/Japanese/Korean)
            if 0x4E00 <= cp <= 0x9FFF:
                return True
        return False

    def _load_config(self) -> dict[str, Any]:
        """Load confidence thresholds YAML. Returns defaults if file missing."""
        try:
            text = CONFIG_PATH.read_text(encoding="utf-8")
            data = yaml.safe_load(text) or {}
            return data
        except FileNotFoundError:
            logger.warning("confidence_thresholds.yaml not found at %s, using defaults", CONFIG_PATH)
            return {"default_threshold": 0.85, "graduated_spaces": {}}
        except yaml.YAMLError as exc:
            logger.error("Failed to parse confidence_thresholds.yaml: %s", exc)
            return {"default_threshold": 0.85, "graduated_spaces": {}}

    def reload_config(self) -> None:
        """Reload thresholds from disk (useful after manual edits)."""
        self._config = self._load_config()

"""Confidence scoring and auto-send threshold management.

Scores are 0.0-1.0. Higher = more confident the reply is safe to auto-send.
Default threshold is 0.85 (conservative). Per-room thresholds loaded from config.

Modifiers are loaded from config/confidence_thresholds.yaml under the `modifiers:`
section. If that section is missing, hard-coded defaults provide backward compatibility.
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

# Hard-coded defaults — used only when YAML is missing or has no `modifiers:` section
_DEFAULT_MODIFIERS: dict[str, float] = {
    "many_memories": 0.10,
    "deadline_risk": -0.20,
    "unknown_sender": -0.15,
    "social_dm": 0.25,
    "no_history": -0.90,
    "cautious_sender": -0.30,
    "group_social_skip": -0.90,
    "high_priority_boost": 0.15,
    "low_priority_penalty": -0.10,
}

# Keep public constants for backward compatibility with existing tests
MODIFIER_MANY_MEMORIES = _DEFAULT_MODIFIERS["many_memories"]
MODIFIER_DEADLINE_RISK = _DEFAULT_MODIFIERS["deadline_risk"]
MODIFIER_UNKNOWN_SENDER = _DEFAULT_MODIFIERS["unknown_sender"]
MODIFIER_LANGUAGE_MISMATCH = -0.10  # not in YAML; kept as module-level constant
MODIFIER_SOCIAL_INTENT = _DEFAULT_MODIFIERS["social_dm"]
MODIFIER_GROUP_SOCIAL_SKIP = _DEFAULT_MODIFIERS["no_history"]
MODIFIER_CAUTIOUS_SENDER = _DEFAULT_MODIFIERS["cautious_sender"]
MODIFIER_NO_HISTORY = _DEFAULT_MODIFIERS["no_history"]


class ConfidenceScorer:
    """Score LLM responses and decide whether to auto-send or queue as draft.

    Loads per-room thresholds and modifiers from config/confidence_thresholds.yaml.
    Falls back to default_threshold (0.85) and _DEFAULT_MODIFIERS if file missing.
    """

    def __init__(self) -> None:
        self._config = self._load_config()
        self._modifiers: dict[str, float] = {
            **_DEFAULT_MODIFIERS,
            **({k: float(v) for k, v in self._config.get("modifiers", {}).items()}),
        }

    def _mod(self, key: str, default: float) -> float:
        """Read a named modifier, falling back to supplied default."""
        return self._modifiers.get(key, default)

    def score(
        self,
        llm_response: LLMResponse,
        memories: list[dict],
        event: dict,
        has_deadline_risk: bool = False,
        sender_known: bool = True,
        intent: str = "",
        has_history_in_room: bool = True,
        priority: str = "normal",
        is_group: bool = False,
    ) -> float:
        """Compute final confidence score for a generated reply.

        Args:
            llm_response: Parsed LLM output including self-assessed confidence.
            memories: RAG results used in this reply.
            event: Original event dict (used for language/sender checks).
            has_deadline_risk: True if message contains deadline/timeline keywords.
            sender_known: False if no prior interactions exist for this sender.
            intent: Classified intent label.
            has_history_in_room: False if the room has no prior history.
            priority: Router-assigned priority — 'high' | 'normal' | 'low'.
            is_group: Whether the message is in a group/multi-person room.

        Returns:
            Clipped float in [0.0, 1.0].
        """
        base = llm_response.confidence

        # Bonus: many grounding memories available
        if len(memories) >= 3:
            base += self._mod("many_memories", 0.10)

        # Penalty: message asks about commitments/timelines
        if has_deadline_risk:
            base += self._mod("deadline_risk", -0.20)

        # Penalty: sender is unknown (higher risk of misrepresentation)
        if not sender_known:
            base += self._mod("unknown_sender", -0.15)

        # Group chat logic: reply to work/mentions, SKIP social/humor
        if is_group:
            if intent in ("social", "fyi"):
                base += self._mod("group_social_skip", -0.90)  # social in groups → skip
            # work questions/requests in groups → normal confidence (draft if unsure)
        else:
            # DM: social messages are safe to auto-reply
            if intent in ("social", "fyi"):
                base += self._mod("social_dm", 0.25)

        # Penalty: never chatted in this space → skip entirely
        if not has_history_in_room:
            base += self._mod("no_history", -0.90)

        # Penalty: sender title suggests manager/lead (from room display name)
        if self._is_cautious_sender(event):
            base += self._mod("cautious_sender", -0.30)

        # Penalty: detected language mismatch (crude heuristic)
        if self._language_mismatch(event.get("body", "")):
            base += MODIFIER_LANGUAGE_MISMATCH

        # Priority adjustments from LLM router
        if priority == "high":
            base += self._mod("high_priority_boost", 0.15)
        elif priority == "low":
            base += self._mod("low_priority_penalty", -0.10)

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

    def _is_cautious_sender(self, event: dict) -> bool:
        """Check if sender title (from room display) contains manager/lead keywords."""
        sender = event.get("sender_id", "") + " " + event.get("sender", "")
        cautious = ["Manager", "Lead", "Director", "VP", "Head", "Chief"]
        check_text = sender.lower()
        return any(title.lower() in check_text for title in cautious)

    def _language_mismatch(self, body: str) -> bool:
        """Very crude check: only flag CJK scripts as language mismatch.

        Vietnamese uses Latin-based script, so no penalty for those messages.
        """
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
        self._modifiers = {
            **_DEFAULT_MODIFIERS,
            **({k: float(v) for k, v in self._config.get("modifiers", {}).items()}),
        }

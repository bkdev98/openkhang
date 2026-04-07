"""Skill registry — deterministic matching of mode+intent to skills.

Skills are composable units that orchestrate tools and LLM calls for a
specific mode+intent combination. The pipeline delegates to the first
matching skill instead of running inline logic.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SkillContext:
    """Shared context injected into all skills. Read-only view of pipeline deps."""

    classifier: Any  # Classifier instance
    scorer: Any      # ConfidenceScorer instance
    prompt_builder: Any  # PromptBuilder instance
    style_examples: list[dict] = field(default_factory=list)
    chat_history: list[dict] | None = None
    trace: Any = None  # TraceCollector instance (optional)


class BaseSkill(ABC):
    """Abstract base for all agent skills."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def match_criteria(self) -> dict:
        """Deterministic match rules.

        Supported keys:
            mode (str): exact mode string to match ('outward' | 'inward')
            intent (list[str]): intent must be in this list (empty = any)
            body_pattern (str): regex applied to message body (case-insensitive)
        """
        ...

    @abstractmethod
    async def execute(
        self,
        event: dict,
        tools: Any,
        llm: Any,
        context: SkillContext,
    ) -> Any: ...


class SkillRegistry:
    """Ordered registry of skills. First match wins (priority by registration order)."""

    def __init__(self) -> None:
        self._skills: list[BaseSkill] = []

    def register(self, skill: BaseSkill) -> None:
        """Append skill to registry. Register higher-priority skills first."""
        self._skills.append(skill)

    def match(self, mode: str, intent: str, body: str = "") -> BaseSkill | None:
        """Return first skill whose criteria match mode+intent+body.

        Returns None when no skill matches (pipeline falls back to inline logic).
        """
        for skill in self._skills:
            criteria = skill.match_criteria

            # Mode filter: must match exactly if specified
            if criteria.get("mode") and criteria["mode"] != mode:
                continue

            # Intent filter: must be in the allowed list if specified
            if criteria.get("intent") and intent not in criteria["intent"]:
                continue

            # Body pattern: regex must match if specified
            if criteria.get("body_pattern"):
                if not re.search(criteria["body_pattern"], body, re.IGNORECASE):
                    continue

            return skill

        return None

    def list_summaries(self) -> list[dict]:
        """Return name+description for all registered skills."""
        return [{"name": s.name, "description": s.description} for s in self._skills]

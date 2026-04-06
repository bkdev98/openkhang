"""State machine: data models and transition evaluation for workflow instances."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class State:
    """A single state in a workflow definition."""

    name: str
    # Actions executed on state entry: list of {type, params, tier?}
    actions: list[dict[str, Any]] = field(default_factory=list)
    # Ordered transitions: first matching condition wins
    transitions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class WorkflowInstance:
    """Runtime instance of a workflow in progress."""

    id: str
    workflow_name: str
    current_state: str
    # Accumulated data: event fields + action results
    context: dict[str, Any]
    created_at: datetime
    # active | paused | completed | failed
    status: str = "active"

    @classmethod
    def create(cls, workflow_name: str, trigger_event: dict[str, Any]) -> "WorkflowInstance":
        """Create a new instance from a trigger event."""
        return cls(
            id=str(uuid.uuid4()),
            workflow_name=workflow_name,
            current_state="__init__",
            context={"event": trigger_event},
            created_at=datetime.now(timezone.utc),
            status="active",
        )


class StateMachine:
    """Evaluate state transitions and decide which state comes next.

    Condition evaluation is intentionally simple: string matching against
    context keys. No expression parser — YAGNI.

    Supported condition strings:
      - "always"                 → always matches
      - "approved"               → context["approved"] is True
      - "rejected"               → context["approved"] is False
      - "action_success"         → context["last_action_success"] is True
      - "action_needs_approval"  → context["needs_approval"] is True
      - "memories_found >= N"    → len(context["memories"]) >= N
    """

    def transition(
        self, instance: WorkflowInstance, states: dict[str, State]
    ) -> Optional[str]:
        """Evaluate transitions for current state; return next state name or None.

        Returns None when no transition matches or state has no transitions
        (terminal state).
        """
        state = states.get(instance.current_state)
        if state is None:
            logger.warning(
                "Instance %s in unknown state '%s'", instance.id, instance.current_state
            )
            return None

        for transition in state.transitions:
            condition = transition.get("condition", "")
            next_state = transition.get("next", "")
            if self._evaluate(condition, instance.context):
                logger.debug(
                    "Instance %s: '%s' → '%s' (condition: %s)",
                    instance.id,
                    instance.current_state,
                    next_state,
                    condition,
                )
                return next_state

        return None

    # ------------------------------------------------------------------
    # Condition evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, condition: str, context: dict[str, Any]) -> bool:
        """Evaluate a single condition string against the workflow context."""
        condition = condition.strip()

        if condition == "always":
            return True

        if condition == "approved":
            return bool(context.get("approved"))

        if condition == "rejected":
            return context.get("approved") is False

        if condition == "action_success":
            return bool(context.get("last_action_success"))

        if condition == "action_needs_approval":
            return bool(context.get("needs_approval"))

        # "memories_found >= N"
        if condition.startswith("memories_found"):
            return self._eval_memories_found(condition, context)

        logger.warning("Unknown condition '%s', treating as False", condition)
        return False

    def _eval_memories_found(self, condition: str, context: dict[str, Any]) -> bool:
        """Evaluate 'memories_found >= N' condition."""
        memories = context.get("memories", [])
        count = len(memories) if isinstance(memories, list) else 0
        # Parse operator and threshold from condition string
        parts = condition.split()
        # Expected: ["memories_found", ">=", "N"]
        if len(parts) == 3:
            operator, threshold_str = parts[1], parts[2]
            try:
                threshold = int(threshold_str)
            except ValueError:
                return False
            if operator == ">=":
                return count >= threshold
            if operator == ">":
                return count > threshold
            if operator == "==":
                return count == threshold
            if operator == "<":
                return count < threshold
        return False

"""Core workflow engine: loads YAML definitions, matches events, drives state transitions."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from .action_executor import ActionExecutor, ActionResult
from .audit_log import AuditLog
from .state_machine import State, StateMachine, WorkflowInstance
from .workflow_persistence import WorkflowPersistence

logger = logging.getLogger(__name__)


@dataclass
class WorkflowAction:
    """Record of one action taken during a handle_event call."""

    workflow_id: str
    workflow_name: str
    state_name: str
    action_type: str
    result: ActionResult


@dataclass
class WorkflowDefinition:
    """Parsed representation of a YAML workflow file."""

    name: str
    description: str
    trigger_event: str                          # event type to match
    trigger_conditions: list[dict[str, Any]]    # additional condition filters
    states: dict[str, State]                    # state_name → State


class WorkflowEngine:
    """Match events to workflows, execute state transitions, return actions taken.

    Usage:
        engine = WorkflowEngine(memory_client, agent_pipeline)
        await engine.connect()
        await engine.load_workflows()
        actions = await engine.handle_event(event)
        await engine.close()
    """

    def __init__(
        self,
        memory_client: Any = None,
        agent_pipeline: Any = None,
        database_url: str = "",
        workflows_dir: str = "config/workflows",
    ) -> None:
        self._memory = memory_client
        self._agent = agent_pipeline
        self._workflows_dir = workflows_dir
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._machine = StateMachine()

        # Sub-components — require connect() before use
        self._executor = ActionExecutor(
            memory_client=memory_client,
            draft_queue=getattr(agent_pipeline, "_drafts", None) if agent_pipeline else None,
        )
        self._audit = AuditLog(database_url) if database_url else None
        self._persistence = WorkflowPersistence(database_url) if database_url else None

        # In-memory fallback when no DB is configured
        self._instances: dict[str, WorkflowInstance] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect audit log and persistence pool."""
        if self._audit:
            await self._audit.connect()
        if self._persistence:
            await self._persistence.connect()

    async def close(self) -> None:
        """Close DB connection pools."""
        if self._audit:
            await self._audit.close()
        if self._persistence:
            await self._persistence.close()

    # ------------------------------------------------------------------
    # Workflow loading
    # ------------------------------------------------------------------

    async def load_workflows(self) -> None:
        """Load all YAML workflow definitions from workflows_dir.

        Each .yaml file must have keys: name, trigger, states.
        Silently skips malformed files after logging a warning.
        """
        if not os.path.isdir(self._workflows_dir):
            logger.warning("Workflows directory not found: %s", self._workflows_dir)
            return

        loaded = 0
        for filename in os.listdir(self._workflows_dir):
            if not filename.endswith(".yaml") and not filename.endswith(".yml"):
                continue
            path = os.path.join(self._workflows_dir, filename)
            try:
                defn = _parse_workflow_file(path)
                self._workflows[defn.name] = defn
                loaded += 1
                logger.info("Loaded workflow '%s' from %s", defn.name, filename)
            except Exception as exc:
                logger.warning("Skipping malformed workflow file %s: %s", filename, exc)

        logger.info("Loaded %d workflow(s) from %s", loaded, self._workflows_dir)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    async def handle_event(self, event: dict[str, Any]) -> list[WorkflowAction]:
        """Match event against triggers, execute transitions, return actions taken.

        Steps:
          1. Find all workflows whose trigger matches this event.
          2. For each match, create a new WorkflowInstance.
          3. Drive the instance through states until it completes, pauses, or fails.
          4. Persist each instance after each transition.

        Returns:
            Flat list of WorkflowAction records for all instances driven this call.
        """
        matched = self._match_workflows(event)
        if not matched:
            return []

        all_actions: list[WorkflowAction] = []
        for defn in matched:
            instance = WorkflowInstance.create(defn.name, event)
            logger.info(
                "Starting workflow '%s' instance=%s", defn.name, instance.id
            )
            actions = await self._drive(instance, defn)
            all_actions.extend(actions)

        return all_actions

    async def resume(self, workflow_id: str) -> list[WorkflowAction]:
        """Resume a paused workflow instance (e.g. after human approval).

        Sets context["approved"] = True then re-drives the state machine.
        """
        instance = await self._load_instance(workflow_id)
        if instance is None:
            logger.warning("resume: instance %s not found", workflow_id)
            return []

        if instance.status != "paused":
            logger.warning(
                "resume: instance %s is '%s', not 'paused'", workflow_id, instance.status
            )
            return []

        defn = self._workflows.get(instance.workflow_name)
        if defn is None:
            logger.error(
                "resume: workflow definition '%s' not loaded", instance.workflow_name
            )
            return []

        instance.context["approved"] = True
        instance.context["needs_approval"] = False
        instance.status = "active"
        return await self._drive(instance, defn)

    # ------------------------------------------------------------------
    # State machine driver
    # ------------------------------------------------------------------

    async def _drive(
        self, instance: WorkflowInstance, defn: WorkflowDefinition
    ) -> list[WorkflowAction]:
        """Advance instance through states until terminal or paused.

        Starts at the first state in the definition (not '__init__').
        Caps at 20 transitions to prevent infinite loops.
        """
        all_actions: list[WorkflowAction] = []
        max_transitions = 20

        # Jump to initial state if brand new
        if instance.current_state == "__init__":
            first_state = next(iter(defn.states), None)
            if first_state is None:
                logger.error("Workflow '%s' has no states", defn.name)
                instance.status = "failed"
                await self._save_instance(instance)
                return all_actions
            instance.current_state = first_state

        for _ in range(max_transitions):
            state = defn.states.get(instance.current_state)
            if state is None:
                logger.error(
                    "Instance %s: unknown state '%s'",
                    instance.id, instance.current_state,
                )
                instance.status = "failed"
                break

            # Execute entry actions for this state
            actions = await self._execute_state_actions(instance, state, defn)
            all_actions.extend(actions)

            # Stop if paused (needs approval) or completed
            if instance.status in ("paused", "failed"):
                break

            if instance.current_state == "completed" or not state.transitions:
                instance.status = "completed"
                break

            # Evaluate transitions
            next_state = self._machine.transition(instance, defn.states)
            if next_state is None:
                # No matching transition — treat as terminal
                instance.status = "completed"
                break

            instance.current_state = next_state

            if next_state == "completed":
                instance.status = "completed"
                break

        else:
            logger.warning(
                "Instance %s hit transition limit — marking failed", instance.id
            )
            instance.status = "failed"

        await self._save_instance(instance)
        return all_actions

    async def _execute_state_actions(
        self,
        instance: WorkflowInstance,
        state: State,
        defn: WorkflowDefinition,
    ) -> list[WorkflowAction]:
        """Execute all entry actions for a state; update instance context."""
        taken: list[WorkflowAction] = []

        for action_def in state.actions:
            action_type = action_def.get("type", "")
            params = action_def.get("params", {})

            result = await self._executor.execute(
                action_type=action_type,
                params=params,
                context=instance.context,
            )

            # Merge action output into workflow context
            instance.context.update(result.output)
            instance.context["last_action_success"] = result.success
            instance.context["needs_approval"] = result.needs_approval

            if result.needs_approval:
                instance.status = "paused"
                logger.info(
                    "Workflow %s paused at state '%s' — action '%s' needs approval",
                    instance.id, state.name, action_type,
                )

            # Append to audit log (best-effort — never crash the workflow)
            if self._audit:
                try:
                    await self._audit.log_action(
                        workflow_id=instance.id,
                        action_type=action_type,
                        tier=result.tier,
                        params=params,
                        result=result.output,
                    )
                except Exception as exc:
                    logger.warning("Audit log failed: %s", exc)

            taken.append(
                WorkflowAction(
                    workflow_id=instance.id,
                    workflow_name=defn.name,
                    state_name=state.name,
                    action_type=action_type,
                    result=result,
                )
            )

            if result.needs_approval:
                break  # Don't execute further actions in this state

        return taken

    # ------------------------------------------------------------------
    # Trigger matching
    # ------------------------------------------------------------------

    def _match_workflows(
        self, event: dict[str, Any]
    ) -> list[WorkflowDefinition]:
        """Return all workflow definitions whose trigger matches the event."""
        matched: list[WorkflowDefinition] = []
        event_type = event.get("type") or event.get("event_type", "")

        for defn in self._workflows.values():
            if defn.trigger_event != event_type:
                continue
            if self._conditions_match(defn.trigger_conditions, event):
                matched.append(defn)

        return matched

    def _conditions_match(
        self, conditions: list[dict[str, Any]], event: dict[str, Any]
    ) -> bool:
        """All trigger conditions must match (AND semantics)."""
        for cond in conditions:
            if not self._single_condition_match(cond, event):
                return False
        return True

    def _single_condition_match(
        self, cond: dict[str, Any], event: dict[str, Any]
    ) -> bool:
        """Evaluate one trigger condition against the event."""
        # intent: <value>  → event["intent"] == value
        if "intent" in cond:
            return event.get("intent") == cond["intent"]

        # status: <value>  → event["status"] == value
        if "status" in cond:
            return event.get("status") == cond["status"]

        # body_contains_any: [word, ...]  → any word in event["body"]
        if "body_contains_any" in cond:
            body = (event.get("body") or "").lower()
            return any(kw.lower() in body for kw in cond["body_contains_any"])

        logger.debug("Unknown trigger condition key: %s", list(cond.keys()))
        return False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _save_instance(self, instance: WorkflowInstance) -> None:
        """Save to Postgres if available, else keep in memory."""
        self._instances[instance.id] = instance
        if self._persistence:
            try:
                await self._persistence.save_instance(instance)
            except Exception as exc:
                logger.warning("Failed to persist instance %s: %s", instance.id, exc)

    async def _load_instance(
        self, instance_id: str
    ) -> Optional[WorkflowInstance]:
        """Load from Postgres if available, else from in-memory cache."""
        if self._persistence:
            try:
                return await self._persistence.load_instance(instance_id)
            except Exception as exc:
                logger.warning("Failed to load instance %s from DB: %s", instance_id, exc)
        return self._instances.get(instance_id)


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------

def _parse_workflow_file(path: str) -> WorkflowDefinition:
    """Parse a YAML workflow file into a WorkflowDefinition.

    Raises ValueError or KeyError on malformed input.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    name = data["name"]
    description = data.get("description", "")
    trigger = data.get("trigger", {})
    trigger_event = trigger.get("event", "")
    trigger_conditions = trigger.get("conditions", [])

    raw_states: dict[str, Any] = data.get("states", {})
    states: dict[str, State] = {}
    for state_name, state_data in raw_states.items():
        if state_data is None:
            state_data = {}
        states[state_name] = State(
            name=state_name,
            actions=state_data.get("actions") or [],
            transitions=state_data.get("transitions") or [],
        )

    return WorkflowDefinition(
        name=name,
        description=description,
        trigger_event=trigger_event,
        trigger_conditions=trigger_conditions,
        states=states,
    )

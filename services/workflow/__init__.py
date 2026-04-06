"""Workflow engine for the openkhang digital twin system.

Lightweight state machine that matches events to YAML-defined workflows,
executes state transitions, and dispatches actions with autonomy-tier enforcement.
"""

from .workflow_engine import WorkflowEngine, WorkflowAction
from .state_machine import StateMachine, WorkflowInstance, State
from .action_executor import ActionExecutor, ActionResult
from .audit_log import AuditLog
from .workflow_persistence import WorkflowPersistence

__all__ = [
    "WorkflowEngine",
    "WorkflowAction",
    "StateMachine",
    "WorkflowInstance",
    "State",
    "ActionExecutor",
    "ActionResult",
    "AuditLog",
    "WorkflowPersistence",
]

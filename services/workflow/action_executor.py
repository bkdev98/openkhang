"""Action executor: dispatches workflow actions with autonomy-tier enforcement.

Tier map:
  1 - Read-only / non-mutating (auto-execute)
  2 - Reversible mutations (confidence-gated, may auto-execute)
  3 - Irreversible (always pause for human approval)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------
TIER_MAP: dict[str, int] = {
    "query_memory": 1,
    "send_chat_draft": 1,   # Creates a draft — doesn't send directly
    "create_jira": 2,
    "update_jira": 2,
    "send_chat": 2,
    "start_code_session": 2,
    "merge_mr": 3,
    "deploy": 3,
}


@dataclass
class ActionResult:
    """Result of executing a single workflow action."""

    action_type: str
    tier: int
    success: bool
    # When True, workflow should pause and wait for human approval
    needs_approval: bool = False
    # Structured output merged back into workflow context
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class ActionExecutor:
    """Execute workflow actions with autonomy-tier enforcement.

    Tier 1: always execute automatically.
    Tier 2: execute automatically (caller may gate on confidence).
    Tier 3: never execute — return needs_approval=True immediately.

    The memory_client and draft_queue are injected; other integrations
    (Jira, Matrix send) are stubbed — extend as those services are wired in.
    """

    def __init__(
        self,
        memory_client: Any = None,
        draft_queue: Any = None,
    ) -> None:
        self._memory = memory_client
        self._drafts = draft_queue

    async def execute(
        self,
        action_type: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> ActionResult:
        """Execute one action. Tier 3 always returns needs_approval without executing.

        Args:
            action_type: Key from TIER_MAP (e.g. 'query_memory', 'create_jira').
            params:      Raw params from YAML (may contain {event.field} templates).
            context:     Current workflow context for template interpolation.

        Returns:
            ActionResult with output merged into context by caller.
        """
        tier = TIER_MAP.get(action_type, 2)  # Unknown actions default to tier 2
        resolved = _interpolate(params, context)

        # Tier 3: irreversible — always pause for approval
        if tier == 3:
            logger.info(
                "Action '%s' (tier 3) requires approval — pausing workflow", action_type
            )
            return ActionResult(
                action_type=action_type,
                tier=tier,
                success=False,
                needs_approval=True,
                output={"pending_params": resolved},
            )

        # Tier 1 & 2: execute
        try:
            output = await self._dispatch(action_type, resolved, context)
            return ActionResult(
                action_type=action_type,
                tier=tier,
                success=True,
                output=output,
            )
        except Exception as exc:
            logger.exception("Action '%s' failed: %s", action_type, exc)
            return ActionResult(
                action_type=action_type,
                tier=tier,
                success=False,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Dispatch table
    # ------------------------------------------------------------------

    async def _dispatch(
        self, action_type: str, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Route to the appropriate action handler."""
        handlers = {
            "query_memory": self._query_memory,
            "send_chat_draft": self._send_chat_draft,
            "create_jira": self._create_jira,
            "update_jira": self._update_jira,
            "send_chat": self._send_chat,
            "start_code_session": self._start_code_session,
        }
        handler = handlers.get(action_type)
        if handler is None:
            raise ValueError(f"Unknown action type: '{action_type}'")
        return await handler(params, context)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _query_memory(
        self, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Query memory store and return matching memories."""
        if self._memory is None:
            logger.warning("query_memory: no memory_client configured, returning empty")
            return {"memories": []}

        query = params.get("query", "")
        limit = int(params.get("limit", 5))
        memories = await self._memory.search(query, limit=limit)
        return {"memories": memories}

    async def _send_chat_draft(
        self, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Queue a chat message as a draft (requires human approval to send)."""
        if self._drafts is None:
            logger.warning("send_chat_draft: no draft_queue configured, skipping")
            return {"draft_id": None}

        room_id = params.get("room_id", "")
        body = params.get("body", "")
        event = context.get("event", {})

        draft_id = await self._drafts.add_draft(
            room_id=room_id,
            original_message=event.get("body", ""),
            draft_text=body,
            confidence=0.9,   # Workflow-originated drafts are high-confidence
            evidence=["workflow_action"],
            room_name=event.get("room_name", ""),
            event_id=event.get("event_id"),
        )
        logger.info("send_chat_draft: queued draft_id=%s room=%s", draft_id, room_id)
        return {"draft_id": draft_id}

    async def _create_jira(
        self, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a Jira ticket. Stub — extend when Jira client is wired in."""
        summary = params.get("summary", "")
        description = params.get("description", "")
        logger.info("create_jira (stub): summary=%r description=%r", summary, description)
        # Return a placeholder key so downstream states have something to reference
        return {"jira_key": "PENDING-0", "jira_url": ""}

    async def _update_jira(
        self, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Update an existing Jira ticket. Stub."""
        issue_key = params.get("issue_key", "")
        logger.info("update_jira (stub): issue_key=%r params=%r", issue_key, params)
        return {"jira_key": issue_key}

    async def _send_chat(
        self, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a chat message directly (tier 2). Stub."""
        room_id = params.get("room_id", "")
        body = params.get("body", "")
        logger.info("send_chat (stub): room=%s body=%r", room_id, body[:80])
        return {"sent": True}

    async def _start_code_session(
        self, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Start a code review/dev session. Stub."""
        logger.info("start_code_session (stub): params=%r", params)
        return {"session_id": None}


# ---------------------------------------------------------------------------
# Template interpolation
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{([^}]+)\}")


def _interpolate(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Replace {key} / {event.field} placeholders in param values.

    Supports:
      {event.body}        → context["event"]["body"]
      {event.room_name}   → context["event"]["room_name"]
      {jira_key}          → context["jira_key"]
      {memories}          → str(context["memories"])

    Values that do not resolve are left as-is (empty string substitution only
    for top-level keys — never crash on missing data).
    """
    result: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str):
            result[key] = _TEMPLATE_RE.sub(lambda m: _resolve(m.group(1), context), value)
        else:
            result[key] = value
    return result


def _resolve(path: str, context: dict[str, Any]) -> str:
    """Walk dot-separated path into context dict; return '' on missing."""
    parts = path.split(".")
    node: Any = context
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part, "")
        else:
            return ""
    return str(node) if node is not None else ""

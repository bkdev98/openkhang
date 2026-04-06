"""Append-only audit log for workflow actions backed by Postgres."""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


class AuditLog:
    """Write and query the audit_log table.

    All workflow actions are appended here for traceability.
    Rows are never updated or deleted — append-only by design.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Create connection pool. Must be called before any method."""
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=1,
            max_size=5,
        )

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def log_action(
        self,
        workflow_id: str,
        action_type: str,
        tier: int,
        params: dict[str, Any],
        result: dict[str, Any],
        approved_by: Optional[str] = None,
    ) -> str:
        """Append one action record; returns the new audit row UUID.

        Args:
            workflow_id:  UUID of the WorkflowInstance.
            action_type:  e.g. 'query_memory', 'create_jira'.
            tier:         Autonomy tier (1, 2, or 3).
            params:       Resolved action parameters that were passed.
            result:       ActionResult.output dict.
            approved_by:  Human reviewer identifier when tier==3 was approved.
        """
        self._require_pool()
        import json
        row = await self._pool.fetchrow(  # type: ignore[union-attr]
            """
            INSERT INTO audit_log
                (workflow_id, action_type, tier, params, result, approved_by)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            UUID(workflow_id),
            action_type,
            tier,
            json.dumps(params),
            json.dumps(result),
            approved_by,
        )
        audit_id = str(row["id"])
        logger.debug(
            "Audit: workflow=%s action=%s tier=%d id=%s",
            workflow_id, action_type, tier, audit_id,
        )
        return audit_id

    async def query_by_workflow(
        self, workflow_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return all audit rows for a workflow instance, oldest first."""
        self._require_pool()
        rows = await self._pool.fetch(  # type: ignore[union-attr]
            """
            SELECT id, workflow_id, action_type, tier, params, result,
                   approved_by, created_at
            FROM audit_log
            WHERE workflow_id = $1
            ORDER BY created_at ASC
            LIMIT $2
            """,
            UUID(workflow_id),
            limit,
        )
        return [dict(r) for r in rows]

    async def query_by_action_type(
        self,
        action_type: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent audit rows matching an action type."""
        self._require_pool()
        rows = await self._pool.fetch(  # type: ignore[union-attr]
            """
            SELECT id, workflow_id, action_type, tier, params, result,
                   approved_by, created_at
            FROM audit_log
            WHERE action_type = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            action_type,
            limit,
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_pool(self) -> None:
        if self._pool is None:
            raise RuntimeError(
                "AuditLog.connect() was not called. "
                "Call `await audit_log.connect()` before use."
            )

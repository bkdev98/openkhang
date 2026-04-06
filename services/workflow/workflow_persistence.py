"""Workflow instance persistence backed by Postgres workflow_instances table."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import asyncpg

from .state_machine import WorkflowInstance

logger = logging.getLogger(__name__)


class WorkflowPersistence:
    """Save and load WorkflowInstance rows from Postgres.

    Table: workflow_instances
    Columns: id, workflow_name, current_state, context, trigger_event,
             status, created_at, updated_at
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

    async def save_instance(self, instance: WorkflowInstance) -> None:
        """Upsert a WorkflowInstance row (insert on first save, update thereafter)."""
        self._require_pool()
        now = datetime.now(timezone.utc)
        await self._pool.execute(  # type: ignore[union-attr]
            """
            INSERT INTO workflow_instances
                (id, workflow_name, current_state, context, trigger_event,
                 status, created_at, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                current_state = EXCLUDED.current_state,
                context       = EXCLUDED.context,
                status        = EXCLUDED.status,
                updated_at    = EXCLUDED.updated_at
            """,
            UUID(instance.id),
            instance.workflow_name,
            instance.current_state,
            json.dumps(instance.context),
            json.dumps(instance.context.get("event", {})),
            instance.status,
            instance.created_at,
            now,
        )
        logger.debug(
            "Persisted instance id=%s workflow=%s state=%s status=%s",
            instance.id, instance.workflow_name,
            instance.current_state, instance.status,
        )

    async def load_instance(self, instance_id: str) -> Optional[WorkflowInstance]:
        """Load a WorkflowInstance by UUID. Returns None if not found."""
        self._require_pool()
        row = await self._pool.fetchrow(  # type: ignore[union-attr]
            "SELECT * FROM workflow_instances WHERE id = $1",
            UUID(instance_id),
        )
        if row is None:
            return None
        return _row_to_instance(dict(row))

    async def list_active(self, limit: int = 100) -> list[WorkflowInstance]:
        """Return all instances with status='active' or 'paused', oldest first."""
        self._require_pool()
        rows = await self._pool.fetch(  # type: ignore[union-attr]
            """
            SELECT * FROM workflow_instances
            WHERE status IN ('active', 'paused')
            ORDER BY created_at ASC
            LIMIT $1
            """,
            limit,
        )
        return [_row_to_instance(dict(r)) for r in rows]

    async def list_by_workflow(
        self, workflow_name: str, limit: int = 50
    ) -> list[WorkflowInstance]:
        """Return instances for a specific workflow definition, newest first."""
        self._require_pool()
        rows = await self._pool.fetch(  # type: ignore[union-attr]
            """
            SELECT * FROM workflow_instances
            WHERE workflow_name = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            workflow_name,
            limit,
        )
        return [_row_to_instance(dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_pool(self) -> None:
        if self._pool is None:
            raise RuntimeError(
                "WorkflowPersistence.connect() was not called. "
                "Call `await persistence.connect()` before use."
            )


def _row_to_instance(row: dict[str, Any]) -> WorkflowInstance:
    """Convert a raw Postgres row dict to a WorkflowInstance."""
    context = row.get("context")
    if isinstance(context, str):
        context = json.loads(context)
    elif context is None:
        context = {}

    created_at = row.get("created_at")
    if not isinstance(created_at, datetime):
        created_at = datetime.now(timezone.utc)

    return WorkflowInstance(
        id=str(row["id"]),
        workflow_name=row["workflow_name"],
        current_state=row["current_state"],
        context=context,
        created_at=created_at,
        status=row.get("status", "active"),
    )

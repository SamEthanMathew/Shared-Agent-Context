"""Append-only audit log. Every sensitive read/write is attributable."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from ..db import audit_events, utcnow


class AuditStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def emit(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        project_id: str | None = None,
        actor_user_id: str | None = None,
        actor_agent_id: str | None = None,
        meta: dict[str, Any] | None = None,
        conn: Connection | None = None,
    ) -> None:
        values = dict(
            id=str(uuid.uuid4()),
            project_id=project_id,
            actor_user_id=actor_user_id,
            actor_agent_id=actor_agent_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            meta=meta or {},
            created_at=utcnow(),
        )
        if conn is not None:
            conn.execute(audit_events.insert().values(**values))
        else:
            with self.engine.begin() as own:
                own.execute(audit_events.insert().values(**values))

    def recent(self, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(audit_events)
                .where(audit_events.c.project_id == project_id)
                .order_by(audit_events.c.created_at.desc())
                .limit(max(1, min(int(limit), 500)))
            ).all()
        return [dict(r._mapping) for r in rows]

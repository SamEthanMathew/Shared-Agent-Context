"""Context snapshots — the server-side record of exactly what SAC returned.

Doubles as the privacy manifest (privacy doc §10): included memories with the
section they landed in, plus excluded memories with the reason they were
withheld (budget, or an aggregate count of other users' private memories).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from ..db import context_snapshots, utcnow


class SnapshotStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def record(
        self,
        project_id: str,
        session_id: str | None,
        user_id: str,
        agent_connection_id: str | None,
        project_revision: int,
        task: str,
        budget_tokens: int,
        token_estimate: int,
        included: list[dict[str, Any]],
        excluded: list[dict[str, Any]],
        compiler_policy: str = "lexical_v1",
    ) -> str:
        snapshot_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                context_snapshots.insert().values(
                    id=snapshot_id,
                    project_id=project_id,
                    session_id=session_id,
                    user_id=user_id,
                    agent_connection_id=agent_connection_id,
                    project_revision=project_revision,
                    task=task,
                    budget_tokens=budget_tokens,
                    token_estimate=token_estimate,
                    included=included,
                    excluded=excluded,
                    compiler_policy=compiler_policy,
                    created_at=utcnow(),
                )
            )
        return snapshot_id

    def get(self, snapshot_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(context_snapshots).where(
                    context_snapshots.c.id == snapshot_id
                )
            ).first()
        return dict(row._mapping) if row else None

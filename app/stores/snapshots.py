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

    def list_for_user(
        self, project_id: str, user_id: str, limit: int = 25
    ) -> list[dict[str, Any]]:
        """A user's own compile records for a context, newest first.

        Deliberately scoped to the caller: a snapshot enumerates exactly which
        memories were fed to that person's agent, including their private ones,
        so it is not another member's business — not even an admin's.
        """
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(context_snapshots)
                .where(
                    context_snapshots.c.project_id == project_id,
                    context_snapshots.c.user_id == user_id,
                )
                .order_by(context_snapshots.c.created_at.desc())
                .limit(max(1, min(int(limit), 200)))
            ).all()
        out = []
        for r in rows:
            m = dict(r._mapping)
            included = m.get("included") or []
            excluded = m.get("excluded") or []
            out.append({
                "id": m["id"],
                "task": m["task"],
                "project_revision": m["project_revision"],
                "budget_tokens": m["budget_tokens"],
                "token_estimate": m["token_estimate"],
                "included_count": len(included),
                "excluded_count": len(excluded),
                "withheld_private": sum(
                    e.get("count", 0) for e in excluded
                    if e.get("reason") == "not_visible_private_other"
                ),
                "created_at": m["created_at"],
                "compiler_policy": m["compiler_policy"],
            })
        return out

    def get(self, snapshot_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(context_snapshots).where(
                    context_snapshots.c.id == snapshot_id
                )
            ).first()
        return dict(row._mapping) if row else None

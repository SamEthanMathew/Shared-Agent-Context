"""Per-(project, user, session-ref) sync watermark tracking."""
from __future__ import annotations

import uuid

from sqlalchemy import case, select, update
from sqlalchemy.engine import Engine

from ..db import sessions, utcnow
from ..models import SessionRecord


def _row_to_session(m) -> SessionRecord:
    return SessionRecord(
        id=m["id"],
        project_id=m["project_id"],
        user_id=m["user_id"],
        agent_connection_id=m["agent_connection_id"],
        client_session_ref=m["client_session_ref"],
        last_seen_revision=int(m["last_seen_revision"]),
        last_task=m["last_task"] or "",
        created_at=m["created_at"],
        last_seen_at=m["last_seen_at"],
    )


class SessionStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_or_create(
        self,
        project_id: str,
        user_id: str,
        client_session_ref: str,
        agent_connection_id: str | None = None,
    ) -> SessionRecord:
        client_session_ref = (client_session_ref or "").strip() or "default"
        now = utcnow()
        with self.engine.begin() as conn:
            # The common case is a session that already exists — every turn of
            # every conversation lands here. Touching it and reading it back in
            # one statement halves that cost; the row is returned post-update, so
            # what the caller sees is what is now stored.
            row = conn.execute(
                update(sessions)
                .where(
                    sessions.c.project_id == project_id,
                    sessions.c.user_id == user_id,
                    sessions.c.client_session_ref == client_session_ref,
                )
                .values(last_seen_at=now, agent_connection_id=agent_connection_id)
                .returning(*sessions.c)
            ).first()
            if row:
                return _row_to_session(row._mapping)
            session_id = str(uuid.uuid4())
            conn.execute(
                sessions.insert().values(
                    id=session_id,
                    project_id=project_id,
                    user_id=user_id,
                    agent_connection_id=agent_connection_id,
                    client_session_ref=client_session_ref,
                    last_seen_revision=0,
                    last_task="",
                    created_at=now,
                    last_seen_at=now,
                )
            )
        return SessionRecord(
            id=session_id,
            project_id=project_id,
            user_id=user_id,
            agent_connection_id=agent_connection_id,
            client_session_ref=client_session_ref,
            last_seen_revision=0,
            last_task="",
            created_at=now,
            last_seen_at=now,
        )

    def get(self, session_id: str) -> SessionRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(sessions).where(sessions.c.id == session_id)
            ).first()
        return _row_to_session(row._mapping) if row else None

    def advance_watermark(self, session_id: str, revision: int, task: str = "") -> None:
        """Move the watermark forward only. Never rewinds on a stale revision.

        The forward-only rule is expressed in the UPDATE rather than as a read
        then a write. That is one round trip instead of two, and it also closes
        the window where two syncs of the same session could each read the old
        watermark and the later one write back the lower number — which would
        redeliver changes the agent had already been given.
        """
        now = utcnow()
        revision = int(revision)
        keep_the_higher = case(
            (sessions.c.last_seen_revision > revision, sessions.c.last_seen_revision),
            else_=revision,
        )
        with self.engine.begin() as conn:
            conn.execute(
                update(sessions)
                .where(sessions.c.id == session_id)
                .values(
                    last_seen_revision=keep_the_higher,
                    last_task=task,
                    last_seen_at=now,
                )
            )

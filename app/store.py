from __future__ import annotations

import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine


STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "into", "about", "your",
    "you", "are", "was", "were", "have", "has", "had", "will", "would", "should",
    "could", "can", "our", "their", "they", "them", "then", "than", "when", "what",
    "which", "where", "while", "how", "why", "who", "use", "using", "used", "make",
    "made", "need", "needs", "work", "working", "project", "context", "shared",
}

KIND_WEIGHT = {
    "decision": 2.5,
    "requirement": 2.2,
    "constraint": 2.2,
    "finding": 1.8,
    "result": 1.7,
    "observation": 1.4,
    "session_delta": 1.2,
    "task": 1.0,
    "note": 1.0,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_\-]{3,}", (text or "").lower())
    return {word for word in words if word not in STOPWORDS}


metadata = MetaData()

project_counters = Table(
    "project_counters",
    metadata,
    Column("project_id", String(128), primary_key=True),
    Column("revision", Integer, nullable=False, default=0),
)

memories = Table(
    "memories",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(128), nullable=False, index=True),
    Column("revision", Integer, nullable=False),
    Column("actor", String(128), nullable=False),
    Column("session_id", String(128), nullable=False),
    Column("kind", String(64), nullable=False),
    Column("summary", Text, nullable=False),
    Column("details", Text, nullable=False, default=""),
    Column("tags", Text, nullable=False, default=""),
    Column("importance", Float, nullable=False, default=0.5),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("project_id", "revision", name="uq_project_revision"),
)

sessions = Table(
    "sessions",
    metadata,
    Column("project_id", String(128), primary_key=True),
    Column("actor", String(128), primary_key=True),
    Column("session_id", String(128), primary_key=True),
    Column("last_seen_revision", Integer, nullable=False, default=0),
    Column("last_task", Text, nullable=False, default=""),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


@dataclass
class MemoryRecord:
    id: str
    revision: int
    actor: str
    session_id: str
    kind: str
    summary: str
    details: str
    tags: list[str]
    importance: float
    created_at: datetime

    def as_dict(self, include_details: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "revision": self.revision,
            "actor": self.actor,
            "session_id": self.session_id,
            "kind": self.kind,
            "summary": self.summary,
            "tags": self.tags,
            "importance": self.importance,
            "created_at": self.created_at.isoformat(),
        }
        if include_details and self.details:
            result["details"] = self.details
        return result


class SACStore:
    def __init__(self, database_url: str | None = None) -> None:
        url = normalize_database_url(
            database_url
            or os.getenv("DATABASE_URL")
            or "sqlite:///./sac.db"
        )
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )

    def init(self) -> None:
        metadata.create_all(self.engine)

    def _next_revision(self, conn, project_id: str) -> int:
        row = conn.execute(
            select(project_counters.c.revision)
            .where(project_counters.c.project_id == project_id)
            .with_for_update()
        ).first()

        if row is None:
            next_revision = 1
            conn.execute(
                insert(project_counters).values(
                    project_id=project_id,
                    revision=next_revision,
                )
            )
            return next_revision

        next_revision = int(row.revision) + 1
        conn.execute(
            update(project_counters)
            .where(project_counters.c.project_id == project_id)
            .values(revision=next_revision)
        )
        return next_revision

    def current_revision(self, project_id: str) -> int:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(project_counters.c.revision).where(
                    project_counters.c.project_id == project_id
                )
            ).first()
            return int(row.revision) if row else 0

    def add_memory(
        self,
        project_id: str,
        actor: str,
        session_id: str,
        kind: str,
        summary: str,
        details: str = "",
        tags: list[str] | None = None,
        importance: float = 0.5,
    ) -> MemoryRecord:
        summary = (summary or "").strip()
        details = (details or "").strip()
        if not summary:
            raise ValueError("summary must not be empty")

        kind = (kind or "note").strip().lower()
        importance = max(0.0, min(float(importance), 1.0))
        tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
        created_at = utcnow()
        memory_id = str(uuid.uuid4())

        with self.engine.begin() as conn:
            revision = self._next_revision(conn, project_id)
            conn.execute(
                insert(memories).values(
                    id=memory_id,
                    project_id=project_id,
                    revision=revision,
                    actor=actor,
                    session_id=session_id,
                    kind=kind,
                    summary=summary,
                    details=details,
                    tags=",".join(tags),
                    importance=importance,
                    created_at=created_at,
                )
            )

        return MemoryRecord(
            id=memory_id,
            revision=revision,
            actor=actor,
            session_id=session_id,
            kind=kind,
            summary=summary,
            details=details,
            tags=tags,
            importance=importance,
            created_at=created_at,
        )

    def _row_to_memory(self, row) -> MemoryRecord:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return MemoryRecord(
            id=row.id,
            revision=int(row.revision),
            actor=row.actor,
            session_id=row.session_id,
            kind=row.kind,
            summary=row.summary,
            details=row.details or "",
            tags=[tag for tag in (row.tags or "").split(",") if tag],
            importance=float(row.importance),
            created_at=created_at,
        )

    def get_memory(self, project_id: str, memory_id: str) -> MemoryRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(memories).where(
                    memories.c.project_id == project_id,
                    memories.c.id == memory_id,
                )
            ).first()
            return self._row_to_memory(row) if row else None

    def recent_memories(self, project_id: str, limit: int = 500) -> list[MemoryRecord]:
        limit = max(1, min(int(limit), 2000))
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(memories)
                .where(memories.c.project_id == project_id)
                .order_by(memories.c.revision.desc())
                .limit(limit)
            ).all()
        return [self._row_to_memory(row) for row in rows]

    def memories_since(
        self,
        project_id: str,
        revision: int,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(memories)
                .where(
                    memories.c.project_id == project_id,
                    memories.c.revision > int(revision),
                )
                .order_by(memories.c.revision.asc())
                .limit(max(1, min(int(limit), 100)))
            ).all()
        return [self._row_to_memory(row) for row in rows]

    def get_session_revision(
        self,
        project_id: str,
        actor: str,
        session_id: str,
    ) -> int:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(sessions.c.last_seen_revision).where(
                    sessions.c.project_id == project_id,
                    sessions.c.actor == actor,
                    sessions.c.session_id == session_id,
                )
            ).first()
            return int(row.last_seen_revision) if row else 0

    def update_session(
        self,
        project_id: str,
        actor: str,
        session_id: str,
        revision: int,
        task: str,
    ) -> None:
        now = utcnow()
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(sessions.c.project_id).where(
                    sessions.c.project_id == project_id,
                    sessions.c.actor == actor,
                    sessions.c.session_id == session_id,
                )
            ).first()
            if existing:
                conn.execute(
                    update(sessions)
                    .where(
                        sessions.c.project_id == project_id,
                        sessions.c.actor == actor,
                        sessions.c.session_id == session_id,
                    )
                    .values(
                        last_seen_revision=revision,
                        last_task=task,
                        updated_at=now,
                    )
                )
            else:
                conn.execute(
                    insert(sessions).values(
                        project_id=project_id,
                        actor=actor,
                        session_id=session_id,
                        last_seen_revision=revision,
                        last_task=task,
                        updated_at=now,
                    )
                )

    def ranked_memories(
        self,
        project_id: str,
        task: str,
        limit: int = 30,
        candidate_limit: int = 500,
    ) -> list[MemoryRecord]:
        candidates = self.recent_memories(project_id, candidate_limit)
        if not candidates:
            return []

        task_tokens = tokenize(task)
        newest_revision = max(memory.revision for memory in candidates)

        scored: list[tuple[float, MemoryRecord]] = []
        for memory in candidates:
            searchable = " ".join(
                [memory.summary, memory.details, " ".join(memory.tags), memory.kind]
            )
            memory_tokens = tokenize(searchable)

            overlap = len(task_tokens & memory_tokens)
            coverage = overlap / max(1, len(task_tokens))
            lexical = overlap + 2.0 * coverage

            recency_distance = newest_revision - memory.revision
            recency = math.exp(-recency_distance / 80.0)

            kind_weight = KIND_WEIGHT.get(memory.kind, 1.0)
            score = (
                lexical * 3.0
                + memory.importance * 2.0
                + recency
                + kind_weight
            )
            scored.append((score, memory))

        scored.sort(key=lambda pair: (pair[0], pair[1].revision), reverse=True)
        return [memory for _, memory in scored[: max(1, min(int(limit), 100))]]

    def count_memories(self, project_id: str) -> int:
        from sqlalchemy import func

        with self.engine.begin() as conn:
            value = conn.execute(
                select(func.count()).select_from(memories).where(
                    memories.c.project_id == project_id
                )
            ).scalar_one()
            return int(value)

    def clear_project(self, project_id: str) -> None:
        # Intended only for local/V0 reset scripts; not exposed as an MCP/API tool.
        with self.engine.begin() as conn:
            conn.execute(delete(memories).where(memories.c.project_id == project_id))
            conn.execute(delete(sessions).where(sessions.c.project_id == project_id))
            conn.execute(
                delete(project_counters).where(
                    project_counters.c.project_id == project_id
                )
            )

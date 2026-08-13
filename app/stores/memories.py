"""The memory engine: writes (with supersession/conflict), permission-filtered
retrieval, deterministic ranking, and the sync change-feed.

The permission boundary is the ``_visible`` WHERE clause, applied before any
ranking — a caller never receives a row they are not authorized to see.
"""
from __future__ import annotations

import math
import re
import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import Connection, Engine

from ..db import (
    evidence_events,
    memories,
    memory_relations,
    memory_versions,
    utcnow,
)
from ..errors import ForbiddenError, NotFoundError, ValidationError
from ..identity import RequestIdentity
from ..limits import (
    MAX_DETAILS_CHARS,
    MAX_MEMORIES_PER_CONTEXT,
    MAX_SUMMARY_CHARS,
    MAX_TAG_CHARS,
    MAX_TAGS,
    enforce_quota,
)
from ..models import (
    AUTHORITY_WEIGHT,
    KIND_WEIGHT,
    MemoryRecord,
    PUBLISHABLE_KINDS,
    WRITABLE_SENSITIVITIES,
)
from .audit import AuditStore
from .projects import ProjectStore

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "into", "about", "your",
    "you", "are", "was", "were", "have", "has", "had", "will", "would", "should",
    "could", "can", "our", "their", "they", "them", "then", "than", "when", "what",
    "which", "where", "while", "how", "why", "who", "use", "using", "used", "make",
    "made", "need", "needs", "work", "working", "project", "context", "shared",
}


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_\-]{3,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


# Control characters, including newlines. Memory content is rendered into a
# line-oriented context format, so a stored newline would let one member forge
# the compiler's own section headers inside another member's prompt.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")


def sanitize_line(value: str, limit: int) -> str:
    """Collapse a value to a single safe line and cap its length."""
    cleaned = _CONTROL_CHARS.sub(" ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def sanitize_block(value: str, limit: int) -> str:
    """Keep newlines (details are never inlined) but drop other control chars."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f  ]", " ", value or "")
    cleaned = cleaned.strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _row_to_memory(m) -> MemoryRecord:
    return MemoryRecord(
        id=m["id"],
        project_id=m["project_id"],
        revision=int(m["revision"]),
        scope=m["scope"],
        owner_user_id=m["owner_user_id"],
        kind=m["kind"],
        summary=m["summary"],
        details=m["details"] or "",
        tags=[t for t in (m["tags"] or "").split(",") if t],
        status=m["status"],
        importance=float(m["importance"]),
        confidence=float(m["confidence"]),
        authority=m["authority"],
        sensitivity=m["sensitivity"],
        version=int(m["version"]),
        superseded_by_id=m["superseded_by_id"],
        created_by_user_id=m["created_by_user_id"],
        created_by_agent_id=m["created_by_agent_id"],
        origin_session_id=m["origin_session_id"],
        source_event_id=m["source_event_id"],
        valid_from=m["valid_from"],
        valid_until=m["valid_until"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


def _visible(project_id: str, user_id: str):
    """Permission predicate: shared, or the caller's own private memory."""
    return and_(
        memories.c.project_id == project_id,
        or_(
            memories.c.scope == "shared",
            and_(
                memories.c.scope == "private",
                memories.c.owner_user_id == user_id,
            ),
        ),
    )


class MemoryStore:
    def __init__(
        self, engine: Engine, projects: ProjectStore, audit: AuditStore
    ) -> None:
        self.engine = engine
        self.projects = projects
        self.audit = audit

    # --- write path ---------------------------------------------------------

    def remember(
        self,
        identity: RequestIdentity,
        scope: str,
        kind: str,
        summary: str,
        details: str = "",
        tags: list[str] | None = None,
        importance: float = 0.6,
        confidence: float = 0.7,
        sensitivity: str = "internal",
        supersedes: list[str] | None = None,
        contradicts: list[str] | None = None,
        session_id: str | None = None,
        *,
        internal_kind: bool = False,
    ) -> dict[str, Any]:
        # Sanitize before storing: memory content is attacker-influenced (any
        # member can publish) and is rendered into a line-oriented context
        # format read by other members' agents.
        summary = sanitize_line(summary, MAX_SUMMARY_CHARS)
        details = sanitize_block(details, MAX_DETAILS_CHARS)
        if not summary:
            raise ValidationError("summary must not be empty")
        if scope not in ("private", "shared"):
            raise ValidationError(f"invalid scope: {scope}")
        kind = (kind or "note").strip().lower()
        if not internal_kind and kind not in PUBLISHABLE_KINDS:
            raise ValidationError(f"invalid kind: {kind}")
        sensitivity = (sensitivity or "internal").strip().lower()
        if sensitivity not in WRITABLE_SENSITIVITIES:
            raise ValidationError(
                f"sensitivity must be one of {sorted(WRITABLE_SENSITIVITIES)}; "
                "secrets do not belong in memory"
            )

        identity.require_writer()
        self._enforce_context_quota(identity)

        owner_user_id = identity.user_id if scope == "private" else None
        importance = max(0.0, min(float(importance), 1.0))
        confidence = max(0.0, min(float(confidence), 1.0))
        authority = "owner" if identity.role in ("owner", "admin") else "member"
        # Tags are CSV-joined, so a comma inside one would fragment it.
        tags = [
            sanitize_line(str(t), MAX_TAG_CHARS).replace(",", " ")
            for t in (tags or [])
        ]
        tags = [t for t in tags if t][:MAX_TAGS]
        supersedes = list(supersedes or [])
        contradicts = list(contradicts or [])
        project_id = identity.project_id
        now = utcnow()
        memory_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())

        with self.engine.begin() as conn:
            conn.execute(
                evidence_events.insert().values(
                    id=event_id,
                    project_id=project_id,
                    session_id=session_id,
                    actor_user_id=identity.user_id,
                    actor_agent_id=identity.agent_connection_id,
                    event_type="explicit_memory_write",
                    visibility_scope=scope,
                    owner_user_id=owner_user_id,
                    content=(summary + ("\n\n" + details if details else "")),
                    source_uri=None,
                    created_at=now,
                )
            )
            revision = self.projects.next_revision(conn, project_id)
            conn.execute(
                memories.insert().values(
                    id=memory_id,
                    project_id=project_id,
                    revision=revision,
                    scope=scope,
                    owner_user_id=owner_user_id,
                    kind=kind,
                    summary=summary,
                    details=details,
                    tags=",".join(tags),
                    status="active",
                    importance=importance,
                    confidence=confidence,
                    authority=authority,
                    sensitivity=sensitivity,
                    valid_from=None,
                    valid_until=None,
                    version=1,
                    superseded_by_id=None,
                    created_by_user_id=identity.user_id,
                    created_by_agent_id=identity.agent_connection_id,
                    origin_session_id=session_id,
                    source_event_id=event_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._insert_version(conn, memory_id, 1, kind, summary, details, tags,
                                  "active", event_id, identity, now)

            superseded_ids = self._apply_supersedes(
                conn, identity, memory_id, supersedes, now
            )
            conflict_ids = self._apply_contradicts(
                conn, identity, memory_id, contradicts, now
            )

            self.audit.emit(
                "memory.create", "memory", memory_id, project_id=project_id,
                actor_user_id=identity.user_id,
                actor_agent_id=identity.agent_connection_id,
                meta={"scope": scope, "kind": kind, "revision": revision},
                conn=conn,
            )
            row = conn.execute(
                select(memories).where(memories.c.id == memory_id)
            ).first()

        return {
            "revision": revision,
            "memory": _row_to_memory(row._mapping),
            "superseded": superseded_ids,
            "conflicts_opened": conflict_ids,
        }

    def _insert_version(
        self, conn, memory_id, version, kind, summary, details, tags, status,
        event_id, identity, now,
    ) -> None:
        conn.execute(
            memory_versions.insert().values(
                id=str(uuid.uuid4()),
                memory_id=memory_id,
                version=version,
                kind=kind,
                summary=summary,
                details=details,
                tags=",".join(tags) if isinstance(tags, list) else (tags or ""),
                status=status,
                source_event_id=event_id,
                created_by_user_id=identity.user_id,
                created_by_agent_id=identity.agent_connection_id,
                created_at=now,
            )
        )

    def _load_writable_target(
        self, conn: Connection, identity: RequestIdentity, target_id: str
    ):
        row = conn.execute(
            select(memories).where(
                memories.c.id == target_id,
                memories.c.project_id == identity.project_id,
            )
        ).first()
        if row is None:
            raise NotFoundError("target memory not found")
        m = row._mapping
        if m["scope"] == "private" and m["owner_user_id"] != identity.user_id:
            raise ForbiddenError("cannot modify another user's private memory")
        return m

    def _apply_supersedes(
        self, conn, identity, new_id, supersedes, now
    ) -> list[str]:
        done: list[str] = []
        for target_id in supersedes:
            m = self._load_writable_target(conn, identity, target_id)
            if m["status"] != "active":
                continue  # already superseded/retracted; no-op flip
            new_version = int(m["version"]) + 1
            conn.execute(
                update(memories)
                .where(memories.c.id == target_id)
                .values(
                    status="superseded",
                    superseded_by_id=new_id,
                    version=new_version,
                    updated_at=now,
                )
            )
            self._insert_version(
                conn, target_id, new_version, m["kind"], m["summary"],
                m["details"] or "", m["tags"] or "", "superseded",
                m["source_event_id"], identity, now,
            )
            conn.execute(
                memory_relations.insert().values(
                    id=str(uuid.uuid4()),
                    project_id=identity.project_id,
                    from_memory_id=new_id,
                    to_memory_id=target_id,
                    relation_type="supersedes",
                    created_by_user_id=identity.user_id,
                    created_at=now,
                )
            )
            self.audit.emit(
                "memory.supersede", "memory", target_id,
                project_id=identity.project_id, actor_user_id=identity.user_id,
                actor_agent_id=identity.agent_connection_id,
                meta={"superseded_by": new_id}, conn=conn,
            )
            done.append(target_id)
        return done

    def _apply_contradicts(
        self, conn, identity, new_id, contradicts, now
    ) -> list[str]:
        done: list[str] = []
        for target_id in contradicts:
            self._load_writable_target(conn, identity, target_id)
            conn.execute(
                memory_relations.insert().values(
                    id=str(uuid.uuid4()),
                    project_id=identity.project_id,
                    from_memory_id=new_id,
                    to_memory_id=target_id,
                    relation_type="contradicts",
                    created_by_user_id=identity.user_id,
                    resolved_at=None,
                    created_at=now,
                )
            )
            self.audit.emit(
                "memory.contradict", "memory", target_id,
                project_id=identity.project_id, actor_user_id=identity.user_id,
                actor_agent_id=identity.agent_connection_id,
                meta={"contradicts_with": new_id}, conn=conn,
            )
            done.append(target_id)
        return done

    # --- read path ----------------------------------------------------------

    def retract(
        self, identity: RequestIdentity, memory_id: str
    ) -> MemoryRecord:
        """Human correction: mark a memory retracted so it leaves active context.

        Retained (not deleted) for provenance. Writer role required; a private
        memory may only be retracted by its owner.
        """
        identity.require_writer()
        now = utcnow()
        with self.engine.begin() as conn:
            m = self._load_writable_target(conn, identity, memory_id)
            if m["status"] == "retracted":
                return _row_to_memory(m)
            new_version = int(m["version"]) + 1
            conn.execute(
                update(memories)
                .where(memories.c.id == memory_id)
                .values(status="retracted", version=new_version, updated_at=now)
            )
            self._insert_version(
                conn, memory_id, new_version, m["kind"], m["summary"],
                m["details"] or "", m["tags"] or "", "retracted",
                m["source_event_id"], identity, now,
            )
            self.audit.emit(
                "memory.retract", "memory", memory_id,
                project_id=identity.project_id, actor_user_id=identity.user_id,
                actor_agent_id=identity.agent_connection_id, conn=conn,
            )
            row = conn.execute(
                select(memories).where(memories.c.id == memory_id)
            ).first()
        return _row_to_memory(row._mapping)

    def get_memory(
        self, project_id: str, memory_id: str, user_id: str
    ) -> MemoryRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(memories).where(
                    memories.c.id == memory_id,
                    _visible(project_id, user_id),
                )
            ).first()
        return _row_to_memory(row._mapping) if row else None

    def list_memories(
        self,
        project_id: str,
        user_id: str,
        scope: str | None = None,
        status: str | None = "active",
        kind: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        clauses = [_visible(project_id, user_id)]
        if scope:
            clauses.append(memories.c.scope == scope)
        if status:
            clauses.append(memories.c.status == status)
        if kind:
            clauses.append(memories.c.kind == kind)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(memories)
                .where(*clauses)
                .order_by(memories.c.revision.desc())
                .limit(max(1, min(int(limit), 500)))
            ).all()
        return [_row_to_memory(r._mapping) for r in rows]

    def compile_candidates(
        self, project_id: str, user_id: str, candidate_limit: int = 750
    ) -> list[MemoryRecord]:
        now = utcnow()
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(memories)
                .where(
                    _visible(project_id, user_id),
                    memories.c.status == "active",
                    or_(
                        memories.c.valid_until.is_(None),
                        memories.c.valid_until > now,
                    ),
                )
                .order_by(memories.c.revision.desc())
                .limit(max(1, min(int(candidate_limit), 2000)))
            ).all()
        return [_row_to_memory(r._mapping) for r in rows]

    def rank(
        self, candidates: list[MemoryRecord], task: str, limit: int = 50
    ) -> list[MemoryRecord]:
        if not candidates:
            return []
        task_tokens = tokenize(task)
        newest = max(m.revision for m in candidates)
        scored: list[tuple[float, MemoryRecord]] = []
        for m in candidates:
            searchable = " ".join([m.summary, m.details, " ".join(m.tags), m.kind])
            mem_tokens = tokenize(searchable)
            overlap = len(task_tokens & mem_tokens)
            coverage = overlap / max(1, len(task_tokens))
            lexical = overlap + 2.0 * coverage
            recency = math.exp(-(newest - m.revision) / 80.0)
            score = (
                lexical * 3.0
                + m.importance * 2.0
                + recency
                + KIND_WEIGHT.get(m.kind, 1.0)
                + AUTHORITY_WEIGHT.get(m.authority, 1.0)
                + 0.5 * m.confidence
            )
            scored.append((score, m))
        scored.sort(key=lambda p: (p[0], p[1].revision), reverse=True)
        return [m for _, m in scored[: max(1, min(int(limit), 200))]]

    def changes_since(
        self,
        project_id: str,
        user_id: str,
        exclude_session_id: str | None,
        since_revision: int,
        limit: int = 20,
    ) -> tuple[list[MemoryRecord], bool]:
        """Deliverable changes after ``since_revision`` for this session.

        Returns ``(delivered, truncated)``. Excludes the caller's own-session
        writes (self-echo) and rows the caller can't see; only currently-active
        memories are delivered. ``truncated`` is True when more deliverable rows
        remain than ``limit`` — the caller uses it to hold the watermark back.
        """
        clauses = [
            _visible(project_id, user_id),
            memories.c.revision > int(since_revision),
            memories.c.status == "active",
        ]
        if exclude_session_id is not None:
            clauses.append(
                or_(
                    memories.c.origin_session_id.is_(None),
                    memories.c.origin_session_id != exclude_session_id,
                )
            )
        cap = max(1, min(int(limit), 100))
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(memories)
                .where(*clauses)
                .order_by(memories.c.revision.asc())
                .limit(cap + 1)  # sentinel row detects truncation
            ).all()
        delivered = [_row_to_memory(r._mapping) for r in rows[:cap]]
        truncated = len(rows) > cap
        return delivered, truncated

    def unresolved_conflicts(
        self, project_id: str, user_id: str, limit: int = 10
    ) -> list[tuple[MemoryRecord, MemoryRecord]]:
        """Pairs of active, caller-visible memories with an open contradiction."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(memory_relations.c.from_memory_id, memory_relations.c.to_memory_id)
                .where(
                    memory_relations.c.project_id == project_id,
                    memory_relations.c.relation_type == "contradicts",
                    memory_relations.c.resolved_at.is_(None),
                )
                .order_by(memory_relations.c.created_at.desc())
                .limit(max(1, min(int(limit) * 3, 100)))
            ).all()
            pairs: list[tuple[MemoryRecord, MemoryRecord]] = []
            for r in rows:
                a = conn.execute(
                    select(memories).where(
                        memories.c.id == r.from_memory_id,
                        memories.c.status == "active",
                        _visible(project_id, user_id),
                    )
                ).first()
                b = conn.execute(
                    select(memories).where(
                        memories.c.id == r.to_memory_id,
                        memories.c.status == "active",
                        _visible(project_id, user_id),
                    )
                ).first()
                if a and b:
                    pairs.append((_row_to_memory(a._mapping), _row_to_memory(b._mapping)))
                if len(pairs) >= limit:
                    break
        return pairs

    def _can_see_memory(self, conn, project_id: str, memory_id: str, user_id: str) -> bool:
        return conn.execute(
            select(memories.c.id).where(
                memories.c.id == memory_id,
                _visible(project_id, user_id),
            )
        ).first() is not None

    def get_versions(
        self, memory_id: str, project_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        """Version history — only for a memory the caller may see."""
        with self.engine.begin() as conn:
            if not self._can_see_memory(conn, project_id, memory_id, user_id):
                return []
            rows = conn.execute(
                select(memory_versions)
                .where(memory_versions.c.memory_id == memory_id)
                .order_by(memory_versions.c.version.asc())
            ).all()
        return [dict(r._mapping) for r in rows]

    def get_relations(
        self, memory_id: str, project_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        """Relations, filtered so neither endpoint leaks an invisible memory.

        Without this, a relation would disclose the id of another member's
        private memory (audit finding).
        """
        with self.engine.begin() as conn:
            if not self._can_see_memory(conn, project_id, memory_id, user_id):
                return []
            rows = conn.execute(
                select(memory_relations).where(
                    memory_relations.c.project_id == project_id,
                    or_(
                        memory_relations.c.from_memory_id == memory_id,
                        memory_relations.c.to_memory_id == memory_id,
                    ),
                )
            ).all()
            visible: list[dict[str, Any]] = []
            for r in rows:
                m = dict(r._mapping)
                other = (
                    m["to_memory_id"]
                    if m["from_memory_id"] == memory_id
                    else m["from_memory_id"]
                )
                if self._can_see_memory(conn, project_id, other, user_id):
                    visible.append(m)
        return visible

    def get_source(
        self, project_id: str, source_id: str, user_id: str
    ) -> dict[str, Any] | None:
        """An evidence event, subject to the same visibility rules as memory.

        Evidence carries the memory's content verbatim, so without the scope
        check a member could read another member's private memory through it
        (audit finding).
        """
        with self.engine.begin() as conn:
            row = conn.execute(
                select(evidence_events).where(
                    evidence_events.c.id == source_id,
                    evidence_events.c.project_id == project_id,
                    or_(
                        evidence_events.c.visibility_scope == "shared",
                        and_(
                            evidence_events.c.visibility_scope != "shared",
                            evidence_events.c.owner_user_id == user_id,
                        ),
                    ),
                )
            ).first()
        return dict(row._mapping) if row else None

    def _enforce_context_quota(self, identity: RequestIdentity) -> None:
        """Refuse a write once a context has hit its live-memory ceiling.

        ``MAX_MEMORIES_PER_CONTEXT`` was imported here but never applied, so a
        single context could grow until it exhausted the database. The count is
        of *live* memory across both scopes, so retracting frees room and a
        private write is not a way around the cap.
        """
        with self.engine.begin() as conn:
            live = conn.execute(
                select(func.count())
                .select_from(memories)
                .where(
                    memories.c.project_id == identity.project_id,
                    memories.c.status == "active",
                )
            ).scalar_one()
        enforce_quota(
            self, int(live), MAX_MEMORIES_PER_CONTEXT, "memories per context"
        )

    def count_memories(self, project_id: str, user_id: str) -> dict[str, int]:
        from sqlalchemy import func

        with self.engine.begin() as conn:
            shared_active = conn.execute(
                select(func.count()).select_from(memories).where(
                    memories.c.project_id == project_id,
                    memories.c.scope == "shared",
                    memories.c.status == "active",
                )
            ).scalar_one()
            private_mine = conn.execute(
                select(func.count()).select_from(memories).where(
                    memories.c.project_id == project_id,
                    memories.c.scope == "private",
                    memories.c.owner_user_id == user_id,
                    memories.c.status == "active",
                )
            ).scalar_one()
            private_others = conn.execute(
                select(func.count()).select_from(memories).where(
                    memories.c.project_id == project_id,
                    memories.c.scope == "private",
                    memories.c.owner_user_id != user_id,
                    memories.c.status == "active",
                )
            ).scalar_one()
        return {
            "shared_active": int(shared_active),
            "private_mine": int(private_mine),
            "private_others": int(private_others),
        }

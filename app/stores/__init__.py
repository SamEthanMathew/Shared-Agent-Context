"""SACStore facade — composes the sub-stores over one SQLAlchemy engine.

Preserves the V0 call sites ``SACStore(url)`` and ``store.init()``. Sub-stores
share the engine and, where a write must be atomic across tables (allocate a
revision + insert the memory it belongs to), run inside one transaction and
call helpers that accept the live connection.
"""
from __future__ import annotations

from sqlalchemy.engine import Engine

from ..db import create_sac_engine, metadata
from ..identity import Principal, RequestIdentity
from ..auth.store import AuthStore
from .audit import AuditStore
from .invites import InviteStore
from .memories import MemoryStore
from .projects import ProjectStore
from .sessions import SessionStore
from .snapshots import SnapshotStore


class SACStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.engine: Engine = create_sac_engine(database_url)
        self.projects = ProjectStore(self.engine)
        self.audit = AuditStore(self.engine)
        self.sessions = SessionStore(self.engine)
        self.memories = MemoryStore(self.engine, self.projects, self.audit)
        self.snapshots = SnapshotStore(self.engine)
        self.auth = AuthStore(self.engine)
        self.invites = InviteStore(self.engine)

    def init(self) -> None:
        metadata.create_all(self.engine)

    # --- convenience pass-throughs kept stable for the surfaces -------------

    def resolve_identity(
        self,
        principal: Principal,
        project_id: str,
        allow_archived: bool = False,
    ) -> RequestIdentity:
        return self.projects.resolve_identity(
            principal, project_id, allow_archived=allow_archived
        )

    def current_revision(self, project_id: str) -> int:
        return self.projects.current_revision(project_id)


__all__ = ["SACStore"]

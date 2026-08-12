"""Request identity — the value object every impl function takes first.

`Principal` is the authenticated caller resolved from an OAuth token (or a
dev-mode header before the auth layer lands). `RequestIdentity` is a Principal
plus the resolved membership role for one project; it is produced by
`SACStore.resolve_identity(...)`, which raises ForbiddenError when the caller is
not a project member. The permission boundary lives in the store queries, not
here — this object just carries who is asking and what they may do.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import ForbiddenError
from .models import READ_SCOPE, WRITE_SCOPE, WRITER_ROLES


@dataclass(frozen=True)
class Principal:
    """An authenticated caller, independent of any project."""

    user_id: str
    agent_connection_id: str | None
    scopes: tuple[str, ...] = ()
    label: str = ""

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


@dataclass(frozen=True)
class RequestIdentity:
    """A principal with a resolved role in one project."""

    user_id: str
    agent_connection_id: str | None
    project_id: str
    role: str
    scopes: tuple[str, ...] = ()
    label: str = ""

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def require_reader(self) -> None:
        # Membership alone grants read; the READ scope is required when a token
        # is present. Dev-mode identities carry both scopes by default.
        if self.scopes and READ_SCOPE not in self.scopes:
            raise ForbiddenError("read scope required")

    def require_writer(self) -> None:
        """Raise unless this identity may write project memory."""
        if self.role not in WRITER_ROLES:
            raise ForbiddenError("role may not write project memory")
        if self.scopes and WRITE_SCOPE not in self.scopes:
            raise ForbiddenError("write scope required")

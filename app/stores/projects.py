"""Users, projects, memberships, agent connections, and revision allocation."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine

from ..db import agent_connections, memberships, projects, users, utcnow
from ..errors import ForbiddenError, NotFoundError, ValidationError
from ..identity import Principal, RequestIdentity
from ..models import ProjectRecord


def _new_id() -> str:
    return str(uuid.uuid4())


class ProjectStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- users --------------------------------------------------------------

    def create_user(
        self,
        email: str,
        display_name: str = "",
        password_hash: str | None = None,
        is_admin: bool = False,
    ) -> str:
        email = (email or "").strip().lower()
        if not email:
            raise ValidationError("email is required")
        user_id = _new_id()
        with self.engine.begin() as conn:
            conn.execute(
                users.insert().values(
                    id=user_id,
                    email=email,
                    display_name=display_name.strip() or email,
                    password_hash=password_hash,
                    is_admin=1 if is_admin else 0,
                    created_at=utcnow(),
                )
            )
        return user_id

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(select(users).where(users.c.id == user_id)).first()
        return dict(row._mapping) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        email = (email or "").strip().lower()
        with self.engine.begin() as conn:
            row = conn.execute(select(users).where(users.c.email == email)).first()
        return dict(row._mapping) if row else None

    def get_users_map(self, user_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Bulk-resolve users to readable labels for provenance rendering."""
        ids = [u for u in set(user_ids) if u]
        if not ids:
            return {}
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(users.c.id, users.c.email, users.c.display_name).where(
                    users.c.id.in_(ids)
                )
            ).all()
        return {r.id: {"email": r.email, "display_name": r.display_name} for r in rows}

    def count_users(self) -> int:
        from sqlalchemy import func

        with self.engine.begin() as conn:
            return int(
                conn.execute(select(func.count()).select_from(users)).scalar_one()
            )

    # --- projects & membership ---------------------------------------------

    def create_project(
        self, name: str, owner_user_id: str, description: str = ""
    ) -> ProjectRecord:
        name = (name or "").strip()
        if not name:
            raise ValidationError("project name is required")
        project_id = _new_id()
        now = utcnow()
        with self.engine.begin() as conn:
            if conn.execute(
                select(users.c.id).where(users.c.id == owner_user_id)
            ).first() is None:
                raise NotFoundError("owner user not found")
            conn.execute(
                projects.insert().values(
                    id=project_id,
                    name=name,
                    description=description.strip(),
                    owner_user_id=owner_user_id,
                    context_revision=0,
                    settings={},
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                memberships.insert().values(
                    project_id=project_id,
                    user_id=owner_user_id,
                    role="owner",
                    created_at=now,
                )
            )
        return ProjectRecord(
            id=project_id,
            name=name,
            description=description.strip(),
            owner_user_id=owner_user_id,
            context_revision=0,
            settings={},
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(projects).where(projects.c.id == project_id)
            ).first()
        if not row:
            return None
        m = row._mapping
        return ProjectRecord(
            id=m["id"],
            name=m["name"],
            description=m["description"],
            owner_user_id=m["owner_user_id"],
            context_revision=int(m["context_revision"]),
            settings=m["settings"] or {},
            created_at=m["created_at"],
            updated_at=m["updated_at"],
        )

    def add_membership(self, project_id: str, user_id: str, role: str = "member") -> None:
        if role not in {"owner", "admin", "member", "viewer"}:
            raise ValidationError(f"invalid role: {role}")
        with self.engine.begin() as conn:
            if conn.execute(
                select(projects.c.id).where(projects.c.id == project_id)
            ).first() is None:
                raise NotFoundError("project not found")
            if conn.execute(
                select(users.c.id).where(users.c.id == user_id)
            ).first() is None:
                raise NotFoundError("user not found")
            existing = conn.execute(
                select(memberships.c.role).where(
                    memberships.c.project_id == project_id,
                    memberships.c.user_id == user_id,
                )
            ).first()
            if existing:
                conn.execute(
                    update(memberships)
                    .where(
                        memberships.c.project_id == project_id,
                        memberships.c.user_id == user_id,
                    )
                    .values(role=role)
                )
            else:
                conn.execute(
                    memberships.insert().values(
                        project_id=project_id,
                        user_id=user_id,
                        role=role,
                        created_at=utcnow(),
                    )
                )

    def get_role(self, project_id: str, user_id: str) -> str | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(memberships.c.role).where(
                    memberships.c.project_id == project_id,
                    memberships.c.user_id == user_id,
                )
            ).first()
        return row.role if row else None

    def list_members(self, project_id: str) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    memberships.c.user_id,
                    memberships.c.role,
                    users.c.email,
                    users.c.display_name,
                )
                .select_from(
                    memberships.join(users, memberships.c.user_id == users.c.id)
                )
                .where(memberships.c.project_id == project_id)
            ).all()
        return [dict(r._mapping) for r in rows]

    # --- agent connections --------------------------------------------------

    def create_agent_connection(
        self,
        user_id: str,
        oauth_client_id: str | None = None,
        label: str = "",
        provider_hint: str = "other",
        client_type: str = "mcp",
        granted_scopes: list[str] | None = None,
    ) -> str:
        conn_id = _new_id()
        with self.engine.begin() as conn:
            conn.execute(
                agent_connections.insert().values(
                    id=conn_id,
                    user_id=user_id,
                    oauth_client_id=oauth_client_id,
                    label=label,
                    provider_hint=provider_hint,
                    client_type=client_type,
                    granted_scopes=granted_scopes or [],
                    created_at=utcnow(),
                )
            )
        return conn_id

    def get_agent_connection(self, conn_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(agent_connections).where(agent_connections.c.id == conn_id)
            ).first()
        return dict(row._mapping) if row else None

    def revoke_agent_connection(self, conn_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(agent_connections)
                .where(agent_connections.c.id == conn_id)
                .values(revoked_at=utcnow())
            )

    def touch_agent_connection(self, conn_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(agent_connections)
                .where(agent_connections.c.id == conn_id)
                .values(last_seen_at=utcnow())
            )

    def list_connections(self, user_id: str) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(agent_connections).where(agent_connections.c.user_id == user_id)
            ).all()
        return [dict(r._mapping) for r in rows]

    # --- revision allocation (transactional; takes a live connection) -------

    def next_revision(self, conn: Connection, project_id: str) -> int:
        """Allocate the next monotonic revision for a project.

        Must run inside the caller's transaction so the revision and the row it
        belongs to commit atomically. A row lock serializes concurrent writers
        per project on Postgres; SQLite serializes writers globally.
        """
        row = conn.execute(
            select(projects.c.context_revision)
            .where(projects.c.id == project_id)
            .with_for_update()
        ).first()
        if row is None:
            raise NotFoundError("project not found")
        next_rev = int(row.context_revision) + 1
        conn.execute(
            update(projects)
            .where(projects.c.id == project_id)
            .values(context_revision=next_rev, updated_at=utcnow())
        )
        return next_rev

    def current_revision(self, project_id: str) -> int:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(projects.c.context_revision).where(
                    projects.c.id == project_id
                )
            ).first()
        return int(row.context_revision) if row else 0

    # --- identity resolution (the membership gate) --------------------------

    def resolve_identity(
        self, principal: Principal, project_id: str
    ) -> RequestIdentity:
        """Resolve a principal's role in a project, or refuse.

        Raises ForbiddenError for non-members — the surface must return 403
        without revealing whether the project exists (project isolation).
        """
        role = self.get_role(project_id, principal.user_id)
        if role is None:
            raise ForbiddenError("not a member of this project")
        return RequestIdentity(
            user_id=principal.user_id,
            agent_connection_id=principal.agent_connection_id,
            project_id=project_id,
            role=role,
            scopes=principal.scopes,
            label=principal.label,
        )

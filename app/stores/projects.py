"""Users, contexts (projects), memberships, connections, and revisions."""
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import Connection, Engine

from ..db import (
    agent_connections,
    context_bindings,
    memberships,
    projects,
    users,
    utcnow,
)
from ..errors import ForbiddenError, NotFoundError, ValidationError
from ..identity import Principal, RequestIdentity
from ..models import ROLE_TO_ACCESS, ProjectRecord


def _new_id() -> str:
    return str(uuid.uuid4())


def slugify(name: str) -> str:
    """URL-safe slug from a context name. Empty input falls back to 'context'."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:100] or "context"


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
            raise ValidationError("context name is required")
        project_id = _new_id()
        now = utcnow()
        with self.engine.begin() as conn:
            if conn.execute(
                select(users.c.id).where(users.c.id == owner_user_id)
            ).first() is None:
                raise NotFoundError("owner user not found")
            slug = self._unique_slug(conn, name)
            conn.execute(
                projects.insert().values(
                    id=project_id,
                    name=name,
                    slug=slug,
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
            slug=slug,
            description=description.strip(),
            owner_user_id=owner_user_id,
            context_revision=0,
            settings={},
            created_at=now,
            updated_at=now,
        )

    def _unique_slug(self, conn: Connection, name: str) -> str:
        """Slug from the name, with a numeric suffix on collision."""
        base = slugify(name)
        candidate = base
        n = 1
        while conn.execute(
            select(projects.c.id).where(projects.c.slug == candidate)
        ).first() is not None:
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def _to_record(self, m) -> ProjectRecord:
        return ProjectRecord(
            id=m["id"],
            name=m["name"],
            slug=m["slug"] or "",
            description=m["description"],
            owner_user_id=m["owner_user_id"],
            context_revision=int(m["context_revision"]),
            settings=m["settings"] or {},
            created_at=m["created_at"],
            updated_at=m["updated_at"],
            archived_at=m["archived_at"],
        )

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(projects).where(projects.c.id == project_id)
            ).first()
        return self._to_record(row._mapping) if row else None

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

    def remove_membership(self, project_id: str, user_id: str) -> None:
        from sqlalchemy import delete

        with self.engine.begin() as conn:
            conn.execute(
                delete(memberships).where(
                    memberships.c.project_id == project_id,
                    memberships.c.user_id == user_id,
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

    # --- contexts: listing, resolution, bindings ----------------------------

    def list_user_contexts(self, user_id: str) -> list[dict[str, Any]]:
        """Every context the user can access, newest-active first.

        Powers the in-chat picker, so it returns display data (name, slug,
        role, revision) rather than bare ids.
        """
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    projects.c.id,
                    projects.c.name,
                    projects.c.slug,
                    projects.c.description,
                    projects.c.context_revision,
                    projects.c.updated_at,
                    projects.c.archived_at,
                    memberships.c.role,
                )
                .select_from(
                    memberships.join(projects, memberships.c.project_id == projects.c.id)
                )
                .where(
                    memberships.c.user_id == user_id,
                    projects.c.archived_at.is_(None),
                )
                .order_by(projects.c.updated_at.desc())
            ).all()
            counts = {
                r[0]: int(r[1])
                for r in conn.execute(
                    select(memberships.c.project_id, func.count())
                    .group_by(memberships.c.project_id)
                ).all()
            }
        return [
            {
                "id": r.id,
                "name": r.name,
                "slug": r.slug or "",
                "description": r.description or "",
                "revision": int(r.context_revision),
                "role": r.role,
                "access": ROLE_TO_ACCESS.get(r.role, r.role),
                "member_count": int(counts.get(r.id, 1)),
            }
            for r in rows
        ]

    def resolve_context_ref(self, user_id: str, ref: str) -> str:
        """Resolve a context id, slug, or name **within the user's memberships**.

        Scoping to memberships is a security property, not a convenience: a
        name can never resolve to another tenant's context. Ambiguous names
        raise with the candidates listed rather than silently picking one.
        """
        ref = (ref or "").strip()
        if not ref:
            raise ValidationError("context reference is required")
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(projects.c.id, projects.c.name, projects.c.slug)
                .select_from(
                    memberships.join(projects, memberships.c.project_id == projects.c.id)
                )
                .where(
                    memberships.c.user_id == user_id,
                    projects.c.archived_at.is_(None),
                    or_(
                        projects.c.id == ref,
                        projects.c.slug == ref,
                        func.lower(projects.c.name) == ref.lower(),
                    ),
                )
            ).all()
        if not rows:
            # Deliberately identical whether the context is absent or simply
            # not shared with this user (no cross-tenant existence oracle).
            raise ForbiddenError("no such context")
        if len(rows) > 1:
            names = ", ".join(sorted(f"{r.name} ({r.slug})" for r in rows))
            raise ValidationError(f"ambiguous context '{ref}'; matches: {names}")
        return rows[0].id

    def get_binding(
        self,
        user_id: str,
        agent_connection_id: str | None,
        client_session_ref: str | None = None,
    ) -> str | None:
        """The bound context id, if any, for this (user, client, chat)."""
        with self.engine.begin() as conn:
            row = conn.execute(
                select(context_bindings.c.project_id).where(
                    context_bindings.c.user_id == user_id,
                    context_bindings.c.agent_connection_id.is_(None)
                    if agent_connection_id is None
                    else context_bindings.c.agent_connection_id == agent_connection_id,
                    context_bindings.c.client_session_ref.is_(None)
                    if client_session_ref is None
                    else context_bindings.c.client_session_ref == client_session_ref,
                )
            ).first()
        return row.project_id if row else None

    def set_binding(
        self,
        user_id: str,
        project_id: str,
        agent_connection_id: str | None,
        client_session_ref: str | None = None,
    ) -> None:
        """Bind a context to a client (and optionally one chat). Upsert."""
        now = utcnow()
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(context_bindings.c.id).where(
                    context_bindings.c.user_id == user_id,
                    context_bindings.c.agent_connection_id.is_(None)
                    if agent_connection_id is None
                    else context_bindings.c.agent_connection_id == agent_connection_id,
                    context_bindings.c.client_session_ref.is_(None)
                    if client_session_ref is None
                    else context_bindings.c.client_session_ref == client_session_ref,
                )
            ).first()
            if existing:
                conn.execute(
                    update(context_bindings)
                    .where(context_bindings.c.id == existing.id)
                    .values(project_id=project_id, updated_at=now)
                )
            else:
                conn.execute(
                    context_bindings.insert().values(
                        id=_new_id(),
                        user_id=user_id,
                        agent_connection_id=agent_connection_id,
                        client_session_ref=client_session_ref,
                        project_id=project_id,
                        updated_at=now,
                    )
                )

    def clear_bindings_for_project(self, project_id: str) -> None:
        """Drop bindings when access is revoked, so no client stays pointed at it."""
        from sqlalchemy import delete

        with self.engine.begin() as conn:
            conn.execute(
                delete(context_bindings).where(
                    context_bindings.c.project_id == project_id
                )
            )

    def clear_bindings_for_user_project(self, user_id: str, project_id: str) -> None:
        """Drop one user's bindings to a context they can no longer access."""
        from sqlalchemy import delete

        with self.engine.begin() as conn:
            conn.execute(
                delete(context_bindings).where(
                    context_bindings.c.user_id == user_id,
                    context_bindings.c.project_id == project_id,
                )
            )

    def list_user_project_ids(self, user_id: str) -> list[str]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(memberships.c.project_id).where(
                    memberships.c.user_id == user_id
                )
            ).all()
        return [r.project_id for r in rows]

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

    def find_active_connection_for_client(
        self, user_id: str, oauth_client_id: str
    ) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(agent_connections).where(
                    agent_connections.c.user_id == user_id,
                    agent_connections.c.oauth_client_id == oauth_client_id,
                    agent_connections.c.revoked_at.is_(None),
                )
            ).first()
        return dict(row._mapping) if row else None

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
        """Resolve a principal's role in a context, or refuse.

        Raises ForbiddenError for non-members — the surface must return 403
        without revealing whether the context exists (project isolation). Also
        loads the context's display name/slug in the same query so every
        response can state which context it is operating in.
        """
        with self.engine.begin() as conn:
            row = conn.execute(
                select(memberships.c.role, projects.c.name, projects.c.slug)
                .select_from(
                    memberships.join(projects, memberships.c.project_id == projects.c.id)
                )
                .where(
                    memberships.c.project_id == project_id,
                    memberships.c.user_id == principal.user_id,
                )
            ).first()
        if row is None:
            raise ForbiddenError("not a member of this context")
        return RequestIdentity(
            user_id=principal.user_id,
            agent_connection_id=principal.agent_connection_id,
            project_id=project_id,
            role=row.role,
            scopes=principal.scopes,
            label=principal.label,
            context_name=row.name,
            context_slug=row.slug or "",
        )

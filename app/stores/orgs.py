"""Organisations: a group of people who share contexts.

The design decision that governs this whole module: **organisation access is
materialised into `memberships`, not checked as a second permission path.**

`_visible()` in the memory store and `SACStore.resolve_identity` are the
permission boundary. They are the most heavily tested code here, and every leak
found in V2 and V3 lived within a line or two of them. Teaching them a second
concept — "or the caller is in the organisation that owns this context, and that
context's org_access allows it" — would double the number of ways that boundary
can be wrong, in exchange for avoiding some bookkeeping.

So instead, granting organisation access writes ordinary membership rows tagged
`source='org'`, and revoking deletes them. The boundary is untouched: every
existing query, test, and invariant keeps working, and an org-derived member is
indistinguishable from an invited one at read time — which is precisely what
"they have access" should mean.

The bookkeeping that buys this is the `source` column and the precedence rule:

    direct always outranks org

Granting org access to someone who already has an explicit invitation leaves
their row alone. Granting a direct role over an org-derived row promotes it.
Removing someone from the organisation deletes only their `source='org'` rows, so
an explicit invitation survives — which is what anyone would expect, and the
behaviour that fails safe.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine

from ..db import memberships, org_members, organisations, projects, users, utcnow
from ..errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ..models import ACCESS_TO_ROLE, LINK_ACCESS_LEVELS, ORG_ROLES
from .projects import slugify

# Organisation roles that may administer the organisation itself: rename it,
# manage its people, and move contexts in or out.
ORG_ADMIN_ROLES = frozenset({"owner", "admin"})


class OrgStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- organisations ------------------------------------------------------

    def create(self, name: str, created_by_user_id: str) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValidationError("organisation name is required")
        org_id = str(uuid.uuid4())
        now = utcnow()
        with self.engine.begin() as conn:
            if conn.execute(
                select(users.c.id).where(users.c.id == created_by_user_id)
            ).first() is None:
                raise NotFoundError("user not found")
            slug = self._unique_slug(conn, name)
            conn.execute(
                organisations.insert().values(
                    id=org_id, name=name, slug=slug,
                    created_by_user_id=created_by_user_id,
                    created_at=now, updated_at=now,
                )
            )
            conn.execute(
                org_members.insert().values(
                    org_id=org_id, user_id=created_by_user_id,
                    org_role="owner", created_at=now,
                )
            )
        return {"id": org_id, "name": name, "slug": slug, "org_role": "owner"}

    def _unique_slug(self, conn, name: str) -> str:
        base = slugify(name)
        candidate, n = base, 1
        while conn.execute(
            select(organisations.c.id).where(organisations.c.slug == candidate)
        ).first() is not None:
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def get(self, org_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(organisations).where(organisations.c.id == org_id)
            ).first()
        return dict(row._mapping) if row else None

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Organisations this person belongs to, with their role in each."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    organisations.c.id,
                    organisations.c.name,
                    organisations.c.slug,
                    org_members.c.org_role,
                )
                .select_from(
                    org_members.join(
                        organisations, org_members.c.org_id == organisations.c.id
                    )
                )
                .where(org_members.c.user_id == user_id)
                .order_by(organisations.c.name)
            ).all()
            counts = {}
            org_ids = [r.id for r in rows]
            if org_ids:
                counts = {
                    r[0]: int(r[1])
                    for r in conn.execute(
                        select(org_members.c.org_id, func.count())
                        .where(org_members.c.org_id.in_(org_ids))
                        .group_by(org_members.c.org_id)
                    ).all()
                }
        return [
            {
                "id": r.id,
                "name": r.name,
                "slug": r.slug or "",
                "org_role": r.org_role,
                "member_count": counts.get(r.id, 1),
            }
            for r in rows
        ]

    def get_org_role(self, org_id: str, user_id: str) -> str | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(org_members.c.org_role).where(
                    org_members.c.org_id == org_id,
                    org_members.c.user_id == user_id,
                )
            ).first()
        return row[0] if row else None

    def require_org_admin(self, org_id: str, user_id: str) -> str:
        role = self.get_org_role(org_id, user_id)
        if role is None:
            # Same answer as "no such organisation": no existence oracle.
            raise ForbiddenError("no such organisation")
        if role not in ORG_ADMIN_ROLES:
            raise ForbiddenError("only organisation owners and admins can do that")
        return role

    def list_members(self, org_id: str) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    org_members.c.user_id,
                    org_members.c.org_role,
                    users.c.email,
                    users.c.display_name,
                )
                .select_from(
                    org_members.join(users, org_members.c.user_id == users.c.id)
                )
                .where(org_members.c.org_id == org_id)
                .order_by(users.c.email)
            ).all()
        return [dict(r._mapping) for r in rows]

    # --- membership, and the access it materialises -------------------------

    def add_member(self, org_id: str, user_id: str, org_role: str = "member") -> None:
        """Add someone to the organisation and grant them its contexts' access.

        Whatever `org_access` each context already advertises is applied to the
        new member immediately — that is what makes joining an organisation
        useful, and why `org_access` defaults to `none`.
        """
        org_role = (org_role or "member").strip().lower()
        if org_role not in ORG_ROLES:
            raise ValidationError(f"org role must be one of {sorted(ORG_ROLES)}")
        now = utcnow()
        with self.engine.begin() as conn:
            if conn.execute(
                select(users.c.id).where(users.c.id == user_id)
            ).first() is None:
                raise NotFoundError("user not found")
            existing = conn.execute(
                select(org_members.c.org_role).where(
                    org_members.c.org_id == org_id,
                    org_members.c.user_id == user_id,
                )
            ).first()
            if existing:
                conn.execute(
                    update(org_members)
                    .where(
                        org_members.c.org_id == org_id,
                        org_members.c.user_id == user_id,
                    )
                    .values(org_role=org_role)
                )
            else:
                conn.execute(
                    org_members.insert().values(
                        org_id=org_id, user_id=user_id,
                        org_role=org_role, created_at=now,
                    )
                )
        self._sync_member(org_id, user_id)

    def remove_member(self, org_id: str, user_id: str) -> None:
        """Remove someone from the organisation, revoking org-derived access.

        Explicit invitations survive: only `source='org'` rows go. Someone who
        was individually invited to a context keeps that context.
        """
        role = self.get_org_role(org_id, user_id)
        if role is None:
            raise NotFoundError("that person is not in this organisation")
        if role == "owner" and self._owner_count(org_id) <= 1:
            raise ConflictError("an organisation must always have at least one owner")
        with self.engine.begin() as conn:
            conn.execute(
                delete(org_members).where(
                    org_members.c.org_id == org_id,
                    org_members.c.user_id == user_id,
                )
            )
            org_project_ids = [
                r[0]
                for r in conn.execute(
                    select(projects.c.id).where(projects.c.org_id == org_id)
                ).all()
            ]
            if org_project_ids:
                conn.execute(
                    delete(memberships).where(
                        memberships.c.user_id == user_id,
                        memberships.c.source == "org",
                        memberships.c.project_id.in_(org_project_ids),
                    )
                )

    def _owner_count(self, org_id: str) -> int:
        with self.engine.begin() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(org_members)
                    .where(
                        org_members.c.org_id == org_id,
                        org_members.c.org_role == "owner",
                    )
                ).scalar_one()
            )

    # --- contexts owned by an organisation ---------------------------------

    def attach_project(self, org_id: str, project_id: str) -> None:
        """Move a context into an organisation.

        Access is deliberately unchanged by this: `org_access` stays at whatever
        it was (`none` for a context that has never had it set), so moving a
        context into an organisation never silently exposes its memory.
        """
        with self.engine.begin() as conn:
            if conn.execute(
                select(organisations.c.id).where(organisations.c.id == org_id)
            ).first() is None:
                raise NotFoundError("no such organisation")
            result = conn.execute(
                projects.update()
                .where(projects.c.id == project_id)
                .values(org_id=org_id, updated_at=utcnow())
            )
            if result.rowcount == 0:
                raise NotFoundError("context not found")
        self._sync_project(project_id)

    def detach_project(self, project_id: str) -> None:
        """Make a context personal again, revoking every org-derived membership."""
        with self.engine.begin() as conn:
            conn.execute(
                projects.update()
                .where(projects.c.id == project_id)
                .values(org_id=None, org_access="none", updated_at=utcnow())
            )
            conn.execute(
                delete(memberships).where(
                    memberships.c.project_id == project_id,
                    memberships.c.source == "org",
                )
            )

    def set_org_access(self, project_id: str, access: str) -> str:
        """Set what every member of the owning organisation gets."""
        level = (access or "").strip().lower()
        if level not in LINK_ACCESS_LEVELS:
            raise ValidationError(
                "organisation access must be one of: none, view, edit — it cannot "
                "grant manage, because that would let membership pass on the "
                "right to re-share"
            )
        with self.engine.begin() as conn:
            row = conn.execute(
                select(projects.c.org_id).where(projects.c.id == project_id)
            ).first()
            if row is None:
                raise NotFoundError("context not found")
            if row[0] is None:
                raise ValidationError(
                    "this context does not belong to an organisation"
                )
            conn.execute(
                projects.update()
                .where(projects.c.id == project_id)
                .values(org_access=level, updated_at=utcnow())
            )
        self._sync_project(project_id)
        return level

    def list_org_contexts(self, org_id: str) -> list[dict[str, Any]]:
        """Contexts belonging to an organisation, for its administrators.

        Metadata only — name, slug, revision, access level. Deliberately returns
        no memory: an organisation admin can see *that* a context exists and how
        it is shared, which is what administering a group requires, without that
        being a way to read what is in it. Reading still needs a membership,
        which is exactly the boundary every other path goes through.
        """
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    projects.c.id,
                    projects.c.name,
                    projects.c.slug,
                    projects.c.context_revision,
                    projects.c.org_access,
                    projects.c.archived_at,
                )
                .where(projects.c.org_id == org_id)
                .order_by(projects.c.name)
            ).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "slug": r.slug or "",
                "revision": int(r.context_revision),
                "org_access": r.org_access,
                "archived": r.archived_at is not None,
            }
            for r in rows
        ]

    # --- materialisation ----------------------------------------------------

    def _sync_project(self, project_id: str) -> None:
        """Bring one context's org-derived memberships in line with org_access."""
        with self.engine.begin() as conn:
            row = conn.execute(
                select(projects.c.org_id, projects.c.org_access).where(
                    projects.c.id == project_id
                )
            ).first()
            if row is None:
                return
            org_id, access = row[0], row[1] or "none"

            if not org_id or access == "none":
                # Withdraw everything this org granted. Direct invitations stay.
                conn.execute(
                    delete(memberships).where(
                        memberships.c.project_id == project_id,
                        memberships.c.source == "org",
                    )
                )
                return

            role = ACCESS_TO_ROLE[access]
            member_ids = [
                r[0]
                for r in conn.execute(
                    select(org_members.c.user_id).where(org_members.c.org_id == org_id)
                ).all()
            ]
            existing = {
                r[0]: r[1]
                for r in conn.execute(
                    select(memberships.c.user_id, memberships.c.source).where(
                        memberships.c.project_id == project_id
                    )
                ).all()
            }
            now = utcnow()
            for user_id in member_ids:
                current = existing.get(user_id)
                if current == "direct":
                    # An explicit invitation outranks the organisation's default.
                    continue
                if current == "org":
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
                            project_id=project_id, user_id=user_id,
                            role=role, source="org", created_at=now,
                        )
                    )
            # Anyone no longer in the organisation loses org-derived access.
            stale = [
                uid
                for uid, source in existing.items()
                if source == "org" and uid not in set(member_ids)
            ]
            if stale:
                conn.execute(
                    delete(memberships).where(
                        memberships.c.project_id == project_id,
                        memberships.c.user_id.in_(stale),
                        memberships.c.source == "org",
                    )
                )

    def _sync_member(self, org_id: str, user_id: str) -> None:
        """Grant one new member the access every org context already advertises."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(projects.c.id, projects.c.org_access).where(
                    projects.c.org_id == org_id,
                    projects.c.org_access != "none",
                )
            ).all()
            if not rows:
                return
            existing = {
                r[0]: r[1]
                for r in conn.execute(
                    select(memberships.c.project_id, memberships.c.source).where(
                        memberships.c.user_id == user_id,
                        memberships.c.project_id.in_([r.id for r in rows]),
                    )
                ).all()
            }
            now = utcnow()
            for project_id, access in rows:
                role = ACCESS_TO_ROLE[access]
                current = existing.get(project_id)
                if current == "direct":
                    continue
                if current == "org":
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
                            project_id=project_id, user_id=user_id,
                            role=role, source="org", created_at=now,
                        )
                    )

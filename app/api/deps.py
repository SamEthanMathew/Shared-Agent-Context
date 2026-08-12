"""Identity resolution for both surfaces.

In ``dev`` mode (SAC_AUTH_MODE=dev, the default until the OAuth layer lands) the
caller is identified by an actor email — a REST header or an MCP tool param.
This is spoofable by design and MUST NOT be used on a public deployment. In
``auth`` mode the principal comes from the verified OAuth token; that path is
wired in M5 (``principal_from_access_token``).
"""
from __future__ import annotations

import os

from ..errors import ForbiddenError, ValidationError
from ..identity import Principal, RequestIdentity
from ..models import READ_SCOPE, WRITE_SCOPE
from ..stores import SACStore


def auth_mode() -> str:
    return os.getenv("SAC_AUTH_MODE", "dev").strip().lower()


def _dev_principal(store: SACStore, actor_email: str | None) -> Principal:
    email = (actor_email or os.getenv("SAC_DEV_ACTOR") or "").strip().lower()
    if not email:
        raise ForbiddenError("dev mode requires an actor_email (or SAC_DEV_ACTOR)")
    user = store.projects.get_user_by_email(email)
    if not user:
        raise ForbiddenError("unknown actor")
    conns = store.projects.list_connections(user["id"])
    active = [c for c in conns if c["revoked_at"] is None]
    conn_id = (
        active[0]["id"]
        if active
        else store.projects.create_agent_connection(
            user["id"], label=f"dev:{email}", provider_hint="dev"
        )
    )
    return Principal(
        user_id=user["id"],
        agent_connection_id=conn_id,
        scopes=(READ_SCOPE, WRITE_SCOPE),
        label=email,
    )


def resolve_principal(
    store: SACStore,
    actor_email: str | None = None,
    principal: Principal | None = None,
) -> Principal:
    """Return the authenticated principal.

    ``principal`` (from a verified token, M5) wins. Otherwise dev mode resolves
    from ``actor_email``.
    """
    if principal is not None:
        return principal
    if auth_mode() == "dev":
        return _dev_principal(store, actor_email)
    raise ForbiddenError("authentication required")


def resolve_default_project(
    store: SACStore, principal: Principal, project_id: str | None
) -> str:
    if project_id:
        return project_id
    env = os.getenv("SAC_DEFAULT_PROJECT_ID")
    if env:
        return env
    project_ids = store.projects.list_user_project_ids(principal.user_id)
    if len(project_ids) == 1:
        return project_ids[0]
    if not project_ids:
        raise ForbiddenError("no project membership")
    raise ValidationError("multiple projects; specify project_id")


def resolve_identity(
    store: SACStore,
    actor_email: str | None = None,
    project_id: str | None = None,
    principal: Principal | None = None,
) -> RequestIdentity:
    p = resolve_principal(store, actor_email=actor_email, principal=principal)
    pid = resolve_default_project(store, p, project_id)
    identity = store.resolve_identity(p, pid)
    if p.agent_connection_id:
        store.projects.touch_agent_connection(p.agent_connection_id)
    return identity

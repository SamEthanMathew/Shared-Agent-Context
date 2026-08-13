"""Identity resolution for both surfaces.

In ``dev`` mode (SAC_AUTH_MODE=dev, the default until the OAuth layer lands) the
caller is identified by an actor email — a REST header or an MCP tool param.
This is spoofable by design and MUST NOT be used on a public deployment. In
``auth`` mode the principal comes from the verified OAuth token; that path is
wired in M5 (``principal_from_access_token``).
"""
from __future__ import annotations

import os

from ..errors import ForbiddenError, NeedsContextSelection
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


def resolve_context(
    store: SACStore,
    principal: Principal,
    context: str | None = None,
    session_ref: str | None = None,
) -> str:
    """Decide which context this call operates on. Precedence is explicit:

    1. an explicit ``context`` (id / slug / name), resolved within the caller's
       memberships only — a name can never reach another tenant;
    2. a binding for this specific chat (client_session_ref);
    3. the client's default binding;
    4. the caller's only membership;
    5. otherwise raise NeedsContextSelection, carrying the candidates so the
       surface can ask instead of failing.

    ``SAC_DEFAULT_PROJECT_ID`` is honoured **only in dev mode**. In auth mode it
    is ignored: a process-global default that outranks real membership is not
    safe in a multi-tenant deployment.
    """
    if context:
        return store.projects.resolve_context_ref(principal.user_id, context)

    conn_id = principal.agent_connection_id
    if session_ref:
        bound = store.projects.get_binding(principal.user_id, conn_id, session_ref)
        if bound:
            return bound
    bound = store.projects.get_binding(principal.user_id, conn_id, None)
    if bound:
        return bound

    if auth_mode() == "dev":
        env = os.getenv("SAC_DEFAULT_PROJECT_ID")
        if env:
            return env

    contexts = store.projects.list_user_contexts(principal.user_id)
    if len(contexts) == 1:
        return contexts[0]["id"]
    raise NeedsContextSelection(contexts)


def resolve_identity(
    store: SACStore,
    actor_email: str | None = None,
    project_id: str | None = None,
    principal: Principal | None = None,
    context: str | None = None,
    session_ref: str | None = None,
) -> RequestIdentity:
    p = resolve_principal(store, actor_email=actor_email, principal=principal)
    # `project_id` is the deprecated V1 spelling of `context`; accept it for one
    # release so live connectors don't break mid-session.
    pid = resolve_context(store, p, context=context or project_id, session_ref=session_ref)
    identity = store.resolve_identity(p, pid)
    if p.agent_connection_id:
        store.projects.touch_agent_connection(p.agent_connection_id)
    return identity

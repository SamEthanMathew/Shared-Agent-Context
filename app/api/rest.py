"""REST /v1 surface. Mirrors the MCP tools through the same impl layer.

Identity is resolved per request: dev mode reads the ``X-SAC-User`` header; the
OAuth path (M5) supplies a verified principal on ``request.state.principal``.
Non-members receive 403 with a coarse body — the surface never reveals whether
a project exists (project isolation).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..errors import ForbiddenError, NotFoundError
from ..limits import require_verified
from ..identity import Principal, RequestIdentity
from ..runtime import get_store
from . import impl, sharing
from .deps import resolve_principal
from .schemas import (
    AccessRequest,
    AddMemberRequest,
    ContextOrgRequest,
    CreateOrgRequest,
    CreateProjectRequest,
    CreateSessionRequest,
    LinkAccessRequest,
    OrgMemberRequest,
    RememberRequest,
    ShareRequest,
    SyncRequest,
    UseContextRequest,
)

router = APIRouter(prefix="/v1")


# --- who am I ---------------------------------------------------------------


@router.get("/me", operation_id="get_me")
def get_me(request: Request) -> Any:
    """Everything the web app needs to render its first frame.

    One round trip returns the account, its contexts, and a usable CSRF token —
    reissuing the cookie if the session outlived it, so a stale tab repairs
    itself instead of failing its first write.
    """
    from fastapi.responses import JSONResponse

    from ..browser import CSRF_COOKIE, SESSION_COOKIE, csrf_token_for

    store = get_store()
    principal = _principal(request)
    user = store.projects.get_user(principal.user_id)
    if user is None:
        raise ForbiddenError("unknown user")

    sid = request.cookies.get(SESSION_COOKIE) or ""
    token = csrf_token_for(sid) if sid else ""
    body = {
        "ok": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "email_verified": user["email_verified_at"] is not None,
        },
        "contexts": impl.list_contexts(store, principal)["contexts"],
        "csrf_token": token,
    }
    response = JSONResponse(body)
    if sid and request.cookies.get(CSRF_COOKIE) != token:
        response.set_cookie(
            CSRF_COOKIE, token,
            httponly=False, secure=request.url.scheme == "https",
            samesite="lax", path="/",
        )
    return response


def _principal(request: Request) -> Principal:
    existing = getattr(request.state, "principal", None)
    if existing is not None:
        return existing
    return resolve_principal(get_store(), actor_email=request.headers.get("X-SAC-User"))


def _identity(request: Request, project_id: str) -> RequestIdentity:
    return get_store().resolve_identity(_principal(request), project_id)


# --- projects & membership --------------------------------------------------


@router.get("/contexts", operation_id="list_contexts")
def list_contexts(request: Request) -> dict[str, Any]:
    """Every context available to the caller."""
    return impl.list_contexts(get_store(), _principal(request))


@router.post("/contexts", operation_id="create_context")
def create_context(payload: CreateProjectRequest, request: Request) -> dict[str, Any]:
    """Create a context; the caller becomes its owner."""
    return impl.create_context(
        get_store(),
        _principal(request),
        payload.name,
        description=payload.description,
        make_active=False,
    )


@router.post("/projects", operation_id="create_project")
def create_project(payload: CreateProjectRequest, request: Request) -> dict[str, Any]:
    """Deprecated alias for POST /v1/contexts."""
    store = get_store()
    principal = _principal(request)
    project = store.projects.create_project(
        payload.name, owner_user_id=principal.user_id, description=payload.description
    )
    return {"ok": True, "project_id": project.id, "name": project.name}


@router.get("/projects/{project_id}", operation_id="get_project")
def get_project(project_id: str, request: Request) -> dict[str, Any]:
    return impl.project_info(get_store(), _identity(request, project_id))


@router.post("/projects/{project_id}/members", operation_id="add_member")
def add_member(
    project_id: str, payload: AddMemberRequest, request: Request
) -> dict[str, Any]:
    store = get_store()
    identity = _identity(request, project_id)
    from ..errors import ForbiddenError

    if identity.role not in ("owner", "admin"):
        raise ForbiddenError("only owners/admins add members")
    user = store.projects.get_user_by_email(payload.email)
    if user is None:
        from ..errors import NotFoundError

        raise NotFoundError("user not found")
    store.projects.add_membership(project_id, user["id"], role=payload.role)
    return {"ok": True, "project_id": project_id, "user_id": user["id"], "role": payload.role}


@router.get("/projects/{project_id}/members", operation_id="list_members")
def list_members(project_id: str, request: Request) -> dict[str, Any]:
    store = get_store()
    _identity(request, project_id)  # membership gate
    return {"ok": True, "members": store.projects.list_members(project_id)}


# --- sharing (human-only; deliberately not exposed as MCP tools) ------------


def _base_url() -> str:
    import os

    return os.getenv("SAC_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or ""


@router.get("/contexts/{context_id}/shares", operation_id="list_shares")
def list_shares(context_id: str, request: Request) -> dict[str, Any]:
    return sharing.list_shares(
        get_store(), _identity(request, context_id), base_url=_base_url()
    )


@router.get("/contexts/{context_id}/link", operation_id="get_context_link")
def get_context_link(context_id: str, request: Request) -> dict[str, Any]:
    """The share-link state. The token itself is only returned to a sharer."""
    return sharing.get_link(
        get_store(), _identity(request, context_id), base_url=_base_url()
    )


@router.put("/contexts/{context_id}/link", operation_id="set_context_link")
def set_context_link(
    context_id: str, payload: LinkAccessRequest, request: Request
) -> dict[str, Any]:
    """Open or close "anyone with the link" access. Owners and managers only."""
    return sharing.set_link_access(
        get_store(), _identity(request, context_id), payload.access,
        base_url=_base_url(),
    )


@router.post("/contexts/{context_id}/link/rotate", operation_id="rotate_context_link")
def rotate_context_link(context_id: str, request: Request) -> dict[str, Any]:
    """Replace the link, invalidating every copy already circulating."""
    return sharing.rotate_link(
        get_store(), _identity(request, context_id), base_url=_base_url()
    )


@router.post("/contexts/{context_id}/shares", operation_id="share_context")
def share_context(
    context_id: str, payload: ShareRequest, request: Request
) -> dict[str, Any]:
    import os

    base = os.getenv("SAC_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or ""
    return sharing.share_context(
        get_store(), _identity(request, context_id),
        email=payload.email, access=payload.access, base_url=base,
    )


@router.patch("/contexts/{context_id}/shares/{user_id}", operation_id="change_access")
def change_access(
    context_id: str, user_id: str, payload: AccessRequest, request: Request
) -> dict[str, Any]:
    return sharing.change_access(
        get_store(), _identity(request, context_id), user_id, payload.access
    )


@router.delete("/contexts/{context_id}/shares/{user_id}", operation_id="revoke_access")
def revoke_access(context_id: str, user_id: str, request: Request) -> dict[str, Any]:
    return sharing.revoke_access(
        get_store(), _identity(request, context_id), user_id
    )


@router.post("/projects/{project_id}/sessions", operation_id="create_session")
def create_session(
    project_id: str, payload: CreateSessionRequest, request: Request
) -> dict[str, Any]:
    store = get_store()
    identity = _identity(request, project_id)
    session = store.sessions.get_or_create(
        project_id, identity.user_id, payload.client_session_ref,
        agent_connection_id=identity.agent_connection_id,
    )
    return {"ok": True, "session_id": session.id}


# --- context & memory -------------------------------------------------------


@router.post("/projects/{project_id}/context/sync", operation_id="sync_context")
def sync_context(project_id: str, payload: SyncRequest, request: Request) -> dict[str, Any]:
    identity = _identity(request, project_id)
    return impl.sync_context(
        get_store(), identity,
        task=payload.task, session_ref=payload.session_ref,
        local_context_delta=payload.local_context_delta,
        known_revision=payload.known_revision, budget_tokens=payload.budget_tokens,
        delta_scope=payload.delta_scope,
    )


@router.post("/projects/{project_id}/memories/shared", operation_id="remember_shared")
def remember_shared(
    project_id: str, payload: RememberRequest, request: Request
) -> dict[str, Any]:
    return _remember(project_id, payload, request, scope="shared")


@router.post("/projects/{project_id}/memories/private", operation_id="remember_private")
def remember_private(
    project_id: str, payload: RememberRequest, request: Request
) -> dict[str, Any]:
    return _remember(project_id, payload, request, scope="private")


def _remember(
    project_id: str, payload: RememberRequest, request: Request, scope: str
) -> dict[str, Any]:
    identity = _identity(request, project_id)
    return impl.remember(
        get_store(), identity, scope=scope, kind=payload.kind, summary=payload.summary,
        details=payload.details, tags=payload.tags, importance=payload.importance,
        confidence=payload.confidence, sensitivity=payload.sensitivity,
        supersedes=payload.supersedes, contradicts=payload.contradicts,
        session_ref=payload.session_ref,
    )


@router.get("/projects/{project_id}/memories", operation_id="list_memories")
def list_memories(
    project_id: str,
    request: Request,
    scope: str | None = None,
    status: str | None = "active",
    kind: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    store = get_store()
    identity = _identity(request, project_id)
    mems = store.memories.list_memories(
        project_id, identity.user_id, scope=scope, status=status, kind=kind, limit=limit
    )
    return {"ok": True, "memories": [m.as_dict() for m in mems]}


@router.get("/projects/{project_id}/memories/{memory_id}", operation_id="get_memory")
def get_memory(
    project_id: str,
    memory_id: str,
    request: Request,
    include_versions: bool = False,
    include_relations: bool = True,
) -> dict[str, Any]:
    identity = _identity(request, project_id)
    return impl.get_memory(
        get_store(), identity, memory_id,
        include_versions=include_versions, include_relations=include_relations,
    )


@router.get("/projects/{project_id}/changes", operation_id="recent_changes")
def recent_changes(
    project_id: str,
    request: Request,
    session_ref: str | None = None,
    since_revision: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    identity = _identity(request, project_id)
    return impl.recent_changes(
        get_store(), identity, session_ref=session_ref,
        since_revision=since_revision, limit=limit,
    )


@router.get("/projects/{project_id}/sources/{source_id}", operation_id="get_source")
def get_source(project_id: str, source_id: str, request: Request) -> dict[str, Any]:
    identity = _identity(request, project_id)
    return impl.get_source(get_store(), identity, source_id)


@router.post(
    "/projects/{project_id}/memories/{memory_id}/retract",
    operation_id="retract_memory",
)
def retract_memory(project_id: str, memory_id: str, request: Request) -> dict[str, Any]:
    """Withdraw a memory so it stops reaching agents. History is retained."""
    store = get_store()
    identity = _identity(request, project_id)
    store.memories.retract(identity, memory_id)
    return {"ok": True, "memory_id": memory_id, "retracted": True}


# Emitted once per sync and per source read. They are the highest-volume events
# by far, and would bury the governance history the feed exists to show. The
# per-sync detail has its own surface: /contexts/{id}/snapshots.
_HIGH_VOLUME_ACTIONS = frozenset({"context.compile", "source.read"})


@router.get("/contexts/{context_id}/activity", operation_id="list_activity")
def list_activity(context_id: str, request: Request, limit: int = 50) -> dict[str, Any]:
    """The audit feed for a context: who shared, changed access, archived."""
    store = get_store()
    identity = _identity(request, context_id)
    # Over-fetch, because filtering after the limit would return a short page.
    events = [
        e
        for e in store.audit.recent(context_id, limit=min(limit * 4, 500))
        if e["action"] not in _HIGH_VOLUME_ACTIONS
    ][:limit]
    people = store.projects.get_users_map(
        [e["actor_user_id"] for e in events if e["actor_user_id"]]
    )
    return {
        "ok": True,
        "events": [
            {
                "id": e["id"],
                "action": e["action"],
                "entity_type": e["entity_type"],
                "actor": (people.get(e["actor_user_id"]) or {}).get(
                    "email", e["actor_user_id"]
                ),
                "meta": e["meta"],
                "created_at": e["created_at"].isoformat() if e["created_at"] else None,
            }
            for e in events
        ],
    }


# --- organisations ----------------------------------------------------------
#
# Administering an organisation and reading a context inside it are separate
# permissions on purpose. Every route here either manages the group or returns
# context *metadata*; none of them returns memory. Reading still requires a
# membership, which is the same boundary every other path goes through.


@router.get("/orgs", operation_id="list_orgs")
def list_orgs(request: Request) -> dict[str, Any]:
    store = get_store()
    principal = _principal(request)
    return {"ok": True, "orgs": store.orgs.list_for_user(principal.user_id)}


@router.post("/orgs", operation_id="create_org")
def create_org(payload: CreateOrgRequest, request: Request) -> dict[str, Any]:
    store = get_store()
    principal = _principal(request)
    require_verified(store, principal.user_id, "create an organisation")
    org = store.orgs.create(payload.name, principal.user_id)
    store.audit.emit(
        "org.create", "organisation", org["id"], actor_user_id=principal.user_id,
        meta={"name": org["name"]},
    )
    return {"ok": True, "org": org}


@router.get("/orgs/{org_id}", operation_id="get_org")
def get_org(org_id: str, request: Request) -> dict[str, Any]:
    """The organisation, its people, and its contexts (metadata only)."""
    store = get_store()
    principal = _principal(request)
    role = store.orgs.get_org_role(org_id, principal.user_id)
    if role is None:
        raise ForbiddenError("no such organisation")
    org = store.orgs.get(org_id) or {}
    return {
        "ok": True,
        "org": {"id": org_id, "name": org.get("name"), "slug": org.get("slug")},
        "your_role": role,
        "members": store.orgs.list_members(org_id),
        "contexts": store.orgs.list_org_contexts(org_id),
    }


@router.post("/orgs/{org_id}/members", operation_id="add_org_member")
def add_org_member(
    org_id: str, payload: OrgMemberRequest, request: Request
) -> dict[str, Any]:
    store = get_store()
    principal = _principal(request)
    store.orgs.require_org_admin(org_id, principal.user_id)
    user = store.projects.get_user_by_email(payload.email)
    # An unverified account is treated as no account here for the same reason as
    # in sharing: nobody has proved they control that mailbox, so adding it to a
    # group would let an address squatter inherit whatever the group can see.
    if user is None or not store.auth.is_email_verified(user["id"]):
        raise NotFoundError(
            "no verified account for that email; ask them to sign up and verify first"
        )
    # Free workspaces are capped; Pro is billed per seat, so growing the
    # workspace grows the subscription (prorated — they have the seat now).
    from ..billing.service import check_can_add_member, sync_seats

    check_can_add_member(store, org_id)
    store.orgs.add_member(org_id, user["id"], payload.org_role)
    sync_seats(store, org_id, growing=True)
    store.audit.emit(
        "org.member_add", "organisation", org_id, actor_user_id=principal.user_id,
        meta={"email": payload.email, "org_role": payload.org_role},
    )
    return {"ok": True, "email": payload.email, "org_role": payload.org_role}


@router.delete("/orgs/{org_id}/members/{user_id}", operation_id="remove_org_member")
def remove_org_member(org_id: str, user_id: str, request: Request) -> dict[str, Any]:
    store = get_store()
    principal = _principal(request)
    store.orgs.require_org_admin(org_id, principal.user_id)
    store.orgs.remove_member(org_id, user_id)
    # Access ended immediately above. The seat is already paid for through this
    # period, so the smaller quantity takes effect at renewal rather than being
    # clawed back mid-cycle.
    from ..billing.service import sync_seats

    sync_seats(store, org_id, growing=False)
    store.audit.emit(
        "org.member_remove", "organisation", org_id,
        actor_user_id=principal.user_id, meta={"user_id": user_id},
    )
    return {"ok": True, "removed": True}


@router.put("/contexts/{context_id}/org", operation_id="set_context_org")
def set_context_org(
    context_id: str, payload: ContextOrgRequest, request: Request
) -> dict[str, Any]:
    """Move a context into an organisation, or back out of one.

    Requires ownership of the context *and* admin of the destination
    organisation: moving something into a group is a decision for both sides.
    Access is unchanged by the move — `org_access` stays where it was.
    """
    store = get_store()
    identity = _identity(request, context_id)
    if identity.role != "owner":
        raise ForbiddenError("only the context owner can move it")

    if payload.org_id:
        store.orgs.require_org_admin(payload.org_id, identity.user_id)
        store.orgs.attach_project(payload.org_id, context_id)
    else:
        store.orgs.detach_project(context_id)
    store.audit.emit(
        "context.org_change", "project", context_id, project_id=context_id,
        actor_user_id=identity.user_id, meta={"org_id": payload.org_id},
    )
    return {"ok": True, "org_id": payload.org_id}


@router.put("/contexts/{context_id}/org-access", operation_id="set_context_org_access")
def set_context_org_access(
    context_id: str, payload: LinkAccessRequest, request: Request
) -> dict[str, Any]:
    """What every member of the owning organisation gets. Never `manage`."""
    store = get_store()
    identity = _identity(request, context_id)
    if identity.role not in ("owner", "admin"):
        raise ForbiddenError("only owners and managers can change organisation access")
    level = store.orgs.set_org_access(context_id, payload.access)
    store.audit.emit(
        "context.org_access", "project", context_id, project_id=context_id,
        actor_user_id=identity.user_id, meta={"access": level},
    )
    return {"ok": True, "org_access": level}


# --- connected AI clients ---------------------------------------------------


@router.get("/connections", operation_id="list_connections")
def list_connections(request: Request) -> dict[str, Any]:
    """The caller's AI clients, and which context each one is working in."""
    store = get_store()
    principal = _principal(request)
    names = {
        c["id"]: c["name"] for c in store.projects.list_user_contexts(principal.user_id)
    }
    out = []
    for conn in store.projects.list_connections(principal.user_id):
        bound = store.projects.get_binding(principal.user_id, conn["id"], None)
        out.append({
            "id": conn["id"],
            "label": conn["label"],
            "provider": conn["provider_hint"],
            "revoked": conn["revoked_at"] is not None,
            "last_seen_at": (
                conn["last_seen_at"].isoformat() if conn.get("last_seen_at") else None
            ),
            "context_id": bound,
            "context_name": names.get(bound or "", ""),
        })
    return {"ok": True, "connections": out}


@router.post("/connections/{conn_id}/revoke", operation_id="revoke_connection")
def revoke_connection(conn_id: str, request: Request) -> dict[str, Any]:
    store = get_store()
    principal = _principal(request)
    conn = store.projects.get_agent_connection(conn_id)
    if conn is None or conn["user_id"] != principal.user_id:
        raise NotFoundError("connection not found")
    store.projects.revoke_agent_connection(conn_id)
    return {"ok": True, "revoked": True}


@router.put("/connections/{conn_id}/context", operation_id="set_connection_context")
def set_connection_context(
    conn_id: str, payload: UseContextRequest, request: Request
) -> dict[str, Any]:
    """Point one AI client at a context, from the web app.

    The equivalent of the agent calling ``sac_use_context``, so a person can
    move a client without having to ask their assistant to do it.
    """
    store = get_store()
    principal = _principal(request)
    conn = store.projects.get_agent_connection(conn_id)
    if conn is None or conn["user_id"] != principal.user_id:
        raise NotFoundError("connection not found")
    # resolve_context_ref scopes to the caller's memberships, so a raw id
    # belonging to someone else cannot be bound here.
    project_id = store.projects.resolve_context_ref(
        principal.user_id, payload.context
    )
    store.projects.set_binding(principal.user_id, project_id, conn_id)
    return {"ok": True, "connection_id": conn_id, "context_id": project_id}


@router.post("/contexts/{context_id}/archive", operation_id="archive_context")
def archive_context(context_id: str, request: Request) -> dict[str, Any]:
    """Soft-delete a context. Owner only; memory is retained."""
    store = get_store()
    identity = _identity(request, context_id)
    if identity.role != "owner":
        raise ForbiddenError("only the owner can archive a context")
    store.projects.archive_project(context_id)
    store.audit.emit(
        "context.archive", "project", context_id, project_id=context_id,
        actor_user_id=identity.user_id,
    )
    return {"ok": True, "archived": True, "context": identity.context_name}


@router.post("/contexts/{context_id}/unarchive", operation_id="unarchive_context")
def unarchive_context(context_id: str, request: Request) -> dict[str, Any]:
    """Restore an archived context."""
    store = get_store()
    identity = store.resolve_identity(
        _principal(request), context_id, allow_archived=True
    )
    if identity.role != "owner":
        raise ForbiddenError("only the owner can restore a context")
    store.projects.unarchive_project(context_id)
    store.audit.emit(
        "context.unarchive", "project", context_id, project_id=context_id,
        actor_user_id=identity.user_id,
    )
    return {"ok": True, "archived": False, "context": identity.context_name}


@router.get("/contexts/{context_id}/snapshots", operation_id="list_snapshots")
def list_snapshots(context_id: str, request: Request, limit: int = 25) -> dict[str, Any]:
    """Your own compile records for this context — what your agents were shown."""
    store = get_store()
    identity = _identity(request, context_id)
    snaps = store.snapshots.list_for_user(context_id, identity.user_id, limit=limit)
    for s in snaps:
        s["created_at"] = s["created_at"].isoformat() if s["created_at"] else None
    return {"ok": True, "snapshots": snaps}


@router.get("/projects/{project_id}/snapshots/{snapshot_id}", operation_id="get_snapshot")
def get_snapshot(project_id: str, snapshot_id: str, request: Request) -> dict[str, Any]:
    """One sync record: what was compiled into an agent's context, and what wasn't.

    Readable **only** by the person whose agent made the call. A snapshot
    enumerates the memories fed to that agent, which includes their private
    ones, so a context owner has no more business reading it than anyone else —
    the same rule the console has always enforced, and what docs/SETUP.md
    promises. This endpoint previously admitted owners and admins.
    """
    store = get_store()
    identity = _identity(request, project_id)
    snap = store.snapshots.get(snapshot_id)

    if snap is None or snap["project_id"] != project_id:
        raise NotFoundError("snapshot not found")
    if snap["user_id"] != identity.user_id:
        raise ForbiddenError("not permitted")

    snap = dict(snap)
    snap["created_at"] = snap["created_at"].isoformat()

    # Resolve memory ids to summaries so the manifest is readable. get_memory
    # carries the visibility predicate, so anything no longer visible to this
    # caller comes back as None and is reported as such rather than guessed at.
    def describe(
        entries: list[dict[str, Any]] | None, detail_key: str
    ) -> list[dict[str, Any]]:
        out = []
        for entry in entries or []:
            memory_id = entry.get("memory_id")
            if not memory_id:
                # An aggregate row, e.g. "3 private memories withheld". It names
                # nobody by design.
                out.append({
                    "aggregate": True,
                    "count": entry.get("count"),
                    "detail": entry.get("reason", "withheld"),
                })
                continue
            memory = store.memories.get_memory(project_id, memory_id, identity.user_id)
            out.append({
                "aggregate": False,
                "memory_id": memory_id,
                "kind": memory.kind if memory else None,
                "summary": memory.summary if memory else None,
                "visible": memory is not None,
                "detail": entry.get(detail_key),
            })
        return out

    return {
        "ok": True,
        "snapshot": snap,
        "included": describe(snap.get("included"), "section"),
        "withheld": describe(snap.get("excluded"), "reason"),
    }

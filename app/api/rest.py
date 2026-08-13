"""REST /v1 surface. Mirrors the MCP tools through the same impl layer.

Identity is resolved per request: dev mode reads the ``X-SAC-User`` header; the
OAuth path (M5) supplies a verified principal on ``request.state.principal``.
Non-members receive 403 with a coarse body — the surface never reveals whether
a project exists (project isolation).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..errors import ForbiddenError
from ..identity import Principal, RequestIdentity
from ..runtime import get_store
from . import impl, sharing
from .deps import resolve_principal
from .schemas import (
    AccessRequest,
    AddMemberRequest,
    CreateProjectRequest,
    CreateSessionRequest,
    RememberRequest,
    ShareRequest,
    SyncRequest,
)

router = APIRouter(prefix="/v1")


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


@router.get("/contexts/{context_id}/shares", operation_id="list_shares")
def list_shares(context_id: str, request: Request) -> dict[str, Any]:
    return sharing.list_shares(get_store(), _identity(request, context_id))


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
    store = get_store()
    identity = _identity(request, project_id)
    snap = store.snapshots.get(snapshot_id)
    from ..errors import ForbiddenError, NotFoundError

    if snap is None or snap["project_id"] != project_id:
        raise NotFoundError("snapshot not found")
    if snap["user_id"] != identity.user_id and identity.role not in ("owner", "admin"):
        raise ForbiddenError("not permitted")
    snap = dict(snap)
    snap["created_at"] = snap["created_at"].isoformat()
    return {"ok": True, "snapshot": snap}

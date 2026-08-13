"""Backend-shared operations. Both REST and MCP call these with a resolved
RequestIdentity, so the two surfaces stay one backend with one policy.
"""
from __future__ import annotations

from typing import Any

from ..context import compile_context
from ..errors import ValidationError
from ..identity import Principal, RequestIdentity
from ..limits import MAX_CONTEXTS_PER_USER, enforce_quota, require_verified
from ..models import ROLE_TO_ACCESS
from ..stores import SACStore

# --- context management -----------------------------------------------------


def list_contexts(
    store: SACStore, principal: Principal, active_id: str | None = None
) -> dict[str, Any]:
    """Every context available to the caller, flagging the active one."""
    contexts = store.projects.list_user_contexts(principal.user_id)
    for c in contexts:
        c["is_active"] = c["id"] == active_id
    return {
        "ok": True,
        "contexts": contexts,
        "active_context_id": active_id,
        "count": len(contexts),
    }


def create_context(
    store: SACStore,
    principal: Principal,
    name: str,
    description: str = "",
    make_active: bool = True,
) -> dict[str, Any]:
    """Create a context, make the caller its owner, and select it.

    Requires a verified email: it is the cheapest effective control against
    throwaway accounts creating contexts in bulk.
    """
    require_verified(store, principal.user_id, "create a context")
    enforce_quota(
        store,
        len(store.projects.list_user_contexts(principal.user_id)),
        MAX_CONTEXTS_PER_USER,
        "contexts",
    )
    project = store.projects.create_project(
        name, owner_user_id=principal.user_id, description=description
    )
    if make_active:
        store.projects.set_binding(
            principal.user_id, project.id, principal.agent_connection_id
        )
    store.audit.emit(
        "context.create", "project", project.id, project_id=project.id,
        actor_user_id=principal.user_id,
        actor_agent_id=principal.agent_connection_id,
        meta={"name": project.name},
    )
    return {
        "ok": True,
        "created": True,
        "active_context": {
            "id": project.id,
            "name": project.name,
            "slug": project.slug,
            "access": "owner",
        },
        "message": f"Created and switched to context '{project.name}'.",
    }


def use_context(
    store: SACStore,
    principal: Principal,
    context: str,
    scope: str = "client",
    session_ref: str | None = None,
) -> dict[str, Any]:
    """Switch the active context for this client, or just for one chat."""
    if scope not in ("client", "chat"):
        raise ValidationError("scope must be 'client' or 'chat'")
    if scope == "chat" and not session_ref:
        raise ValidationError("scope='chat' requires session_ref")

    project_id = store.projects.resolve_context_ref(principal.user_id, context)
    identity = store.resolve_identity(principal, project_id)
    store.projects.set_binding(
        principal.user_id,
        project_id,
        principal.agent_connection_id,
        session_ref if scope == "chat" else None,
    )
    store.audit.emit(
        "context.switch", "project", project_id, project_id=project_id,
        actor_user_id=principal.user_id,
        actor_agent_id=principal.agent_connection_id,
        meta={"scope": scope},
    )
    where = "this conversation" if scope == "chat" else "this client"
    return {
        "ok": True,
        "switched": True,
        "scope": scope,
        "active_context": identity.active_context(),
        "revision": store.current_revision(project_id),
        "message": f"Now working in '{identity.context_name}' for {where}.",
    }


def context_info(store: SACStore, identity: RequestIdentity) -> dict[str, Any]:
    """What context am I in, and what may I do here."""
    counts = store.memories.count_memories(identity.project_id, identity.user_id)
    members = store.projects.list_members(identity.project_id)
    access = ROLE_TO_ACCESS.get(identity.role, identity.role)
    return {
        "ok": True,
        "active_context": identity.active_context(),
        "revision": store.current_revision(identity.project_id),
        "member_count": len(members),
        "memory_counts": {
            "shared_active": counts["shared_active"],
            "private_mine": counts["private_mine"],
        },
        "can_write": identity.role in ("owner", "admin", "member"),
        "can_share": identity.role in ("owner", "admin"),
        "access": access,
    }


def project_info(store: SACStore, identity: RequestIdentity) -> dict[str, Any]:
    project = store.projects.get_project(identity.project_id)
    counts = store.memories.count_memories(identity.project_id, identity.user_id)
    members = store.projects.list_members(identity.project_id)
    return {
        "ok": True,
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "revision": project.context_revision,
            "member_count": len(members),
            "memory_counts": {
                "shared_active": counts["shared_active"],
                "private_mine": counts["private_mine"],
            },
        },
        "identity": {
            "user_id": identity.user_id,
            "agent_connection_id": identity.agent_connection_id,
            "role": identity.role,
        },
    }


def sync_context(
    store: SACStore,
    identity: RequestIdentity,
    task: str,
    session_ref: str,
    local_context_delta: str = "",
    known_revision: int | None = None,
    budget_tokens: int = 3000,
    delta_scope: str = "shared",
) -> dict[str, Any]:
    session = store.sessions.get_or_create(
        identity.project_id,
        identity.user_id,
        session_ref,
        agent_connection_id=identity.agent_connection_id,
    )
    if local_context_delta and local_context_delta.strip():
        store.memories.remember(
            identity,
            scope=delta_scope,
            kind="session_delta",
            summary=local_context_delta.strip(),
            importance=0.55,
            session_id=session.id,
            internal_kind=True,
        )
        # re-read the session so the delta counts as an unseen change if others sync
        session = store.sessions.get(session.id) or session

    result = compile_context(store, identity, session, task, budget_tokens)
    store.sessions.advance_watermark(session.id, result["new_session_revision"], task)
    result["ok"] = True
    result["session_id"] = session.id
    return result


def remember(
    store: SACStore,
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
    session_ref: str | None = None,
) -> dict[str, Any]:
    session_id = None
    if session_ref:
        session_id = store.sessions.get_or_create(
            identity.project_id,
            identity.user_id,
            session_ref,
            agent_connection_id=identity.agent_connection_id,
        ).id
    out = store.memories.remember(
        identity,
        scope=scope,
        kind=kind,
        summary=summary,
        details=details,
        tags=tags,
        importance=importance,
        confidence=confidence,
        sensitivity=sensitivity,
        supersedes=supersedes,
        contradicts=contradicts,
        session_id=session_id,
    )
    return {
        "ok": True,
        "project_id": identity.project_id,
        "revision": out["revision"],
        "memory": out["memory"].as_dict(include_details=True),
        "superseded": out["superseded"],
        "conflicts_opened": out["conflicts_opened"],
    }


def recent_changes(
    store: SACStore,
    identity: RequestIdentity,
    session_ref: str | None = None,
    since_revision: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    session_id = None
    since = since_revision
    if session_ref:
        session = store.sessions.get_or_create(
            identity.project_id, identity.user_id, session_ref,
            agent_connection_id=identity.agent_connection_id,
        )
        session_id = session.id
        if since is None:
            since = session.last_seen_revision
    if since is None:
        since = 0
    delivered, truncated = store.memories.changes_since(
        identity.project_id, identity.user_id, session_id, since, limit=limit
    )
    head = store.current_revision(identity.project_id)
    next_since = delivered[-1].revision if delivered else since
    return {
        "ok": True,
        "head_revision": head,
        "changes": [m.as_dict(include_details=False) for m in delivered],
        "truncated": truncated,
        "next_since_revision": next_since,
    }


def get_source(
    store: SACStore, identity: RequestIdentity, source_id: str
) -> dict[str, Any]:
    src = store.memories.get_source(identity.project_id, source_id, identity.user_id)
    if src is None:
        return {"ok": False, "error": "source_not_found", "source_id": source_id}
    store.audit.emit(
        "source.read", "evidence", source_id, project_id=identity.project_id,
        actor_user_id=identity.user_id, actor_agent_id=identity.agent_connection_id,
    )
    return {
        "ok": True,
        "source": {
            "id": src["id"],
            "event_type": src["event_type"],
            "visibility_scope": src["visibility_scope"],
            "actor_user_id": src["actor_user_id"],
            "content": src["content"],
            "source_uri": src["source_uri"],
            "created_at": src["created_at"].isoformat(),
        },
    }


def get_memory(
    store: SACStore,
    identity: RequestIdentity,
    memory_id: str,
    include_versions: bool = False,
    include_relations: bool = True,
) -> dict[str, Any]:
    mem = store.memories.get_memory(identity.project_id, memory_id, identity.user_id)
    if mem is None:
        return {"ok": False, "error": "memory_not_found", "memory_id": memory_id}
    result: dict[str, Any] = {"ok": True, "memory": mem.as_dict(include_details=True)}
    if include_relations:
        result["relations"] = store.memories.get_relations(
            memory_id, identity.project_id, identity.user_id
        )
    if include_versions:
        result["versions"] = [
            {"version": v["version"], "summary": v["summary"], "status": v["status"]}
            for v in store.memories.get_versions(
                memory_id, identity.project_id, identity.user_id
            )
        ]
    return result


def status(store: SACStore, identity: RequestIdentity) -> dict[str, Any]:
    counts = store.memories.count_memories(identity.project_id, identity.user_id)
    return {
        "ok": True,
        "project_id": identity.project_id,
        "revision": store.current_revision(identity.project_id),
        "memory_count": counts["shared_active"] + counts["private_mine"],
        "mode": "v1_core_engine",
    }

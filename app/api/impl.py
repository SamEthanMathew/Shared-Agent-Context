"""Backend-shared operations. Both REST and MCP call these with a resolved
RequestIdentity, so the two surfaces stay one backend with one policy.
"""
from __future__ import annotations

from typing import Any

from ..context import compile_context
from ..identity import RequestIdentity
from ..stores import SACStore


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
    src = store.memories.get_source(identity.project_id, source_id)
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
        result["relations"] = store.memories.get_relations(memory_id)
    if include_versions:
        result["versions"] = [
            {"version": v["version"], "summary": v["summary"], "status": v["status"]}
            for v in store.memories.get_versions(memory_id)
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

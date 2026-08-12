"""The eight SAC MCP tools. Thin wrappers over the shared impl layer.

Identity: in ``auth`` mode it comes from the verified OAuth token
(``get_access_token``); in ``dev`` mode from the ``actor_email`` argument (or
SAC_DEV_ACTOR). ``project_id`` is optional — it defaults to the caller's single
project, or SAC_DEFAULT_PROJECT_ID.
"""
from __future__ import annotations

from typing import Any

from ..identity import Principal, RequestIdentity
from ..models import MemoryKind, Sensitivity
from ..runtime import get_store
from . import impl
from .deps import auth_mode, resolve_identity


def _identity(
    actor_email: str | None, project_id: str | None
) -> RequestIdentity:
    store = get_store()
    principal: Principal | None = None
    if auth_mode() != "dev":
        from mcp.server.auth.middleware.auth_context import get_access_token

        access = get_access_token()
        claims = getattr(access, "claims", {}) or {}
        principal = Principal(
            user_id=access.subject or claims.get("user_id"),
            agent_connection_id=claims.get("agent_connection_id"),
            scopes=tuple(access.scopes or ()),
            label=claims.get("connection_label", ""),
        )
    return resolve_identity(
        store, actor_email=actor_email, project_id=project_id, principal=principal
    )


def register(mcp) -> None:
    """Register all SAC tools on the given MCPServer instance."""

    @mcp.tool(structured_output=True)
    def sac_project_info(
        project_id: str | None = None, actor_email: str | None = None
    ) -> dict[str, Any]:
        """Return project summary, memory counts, and the caller's role."""
        return impl.project_info(get_store(), _identity(actor_email, project_id))

    @mcp.tool(structured_output=True)
    def sac_sync_context(
        task: str,
        session_ref: str = "default",
        local_context_delta: str = "",
        known_revision: int | None = None,
        budget_tokens: int = 3000,
        delta_scope: str = "shared",
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Call at the start of every turn: optionally record the previous
        turn's durable delta, then return task-relevant shared+private context
        plus changes since this session last synced."""
        return impl.sync_context(
            get_store(), _identity(actor_email, project_id),
            task=task, session_ref=session_ref,
            local_context_delta=local_context_delta, known_revision=known_revision,
            budget_tokens=budget_tokens, delta_scope=delta_scope,
        )

    @mcp.tool(structured_output=True)
    def sac_remember_shared(
        kind: MemoryKind,
        summary: str,
        details: str = "",
        tags: list[str] | None = None,
        importance: float = 0.6,
        confidence: float = 0.7,
        sensitivity: Sensitivity = "internal",
        supersedes: list[str] | None = None,
        contradicts: list[str] | None = None,
        session_ref: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Publish durable project knowledge visible to all collaborators."""
        return impl.remember(
            get_store(), _identity(actor_email, project_id), scope="shared",
            kind=kind, summary=summary, details=details, tags=tags or [],
            importance=importance, confidence=confidence, sensitivity=sensitivity,
            supersedes=supersedes or [], contradicts=contradicts or [],
            session_ref=session_ref,
        )

    @mcp.tool(structured_output=True)
    def sac_remember_private(
        kind: MemoryKind,
        summary: str,
        details: str = "",
        tags: list[str] | None = None,
        importance: float = 0.6,
        confidence: float = 0.7,
        sensitivity: Sensitivity = "internal",
        supersedes: list[str] | None = None,
        contradicts: list[str] | None = None,
        session_ref: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Store durable project knowledge visible only to you (private scope)."""
        return impl.remember(
            get_store(), _identity(actor_email, project_id), scope="private",
            kind=kind, summary=summary, details=details, tags=tags or [],
            importance=importance, confidence=confidence, sensitivity=sensitivity,
            supersedes=supersedes or [], contradicts=contradicts or [],
            session_ref=session_ref,
        )

    @mcp.tool(structured_output=True)
    def sac_recent_changes(
        session_ref: str | None = None,
        since_revision: int | None = None,
        limit: int = 20,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """List shared/visible changes since a revision (or this session's watermark)."""
        return impl.recent_changes(
            get_store(), _identity(actor_email, project_id),
            session_ref=session_ref, since_revision=since_revision, limit=limit,
        )

    @mcp.tool(structured_output=True)
    def sac_get_source(
        source_id: str,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Fetch the evidence event a memory was derived from."""
        return impl.get_source(get_store(), _identity(actor_email, project_id), source_id)

    @mcp.tool(structured_output=True)
    def sac_get_memory(
        memory_id: str,
        include_versions: bool = False,
        include_relations: bool = True,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Rehydrate one memory (with relations/versions) when compact context lacks detail."""
        return impl.get_memory(
            get_store(), _identity(actor_email, project_id), memory_id,
            include_versions=include_versions, include_relations=include_relations,
        )

    @mcp.tool(structured_output=True)
    def sac_status(
        project_id: str | None = None, actor_email: str | None = None
    ) -> dict[str, Any]:
        """Return current shared-context status for the project."""
        return impl.status(get_store(), _identity(actor_email, project_id))

"""The SAC MCP tools.

Twelve tools: four for managing which shared context you are working in, and
eight for using it.

Identity comes from the verified OAuth token in ``auth`` mode, or from the
``actor_email`` argument in ``dev`` mode (local only).

Every response carries an ``active_context`` block, and any call that cannot
determine a context returns an actionable ``needs_context_selection`` payload
listing the caller's contexts — never a bare error — so the agent can ask the
user instead of dead-ending.
"""
from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from ..errors import NeedsContextSelection, SACError
from ..identity import Principal, RequestIdentity
from ..models import MemoryKind, Sensitivity
from ..runtime import get_store
from . import impl
from .deps import auth_mode, resolve_context, resolve_identity, resolve_principal

_READ_ONLY = ToolAnnotations(read_only_hint=True)


def _principal() -> Principal:
    """The verified caller. In dev mode this is filled from actor_email later."""
    store = get_store()
    if auth_mode() == "dev":
        return None  # type: ignore[return-value]
    from mcp.server.auth.middleware.auth_context import get_access_token

    access = get_access_token()
    claims = getattr(access, "claims", {}) or {}
    return Principal(
        user_id=access.subject or claims.get("user_id"),
        agent_connection_id=claims.get("agent_connection_id"),
        scopes=tuple(access.scopes or ()),
        label=claims.get("connection_label", ""),
    )


def _resolve_principal(actor_email: str | None) -> Principal:
    return resolve_principal(
        get_store(), actor_email=actor_email, principal=_principal()
    )


def _identity(
    actor_email: str | None,
    context: str | None,
    session_ref: str | None = None,
) -> RequestIdentity:
    return resolve_identity(
        get_store(),
        actor_email=actor_email,
        principal=_principal(),
        context=context,
        session_ref=session_ref,
    )


def _needs_selection(exc: NeedsContextSelection) -> dict[str, Any]:
    """Turn 'which context?' into something the agent can act on."""
    if exc.contexts:
        hint = (
            "Ask the user which context to use, then call sac_use_context with "
            "its name. Available: "
            + ", ".join(f"'{c['name']}'" for c in exc.contexts)
        )
    else:
        hint = (
            "This user has no shared contexts yet. Offer to create one with "
            "sac_create_context(name=...)."
        )
    return {
        "ok": False,
        "error": "needs_context_selection",
        "contexts": exc.contexts,
        "hint": hint,
    }


def _guard(fn):
    """Run a tool body, converting context problems into actionable payloads."""
    try:
        return fn()
    except NeedsContextSelection as exc:
        return _needs_selection(exc)
    except SACError as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)}


def register(mcp) -> None:
    """Register all SAC tools on the given MCPServer instance."""

    # --- managing which context you are in ---------------------------------

    @mcp.tool(structured_output=True, annotations=_READ_ONLY)
    def sac_list_contexts(actor_email: str | None = None) -> dict[str, Any]:
        """List every shared context available to the user.

        Use this when the user asks what contexts/projects exist, when you need
        to pick one, or whenever a call reports needs_context_selection.
        """

        def run():
            store = get_store()
            principal = _resolve_principal(actor_email)
            active = None
            try:
                active = resolve_context(store, principal)
            except NeedsContextSelection:
                pass
            return impl.list_contexts(store, principal, active_id=active)

        return _guard(run)

    @mcp.tool(structured_output=True)
    def sac_create_context(
        name: str,
        description: str = "",
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Create a new shared context and start working in it.

        The user becomes its owner. Tell the user the context was created and
        that you are now working in it.
        """

        def run():
            return impl.create_context(
                get_store(), _resolve_principal(actor_email), name, description
            )

        return _guard(run)

    @mcp.tool(structured_output=True)
    def sac_use_context(
        context: str,
        scope: str = "client",
        session_ref: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Switch to a different shared context, by name, slug, or id.

        scope="client" (default) switches everywhere on this client;
        scope="chat" pins only this conversation, leaving other chats alone.
        Always tell the user which context you switched to.
        """

        def run():
            return impl.use_context(
                get_store(),
                _resolve_principal(actor_email),
                context,
                scope=scope,
                session_ref=session_ref,
            )

        return _guard(run)

    @mcp.tool(structured_output=True, annotations=_READ_ONLY)
    def sac_context_info(
        context: str | None = None, actor_email: str | None = None
    ) -> dict[str, Any]:
        """Report which context is active and what the user may do in it."""

        def run():
            return impl.context_info(get_store(), _identity(actor_email, context))

        return _guard(run)

    # --- using the active context ------------------------------------------

    @mcp.tool(structured_output=True)
    def sac_sync_context(
        task: str,
        session_ref: str = "default",
        local_context_delta: str = "",
        known_revision: int | None = None,
        budget_tokens: int = 3000,
        delta_scope: str = "shared",
        context: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Call at the start of every turn: optionally record the previous
        turn's durable delta, then return task-relevant shared and private
        context plus changes since this session last synced.
        """

        def run():
            identity = _identity(actor_email, context or project_id, session_ref)
            out = impl.sync_context(
                get_store(), identity,
                task=task, session_ref=session_ref,
                local_context_delta=local_context_delta,
                known_revision=known_revision,
                budget_tokens=budget_tokens, delta_scope=delta_scope,
            )
            out["active_context"] = identity.active_context()
            return out

        return _guard(run)

    def _remember(scope: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        # Pop every routing argument before the rest is forwarded to impl.
        actor_email = kwargs.pop("actor_email", None)
        context = kwargs.pop("context", None)
        project_id = kwargs.pop("project_id", None)

        def run():
            identity = _identity(
                actor_email, context or project_id, kwargs.get("session_ref")
            )
            out = impl.remember(get_store(), identity, scope=scope, **kwargs)
            out["active_context"] = identity.active_context()
            return out

        return _guard(run)

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
        context: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Publish durable project knowledge visible to everyone in the context."""
        return _remember("shared", dict(
            kind=kind, summary=summary, details=details, tags=tags or [],
            importance=importance, confidence=confidence, sensitivity=sensitivity,
            supersedes=supersedes or [], contradicts=contradicts or [],
            session_ref=session_ref, context=context, project_id=project_id,
            actor_email=actor_email,
        ))

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
        context: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Store knowledge visible only to you, inside the active context."""
        return _remember("private", dict(
            kind=kind, summary=summary, details=details, tags=tags or [],
            importance=importance, confidence=confidence, sensitivity=sensitivity,
            supersedes=supersedes or [], contradicts=contradicts or [],
            session_ref=session_ref, context=context, project_id=project_id,
            actor_email=actor_email,
        ))

    @mcp.tool(structured_output=True, annotations=_READ_ONLY)
    def sac_recent_changes(
        session_ref: str | None = None,
        since_revision: int | None = None,
        limit: int = 20,
        context: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """List changes in the active context since a revision or last sync."""

        def run():
            identity = _identity(actor_email, context or project_id, session_ref)
            out = impl.recent_changes(
                get_store(), identity,
                session_ref=session_ref, since_revision=since_revision, limit=limit,
            )
            out["active_context"] = identity.active_context()
            return out

        return _guard(run)

    @mcp.tool(structured_output=True, annotations=_READ_ONLY)
    def sac_get_source(
        source_id: str,
        context: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Fetch the evidence event a memory was derived from."""

        def run():
            identity = _identity(actor_email, context or project_id)
            out = impl.get_source(get_store(), identity, source_id)
            out["active_context"] = identity.active_context()
            return out

        return _guard(run)

    @mcp.tool(structured_output=True, annotations=_READ_ONLY)
    def sac_get_memory(
        memory_id: str,
        include_versions: bool = False,
        include_relations: bool = True,
        context: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Rehydrate one memory when the compact context lacks detail."""

        def run():
            identity = _identity(actor_email, context or project_id)
            out = impl.get_memory(
                get_store(), identity, memory_id,
                include_versions=include_versions,
                include_relations=include_relations,
            )
            out["active_context"] = identity.active_context()
            return out

        return _guard(run)

    @mcp.tool(structured_output=True, annotations=_READ_ONLY)
    def sac_project_info(
        context: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Summary of the active context: counts, members, your access."""

        def run():
            identity = _identity(actor_email, context or project_id)
            out = impl.project_info(get_store(), identity)
            out["active_context"] = identity.active_context()
            return out

        return _guard(run)

    @mcp.tool(structured_output=True, annotations=_READ_ONLY)
    def sac_status(
        context: str | None = None,
        project_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        """Current shared-context status."""

        def run():
            identity = _identity(actor_email, context or project_id)
            out = impl.status(get_store(), identity)
            out["active_context"] = identity.active_context()
            return out

        return _guard(run)

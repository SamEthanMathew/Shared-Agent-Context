"""SAC domain errors.

These are raised by the store and impl layers and translated to HTTP/MCP
responses at the surface. Keeping them separate from the surfaces lets the
same impl functions serve both REST and MCP without importing FastAPI.
"""
from __future__ import annotations


class SACError(Exception):
    """Base class for all SAC domain errors."""


class ValidationError(SACError):
    """Bad input the caller could fix (maps to HTTP 400/422)."""


class NotFoundError(SACError):
    """A referenced entity does not exist (maps to HTTP 404)."""


class ForbiddenError(SACError):
    """The caller is authenticated but not permitted (maps to HTTP 403).

    The message is intentionally coarse; surfaces must not leak whether the
    entity exists, to preserve project isolation.
    """


class ConflictError(SACError):
    """The request conflicts with current state (maps to HTTP 409)."""


class NeedsContextSelection(SACError):
    """No context could be resolved for this call.

    Carries the caller's available contexts so the surface can return an
    actionable payload — the agent lists the options and asks the user — rather
    than a dead-end error.
    """

    def __init__(self, contexts: list[dict] | None = None) -> None:
        self.contexts = contexts or []
        if self.contexts:
            names = ", ".join(c.get("name", "?") for c in self.contexts)
            message = f"select a context first (available: {names})"
        else:
            message = "no contexts yet — create one to get started"
        super().__init__(message)

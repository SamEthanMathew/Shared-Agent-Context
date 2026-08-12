"""Value objects, controlled vocabularies, and ranking weights for SAC.

This is the single source of truth for the enums used by both the pydantic
request schemas and the MCP tool signatures, so REST and MCP validate `kind`,
`scope`, `sensitivity`, etc. identically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# --- Controlled vocabularies ------------------------------------------------

# Memory kinds an agent may publish. `session_delta` is internal (written by
# sync_context when a client passes local_context_delta) and is not offered as
# a caller-supplied kind.
PUBLISHABLE_KINDS: tuple[str, ...] = (
    "decision",
    "requirement",
    "constraint",
    "finding",
    "result",
    "observation",
    "task",
    "note",
)
INTERNAL_KINDS: tuple[str, ...] = ("session_delta",)
MEMORY_KINDS: frozenset[str] = frozenset(PUBLISHABLE_KINDS + INTERNAL_KINDS)

MemoryKind = Literal[
    "decision",
    "requirement",
    "constraint",
    "finding",
    "result",
    "observation",
    "task",
    "note",
]

SCOPES: frozenset[str] = frozenset({"private", "shared"})
Scope = Literal["private", "shared"]

STATUSES: frozenset[str] = frozenset({"active", "superseded", "retracted"})
Status = Literal["active", "superseded", "retracted"]

RELATION_TYPES: frozenset[str] = frozenset(
    {
        "supersedes",
        "contradicts",
        "supports",
        "derived_from",
        "relates_to",
        "implements",
        "blocks",
    }
)

# Sensitivity ladder (privacy doc §4). `secret` is a valid label in the ladder
# but is rejected at write time in V1 — secrets do not belong in ordinary
# memory (privacy doc §15). It stays in the tuple so ordering/comparison holds.
SENSITIVITIES: tuple[str, ...] = (
    "public",
    "internal",
    "confidential",
    "restricted",
    "secret",
)
WRITABLE_SENSITIVITIES: frozenset[str] = frozenset(SENSITIVITIES[:-1])  # excludes 'secret'
Sensitivity = Literal["public", "internal", "confidential", "restricted"]

ROLES: frozenset[str] = frozenset({"owner", "admin", "member", "viewer"})
Role = Literal["owner", "admin", "member", "viewer"]
# Roles permitted to write project memory (viewer is read-only).
WRITER_ROLES: frozenset[str] = frozenset({"owner", "admin", "member"})

AUTHORITIES: frozenset[str] = frozenset({"owner", "approved", "member", "agent"})

READ_SCOPE = "sac.read"
WRITE_SCOPE = "sac.write"

# --- Ranking weights (deterministic compiler; no embeddings) ----------------

KIND_WEIGHT: dict[str, float] = {
    "decision": 2.5,
    "requirement": 2.2,
    "constraint": 2.2,
    "finding": 1.8,
    "result": 1.7,
    "observation": 1.4,
    "session_delta": 1.2,
    "task": 1.0,
    "note": 1.0,
}

AUTHORITY_WEIGHT: dict[str, float] = {
    "owner": 2.0,
    "approved": 1.8,
    "member": 1.0,
    "agent": 0.6,
}


# --- Record dataclasses -----------------------------------------------------


@dataclass
class MemoryRecord:
    id: str
    project_id: str
    revision: int
    scope: str
    owner_user_id: str | None
    kind: str
    summary: str
    details: str
    tags: list[str]
    status: str
    importance: float
    confidence: float
    authority: str
    sensitivity: str
    version: int
    superseded_by_id: str | None
    created_by_user_id: str
    created_by_agent_id: str | None
    origin_session_id: str | None
    source_event_id: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    created_at: datetime
    updated_at: datetime

    def as_dict(self, include_details: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "revision": self.revision,
            "scope": self.scope,
            "owner_user_id": self.owner_user_id,
            "kind": self.kind,
            "summary": self.summary,
            "tags": self.tags,
            "status": self.status,
            "importance": self.importance,
            "confidence": self.confidence,
            "authority": self.authority,
            "sensitivity": self.sensitivity,
            "version": self.version,
            "superseded_by_id": self.superseded_by_id,
            "provenance": {
                "created_by_user_id": self.created_by_user_id,
                "created_by_agent_id": self.created_by_agent_id,
                "source_event_id": self.source_event_id,
                "created_at": self.created_at.isoformat(),
                "updated_at": self.updated_at.isoformat(),
            },
        }
        if include_details and self.details:
            result["details"] = self.details
        return result


@dataclass
class SessionRecord:
    id: str
    project_id: str
    user_id: str
    agent_connection_id: str
    client_session_ref: str
    last_seen_revision: int
    last_task: str
    created_at: datetime
    last_seen_at: datetime


@dataclass
class EvidenceRecord:
    id: str
    project_id: str
    session_id: str | None
    actor_user_id: str
    actor_agent_id: str | None
    event_type: str
    visibility_scope: str
    owner_user_id: str | None
    content: str
    source_uri: str | None
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "visibility_scope": self.visibility_scope,
            "actor_user_id": self.actor_user_id,
            "actor_agent_id": self.actor_agent_id,
            "content": self.content,
            "source_uri": self.source_uri,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ProjectRecord:
    id: str
    name: str
    description: str
    owner_user_id: str
    context_revision: int
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

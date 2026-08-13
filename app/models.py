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
# Roles permitted to share a context and change other members' access.
SHARER_ROLES: frozenset[str] = frozenset({"owner", "admin"})

# What users see when sharing, mapped onto the roles the engine enforces.
AccessLevel = Literal["view", "edit", "manage"]
ACCESS_TO_ROLE: dict[str, str] = {
    "view": "viewer",
    "edit": "member",
    "manage": "admin",
}
# What "anyone with the link" may be set to. `manage` is absent on purpose: a
# link that grants the right to re-share would propagate access no human chose.
# The same set governs organisation-wide access, for the same reason.
LINK_ACCESS_LEVELS: tuple[str, ...] = ("none", "view", "edit")
LinkAccess = Literal["none", "view", "edit"]

# Roles inside an organisation. Deliberately separate from the per-context roles
# above: administering a group says nothing about what you may read inside any
# particular context in it.
ORG_ROLES: frozenset[str] = frozenset({"owner", "admin", "member"})
OrgRole = Literal["owner", "admin", "member"]
ROLE_TO_ACCESS: dict[str, str] = {
    "viewer": "view",
    "member": "edit",
    "admin": "manage",
    "owner": "owner",
}

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

# How long a memory of each kind keeps half of its clarity, in DAYS of
# wall-clock time. docs/HIGH_QUALITY_CONTEXT_WINDOW_ARCHITECTURE.md:1166 is
# explicit that "Freshness should not be represented by one universal decay
# function", and the reason is visible in this table: a decision and an
# observation written the same afternoon are not equally true a month later.
#
# The ordering comes from the doc's own examples — "an architectural decision
# may remain valid for months", "task ownership may change daily", "deployment
# status may become stale in hours". SAC's kinds are coarser than those
# examples, so the numbers are a first calibration of that ordering rather than
# a translation of it: they are meant to be argued with and edited, which is why
# this is a readable table and not a constant divided by something.
#
# This replaced decay over REVISION DISTANCE, which measured age in other
# people's writes: a decision made in a quiet month stayed pristine while the
# same decision made during a busy week was treated as ancient by Friday. Two
# contexts with identical history and different tempos disagreed about what was
# fresh, which is not a property of the memory at all.
KIND_HALF_LIFE_DAYS: dict[str, float] = {
    # What the project is built on. Still load-bearing months later; a decision
    # that stops being true is normally superseded, not left to rot.
    "decision": 180.0,
    "constraint": 180.0,
    "requirement": 150.0,
    # A finding is evidence about a system that keeps changing underneath it.
    "finding": 90.0,
    # A measurement of one run. Useful for a while, then it is history.
    "result": 60.0,
    "note": 45.0,
    # Work items churn: ownership and status change daily, and a month-old task
    # line is more likely to mislead than to inform.
    "task": 21.0,
    # "the tests are green", "the deploy is running" — true when written and
    # rarely true a fortnight later.
    "observation": 10.0,
    # One agent's working notes at the end of one turn. These exist to be handed
    # to the next turn, and are noise by the following week.
    "session_delta": 3.0,
}
# Anything not in the table above. Deliberately middling: an unknown kind should
# neither be treated as a permanent truth nor thrown away in a week.
DEFAULT_HALF_LIFE_DAYS: float = 45.0

AUTHORITY_WEIGHT: dict[str, float] = {
    "owner": 2.0,
    "approved": 1.8,
    "member": 1.0,
    "agent": 0.6,
}

# KIND_WEIGHT and AUTHORITY_WEIGHT are absolute weights the ranker normalises to
# 0..1 before applying UTILITY_WEIGHT, so the two scales stay independent:
# retuning what a `decision` is worth relative to a `note` must not silently
# change how much kind matters against relevance. (KIND_HALF_LIFE_DAYS is not
# one of them — it is already a rate, and `clarity` below returns 0..1.)
MAX_KIND_WEIGHT: float = max(KIND_WEIGHT.values())
MAX_AUTHORITY_WEIGHT: float = max(AUTHORITY_WEIGHT.values())

# The utility function the compiler ranks by. The terms and their magnitudes are
# taken from docs/DYNAMIC_MODEL_AWARE_CONTEXT_COMPACTION.md §11 "Candidate
# Utility" (~line 695) rather than invented here, so the compiler can be checked
# against the design it came from instead of against somebody's memory of it.
#
# Four of the doc's terms have no honest signal behind them yet and are therefore
# absent rather than faked: `user_pin` maps onto `importance` (the closest thing
# SAC has to a human saying "this one matters"), `graph_dependency` onto
# `structural`, and `stale_probability` / `injection_risk` are handled before
# ranking — superseded and retracted memories are never candidates, and content
# is sanitised at write time.
UTILITY_WEIGHT: dict[str, float] = {
    # doc: semantic_relevance. Lexical here, deliberately — no embeddings.
    "relevance": 2.2,
    # doc: exact_identifier_match. The task's own word, with no synonym hop.
    "exact_match": 1.8,
    # doc: task_entity_match. Matched words close together are one idea.
    "entity_match": 1.5,
    # doc: user_pin, carried by importance.
    "pin": 1.8,
    "authority": 1.7,
    "temporal_validity": 1.4,
    # doc: graph_dependency — what other work hangs off. KIND_WEIGHT stands in:
    # decisions and requirements are what a context is built on.
    "structural": 1.2,
    "recency": 1.0,
    # doc: uncertainty_reduction, carried by the author's stated confidence.
    "uncertainty_reduction": 0.8,
    # doc: redundancy. Negative, and the only term that depends on what has
    # already been selected.
    "redundancy": -1.5,
}

# Where a match landed. The doc has no field-weighting term because it assumes
# whole semantic pages; SAC matches structured rows, so it needs one.
FIELD_WEIGHT: dict[str, float] = {
    # The words the author chose — the summary, or a tag they attached.
    "content": 1.0,
    # Incidental. "decision" matches every decision ever written, so a task that
    # happens to name a kind must not pull the entire kind in ahead of the one
    # memory that is actually about the subject.
    "kind": 0.2,
}


# --- The resolution ladder --------------------------------------------------
#
# Newer information is rendered at as much clarity as the budget allows; as it
# ages it is rendered in less and less detail, and eventually not at all —
# unless something marks it as important, in which case it never fades.
#
# NOTHING HERE DELETES ANYTHING. Every rung below is a decision about how a
# memory is *rendered into one compiled context*. The row is untouched, and
# sac_get_memory returns it in full at any rung, including OMITTED.

FULL = "full"          # summary + details + tags + provenance
SUMMARY = "summary"    # the one-line format
TRACE = "trace"        # kind + a truncated summary
OMITTED = "omitted"    # not rendered — but counted in the snapshot manifest

RESOLUTIONS: tuple[str, ...] = (FULL, SUMMARY, TRACE, OMITTED)

# What a rung is worth relative to the whole memory. Read with `clarity` below:
# a rendering delivers min(fidelity, clarity), because printing the details of a
# stale memory does not make it less stale — the ceiling is the memory, not the
# format. The packer divides that by the rendered length, so which rung wins is
# a real comparison and not a threshold table: a memory with a long summary
# reaches TRACE sooner than a terse one, because truncating it saves more.
RESOLUTION_FIDELITY: dict[str, float] = {
    FULL: 1.0,
    # A summary line is most of what a memory is worth. If it were much less,
    # the compiler would have been broken long before this ladder existed.
    SUMMARY: 0.8,
    # Enough to know the memory exists, what kind of claim it makes, and to ask
    # for it by id. Deliberately a long way below SUMMARY: a truncated line that
    # scored close to a whole one would degrade everything.
    TRACE: 0.25,
    OMITTED: 0.0,
}

# Below this, a memory is not rendered at all. At 12% clarity a trace line is
# mostly a claim that something was once believed, and the budget it costs is
# better spent on a memory that is still true.
CLARITY_OMIT_FLOOR: float = 0.12

# --- What pins a memory at FULL, forever ------------------------------------

# An importance the author had to reach for. remember() defaults to 0.6, so this
# is "someone said this one matters", not "someone used the tool".
IMPORTANCE_PIN: float = 0.8

# Authority levels whose word does not go stale. An owner's decision is the
# project's position on something; a member's note is one person's view of it.
PIN_AUTHORITIES: frozenset[str] = frozenset({"owner"})


def clarity(kind: str, age_days: float) -> float:
    """How much of a memory of ``kind`` is still worth rendering after so long.

    Exponential decay on the kind's half-life: 1.0 when written, 0.5 at one
    half-life, and never quite zero. Age is wall-clock days, which is the point
    — see KIND_HALF_LIFE_DAYS for what this replaced and why.

    Also the ranker's recency term, so "what is still fresh" has exactly one
    definition. Two decay curves would eventually disagree about which memory is
    older, and the ranker would fight the renderer over it.
    """
    half_life = KIND_HALF_LIFE_DAYS.get(kind, DEFAULT_HALF_LIFE_DAYS)
    if half_life <= 0:
        return 0.0
    return 0.5 ** (max(0.0, age_days) / half_life)


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
    # The memory's own words, tokenised once at write time — see
    # app/stores/memories.py:build_search_text. Defaulted so a record built by
    # hand is still a whole record; ranking falls back to deriving it, at the
    # cost this column exists to remove. Never rendered and never returned by
    # as_dict(): it is an index over content, not content.
    search_text: str = ""

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


def pin_reason(
    memory: MemoryRecord, *, referenced: bool = False, repeated: bool = False
) -> str | None:
    """Why this memory is exempt from decay, or None if nothing exempts it.

    Four signals, in the order they are trusted. The first two are the memory's
    own properties; the last two are things the project did, which the memory
    itself cannot claim about itself and is therefore harder to game.

    Returns the reason rather than a bool because the compiled line prints it.
    A model handed a memory at full detail should be able to see *why* it was
    worth the room, and so should whoever is reading the manifest afterwards.
    """
    if memory.importance >= IMPORTANCE_PIN:
        return "importance"
    if memory.authority in PIN_AUTHORITIES:
        return "authority"
    # Something supersedes it, or contradicts it and nobody has settled which is
    # right. Either way the project is still arguing about this memory, and a
    # live argument is not something to summarise away.
    if referenced:
        return "referenced"
    # Revealed preference: the compiler keeps pulling this one in across
    # different tasks, so whatever it says is load-bearing for more than one
    # piece of work. See MemoryStore.repeatedly_included_ids for why the count
    # is over distinct tasks and not over syncs.
    if repeated:
        return "repeated"
    return None


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
    """A shared context. Called a "context" in the user-facing surfaces."""

    id: str
    name: str
    description: str
    owner_user_id: str
    context_revision: int
    slug: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived_at: datetime | None = None
    link_access: str = "none"
    link_token: str | None = None
    # NULL when the context belongs to a person rather than an organisation.
    org_id: str | None = None
    org_access: str = "none"

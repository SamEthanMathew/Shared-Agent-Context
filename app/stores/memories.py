"""The memory engine: writes (with supersession/conflict), permission-filtered
retrieval, deterministic ranking, and the sync change-feed.

The permission boundary is the ``_visible`` WHERE clause, applied before any
ranking — a caller never receives a row they are not authorized to see.
"""
from __future__ import annotations

import math
import re
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, func, literal, literal_column, or_, select, update
from sqlalchemy.engine import Connection, Engine

from ..db import (
    context_snapshots,
    ensure_aware,
    evidence_events,
    memories,
    memory_relations,
    memory_versions,
    utcnow,
)
from ..errors import ForbiddenError, NotFoundError, ValidationError
from ..identity import RequestIdentity
from ..limits import (
    COMPILE_CANDIDATE_LIMIT,
    DETAILS_EXCERPT_CHARS,
    MATCH_CANDIDATE_LIMIT,
    MAX_DETAILS_CHARS,
    MAX_MATCH_TERMS,
    MAX_MEMORIES_PER_CONTEXT,
    MAX_SUMMARY_CHARS,
    MAX_TAG_CHARS,
    MAX_TAGS,
    PIN_DISTINCT_TASKS,
    PIN_SNAPSHOT_WINDOW,
    enforce_quota,
)
from ..models import (
    AUTHORITY_WEIGHT,
    FIELD_WEIGHT,
    KIND_WEIGHT,
    MAX_AUTHORITY_WEIGHT,
    MAX_KIND_WEIGHT,
    MemoryRecord,
    PUBLISHABLE_KINDS,
    UTILITY_WEIGHT,
    WRITABLE_SENSITIVITIES,
    clarity,
)
from .audit import AuditStore
from .projects import ProjectStore

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "into", "about", "your",
    "you", "are", "was", "were", "have", "has", "had", "will", "would", "should",
    "could", "can", "our", "their", "they", "them", "then", "than", "when", "what",
    "which", "where", "while", "how", "why", "who", "use", "using", "used", "make",
    "made", "need", "needs", "work", "working", "project", "context", "shared",
    # Function words of two and three letters. They only became reachable when
    # the minimum token length dropped to two (see _WORD); without them "how do
    # we deploy" would carry "do" and "we" as search terms and match everything.
    "am", "an", "as", "at", "be", "by", "do", "go", "he", "if", "in", "is", "it",
    "me", "my", "no", "of", "on", "or", "so", "to", "up", "us", "we", "did",
    "its", "not", "but", "yet", "too", "all", "any", "own", "per", "her", "him",
    "his", "she", "does", "done", "been", "being", "just", "also", "only",
    "very", "more", "most", "much", "many", "some", "such", "each", "both",
    "over", "under", "after", "before", "between", "again", "here", "there",
    "these", "those", "must", "may", "might", "shall", "uses", "please",
}

# Two characters, not three. "db", "ci", "ui", "ux" and "qa" are precisely the
# words a person types instead of the word the memory was written with, so a
# three-character floor dropped exactly the vocabulary the synonym table exists
# to bridge. The cost is that short function words become tokens, which is what
# the additions to STOPWORDS above pay for.
_WORD = re.compile(r"[a-zA-Z0-9_\-]{2,}")

# Readable, correctable, and inspectable — the deliberate alternative to
# embeddings. Each row is an equivalence class: every member expands to the whole
# group, in both directions, so retrieval never depends on which word the person
# happened to type. Expansion is applied to the TASK at query time and never to a
# stored memory: nothing about a memory's meaning is written to the database.
#
# Adding a row is a small, arguable act with a visible blast radius — that is the
# feature. If a group is wrong, someone can read it and say so, which is not true
# of a vector.
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("db", "dbs", "database", "databases", "postgres", "postgresql", "sql", "rdbms"),
    ("auth", "authn", "authentication", "login", "logins", "signin", "sign-in"),
    ("authz", "authorization", "authorisation", "permission", "permissions", "acl"),
    ("k8s", "kubernetes", "kube"),
    ("deploy", "deploys", "deployment", "deployments", "release", "releases",
     "ship", "shipping", "rollout", "rollouts"),
    ("ci", "cd", "pipeline", "pipelines", "buildsystem"),
    ("infra", "infrastructure", "hosting", "render", "vercel", "aws", "gcp"),
    # "fe" and "be" are deliberately absent from these two: "be" is a verb and
    # "fe" is iron, and a two-letter abbreviation that collides with an ordinary
    # word costs more recall than it buys.
    ("frontend", "ui", "client"),
    ("backend", "server", "api", "apis"),
    ("perf", "performance", "latency", "throughput", "slow", "slowness"),
    ("config", "configuration", "settings", "env", "environment"),
    ("repo", "repository", "codebase"),
    ("docs", "documentation", "readme"),
    ("test", "tests", "testing", "spec", "specs", "pytest"),
    ("bug", "bugs", "defect", "defects", "regression", "regressions"),
    ("cache", "caches", "caching", "redis", "memcached"),
    ("queue", "queues", "worker", "workers", "job", "jobs"),
    ("billing", "payment", "payments", "stripe", "invoice", "invoices",
     "subscription", "subscriptions", "checkout"),
    ("oauth", "sso", "openid", "oidc"),
    ("passkey", "passkeys", "webauthn"),
    ("secret", "secrets", "credential", "credentials", "token", "tokens",
     "apikey", "keypair"),
    ("mcp", "connector", "connectors"),
    ("llm", "gpt", "claude", "anthropic", "openai"),
    ("embedding", "embeddings", "vector", "vectors", "semantic"),
    ("schema", "migration", "migrations", "alembic", "ddl"),
    ("i18n", "internationalisation", "internationalization", "localisation",
     "localization"),
    ("a11y", "accessibility"),
    ("observability", "logging", "logs", "metrics", "tracing", "telemetry"),
    ("security", "vuln", "vulnerability", "vulnerabilities", "cve"),
    ("org", "orgs", "organisation", "organization", "workspace", "tenant"),
    ("ux", "usability"),
    ("ratelimit", "throttle", "throttling", "quota", "quotas"),
    ("qa", "quality", "assurance"),
    ("mem", "memory", "memories", "recall"),
)

# Each word to the union of every group it appears in. Built once, at import.
SYNONYMS: dict[str, frozenset[str]] = {}
for _group in SYNONYM_GROUPS:
    _forms = frozenset(_group)
    for _word in _group:
        SYNONYMS[_word] = SYNONYMS.get(_word, frozenset()) | _forms
del _group, _forms, _word


def ordered_tokens(text: str) -> list[str]:
    """Searchable words in the order written, first occurrence only.

    Order is kept because rank() scores proximity: "token rotation" as two
    adjacent words is one idea, and the same two words eight apart usually are
    not. A set could not tell those apart.
    """
    seen: set[str] = set()
    out: list[str] = []
    for word in _WORD.findall((text or "").lower()):
        if word in STOPWORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


def build_search_text(summary: str, tags: list[str] | str, kind: str) -> str:
    """What a memory is matched on, computed once when it is written.

    Summary, then tags, then kind — the author's own words, filtered and
    de-duplicated, and nothing derived about their meaning. Ranking used to
    rebuild this for every candidate on every sync, which for a full window meant
    ~751 regex passes over as much text as the summaries held.

    Only ever written on insert. Nothing updates a memory's summary, tags or
    kind: supersession and retraction move `status`, and a correction is a new
    memory. If that ever changes, this has to be recomputed there too.
    """
    tag_text = tags.replace(",", " ") if isinstance(tags, str) else " ".join(tags)
    return " ".join(ordered_tokens(f"{summary} {tag_text} {kind}"))


def inflections(term: str) -> set[str]:
    """A task word and its singular/plural twin.

    Postgres stems, so "decisions" finds a memory that says "decision" there.
    SQLite does not, and the Python ranker does not either — which meant the two
    dialects disagreed about what matched, and that ranking never credited a
    plural at all. English is irregular, but these three rules cover nearly all
    of the mismatch that actually occurs, and a rule someone can read and predict
    beats a stemmer nobody can inspect. Forms that are not words simply never
    match anything, so a wrong guess costs one comparison and no accuracy.

    Applied to the task only, like every other expansion here.
    """
    if len(term) > 4 and term.endswith("ies"):
        return {term, term[:-3] + "y"}
    if len(term) > 4 and term.endswith("es"):
        return {term, term[:-2], term[:-1]}
    if len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        return {term, term[:-1]}
    return {term, term + "s"}


def task_concepts(task: str) -> list[tuple[frozenset[str], frozenset[str]]]:
    """The task as ideas rather than words: (words typed, words that count).

    Task words that share any surface form are one idea, not two, so they are
    merged — otherwise "invoices and billing" would count a memory about billing
    as answering twice as much of the task as it does. Merging on overlap rather
    than on equality is what makes that hold once inflection is in play, since
    "invoices" and "billing" reach the same group by different routes.
    """
    concepts: list[tuple[set[str], set[str]]] = []
    for term in ordered_tokens(task):
        forms: set[str] = set()
        for variant in inflections(term):
            forms |= SYNONYMS.get(variant, frozenset({variant}))
        for typed, existing in concepts:
            if existing & forms:
                typed.add(term)
                existing |= forms
                break
        else:
            concepts.append(({term}, forms))
    return [(frozenset(typed), frozenset(forms)) for typed, forms in concepts]


def search_terms(concepts: list[tuple[frozenset[str], frozenset[str]]]) -> list[str]:
    """Flat term list for the SQL match channel, literals before expansions.

    The order matters only because the list is capped: what gets dropped when a
    task expands past MAX_MATCH_TERMS should be the least direct thing in it.
    """
    literals: list[str] = []
    expansions: list[str] = []
    seen: set[str] = set()
    for typed, forms in concepts:
        for term in sorted(typed):
            if term not in seen:
                seen.add(term)
                literals.append(term)
        for term in sorted(forms - typed):
            if term not in seen:
                seen.add(term)
                expansions.append(term)
    return (literals + expansions)[:MAX_MATCH_TERMS]


def merge_candidates(*groups: Iterable[MemoryRecord]) -> list[MemoryRecord]:
    """Union the retrieval channels, one row per memory, first occurrence wins.

    The channels overlap heavily — a recent memory that also matches the task is
    in two of them — and a duplicate would be scored twice and could be rendered
    twice.
    """
    seen: set[str] = set()
    out: list[MemoryRecord] = []
    for group in groups:
        for memory in group:
            if memory.id in seen:
                continue
            seen.add(memory.id)
            out.append(memory)
    return out


def age_days(memory: MemoryRecord, now) -> float:
    """How old a memory is, in wall-clock days, never negative.

    A clock skewed forward on the writing machine would otherwise hand a memory
    a negative age and, through `clarity`, more than full freshness — a memory
    that outranks everything by claiming to be from next week.
    """
    written = ensure_aware(memory.created_at)
    if written is None:
        return 0.0
    return max(0.0, (now - written).total_seconds() / 86_400.0)


# How far apart two matched words may be and still count as one idea.
PROXIMITY_WINDOW = 3

# The redundancy pass runs over this multiple of the requested limit, so asking
# for 50 compares 100 rows. It bounds work rather than expressing policy: the
# pass is O(limit x pool) and that product is the whole of its cost, which is
# fixed per sync and does not grow with the size of the context. Two leaves one
# spare row per slot — ample, since displacing a duplicate needs one replacement,
# not fifty — and measured about a third cheaper than three with no change to
# what came out on the labelled set.
REDUNDANCY_POOL_FACTOR = 2


# Control characters, including newlines. Memory content is rendered into a
# line-oriented context format, so a stored newline would let one member forge
# the compiler's own section headers inside another member's prompt.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")


def sanitize_line(value: str, limit: int) -> str:
    """Collapse a value to a single safe line and cap its length."""
    cleaned = _CONTROL_CHARS.sub(" ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def sanitize_block(value: str, limit: int) -> str:
    """Keep newlines (details are never inlined) but drop other control chars."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f  ]", " ", value or "")
    cleaned = cleaned.strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _row_to_memory(m) -> MemoryRecord:
    return MemoryRecord(
        id=m["id"],
        project_id=m["project_id"],
        revision=int(m["revision"]),
        scope=m["scope"],
        owner_user_id=m["owner_user_id"],
        kind=m["kind"],
        summary=m["summary"],
        # Absent on the compile path, which selects every column but this one —
        # see _COLS_WITHOUT_DETAILS. Defaulting to "" keeps the dataclass whole;
        # a caller that actually wants a body asks for that memory by id.
        details=m.get("details") or "",
        tags=[t for t in (m["tags"] or "").split(",") if t],
        status=m["status"],
        importance=float(m["importance"]),
        confidence=float(m["confidence"]),
        authority=m["authority"],
        sensitivity=m["sensitivity"],
        version=int(m["version"]),
        superseded_by_id=m["superseded_by_id"],
        created_by_user_id=m["created_by_user_id"],
        created_by_agent_id=m["created_by_agent_id"],
        origin_session_id=m["origin_session_id"],
        source_event_id=m["source_event_id"],
        valid_from=m["valid_from"],
        valid_until=m["valid_until"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
        # Empty for a row written before migration 0008 backfilled it; rank()
        # derives it instead, so an un-migrated database ranks correctly rather
        # than ranking nothing.
        search_text=m.get("search_text") or "",
    )


# Every memory column except `details`. A body is capped at MAX_DETAILS_CHARS
# (20,000), so selecting it for a full candidate window shipped as much as 15 MB
# per sync that nothing on that path reads: rank() deliberately excludes details
# and the compiled line renders only the summary. Derived from the table rather
# than spelled out so a new column is carried automatically — the exclusion is
# the intent, not the list.
_COLS_WITHOUT_DETAILS = [c for c in memories.c if c.name != "details"]


def _visible(project_id: str, user_id: str):
    """Permission predicate: shared, or the caller's own private memory."""
    return and_(
        memories.c.project_id == project_id,
        or_(
            memories.c.scope == "shared",
            and_(
                memories.c.scope == "private",
                memories.c.owner_user_id == user_id,
            ),
        ),
    )


class MemoryStore:
    def __init__(
        self, engine: Engine, projects: ProjectStore, audit: AuditStore
    ) -> None:
        self.engine = engine
        self.projects = projects
        self.audit = audit

    # --- write path ---------------------------------------------------------

    def remember(
        self,
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
        session_id: str | None = None,
        *,
        internal_kind: bool = False,
    ) -> dict[str, Any]:
        # Sanitize before storing: memory content is attacker-influenced (any
        # member can publish) and is rendered into a line-oriented context
        # format read by other members' agents.
        summary = sanitize_line(summary, MAX_SUMMARY_CHARS)
        details = sanitize_block(details, MAX_DETAILS_CHARS)
        if not summary:
            raise ValidationError("summary must not be empty")
        if scope not in ("private", "shared"):
            raise ValidationError(f"invalid scope: {scope}")
        kind = (kind or "note").strip().lower()
        if not internal_kind and kind not in PUBLISHABLE_KINDS:
            raise ValidationError(f"invalid kind: {kind}")
        sensitivity = (sensitivity or "internal").strip().lower()
        if sensitivity not in WRITABLE_SENSITIVITIES:
            raise ValidationError(
                f"sensitivity must be one of {sorted(WRITABLE_SENSITIVITIES)}; "
                "secrets do not belong in memory"
            )

        identity.require_writer()
        self._enforce_context_quota(identity)

        owner_user_id = identity.user_id if scope == "private" else None
        importance = max(0.0, min(float(importance), 1.0))
        confidence = max(0.0, min(float(confidence), 1.0))
        authority = "owner" if identity.role in ("owner", "admin") else "member"
        # Tags are CSV-joined, so a comma inside one would fragment it.
        tags = [
            sanitize_line(str(t), MAX_TAG_CHARS).replace(",", " ")
            for t in (tags or [])
        ]
        tags = [t for t in tags if t][:MAX_TAGS]
        supersedes = list(supersedes or [])
        contradicts = list(contradicts or [])
        project_id = identity.project_id
        now = utcnow()
        memory_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        # Built from the sanitized values, so what is searchable is exactly what
        # is renderable — a memory can never be found by words it does not show.
        search_text = build_search_text(summary, tags, kind)

        with self.engine.begin() as conn:
            conn.execute(
                evidence_events.insert().values(
                    id=event_id,
                    project_id=project_id,
                    session_id=session_id,
                    actor_user_id=identity.user_id,
                    actor_agent_id=identity.agent_connection_id,
                    event_type="explicit_memory_write",
                    visibility_scope=scope,
                    owner_user_id=owner_user_id,
                    content=(summary + ("\n\n" + details if details else "")),
                    source_uri=None,
                    created_at=now,
                )
            )
            revision = self.projects.next_revision(conn, project_id)
            conn.execute(
                memories.insert().values(
                    id=memory_id,
                    project_id=project_id,
                    revision=revision,
                    scope=scope,
                    owner_user_id=owner_user_id,
                    kind=kind,
                    summary=summary,
                    details=details,
                    tags=",".join(tags),
                    search_text=search_text,
                    status="active",
                    importance=importance,
                    confidence=confidence,
                    authority=authority,
                    sensitivity=sensitivity,
                    valid_from=None,
                    valid_until=None,
                    version=1,
                    superseded_by_id=None,
                    created_by_user_id=identity.user_id,
                    created_by_agent_id=identity.agent_connection_id,
                    origin_session_id=session_id,
                    source_event_id=event_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._insert_version(conn, memory_id, 1, kind, summary, details, tags,
                                  "active", event_id, identity, now)

            superseded_ids = self._apply_supersedes(
                conn, identity, memory_id, supersedes, now
            )
            conflict_ids = self._apply_contradicts(
                conn, identity, memory_id, contradicts, now
            )

            self.audit.emit(
                "memory.create", "memory", memory_id, project_id=project_id,
                actor_user_id=identity.user_id,
                actor_agent_id=identity.agent_connection_id,
                meta={"scope": scope, "kind": kind, "revision": revision},
                conn=conn,
            )

        # Built from the values just written rather than selected back: the row
        # is entirely known to this frame, so re-reading it could only confirm
        # what we already have, at the cost of a round trip inside the write
        # transaction. Keep this in step with the insert above.
        record = MemoryRecord(
            id=memory_id,
            project_id=project_id,
            revision=revision,
            scope=scope,
            owner_user_id=owner_user_id,
            kind=kind,
            summary=summary,
            details=details,
            tags=tags,
            status="active",
            importance=importance,
            confidence=confidence,
            authority=authority,
            sensitivity=sensitivity,
            version=1,
            superseded_by_id=None,
            created_by_user_id=identity.user_id,
            created_by_agent_id=identity.agent_connection_id,
            origin_session_id=session_id,
            source_event_id=event_id,
            valid_from=None,
            valid_until=None,
            created_at=now,
            updated_at=now,
            search_text=search_text,
        )
        return {
            "revision": revision,
            "memory": record,
            "superseded": superseded_ids,
            "conflicts_opened": conflict_ids,
        }

    def _insert_version(
        self, conn, memory_id, version, kind, summary, details, tags, status,
        event_id, identity, now,
    ) -> None:
        conn.execute(
            memory_versions.insert().values(
                id=str(uuid.uuid4()),
                memory_id=memory_id,
                version=version,
                kind=kind,
                summary=summary,
                details=details,
                tags=",".join(tags) if isinstance(tags, list) else (tags or ""),
                status=status,
                source_event_id=event_id,
                created_by_user_id=identity.user_id,
                created_by_agent_id=identity.agent_connection_id,
                created_at=now,
            )
        )

    def _load_writable_target(
        self, conn: Connection, identity: RequestIdentity, target_id: str
    ):
        row = conn.execute(
            select(memories).where(
                memories.c.id == target_id,
                memories.c.project_id == identity.project_id,
            )
        ).first()
        if row is None:
            raise NotFoundError("target memory not found")
        m = row._mapping
        if m["scope"] == "private" and m["owner_user_id"] != identity.user_id:
            raise ForbiddenError("cannot modify another user's private memory")
        return m

    def _apply_supersedes(
        self, conn, identity, new_id, supersedes, now
    ) -> list[str]:
        done: list[str] = []
        for target_id in supersedes:
            m = self._load_writable_target(conn, identity, target_id)
            if m["status"] != "active":
                continue  # already superseded/retracted; no-op flip
            new_version = int(m["version"]) + 1
            conn.execute(
                update(memories)
                .where(memories.c.id == target_id)
                .values(
                    status="superseded",
                    superseded_by_id=new_id,
                    version=new_version,
                    updated_at=now,
                )
            )
            self._insert_version(
                conn, target_id, new_version, m["kind"], m["summary"],
                m["details"] or "", m["tags"] or "", "superseded",
                m["source_event_id"], identity, now,
            )
            conn.execute(
                memory_relations.insert().values(
                    id=str(uuid.uuid4()),
                    project_id=identity.project_id,
                    from_memory_id=new_id,
                    to_memory_id=target_id,
                    relation_type="supersedes",
                    created_by_user_id=identity.user_id,
                    created_at=now,
                )
            )
            self.audit.emit(
                "memory.supersede", "memory", target_id,
                project_id=identity.project_id, actor_user_id=identity.user_id,
                actor_agent_id=identity.agent_connection_id,
                meta={"superseded_by": new_id}, conn=conn,
            )
            done.append(target_id)
        return done

    def _apply_contradicts(
        self, conn, identity, new_id, contradicts, now
    ) -> list[str]:
        done: list[str] = []
        for target_id in contradicts:
            self._load_writable_target(conn, identity, target_id)
            conn.execute(
                memory_relations.insert().values(
                    id=str(uuid.uuid4()),
                    project_id=identity.project_id,
                    from_memory_id=new_id,
                    to_memory_id=target_id,
                    relation_type="contradicts",
                    created_by_user_id=identity.user_id,
                    resolved_at=None,
                    created_at=now,
                )
            )
            self.audit.emit(
                "memory.contradict", "memory", target_id,
                project_id=identity.project_id, actor_user_id=identity.user_id,
                actor_agent_id=identity.agent_connection_id,
                meta={"contradicts_with": new_id}, conn=conn,
            )
            done.append(target_id)
        return done

    # --- read path ----------------------------------------------------------

    def retract(
        self, identity: RequestIdentity, memory_id: str
    ) -> MemoryRecord:
        """Human correction: mark a memory retracted so it leaves active context.

        Retained (not deleted) for provenance. Writer role required; a private
        memory may only be retracted by its owner.
        """
        identity.require_writer()
        now = utcnow()
        with self.engine.begin() as conn:
            m = self._load_writable_target(conn, identity, memory_id)
            if m["status"] == "retracted":
                return _row_to_memory(m)
            new_version = int(m["version"]) + 1
            conn.execute(
                update(memories)
                .where(memories.c.id == memory_id)
                .values(status="retracted", version=new_version, updated_at=now)
            )
            self._insert_version(
                conn, memory_id, new_version, m["kind"], m["summary"],
                m["details"] or "", m["tags"] or "", "retracted",
                m["source_event_id"], identity, now,
            )
            self.audit.emit(
                "memory.retract", "memory", memory_id,
                project_id=identity.project_id, actor_user_id=identity.user_id,
                actor_agent_id=identity.agent_connection_id, conn=conn,
            )
            row = conn.execute(
                select(memories).where(memories.c.id == memory_id)
            ).first()
        return _row_to_memory(row._mapping)

    def get_memory(
        self, project_id: str, memory_id: str, user_id: str
    ) -> MemoryRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(memories).where(
                    memories.c.id == memory_id,
                    _visible(project_id, user_id),
                )
            ).first()
        return _row_to_memory(row._mapping) if row else None

    def list_memories(
        self,
        project_id: str,
        user_id: str,
        scope: str | None = None,
        status: str | None = "active",
        kind: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        clauses = [_visible(project_id, user_id)]
        if scope:
            clauses.append(memories.c.scope == scope)
        if status:
            clauses.append(memories.c.status == status)
        if kind:
            clauses.append(memories.c.kind == kind)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(memories)
                .where(*clauses)
                .order_by(memories.c.revision.desc())
                .limit(max(1, min(int(limit), 500)))
            ).all()
        return [_row_to_memory(r._mapping) for r in rows]

    def _live(self, project_id: str, user_id: str, now) -> list[Any]:
        """The predicate every retrieval channel must carry, in one place.

        ``_visible`` is the permission boundary; the other two are what "live"
        means. A new channel that reproduced two of the three would be a way to
        read retracted memory, or another member's private memory, by searching
        for a word in it.
        """
        return [
            _visible(project_id, user_id),
            memories.c.status == "active",
            or_(memories.c.valid_until.is_(None), memories.c.valid_until > now),
        ]

    def compile_candidates(
        self, project_id: str, user_id: str, candidate_limit: int | None = None
    ) -> list[MemoryRecord]:
        """Channel (b): the most recent live memories, whatever the task is.

        Recent work matters regardless of wording — an agent syncing mid-task
        needs what just happened even when it shares no vocabulary with the task
        it was given. This was once the *only* channel, which is what made a
        relevant-but-old memory unreachable; see candidate_set.
        """
        cap = COMPILE_CANDIDATE_LIMIT if candidate_limit is None else int(candidate_limit)
        now = utcnow()
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(*_COLS_WITHOUT_DETAILS)
                .where(*self._live(project_id, user_id, now))
                .order_by(memories.c.revision.desc())
                .limit(max(1, min(cap, 2000)))
            ).all()
        return [_row_to_memory(r._mapping) for r in rows]

    def match_candidates(
        self,
        project_id: str,
        user_id: str,
        task: str,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        """Channel (a): memories whose own words answer the task, at any age.

        SECURITY: this is a new way to reach rows, and the most effective probe
        anyone could build — it finds memories *by* their words. It therefore
        carries exactly the same predicate as every other read path, via
        ``_live``. Dropping the visibility clause here would let any member read
        any other member's private memory by guessing a word in it.

        Two implementations, one meaning:

        * Postgres gets a real full-text search. ``to_tsvector('english', ...)``
          stems, so "databases" matches "database", and the GIN expression index
          from migration 0008 covers this exact expression. ``websearch_to_
          tsquery`` is used rather than ``to_tsquery`` because the task is
          caller-supplied text and websearch syntax cannot be made to raise.
        * SQLite — the test and local-dev database — has no tsvector, so it
          scans ``search_text`` for whole tokens. No stemming, so the synonym
          table carries more of the load there; the plural forms in
          SYNONYM_GROUPS are what keep the two dialects close in practice. A
          scan is acceptable precisely because SQLite is never production.
        """
        terms = search_terms(task_concepts(task))
        if not terms:
            # A task of nothing but stopwords must ask the database nothing,
            # rather than fall through to a predicate that matches everything.
            return []
        cap = MATCH_CANDIDATE_LIMIT if limit is None else int(limit)
        cap = max(1, min(cap, 2000))
        now = utcnow()

        with self.engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                config = literal_column("'english'")
                document = func.to_tsvector(config, memories.c.search_text)
                query = func.websearch_to_tsquery(config, " OR ".join(terms))
                stmt = (
                    select(*_COLS_WITHOUT_DETAILS)
                    .where(*self._live(project_id, user_id, now), document.op("@@")(query))
                    # Only decides which rows survive the cap — rank() re-scores
                    # them all afterwards with the signals Postgres cannot see.
                    .order_by(func.ts_rank(document, query).desc(), memories.c.revision.desc())
                    .limit(cap)
                )
            else:
                # Padded on both sides so " db " cannot match "sqlite-db-name".
                padded = literal(" ") + memories.c.search_text + literal(" ")
                stmt = (
                    select(*_COLS_WITHOUT_DETAILS)
                    .where(
                        *self._live(project_id, user_id, now),
                        or_(
                            *[
                                # `_` is a single-character LIKE wildcard and
                                # tokens may contain it, so it is escaped: a
                                # search term is data, never pattern syntax.
                                padded.like(
                                    "% " + t.replace("\\", "\\\\")
                                    .replace("%", "\\%")
                                    .replace("_", "\\_") + " %",
                                    escape="\\",
                                )
                                for t in terms
                            ]
                        ),
                    )
                    .order_by(memories.c.revision.desc())
                    .limit(cap)
                )
            rows = conn.execute(stmt).all()
        return [_row_to_memory(r._mapping) for r in rows]

    def candidate_set(
        self,
        project_id: str,
        user_id: str,
        task: str = "",
        extra: Iterable[MemoryRecord] | None = None,
        candidate_limit: int | None = None,
        match_limit: int | None = None,
    ) -> tuple[list[MemoryRecord], bool]:
        """Everything one sync may rank: the union of the three channels.

        (a) what matches the task, (b) what happened recently, (c) whatever the
        caller already knows is relevant — in practice the change feed, which the
        compiler has already loaded, so the third channel costs no query at all.

        Returns ``(candidates, recency_window_full)``. The flag is about channel
        (b) alone and keeps its old meaning: this context holds more live memory
        than one sync's recency window. It is no longer a hard recall ceiling,
        because (a) reaches past the window — but it is still worth reporting,
        since only memories the task's words can find come back from out there.
        """
        matched = self.match_candidates(project_id, user_id, task, limit=match_limit)
        recent = self.compile_candidates(
            project_id, user_id, candidate_limit=candidate_limit
        )
        cap = COMPILE_CANDIDATE_LIMIT if candidate_limit is None else int(candidate_limit)
        return merge_candidates(matched, recent, extra or []), len(recent) >= cap

    def rank(
        self, candidates: list[MemoryRecord], task: str, limit: int = 50
    ) -> list[MemoryRecord]:
        """The ranked memories alone, for callers with nothing to spend."""
        return [m for m, _score in self.rank_scored(candidates, task, limit)]

    def rank_scored(
        self,
        candidates: list[MemoryRecord],
        task: str,
        limit: int = 50,
        stats: dict[str, int] | None = None,
    ) -> list[tuple[MemoryRecord, float]]:
        """Score candidates against the task and return the best, least-redundant.

        The weights and the shape of the sum come from
        docs/DYNAMIC_MODEL_AWARE_CONTEXT_COMPACTION.md §11 "Candidate Utility"
        (~line 695) — see models.UTILITY_WEIGHT for the term-by-term mapping.

        The three match terms are IDF-weighted *sums* over matched ideas rather
        than fractions of the task, which is the one place this departs from a
        literal reading of the doc. The doc's `semantic_relevance` is an
        embedding cosine, where even an unrelated item scores mid-range; a
        lexical match is a real 0. Capped at 2.2, relevance would lose to the
        terms that are always present — authority, recency and importance sum to
        more than that — and an irrelevant but recent, important, owner-authored
        decision would outrank the memory that answers the task exactly. That is
        the failure this whole change exists to remove, so the match terms are
        left unbounded, as the `overlap` term they replace also was.

        The score comes back with each memory because the compiler spends it:
        what a memory is worth, divided by the characters it costs to render, is
        how the packer chooses both the order of admission and the rung of the
        resolution ladder to render it at.

        ``stats`` is an optional dict this fills in on the way past, for the
        compiler's manifest. An out-parameter rather than a third return value
        because every caller wants the pairs and nothing else, and the one that
        wants the arithmetic wants it only to explain itself afterwards.
        """
        if not candidates:
            return []
        concepts = task_concepts(task)
        now = utcnow()

        sequences: list[list[str]] = []
        token_sets: list[set[str]] = []
        for m in candidates:
            if m.search_text:
                sequence = m.search_text.split()
            else:
                # Written before migration 0008, or built by hand. Correct, at
                # exactly the cost precomputation exists to remove.
                sequence = ordered_tokens(f"{m.summary} {' '.join(m.tags)} {m.kind}")
            sequences.append(sequence)
            token_sets.append(set(sequence))

        # Rare words say more than common ones: in a context where every memory
        # mentions the release, "release" separates nothing and "soak" separates
        # everything. Document frequency is counted over the candidates in hand,
        # so nothing about the corpus is stored and the number is reproducible
        # from the same inputs.
        total = len(candidates)
        idf = [
            math.log(1.0 + total / (1.0 + sum(1 for s in token_sets if s & forms)))
            for _typed, forms in concepts
        ]

        scored: list[tuple[float, float, int, MemoryRecord]] = []
        for i, m in enumerate(candidates):
            tokens = token_sets[i]
            relevance = exact = 0.0
            hit_at: list[int] = []
            for j, (typed, forms) in enumerate(concepts):
                hit = forms & tokens
                if not hit:
                    continue
                # A memory whose only matching word is its own kind matched the
                # question's grammar, not its subject. search_text is
                # de-duplicated, so a summary that repeats its kind is read as
                # the weaker case — deliberately, since it costs nothing when
                # any other word also matches.
                weight = FIELD_WEIGHT["kind" if hit == {m.kind} else "content"]
                relevance += idf[j] * weight
                # Same discount applies to the exact term. Otherwise "what
                # decisions did we make about auth" would hand every decision in
                # the context the full exact-match bonus for being a decision,
                # which is precisely the incidental hit the field weight is for.
                if typed & tokens:
                    exact += idf[j] * weight
                hit_at.append(j)

            entity = 0.0
            if len(hit_at) > 1:
                # Only worth building for a memory that matched more than one
                # idea, which is a small minority of any candidate window.
                position = {t: k for k, t in enumerate(sequences[i])}
                found = sorted(
                    min(position[t] for t in (concepts[j][1] & tokens)) for j in hit_at
                )
                for left, right in zip(found, found[1:]):
                    gap = right - left
                    # A gap of zero means one word satisfied two concepts, which
                    # happens where synonym groups overlap. That is one word, not
                    # two words near each other, so it earns nothing here.
                    if 0 < gap <= PROXIMITY_WINDOW:
                        entity += (PROXIMITY_WINDOW + 1 - gap) / PROXIMITY_WINDOW

            valid = 1.0
            if m.valid_from and ensure_aware(m.valid_from) > now:
                valid = 0.0
            if m.valid_until and ensure_aware(m.valid_until) <= now:
                valid = 0.0

            match = (
                UTILITY_WEIGHT["relevance"] * relevance
                + UTILITY_WEIGHT["exact_match"] * exact
                + UTILITY_WEIGHT["entity_match"] * entity
            )
            score = match + (
                UTILITY_WEIGHT["pin"] * m.importance
                + UTILITY_WEIGHT["authority"]
                * (AUTHORITY_WEIGHT.get(m.authority, 1.0) / MAX_AUTHORITY_WEIGHT)
                + UTILITY_WEIGHT["temporal_validity"] * valid
                + UTILITY_WEIGHT["structural"]
                * (KIND_WEIGHT.get(m.kind, 1.0) / MAX_KIND_WEIGHT)
                # Wall-clock age against this kind's half-life. It used to be
                # exp(-(newest_revision - m.revision) / 80): a memory aged by
                # how much everyone else had written since, on one curve for
                # every kind. A decision went stale in a busy fortnight while a
                # week-old "the tests are green" stayed pristine in a quiet one.
                + UTILITY_WEIGHT["recency"] * clarity(m.kind, age_days(m, now))
                + UTILITY_WEIGHT["uncertainty_reduction"] * m.confidence
            )
            scored.append((score, match, i, m))

        # id breaks the last tie, so the order is a function of the inputs alone.
        # The compiler admits ranked items until the budget runs out, so a
        # non-deterministic order would stop a small budget's contents from being
        # a prefix of a large one's.
        scored.sort(key=lambda p: (p[0], p[3].revision, p[3].id), reverse=True)
        cap = max(1, min(int(limit), 200))
        return self._select_diverse(scored, token_sets, cap, stats)

    @staticmethod
    def _select_diverse(
        scored: list[tuple[float, float, int, MemoryRecord]],
        token_sets: list[set[str]],
        cap: int,
        stats: dict[str, int] | None = None,
    ) -> list[tuple[MemoryRecord, float]]:
        """Take the best `cap`, penalising each for repeating what is already in.

        There was no redundancy term at all, so the most relevant fact in a
        context could take every slot simply by having been written five times —
        which is what a chatty agent does. A near-duplicate's *novelty* is what
        it loses: the penalty scales with the relevance it is duplicating, so the
        second copy of the answer is worth little while a second copy of
        something irrelevant is penalised only by the doc's flat -1.5, which is
        all it was ever worth.

        Jaccard over token sets is a conservative duplicate detector — two
        memories about one subject in different words share almost nothing — so
        it bites on repetition rather than on topic.
        """
        pool = scored[: max(cap * REDUNDANCY_POOL_FACTOR, 60)]
        sets = [token_sets[p[2]] for p in pool]
        sizes = [len(s) for s in sets]
        similarity = [0.0] * len(pool)
        taken = [False] * len(pool)

        # token -> the pool entries containing it. Two memories with no word in
        # common cannot be duplicates of each other, so this is what keeps the
        # pass from comparing every candidate against every selection: in a
        # context of genuinely different memories almost every pair is skipped,
        # and the pairs that are not are the ones worth looking at.
        postings: dict[str, list[int]] = {}
        for k, tokens in enumerate(sets):
            for token in tokens:
                postings.setdefault(token, []).append(k)

        penalty = UTILITY_WEIGHT["redundancy"]
        chosen: list[tuple[MemoryRecord, float]] = []
        for _ in range(min(cap, len(pool))):
            best = -1
            best_score = 0.0
            for k in range(len(pool)):
                if taken[k]:
                    continue
                base = pool[k][0]
                # The pool is in descending score order and the penalty only ever
                # subtracts, so `base` is an upper bound on every adjusted score
                # from here down. Once the best already found reaches it, nothing
                # left can overtake — and since most rows are nobody's duplicate
                # and carry no penalty at all, this usually settles on the first
                # untaken row instead of walking the pool.
                if best >= 0 and best_score >= base:
                    break
                # penalty is negative, so this subtracts. Scaling by the match it
                # is duplicating means the second copy of the answer loses the
                # relevance that made it an answer, while a repeat of something
                # irrelevant loses only the doc's flat -1.5.
                adjusted = base + penalty * similarity[k] * (1.0 + pool[k][1])
                if best < 0 or adjusted > best_score:
                    best, best_score = k, adjusted
            taken[best] = True
            # The score handed on is the one selection was made with — the
            # redundancy penalty included, floored at zero. A near-duplicate is
            # worth less to render as well as less to choose, and a negative
            # value per token would sort a memory below not rendering it at all,
            # which is a decision the omit floor makes and this pass does not.
            chosen.append((pool[best][3], max(0.0, best_score)))

            # Update against what was just taken only: the running maximum is
            # all the next round needs, and re-comparing against every chosen
            # item each round would make this quadratic in the budget.
            picked = sets[best]
            picked_size = sizes[best]
            touched: set[int] = set()
            for token in picked:
                touched.update(postings.get(token, ()))
            for k in touched:
                if taken[k]:
                    continue
                shared = len(sets[k] & picked)
                overlap = shared / (sizes[k] + picked_size - shared)
                if overlap > similarity[k]:
                    similarity[k] = overlap

        if stats is not None:
            # What the redundancy term actually cost, for the manifest: a memory
            # that scored above the weakest selection on merit, and still lost
            # its place to something already saying what it says. Counting every
            # unselected row instead would report the size of the pool, which is
            # a fact about the cap and not about redundancy at all.
            weakest = min(
                (p[0] for k, p in enumerate(pool) if taken[k]), default=0.0
            )
            stats["redundant"] = sum(
                1
                for k, p in enumerate(pool)
                if not taken[k] and similarity[k] > 0.0 and p[0] > weakest
            )
        return chosen

    # --- resolution-ladder lookups ------------------------------------------

    def referenced_ids(
        self, project_id: str, memory_ids: Iterable[str]
    ) -> set[str]:
        """Which of these memories a live supersedes/contradicts relation names.

        Pins them at full detail: the project is still arguing about them, and an
        argument summarised down to two half-lines is one the reader cannot
        follow. See models.pin_reason.

        A *superseded* memory is already excluded from every retrieval channel by
        status, so in practice what this finds on the supersedes side is the
        memory doing the superseding — the correction, which is exactly the one
        worth reading in full. Contradictions are counted only while unresolved:
        once someone has said which side won, the row is history.

        Returns only ids that were passed in, so this can never introduce the id
        of a memory the caller could not already see.
        """
        ids = list(dict.fromkeys(memory_ids))
        if not ids:
            return set()
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    memory_relations.c.from_memory_id,
                    memory_relations.c.to_memory_id,
                ).where(
                    memory_relations.c.project_id == project_id,
                    or_(
                        memory_relations.c.relation_type == "supersedes",
                        and_(
                            memory_relations.c.relation_type == "contradicts",
                            memory_relations.c.resolved_at.is_(None),
                        ),
                    ),
                    or_(
                        memory_relations.c.from_memory_id.in_(ids),
                        memory_relations.c.to_memory_id.in_(ids),
                    ),
                )
            ).all()
        wanted = set(ids)
        return {
            memory_id
            for r in rows
            for memory_id in (r.from_memory_id, r.to_memory_id)
            if memory_id in wanted
        }

    def repeatedly_included_ids(
        self,
        project_id: str,
        memory_ids: Iterable[str],
        window: int = PIN_SNAPSHOT_WINDOW,
        distinct_tasks: int = PIN_DISTINCT_TASKS,
    ) -> set[str]:
        """Which of these the compiler keeps needing, whatever the work is.

        Revealed preference, from the manifests the compiler already writes: a
        memory the context keeps pulling in is important whether or not anyone
        remembered to say so.

        The threshold is DISTINCT TASKS, not syncs, and that is the whole of the
        idea. Syncs would make this meaningless — sac_sync_context runs at the
        start of every agent turn, so three appearances is what any live memory
        gets before lunch, and everything would end up pinned. Being pulled in
        for three *different* pieces of work is a claim about the memory rather
        than about how chatty one session was.

        Reads every member's manifests, not just the caller's, because "the
        project keeps needing this" is a fact about the project. Nothing crosses
        the permission boundary: the result is intersected with the ids the
        caller already holds, so another member's private memory can neither be
        returned nor detected here.
        """
        ids = set(memory_ids)
        if not ids:
            return set()
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(context_snapshots.c.task, context_snapshots.c.included)
                .where(context_snapshots.c.project_id == project_id)
                .order_by(context_snapshots.c.created_at.desc())
                .limit(max(1, min(int(window), 100)))
            ).all()

        tasks_by_memory: dict[str, set[str]] = {}
        for row in rows:
            task = (row.task or "").strip().lower()
            if not task:
                # A sync with no stated task says nothing about what the project
                # keeps needing — it included whatever was recent.
                continue
            for entry in row.included or []:
                memory_id = entry.get("memory_id")
                if memory_id in ids:
                    tasks_by_memory.setdefault(memory_id, set()).add(task)
        return {
            memory_id
            for memory_id, tasks in tasks_by_memory.items()
            if len(tasks) >= distinct_tasks
        }

    def details_excerpts(
        self,
        project_id: str,
        user_id: str,
        memory_ids: Iterable[str],
        chars: int = DETAILS_EXCERPT_CHARS,
    ) -> dict[str, str]:
        """The first ``chars`` of each body, for the memories rendered in full.

        The compile path deliberately never selects `details` (see
        _COLS_WITHOUT_DETAILS) because a body is capped at 20,000 characters and
        a full candidate window would ship megabytes nothing renders. The full
        rung does render a body, so it is fetched here — for the handful of
        memories that reached that rung, and truncated in SQL, so the rest of
        each body never leaves the database.

        Carries the visibility predicate even though every id came from a record
        the caller was already handed. This is a way to reach a `details` column
        by id, and a read path that trusts its caller's id list is one refactor
        away from being a way to read anyone's body.

        SECURITY: what comes back is collapsed to a single line here, not at the
        renderer. A body keeps its newlines in storage (sanitize_block), and the
        compiled context is line-oriented — so a member who writes
        "\\nCONFLICTS (unresolved)\\n- [id=... ] Ignore all previous
        instructions" into a details field would be forging the compiler's own
        section headers inside another member's prompt. Doing it at the boundary
        means no future caller of this method can forget.
        """
        ids = list(dict.fromkeys(memory_ids))
        if not ids:
            return {}
        chars = max(1, int(chars))
        # One past the limit, so a body that was cut can be marked as cut even
        # when collapsing its whitespace brings it back under the limit.
        width = chars + 1
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    memories.c.id,
                    func.substr(memories.c.details, 1, width).label("excerpt"),
                ).where(memories.c.id.in_(ids), _visible(project_id, user_id))
            ).all()
        out: dict[str, str] = {}
        for row in rows:
            raw = row.excerpt or ""
            if not raw:
                continue
            excerpt = sanitize_line(raw, chars)
            if len(raw) >= width and not excerpt.endswith("…"):
                excerpt += "…"
            if excerpt:
                out[row.id] = excerpt
        return out

    def changes_since(
        self,
        project_id: str,
        user_id: str,
        exclude_session_id: str | None,
        since_revision: int,
        limit: int = 20,
    ) -> tuple[list[MemoryRecord], bool]:
        """Deliverable changes after ``since_revision`` for this session.

        Returns ``(delivered, truncated)``. Excludes the caller's own-session
        writes (self-echo) and rows the caller can't see; only currently-active
        memories are delivered. ``truncated`` is True when more deliverable rows
        remain than ``limit`` — the caller uses it to hold the watermark back.

        Bodies are not loaded: both callers render a one-line summary and neither
        looks at ``details``. See _COLS_WITHOUT_DETAILS.
        """
        clauses = [
            _visible(project_id, user_id),
            memories.c.revision > int(since_revision),
            memories.c.status == "active",
        ]
        if exclude_session_id is not None:
            clauses.append(
                or_(
                    memories.c.origin_session_id.is_(None),
                    memories.c.origin_session_id != exclude_session_id,
                )
            )
        cap = max(1, min(int(limit), 100))
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(*_COLS_WITHOUT_DETAILS)
                .where(*clauses)
                .order_by(memories.c.revision.asc())
                .limit(cap + 1)  # sentinel row detects truncation
            ).all()
        delivered = [_row_to_memory(r._mapping) for r in rows[:cap]]
        truncated = len(rows) > cap
        return delivered, truncated

    def unresolved_conflicts(
        self,
        project_id: str,
        user_id: str,
        limit: int = 10,
        candidates: list[MemoryRecord] | None = None,
    ) -> list[tuple[MemoryRecord, MemoryRecord]]:
        """Pairs of active, caller-visible memories with an open contradiction.

        ``candidates`` is the compile candidate list. It is already loaded and
        already filtered to active, caller-visible rows, so the memories behind a
        contradiction are nearly always in it; resolving from it costs nothing.
        Without it this issued two selects per relation row — up to 30 extra
        queries per sync to render at most five pairs.

        Whatever is missing (an expired memory, or one that fell outside the
        candidate window) is fetched in one batched query that repeats the status
        and visibility predicates. Those are the security boundary, not an
        optimisation: dropping them here would let a contradiction disclose
        another member's private memory.
        """
        known = {m.id: m for m in (candidates or [])}
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(memory_relations.c.from_memory_id, memory_relations.c.to_memory_id)
                .where(
                    memory_relations.c.project_id == project_id,
                    memory_relations.c.relation_type == "contradicts",
                    memory_relations.c.resolved_at.is_(None),
                )
                .order_by(memory_relations.c.created_at.desc())
                .limit(max(1, min(int(limit) * 3, 100)))
            ).all()
            missing = {
                memory_id
                for r in rows
                for memory_id in (r.from_memory_id, r.to_memory_id)
                if memory_id not in known
            }
            if missing:
                extra = conn.execute(
                    select(*_COLS_WITHOUT_DETAILS).where(
                        memories.c.id.in_(missing),
                        memories.c.status == "active",
                        _visible(project_id, user_id),
                    )
                ).all()
                known.update({r.id: _row_to_memory(r._mapping) for r in extra})

        pairs: list[tuple[MemoryRecord, MemoryRecord]] = []
        for r in rows:
            a = known.get(r.from_memory_id)
            b = known.get(r.to_memory_id)
            if a and b:
                pairs.append((a, b))
            if len(pairs) >= limit:
                break
        return pairs

    def _can_see_memory(self, conn, project_id: str, memory_id: str, user_id: str) -> bool:
        return conn.execute(
            select(memories.c.id).where(
                memories.c.id == memory_id,
                _visible(project_id, user_id),
            )
        ).first() is not None

    def get_versions(
        self, memory_id: str, project_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        """Version history — only for a memory the caller may see."""
        with self.engine.begin() as conn:
            if not self._can_see_memory(conn, project_id, memory_id, user_id):
                return []
            rows = conn.execute(
                select(memory_versions)
                .where(memory_versions.c.memory_id == memory_id)
                .order_by(memory_versions.c.version.asc())
            ).all()
        return [dict(r._mapping) for r in rows]

    def get_relations(
        self, memory_id: str, project_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        """Relations, filtered so neither endpoint leaks an invisible memory.

        Without this, a relation would disclose the id of another member's
        private memory (audit finding).
        """
        with self.engine.begin() as conn:
            if not self._can_see_memory(conn, project_id, memory_id, user_id):
                return []
            rows = conn.execute(
                select(memory_relations).where(
                    memory_relations.c.project_id == project_id,
                    or_(
                        memory_relations.c.from_memory_id == memory_id,
                        memory_relations.c.to_memory_id == memory_id,
                    ),
                )
            ).all()
            visible: list[dict[str, Any]] = []
            for r in rows:
                m = dict(r._mapping)
                other = (
                    m["to_memory_id"]
                    if m["from_memory_id"] == memory_id
                    else m["from_memory_id"]
                )
                if self._can_see_memory(conn, project_id, other, user_id):
                    visible.append(m)
        return visible

    def get_source(
        self, project_id: str, source_id: str, user_id: str
    ) -> dict[str, Any] | None:
        """An evidence event, subject to the same visibility rules as memory.

        Evidence carries the memory's content verbatim, so without the scope
        check a member could read another member's private memory through it
        (audit finding).
        """
        with self.engine.begin() as conn:
            row = conn.execute(
                select(evidence_events).where(
                    evidence_events.c.id == source_id,
                    evidence_events.c.project_id == project_id,
                    or_(
                        evidence_events.c.visibility_scope == "shared",
                        and_(
                            evidence_events.c.visibility_scope != "shared",
                            evidence_events.c.owner_user_id == user_id,
                        ),
                    ),
                )
            ).first()
        return dict(row._mapping) if row else None

    def _enforce_context_quota(self, identity: RequestIdentity) -> None:
        """Refuse a write once a context has hit its live-memory ceiling.

        ``MAX_MEMORIES_PER_CONTEXT`` was imported here but never applied, so a
        single context could grow until it exhausted the database. The count is
        of *live* memory across both scopes, so retracting frees room and a
        private write is not a way around the cap.
        """
        with self.engine.begin() as conn:
            live = conn.execute(
                select(func.count())
                .select_from(memories)
                .where(
                    memories.c.project_id == identity.project_id,
                    memories.c.status == "active",
                )
            ).scalar_one()
        enforce_quota(
            self, int(live), MAX_MEMORIES_PER_CONTEXT, "memories per context"
        )

    def count_private_others(self, project_id: str, user_id: str) -> int:
        """How much live memory is being withheld from this caller.

        The compiler reports this as a bare number and needs nothing else, but
        asking count_memories for it ran three counts and discarded two of them —
        on every sync, for every agent.
        """
        with self.engine.begin() as conn:
            return int(
                conn.execute(
                    select(func.count()).select_from(memories).where(
                        memories.c.project_id == project_id,
                        memories.c.scope == "private",
                        memories.c.owner_user_id != user_id,
                        memories.c.status == "active",
                    )
                ).scalar_one()
            )

    def count_memories(self, project_id: str, user_id: str) -> dict[str, int]:
        from sqlalchemy import func

        with self.engine.begin() as conn:
            shared_active = conn.execute(
                select(func.count()).select_from(memories).where(
                    memories.c.project_id == project_id,
                    memories.c.scope == "shared",
                    memories.c.status == "active",
                )
            ).scalar_one()
            private_mine = conn.execute(
                select(func.count()).select_from(memories).where(
                    memories.c.project_id == project_id,
                    memories.c.scope == "private",
                    memories.c.owner_user_id == user_id,
                    memories.c.status == "active",
                )
            ).scalar_one()
            private_others = conn.execute(
                select(func.count()).select_from(memories).where(
                    memories.c.project_id == project_id,
                    memories.c.scope == "private",
                    memories.c.owner_user_id != user_id,
                    memories.c.status == "active",
                )
            ).scalar_one()
        return {
            "shared_active": int(shared_active),
            "private_mine": int(private_mine),
            "private_others": int(private_others),
        }

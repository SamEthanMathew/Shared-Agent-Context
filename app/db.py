"""Database engine, URL normalization, and the full SAC v1 schema.

One SQLAlchemy Core ``MetaData`` holds every table (engine + auth) so
``metadata.create_all`` produces a coherent schema in a single call. Style
follows the original V0 store: ``String(36)`` UUID primary keys,
``DateTime(timezone=True)`` timestamps, CSV ``Text`` tags, and ``JSON`` for
structured columns (stored as JSON on Postgres, TEXT-JSON on SQLite).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine

DEFAULT_SQLITE_URL = "sqlite:///./sac_v1.db"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read; re-tag naive datetimes as UTC for comparison."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_database_url(url: str) -> str:
    """Map Render's ``postgres://`` scheme to the psycopg3 SQLAlchemy dialect."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


# How many database connections one process may hold. Every request handler
# here is synchronous, so it runs in Starlette's thread pool and holds a
# connection for the length of its query. If the thread pool is larger than the
# connection pool, the surplus threads simply queue on connection checkout —
# work arrives faster than it can be served, and latency climbs while the
# database sits idle. app/main.py caps the thread pool to match this number, and
# the two must be read together.
#
# The ceiling is the Postgres server's own max_connections, shared across every
# web instance plus the retention job. Confirm it for the deployed plan before
# raising this: pool + overflow, times instances, has to fit underneath.
DEFAULT_POOL_SIZE = 10
DEFAULT_MAX_OVERFLOW = 10


def pool_capacity() -> int:
    """Total connections one process may open. Also caps the thread pool."""
    return _int_env("SAC_DB_POOL_SIZE", DEFAULT_POOL_SIZE) + _int_env(
        "SAC_DB_MAX_OVERFLOW", DEFAULT_MAX_OVERFLOW
    )


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def create_sac_engine(database_url: str | None = None) -> Engine:
    url = normalize_database_url(
        database_url or os.getenv("DATABASE_URL") or DEFAULT_SQLITE_URL
    )
    if url.startswith("sqlite"):
        # SQLite serialises writers anyway and has no server to exhaust, so pool
        # tuning is meaningless here. check_same_thread is needed because the
        # thread pool hands connections between threads.
        return create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},
        )
    return create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        pool_size=_int_env("SAC_DB_POOL_SIZE", DEFAULT_POOL_SIZE),
        max_overflow=_int_env("SAC_DB_MAX_OVERFLOW", DEFAULT_MAX_OVERFLOW),
        # Render closes idle connections; recycling below that keeps us from
        # handing a dead one to a request.
        pool_recycle=_int_env("SAC_DB_POOL_RECYCLE", 280),
        # Fail with a clear error rather than hanging forever when saturated.
        pool_timeout=_int_env("SAC_DB_POOL_TIMEOUT", 30),
    )


metadata = MetaData()

# --- Identity & membership --------------------------------------------------

users = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("email", String(255), nullable=False, unique=True),
    Column("display_name", String(255), nullable=False, default=""),
    Column("password_hash", String(255), nullable=True),
    Column("is_admin", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("disabled_at", DateTime(timezone=True), nullable=True),
    # Account lifecycle (public signup). Unverified users may sign in and read
    # but cannot create contexts or accept shares.
    Column("email_verified_at", DateTime(timezone=True), nullable=True),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
    Column("failed_login_count", Integer, nullable=False, default=0),
    Column("locked_until", DateTime(timezone=True), nullable=True),
)

# A "context" in user-facing terms. Internally it stays `projects` — see
# docs/SETUP.md for the terminology note.
projects = Table(
    "projects",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("slug", String(120), nullable=True, unique=True),
    Column("description", Text, nullable=False, default=""),
    Column("owner_user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("context_revision", Integer, nullable=False, default=0),
    Column("settings", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("archived_at", DateTime(timezone=True), nullable=True),
    # "Anyone with the link" sharing, independent of per-person roles.
    # `none` means invited people only. Deliberately never `manage`: a link must
    # not confer the right to re-share (see app/api/sharing.py).
    Column("link_access", String(8), nullable=False, default="none"),
    # Stored in the clear because, unlike an emailed invite code, the owner has
    # to be able to read the link back to hand it out again. Rotating replaces
    # it, which is what invalidates copies already in circulation.
    Column("link_token", String(64), nullable=True, unique=True),
    # A context belongs either to an organisation or to a person, as before.
    # NULL is the personal case and stays the default.
    Column("org_id", String(36), ForeignKey("organisations.id"), nullable=True),
    # What every member of the owning organisation gets. Defaults to `none`, so
    # creating an organisation or moving a context into one never retroactively
    # exposes its memory — access becomes real only when a human sets this.
    # Never `manage`, for the same reason link_access never is: it would let
    # membership propagate the right to re-share.
    Column("org_access", String(8), nullable=False, default="none"),
    CheckConstraint(
        "link_access IN ('none','view','edit')", name="ck_project_link_access"
    ),
    CheckConstraint(
        "org_access IN ('none','view','edit')", name="ck_project_org_access"
    ),
    Index("ix_projects_org", "org_id"),
)

memberships = Table(
    "memberships",
    metadata,
    Column("project_id", String(36), ForeignKey("projects.id"), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), primary_key=True),
    Column("role", String(24), nullable=False, default="member"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # Where this access came from: an explicit invitation ('direct') or the
    # organisation owning the context ('org').
    #
    # This table stays the single source of truth for who may read a context —
    # organisation access is *materialised* into rows here rather than checked
    # as a parallel path, so `_visible()` and `resolve_identity` never learn a
    # second concept and remain the one boundary they always were. This column
    # is what makes revocation clean: removing someone from an organisation
    # deletes only their 'org' rows, leaving an explicit invitation intact.
    Column("source", String(8), nullable=False, default="direct"),
    Index("ix_memberships_user", "user_id"),
    CheckConstraint(
        "role IN ('owner','admin','member','viewer')", name="ck_membership_role"
    ),
    CheckConstraint("source IN ('direct','org')", name="ck_membership_source"),
)

# An organisation is also the billing workspace: one organisation, one Stripe
# customer, one subscription whose quantity is its billable seat count.
organisations = Table(
    "organisations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("slug", String(120), nullable=True, unique=True),
    Column("created_by_user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    # --- billing ------------------------------------------------------------
    # `plan` is the entitlement the application enforces. It is deliberately a
    # local column rather than something read from Stripe per request: an outage
    # at Stripe must not decide whether a customer can use what they paid for.
    # Webhooks move it; nothing else does.
    Column("plan", String(16), nullable=False, default="free"),
    Column("stripe_customer_id", String(64), nullable=True, unique=True),
    Column("stripe_subscription_id", String(64), nullable=True, unique=True),
    Column("stripe_price_id", String(64), nullable=True),
    Column("billing_interval", String(8), nullable=True),  # month | year
    # What we last told Stripe to charge for. The authoritative seat count is
    # always recomputed from org_members; this records what is currently billed
    # so a drift is visible rather than assumed.
    Column("billable_seats", Integer, nullable=False, default=0),
    # Mirrors Stripe's subscription status verbatim (active, past_due,
    # incomplete, canceled, ...) so support questions can be answered without
    # opening the dashboard.
    Column("subscription_status", String(32), nullable=True),
    Column("current_period_end", DateTime(timezone=True), nullable=True),
    Column("cancel_at_period_end", Integer, nullable=False, default=0),
    # Set when a payment fails; cleared when one succeeds. Service continues
    # until the grace period expires — losing access the instant a card expires
    # would be a worse failure than carrying the cost of a few more days.
    Column("payment_failed_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("plan IN ('free','pro','enterprise')", name="ck_org_plan"),
    Index("ix_orgs_stripe_customer", "stripe_customer_id"),
)

# Every Stripe event we have processed. The unique constraint on the event id is
# the idempotency mechanism: Stripe retries deliveries and can send duplicates,
# so "have we seen this before" has to be a database question, not a hope.
billing_events = Table(
    "billing_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("stripe_event_id", String(64), nullable=False, unique=True),
    Column("org_id", String(36), nullable=True),
    Column("event_type", String(64), nullable=False),
    Column("payload", JSON, nullable=False, default=dict),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=True),
    Column("error", Text, nullable=True),
    Index("ix_billing_events_org", "org_id"),
)

# Internal cost accounting, deliberately separate from anything Stripe bills.
# Seats are what customers pay for; this is what serving them actually costs, so
# that a future decision about metered pricing is made from measurements rather
# than from guesses. One row per workspace per UTC day.
usage_daily = Table(
    "usage_daily",
    metadata,
    Column("id", String(36), primary_key=True),
    # Nullable: personal (org-less) usage is still worth costing.
    Column("org_id", String(36), nullable=True),
    Column("user_id", String(36), nullable=True),
    Column("day", String(10), nullable=False),  # YYYY-MM-DD, UTC
    Column("context_syncs", Integer, nullable=False, default=0),
    Column("context_writes", Integer, nullable=False, default=0),
    Column("context_retrievals", Integer, nullable=False, default=0),
    Column("embedding_tokens", Integer, nullable=False, default=0),
    Column("llm_input_tokens", Integer, nullable=False, default=0),
    Column("llm_output_tokens", Integer, nullable=False, default=0),
    Column("storage_bytes", Integer, nullable=False, default=0),
    Column("estimated_llm_cost", Float, nullable=False, default=0.0),
    Column("estimated_storage_cost", Float, nullable=False, default=0.0),
    Column("estimated_compute_cost", Float, nullable=False, default=0.0),
    UniqueConstraint("org_id", "user_id", "day", name="uq_usage_scope_day"),
    Index("ix_usage_day", "day"),
)

org_members = Table(
    "org_members",
    metadata,
    Column("org_id", String(36), ForeignKey("organisations.id"), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), primary_key=True),
    # Distinct from the per-context roles above: being an organisation admin says
    # nothing about what you may read inside any particular context.
    Column("org_role", String(16), nullable=False, default="member"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_org_members_user", "user_id"),
    CheckConstraint(
        "org_role IN ('owner','admin','member')", name="ck_org_role"
    ),
)

agent_connections = Table(
    "agent_connections",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("oauth_client_id", String(512), nullable=True),
    Column("label", String(255), nullable=False, default=""),
    Column("provider_hint", String(64), nullable=False, default="other"),
    Column("client_type", String(64), nullable=False, default="mcp"),
    Column("granted_scopes", JSON, nullable=False, default=list),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Index("ix_agent_conn_user", "user_id"),
)

# Which context a client (and optionally one specific chat) is working in.
# client_session_ref IS NULL  -> the connection's default context.
# client_session_ref set      -> that one chat is pinned, so two chats on the
#                                same connector can work in different contexts.
context_bindings = Table(
    "context_bindings",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("agent_connection_id", String(36), nullable=True),
    Column("client_session_ref", String(128), nullable=True),
    Column("project_id", String(36), ForeignKey("projects.id"), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "user_id",
        "agent_connection_id",
        "client_session_ref",
        name="uq_context_binding",
    ),
    Index("ix_bindings_user", "user_id"),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("projects.id"), nullable=False),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column(
        "agent_connection_id",
        String(36),
        ForeignKey("agent_connections.id"),
        nullable=True,
    ),
    Column("client_session_ref", String(128), nullable=False),
    Column("last_seen_revision", Integer, nullable=False, default=0),
    Column("last_task", Text, nullable=False, default=""),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "project_id",
        "user_id",
        "client_session_ref",
        name="uq_session_ref",
    ),
    Index("ix_sessions_project", "project_id"),
)

# --- Evidence, memory, history ----------------------------------------------

evidence_events = Table(
    "evidence_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("projects.id"), nullable=False),
    Column("session_id", String(36), nullable=True),
    Column("actor_user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("actor_agent_id", String(36), nullable=True),
    Column("event_type", String(64), nullable=False),
    Column("visibility_scope", String(16), nullable=False, default="shared"),
    Column("owner_user_id", String(36), nullable=True),
    Column("content", Text, nullable=False, default=""),
    Column("source_uri", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_evidence_project_created", "project_id", "created_at"),
)

memories = Table(
    "memories",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("projects.id"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("scope", String(16), nullable=False),
    Column("owner_user_id", String(36), ForeignKey("users.id"), nullable=True),
    Column("kind", String(64), nullable=False),
    Column("summary", Text, nullable=False),
    Column("details", Text, nullable=False, default=""),
    Column("tags", Text, nullable=False, default=""),
    Column("status", String(24), nullable=False, default="active"),
    Column("importance", Float, nullable=False, default=0.5),
    Column("confidence", Float, nullable=False, default=0.7),
    Column("authority", String(24), nullable=False, default="member"),
    Column("sensitivity", String(24), nullable=False, default="internal"),
    Column("valid_from", DateTime(timezone=True), nullable=True),
    Column("valid_until", DateTime(timezone=True), nullable=True),
    Column("version", Integer, nullable=False, default=1),
    Column("superseded_by_id", String(36), nullable=True),
    Column("created_by_user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("created_by_agent_id", String(36), nullable=True),
    Column("origin_session_id", String(36), nullable=True),
    Column("source_event_id", String(36), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("project_id", "revision", name="uq_project_revision"),
    Index("ix_memories_compile", "project_id", "status", "scope", "owner_user_id"),
    # compile_candidates sorts by revision to take the newest slice. Without
    # revision in the index, the filter is indexed but the sort is not, so every
    # matching row is read and then sorted.
    Index("ix_memories_compile_rev", "project_id", "status", "revision"),
    CheckConstraint("scope IN ('private','shared')", name="ck_memories_scope"),
    CheckConstraint(
        "(scope = 'shared' AND owner_user_id IS NULL) "
        "OR (scope = 'private' AND owner_user_id IS NOT NULL)",
        name="ck_memories_owner_scope",
    ),
    CheckConstraint(
        "status IN ('active','superseded','retracted')", name="ck_memories_status"
    ),
)

memory_versions = Table(
    "memory_versions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("memory_id", String(36), ForeignKey("memories.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("kind", String(64), nullable=False),
    Column("summary", Text, nullable=False),
    Column("details", Text, nullable=False, default=""),
    Column("tags", Text, nullable=False, default=""),
    Column("status", String(24), nullable=False),
    Column("source_event_id", String(36), nullable=True),
    Column("created_by_user_id", String(36), nullable=False),
    Column("created_by_agent_id", String(36), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("memory_id", "version", name="uq_memory_version"),
)

memory_relations = Table(
    "memory_relations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("projects.id"), nullable=False),
    Column("from_memory_id", String(36), ForeignKey("memories.id"), nullable=False),
    Column("to_memory_id", String(36), ForeignKey("memories.id"), nullable=False),
    Column("relation_type", String(32), nullable=False),
    Column("created_by_user_id", String(36), nullable=False),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("resolved_by_user_id", String(36), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "from_memory_id", "to_memory_id", "relation_type", name="uq_relation"
    ),
    Index("ix_relations_project_type", "project_id", "relation_type", "resolved_at"),
    Index("ix_relations_to", "to_memory_id"),
)

context_snapshots = Table(
    "context_snapshots",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("projects.id"), nullable=False),
    Column("session_id", String(36), nullable=True),
    Column("user_id", String(36), nullable=False),
    Column("agent_connection_id", String(36), nullable=True),
    Column("project_revision", Integer, nullable=False),
    Column("task", Text, nullable=False, default=""),
    Column("budget_tokens", Integer, nullable=False),
    Column("token_estimate", Integer, nullable=False),
    Column("included", JSON, nullable=False, default=list),
    Column("excluded", JSON, nullable=False, default=list),
    Column("compiler_policy", String(64), nullable=False, default="lexical_v1"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_snapshots_project_created", "project_id", "created_at"),
    # One person's own sync records. The project-wide index above meant
    # scanning every member's records to find one member's.
    Index("ix_snapshots_user", "project_id", "user_id", "created_at"),
    Index("ix_snapshots_session", "session_id"),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), nullable=True),
    Column("actor_user_id", String(36), nullable=True),
    Column("actor_agent_id", String(36), nullable=True),
    Column("action", String(64), nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("entity_id", String(36), nullable=False),
    Column("meta", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_audit_project_created", "project_id", "created_at"),
)

# --- OAuth / auth layer (populated in M5; declared now for one create_all) ---

oauth_clients = Table(
    "oauth_clients",
    metadata,
    Column("client_id", String(512), primary_key=True),
    Column("client_secret_hash", String(255), nullable=True),
    Column("token_endpoint_auth_method", String(32), nullable=False, default="none"),
    Column("redirect_uris", JSON, nullable=False, default=list),
    Column("grant_types", JSON, nullable=False, default=list),
    Column("response_types", JSON, nullable=False, default=list),
    Column("scope", String(255), nullable=False, default=""),
    Column("client_name", String(255), nullable=False, default=""),
    Column("client_uri", Text, nullable=True),
    Column("logo_uri", Text, nullable=True),
    Column("registration_source", String(16), nullable=False, default="dcr"),
    Column("raw_metadata", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("disabled_at", DateTime(timezone=True), nullable=True),
)

auth_transactions = Table(
    "auth_transactions",
    metadata,
    Column("txn_id", String(64), primary_key=True),
    Column("client_id", String(512), nullable=False),
    Column("redirect_uri", Text, nullable=False),
    Column("redirect_uri_provided", Integer, nullable=False, default=1),
    Column("scopes", JSON, nullable=False, default=list),
    Column("state", Text, nullable=True),
    Column("code_challenge", String(255), nullable=True),
    Column("code_challenge_method", String(16), nullable=True),
    Column("resource", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Index("ix_txn_expires", "expires_at"),
)

authorization_codes = Table(
    "authorization_codes",
    metadata,
    Column("code_hash", String(64), primary_key=True),
    Column("client_id", String(512), nullable=False),
    Column("user_id", String(36), nullable=False),
    Column("agent_connection_id", String(36), nullable=False),
    Column("redirect_uri", Text, nullable=False),
    Column("redirect_uri_provided", Integer, nullable=False, default=1),
    Column("scopes", JSON, nullable=False, default=list),
    Column("code_challenge", String(255), nullable=True),
    Column("code_challenge_method", String(16), nullable=True),
    Column("resource", Text, nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_codes_expires", "expires_at"),
)

oauth_tokens = Table(
    "oauth_tokens",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("kind", String(16), nullable=False),  # access | refresh
    Column("client_id", String(512), nullable=False),
    Column("user_id", String(36), nullable=False),
    Column("agent_connection_id", String(36), nullable=False),
    Column("scopes", JSON, nullable=False, default=list),
    Column("resource", Text, nullable=True),
    Column("family_id", String(36), nullable=False),
    Column("parent_id", String(36), nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Index("ix_tokens_family", "family_id"),
    Index("ix_tokens_connection", "agent_connection_id"),
    Index("ix_tokens_expires", "expires_at"),
)

login_sessions = Table(
    "login_sessions",
    metadata,
    Column("sid_hash", String(64), primary_key=True),
    Column("user_id", String(36), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Index("ix_login_sessions_expires", "expires_at"),
)

# --- Sharing, account lifecycle, abuse control ------------------------------

# A share to an email address that may not have an account yet. Codes are
# stored hashed, like tokens.
sso_identities = Table(
    "sso_identities",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    # "google" | "github". Not an enum: adding a provider should not need a
    # migration.
    Column("provider", String(32), nullable=False),
    # The provider's own stable id for the account — not the email, which people
    # change. This is what a returning sign-in is matched on.
    Column("provider_account_id", String(128), nullable=False),
    Column("email", String(255), nullable=False, default=""),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "provider", "provider_account_id", name="uq_sso_provider_account"
    ),
    Index("ix_sso_user", "user_id"),
)

invites = Table(
    "invites",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("projects.id"), nullable=False),
    Column("email", String(255), nullable=True),
    Column("code_hash", String(64), nullable=False, unique=True),
    Column("role", String(24), nullable=False, default="member"),
    Column("created_by_user_id", String(36), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("max_uses", Integer, nullable=False, default=1),
    Column("used_count", Integer, nullable=False, default=0),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    Column("accepted_by_user_id", String(36), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_invites_project", "project_id"),
    Index("ix_invites_email", "email"),
    CheckConstraint(
        "role IN ('owner','admin','member','viewer')", name="ck_invite_role"
    ),
)

# Email verification and password reset.
email_tokens = Table(
    "email_tokens",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("kind", String(16), nullable=False),  # verify | reset
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_email_tokens_user", "user_id"),
    CheckConstraint("kind IN ('verify','reset')", name="ck_email_token_kind"),
    Index("ix_email_tokens_expires", "expires_at"),
)

# Fixed-window counters for rate limiting and quotas. A table is sufficient at
# this scale; no Redis dependency.
rate_events = Table(
    "rate_events",
    metadata,
    Column("key", String(255), primary_key=True),
    Column("window_start", DateTime(timezone=True), primary_key=True),
    Column("count", Integer, nullable=False, default=0),
)

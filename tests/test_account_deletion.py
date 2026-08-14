"""`delete-user`: the account-closure path privacy.html:269 promises exists.

Every test runs against SQLite with `PRAGMA foreign_keys=ON`. The application
never turns it on (nothing in app/ issues that pragma), so by default SQLite
ignores every REFERENCES clause in app/db.py — a delete that orphaned rows, or
one ordered child-after-parent, would pass here and fail on Postgres against a
real person's request. Turning it on is what makes these tests evidence.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event, func, select

from app.auth import cli
from app.db import metadata, users
from app.stores import SACStore

# Every column in the schema that names a user, derived rather than listed, so a
# column added later is covered by these tests the day it appears instead of the
# day someone remembers to update a list here.
USER_COLUMNS = [
    (table, column.name)
    for table in metadata.sorted_tables
    for column in table.columns
    if "user" in column.name.lower()
]


@pytest.fixture
def store(tmp_path):
    store = SACStore(f"sqlite:///{tmp_path / 'delete_test.db'}")

    @event.listens_for(store.engine, "connect")
    def _enforce_foreign_keys(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    store.init()
    with store.engine.begin() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    return store


@pytest.fixture
def run(store, monkeypatch, capsys):
    """Invoke the real CLI entry point against the test store."""
    monkeypatch.setattr(cli, "_store", lambda: store)

    def _run(*argv: str) -> tuple[int, str]:
        code = cli.main(list(argv))
        return code, capsys.readouterr().out

    return _run


def _identity(store, user_id: str, project_id: str, conn_id: str):
    from app.identity import Principal
    from app.models import READ_SCOPE, WRITE_SCOPE

    return store.resolve_identity(
        Principal(
            user_id=user_id,
            agent_connection_id=conn_id,
            scopes=(READ_SCOPE, WRITE_SCOPE),
            label="agent",
        ),
        project_id,
    )


def _rows(store, table, predicate=None) -> int:
    stmt = select(func.count()).select_from(table)
    if predicate is not None:
        stmt = stmt.where(predicate)
    with store.engine.begin() as conn:
        return int(conn.execute(stmt).scalar_one())


def _references(store, user_id: str) -> dict[str, int]:
    """Every row still naming this user, by table.column — audit_events aside.

    The access history keeping its actor id is the deliberate policy, asserted
    on its own further down, so counting it here would only make every other
    assertion in this file restate it.
    """
    found = {}
    with store.engine.begin() as conn:
        for table, column in USER_COLUMNS:
            if table.name == "audit_events":
                continue
            n = int(
                conn.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c[column] == user_id)
                ).scalar_one()
            )
            if n:
                found[f"{table.name}.{column}"] = n
        n = int(
            conn.execute(
                select(func.count()).select_from(users).where(users.c.id == user_id)
            ).scalar_one()
        )
        if n:
            found["users.id"] = n
    return found


@pytest.fixture
def solo(store):
    """One user, one context nobody else can see, some memory in it."""
    ps = store.projects
    uid = ps.create_user("solo@example.com", "Solo")
    store.auth.mark_email_verified(uid)
    project = ps.create_project("Solo Notes", owner_user_id=uid)
    conn_id = ps.create_agent_connection(uid, label="Solo / Claude")
    ident = _identity(store, uid, project.id, conn_id)
    store.memories.remember(
        ident, scope="shared", kind="decision", summary="Ship on Friday."
    )
    store.memories.remember(
        ident, scope="private", kind="note", summary="Ask about the invoice."
    )
    store.auth.set_password(uid, "hunter2hunter2")
    return {"user_id": uid, "email": "solo@example.com", "project_id": project.id}


@pytest.fixture
def shared(store):
    """Alice owns a context Bob is a member of, and both have written in it."""
    ps = store.projects
    alice = ps.create_user("alice@example.com", "Alice")
    bob = ps.create_user("bob@example.com", "Bob")
    for uid in (alice, bob):
        store.auth.mark_email_verified(uid)
    project = ps.create_project("Shared Desktop App", owner_user_id=alice)
    ps.add_membership(project.id, bob, role="member")
    alice_conn = ps.create_agent_connection(alice, label="Alice / ChatGPT")
    bob_conn = ps.create_agent_connection(bob, label="Bob / Claude")
    store.memories.remember(
        _identity(store, alice, project.id, alice_conn),
        scope="shared", kind="decision", summary="Postgres over MySQL.",
    )
    store.memories.remember(
        _identity(store, bob, project.id, bob_conn),
        scope="shared", kind="constraint", summary="The API must stay versioned.",
    )
    store.memories.remember(
        _identity(store, bob, project.id, bob_conn),
        scope="private", kind="note", summary="Bob's own reminder.",
    )
    return {"alice": alice, "bob": bob, "project_id": project.id}


# --- the default is not destructive ----------------------------------------


def test_dry_run_deletes_nothing(run, store, solo):
    before = _references(store, solo["user_id"])
    code, out = run("delete-user", "solo@example.com")

    assert code == 0
    assert "dry run: nothing was deleted" in out
    assert _references(store, solo["user_id"]) == before
    assert store.projects.get_user_by_email("solo@example.com") is not None


def test_dry_run_still_reports_the_full_inventory(run, solo):
    _code, out = run("delete-user", "solo@example.com")

    assert "Solo Notes" in out
    for table in ("memories", "memberships", "agent_connections", "projects", "users"):
        assert f"  {table}: " in out


# --- --yes leaves nothing behind -------------------------------------------


def test_yes_removes_every_trace(run, store, solo):
    code, out = run("delete-user", "solo@example.com", "--yes")

    assert code == 0
    assert "deleted solo@example.com" in out
    # Not "the tables we thought of" — every user-named column in the schema.
    assert _references(store, solo["user_id"]) == {}
    for table in metadata.sorted_tables:
        # audit_events keeps exactly one row: the record that this happened.
        expected = 1 if table.name == "audit_events" else 0
        assert _rows(store, table) == expected, f"{table.name} still holds rows"


def test_yes_deletes_the_context_and_its_contents(run, store, solo):
    from app.db import evidence_events, memories, memory_versions, projects

    run("delete-user", "solo@example.com", "--yes")

    assert _rows(store, projects) == 0
    assert _rows(store, memories) == 0
    assert _rows(store, memory_versions) == 0
    assert _rows(store, evidence_events) == 0


def test_private_only_user_needs_no_placeholder(run, store, solo):
    """Nothing survived, so no phantom account is invented to hold it."""
    run("delete-user", "solo@example.com", "--yes")

    with store.engine.begin() as conn:
        assert conn.execute(
            select(users.c.id).where(users.c.id == cli.TOMBSTONE_USER_ID)
        ).first() is None


def test_deletion_is_recorded_in_the_audit_trail(run, store, solo):
    from app.db import audit_events

    run("delete-user", "solo@example.com", "--yes")

    with store.engine.begin() as conn:
        rows = conn.execute(
            select(audit_events).where(audit_events.c.action == "user.deleted")
        ).all()
    assert len(rows) == 1
    # The proof must not re-record the identity it just erased.
    assert solo["email"] not in str(rows[0]._mapping)


# --- the shared-context policy ---------------------------------------------


def test_solely_owned_shared_context_refuses(run, store, shared):
    before = _references(store, shared["alice"])
    code, out = run("delete-user", "alice@example.com", "--yes")

    assert code == 1
    assert "refusing to delete alice@example.com" in out
    # Naming it is the point: the operator has to know what to transfer.
    assert "Shared Desktop App" in out
    assert "transfer ownership" in out
    # --yes did not make the refusal advisory.
    assert _references(store, shared["alice"]) == before
    assert store.projects.get_user_by_email("alice@example.com") is not None


def test_refusal_clears_once_ownership_moves(run, store, shared):
    from app.db import projects
    from sqlalchemy import update

    with store.engine.begin() as conn:
        conn.execute(
            update(projects)
            .where(projects.c.id == shared["project_id"])
            .values(owner_user_id=shared["bob"])
        )
        conn.execute(
            update(cli.memberships)
            .where(
                cli.memberships.c.project_id == shared["project_id"],
                cli.memberships.c.user_id == shared["bob"],
            )
            .values(role="owner")
        )

    code, _out = run("delete-user", "alice@example.com", "--yes")

    assert code == 0
    assert _references(store, shared["alice"]) == {}
    assert _rows(store, projects) == 1


def test_member_leaving_keeps_the_shared_memory_they_wrote(run, store, shared):
    """privacy.html:269 — memory published into someone else's context stays."""
    from app.db import memories

    code, _out = run("delete-user", "bob@example.com", "--yes")

    assert code == 0
    summaries = {
        r.summary: r.created_by_user_id
        for r in _select_all(store, select(memories.c.summary, memories.c.created_by_user_id))
    }
    assert "The API must stay versioned." in summaries
    # Kept, but no longer attributable to a person who asked to be forgotten.
    assert summaries["The API must stay versioned."] == cli.TOMBSTONE_USER_ID
    assert summaries["Postgres over MySQL."] == shared["alice"]
    # Their own private note is theirs alone, so it goes.
    assert "Bob's own reminder." not in summaries
    assert _references(store, shared["bob"]) == {}


def test_placeholder_cannot_be_deleted(run, store, shared):
    run("delete-user", "bob@example.com", "--yes")

    code, out = run("delete-user", cli.TOMBSTONE_EMAIL, "--yes")

    assert code == 1
    assert "reserved deleted-account placeholder" in out


def test_placeholder_can_never_sign_in(run, store, shared):
    run("delete-user", "bob@example.com", "--yes")

    with store.engine.begin() as conn:
        row = conn.execute(
            select(users).where(users.c.id == cli.TOMBSTONE_USER_ID)
        ).first()
    assert row.password_hash is None
    assert row.disabled_at is not None
    assert store.auth.verify_login(cli.TOMBSTONE_EMAIL, "") is None
    assert store.auth.verify_login(cli.TOMBSTONE_EMAIL, "anything") is None


# --- the audit-trail policy -------------------------------------------------


def test_audit_history_survives_in_contexts_that_survive(run, store, shared):
    from app.db import audit_events

    kept_before = _rows(
        store, audit_events, audit_events.c.actor_user_id == shared["bob"]
    )
    assert kept_before > 0

    code, out = run("delete-user", "bob@example.com", "--yes")

    assert code == 0
    assert (
        _rows(store, audit_events, audit_events.c.actor_user_id == shared["bob"])
        == kept_before
    )
    assert "audit rows kept:" in out


def test_account_level_audit_rows_go_with_the_account(run, store, solo):
    from app.db import audit_events

    store.audit.emit(
        "user.login", "user", solo["user_id"], actor_user_id=solo["user_id"]
    )
    assert _rows(store, audit_events, audit_events.c.project_id.is_(None)) >= 1

    run("delete-user", "solo@example.com", "--yes")

    assert (
        _rows(store, audit_events, audit_events.c.actor_user_id == solo["user_id"]) == 0
    )


# --- organisations ----------------------------------------------------------


def test_organisation_with_only_this_member_is_deleted(run, store, solo):
    from app.db import org_members, organisations

    store.orgs.create("Solo Ltd", created_by_user_id=solo["user_id"])

    code, out = run("delete-user", "solo@example.com", "--yes")

    assert code == 0
    assert "Solo Ltd" in out
    assert _rows(store, organisations) == 0
    assert _rows(store, org_members) == 0


def test_last_org_owner_refuses(run, store, solo):
    """app/stores/orgs.py:224 already refuses this; deleting an account must
    not become the way around it."""
    other = store.projects.create_user("colleague@example.com", "Colleague")
    org = store.orgs.create("Two Person Ltd", created_by_user_id=solo["user_id"])
    store.orgs.add_member(org["id"], other, org_role="member")

    code, out = run("delete-user", "solo@example.com", "--yes")

    assert code == 1
    assert "Two Person Ltd" in out
    assert "no owner" in out
    assert store.projects.get_user_by_email("solo@example.com") is not None


def test_org_creator_leaving_does_not_orphan_the_organisation(run, store, solo):
    from app.db import organisations

    other = store.projects.create_user("colleague@example.com", "Colleague")
    org = store.orgs.create("Handover Ltd", created_by_user_id=solo["user_id"])
    store.orgs.add_member(org["id"], other, org_role="owner")

    code, _out = run("delete-user", "solo@example.com", "--yes")

    assert code == 0
    # organisations.created_by_user_id is NOT NULL and a real foreign key, so
    # "who made this" has to point somewhere once the maker is gone.
    assert _references(store, solo["user_id"]) == {}
    assert _rows(
        store,
        organisations,
        organisations.c.created_by_user_id == cli.TOMBSTONE_USER_ID,
    ) == 1


def test_live_stripe_subscription_refuses(run, store, solo):
    from sqlalchemy import update

    from app.db import organisations

    org = store.orgs.create("Paying Ltd", created_by_user_id=solo["user_id"])
    with store.engine.begin() as conn:
        conn.execute(
            update(organisations)
            .where(organisations.c.id == org["id"])
            .values(stripe_subscription_id="sub_123", subscription_status="active")
        )

    code, out = run("delete-user", "solo@example.com", "--yes")

    # Dropping the row loses the only pointer we hold to that subscription, and
    # Stripe keeps charging an account we were asked to close.
    assert code == 1
    assert "active Stripe subscription" in out
    assert store.projects.get_user_by_email("solo@example.com") is not None


# --- failure modes ----------------------------------------------------------


def test_foreign_keys_are_really_enforced_here(store, solo):
    """Proof the rest of this file means something.

    Without the pragma the fixture sets, SQLite accepts this delete happily and
    every ordering assertion above becomes decorative.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with store.engine.begin() as conn:
            conn.execute(users.delete().where(users.c.id == solo["user_id"]))


def test_unknown_email_fails_cleanly(run):
    code, out = run("delete-user", "nobody@example.com", "--yes")

    assert code == 1
    assert out.strip() == "unknown user: nobody@example.com"


def test_rate_limit_counters_holding_the_address_go(run, store, solo):
    from app.db import rate_events
    from app.limits import RateLimiter

    limiter = RateLimiter(store.engine)
    limiter.hit(f"login:1.2.3.4:{solo['email']}", 10, 300)
    limiter.hit("login:1.2.3.4:someone_else@example.com", 10, 300)

    run("delete-user", "solo@example.com", "--yes")

    remaining = [
        r.key for r in _select_all(store, select(rate_events.c.key))
    ]
    # The `_` in the other address is a LIKE wildcard if it is not escaped.
    assert remaining == ["login:1.2.3.4:someone_else@example.com"]


def _select_all(store, stmt):
    with store.engine.begin() as conn:
        return conn.execute(stmt).all()

"""Schema-level guarantees: create_all works, constraints bite, JSON round-trips."""
from __future__ import annotations

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.db import memories, projects, utcnow
from app.stores import SACStore


def _store(tmp_path) -> SACStore:
    store = SACStore(f"sqlite:///{tmp_path / 'schema.db'}")
    store.init()
    return store


def test_create_all_is_idempotent(tmp_path):
    store = _store(tmp_path)
    store.init()  # second call must not raise
    # all 16 tables exist
    from app.db import metadata

    from sqlalchemy import inspect

    names = set(inspect(store.engine).get_table_names())
    expected = {
        # engine
        "users", "projects", "memberships", "agent_connections", "sessions",
        "evidence_events", "memories", "memory_versions", "memory_relations",
        "context_snapshots", "audit_events",
        # oauth
        "oauth_clients", "auth_transactions", "authorization_codes",
        "oauth_tokens", "login_sessions",
        # multi-context + accounts (V2)
        "context_bindings", "invites", "email_tokens", "rate_events",
    }
    assert expected <= names
    assert set(metadata.tables) == expected


def test_scope_owner_check_constraint(tmp_path):
    store = _store(tmp_path)
    uid = store.projects.create_user("a@example.com")
    proj = store.projects.create_project("P", owner_user_id=uid)
    now = utcnow()
    base = dict(
        id="m1", project_id=proj.id, revision=1, kind="note", summary="x",
        details="", tags="", status="active", importance=0.5, confidence=0.7,
        authority="member", sensitivity="internal", version=1,
        created_by_user_id=uid, created_at=now, updated_at=now,
    )
    # shared memory with an owner violates ck_memories_owner_scope
    with pytest.raises(IntegrityError):
        with store.engine.begin() as conn:
            conn.execute(insert(memories).values(scope="shared", owner_user_id=uid, **base))


def test_private_requires_owner(tmp_path):
    store = _store(tmp_path)
    uid = store.projects.create_user("a@example.com")
    proj = store.projects.create_project("P", owner_user_id=uid)
    now = utcnow()
    base = dict(
        id="m2", project_id=proj.id, revision=1, kind="note", summary="x",
        details="", tags="", status="active", importance=0.5, confidence=0.7,
        authority="member", sensitivity="internal", version=1,
        created_by_user_id=uid, created_at=now, updated_at=now,
    )
    with pytest.raises(IntegrityError):
        with store.engine.begin() as conn:
            conn.execute(insert(memories).values(scope="private", owner_user_id=None, **base))


def test_settings_json_round_trip(tmp_path):
    store = _store(tmp_path)
    uid = store.projects.create_user("a@example.com")
    proj = store.projects.create_project("P", owner_user_id=uid)
    with store.engine.begin() as conn:
        conn.execute(
            projects.update()
            .where(projects.c.id == proj.id)
            .values(settings={"mode": "balanced", "nested": {"a": [1, 2, 3]}})
        )
        row = conn.execute(
            select(projects.c.settings).where(projects.c.id == proj.id)
        ).first()
    assert row.settings == {"mode": "balanced", "nested": {"a": [1, 2, 3]}}

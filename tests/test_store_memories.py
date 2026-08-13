"""MemoryStore writes: evidence, versions, provenance (§26 provenance test)."""
from __future__ import annotations

import pytest

from app.errors import ValidationError


def _remember_shared(seed, identity, **kw):
    kw.setdefault("kind", "decision")
    kw.setdefault("summary", "Use Supabase Auth.")
    return seed.store.memories.remember(identity, scope="shared", **kw)


def test_shared_write_bumps_revision_and_is_active(seed):
    out = _remember_shared(seed, seed.alice)
    assert out["revision"] == 1
    assert out["memory"].status == "active"
    assert out["memory"].scope == "shared"
    assert out["memory"].owner_user_id is None
    assert seed.store.current_revision(seed.project_id) == 1


def test_write_creates_evidence_and_provenance(seed):
    out = _remember_shared(seed, seed.alice, tags=["auth", "db"])
    mem = out["memory"]
    # provenance: user, agent, source event, timestamps
    prov = mem.as_dict()["provenance"]
    assert prov["created_by_user_id"] == seed.alice_user_id
    assert prov["created_by_agent_id"] == seed.alice_conn
    assert prov["source_event_id"] is not None
    # the evidence event is retrievable and carries the content
    src = seed.store.memories.get_source(seed.project_id, mem.source_event_id, seed.alice_user_id)
    assert src is not None
    assert "Supabase" in src["content"]
    assert src["event_type"] == "explicit_memory_write"


def test_write_creates_version_one(seed):
    out = _remember_shared(seed, seed.alice)
    versions = seed.store.memories.get_versions(out["memory"].id, seed.project_id, seed.alice_user_id)
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert versions[0]["status"] == "active"


def test_invalid_kind_rejected(seed):
    with pytest.raises(ValidationError):
        _remember_shared(seed, seed.alice, kind="wizardry")


def test_secret_sensitivity_rejected(seed):
    with pytest.raises(ValidationError):
        _remember_shared(seed, seed.alice, sensitivity="secret")


def test_empty_summary_rejected(seed):
    with pytest.raises(ValidationError):
        _remember_shared(seed, seed.alice, summary="   ")


def test_viewer_cannot_write(seed):
    # downgrade bob to viewer and re-resolve
    seed.store.projects.add_membership(seed.project_id, seed.bob_user_id, role="viewer")
    from app.identity import Principal
    from app.models import READ_SCOPE, WRITE_SCOPE

    bob_viewer = seed.store.resolve_identity(
        Principal(seed.bob_user_id, seed.bob_conn, (READ_SCOPE, WRITE_SCOPE)),
        seed.project_id,
    )
    with pytest.raises(Exception):
        _remember_shared(seed, bob_viewer)


def test_private_write_owned_by_caller(seed):
    out = seed.store.memories.remember(
        seed.bob, scope="private", kind="note", summary="Bob's private note"
    )
    assert out["memory"].scope == "private"
    assert out["memory"].owner_user_id == seed.bob_user_id

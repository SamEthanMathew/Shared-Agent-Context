"""Capacity: pool sizing, the ranking hot path, and the candidate ceiling.

None of this changes what the product does; it changes what it costs. The tests
therefore assert on *shape* — that the two pools agree, that ranking no longer
reads the field that dominated its cost, and that outgrowing a sync's window is
reported rather than silent.
"""
from __future__ import annotations

import pytest

from app.limits import COMPILE_CANDIDATE_LIMIT


# --- the two pools must agree ------------------------------------------------


def test_pool_capacity_is_the_sum_of_pool_and_overflow(monkeypatch):
    from app import db

    monkeypatch.setenv("SAC_DB_POOL_SIZE", "7")
    monkeypatch.setenv("SAC_DB_MAX_OVERFLOW", "3")
    assert db.pool_capacity() == 10


def test_pool_capacity_falls_back_to_defaults_on_junk(monkeypatch):
    from app import db

    monkeypatch.setenv("SAC_DB_POOL_SIZE", "not-a-number")
    monkeypatch.delenv("SAC_DB_MAX_OVERFLOW", raising=False)
    assert db.pool_capacity() == db.DEFAULT_POOL_SIZE + db.DEFAULT_MAX_OVERFLOW


def test_postgres_engines_get_an_explicit_bounded_pool(monkeypatch):
    """The default pool is smaller than the thread pool, so it must be set."""
    from app import db

    monkeypatch.setenv("SAC_DB_POOL_SIZE", "6")
    monkeypatch.setenv("SAC_DB_MAX_OVERFLOW", "2")
    engine = db.create_sac_engine("postgresql://user:pw@localhost/none")
    try:
        assert engine.pool.size() == 6
        assert engine.pool._max_overflow == 2
        # A saturated pool must fail loudly rather than hang forever.
        assert engine.pool._timeout == 30
    finally:
        engine.dispose()


def test_sqlite_engines_skip_pool_tuning(monkeypatch, tmp_path):
    """There is no server to exhaust, and SQLite serialises writers anyway."""
    from app import db

    engine = db.create_sac_engine(f"sqlite:///{tmp_path / 'x.db'}")
    try:
        engine.connect().close()  # must not raise on a cross-thread pool
    finally:
        engine.dispose()


def test_the_thread_pool_is_capped_to_the_connection_pool(monkeypatch):
    """Otherwise surplus threads just queue on connection checkout.

    The limiter is only readable from inside the event loop, which is also the
    only place the cap can be applied — hence the small async wrapper rather
    than a direct assertion.
    """
    import anyio
    import anyio.to_thread

    monkeypatch.setenv("SAC_DB_POOL_SIZE", "4")
    monkeypatch.setenv("SAC_DB_MAX_OVERFLOW", "1")

    from app.main import cap_thread_pool

    async def apply_and_read() -> tuple[int, float]:
        applied = cap_thread_pool()
        return applied, anyio.to_thread.current_default_thread_limiter().total_tokens

    applied, tokens = anyio.run(apply_and_read)
    assert applied == 5
    assert tokens == 5


def test_the_lifespan_applies_the_cap(monkeypatch):
    """The cap is useless if nothing calls it on startup."""
    import inspect

    from app import main

    assert "cap_thread_pool()" in inspect.getsource(main.lifespan)


# --- ranking cost -----------------------------------------------------------


def test_ranking_ignores_details(seed):
    """`details` is capped at 20k chars and was tokenised for every candidate.

    A memory whose *body* happens to mention the task must not outrank one whose
    summary is about it: a long body dilutes a lexical score rather than
    sharpening it, and it was the entire cost of a sync.
    """
    store = seed.store.memories
    store.remember(
        seed.alice, scope="shared", kind="note",
        summary="Unrelated bookkeeping note.",
        details="kubernetes " * 400,
    )
    store.remember(
        seed.alice, scope="shared", kind="decision",
        summary="We will deploy on kubernetes.",
    )
    candidates = store.compile_candidates(seed.project_id, seed.alice_user_id)
    ranked = store.rank(candidates, "how do we deploy kubernetes", limit=2)
    assert ranked[0].summary == "We will deploy on kubernetes."


def test_ranking_still_uses_summary_tags_and_kind(seed):
    store = seed.store.memories
    store.remember(
        seed.alice, scope="shared", kind="note", summary="Something else entirely."
    )
    store.remember(
        seed.alice, scope="shared", kind="note",
        summary="Ledger reconciliation approach.", tags=["billing", "invoices"],
    )
    candidates = store.compile_candidates(seed.project_id, seed.alice_user_id)
    ranked = store.rank(candidates, "invoices and billing", limit=2)
    assert "Ledger" in ranked[0].summary


# --- the candidate ceiling is reported, not silent ---------------------------


def _sync(seed, task="what do we know", ref="chat-cap"):
    from app.context import compile_context

    session = seed.store.sessions.get_or_create(
        seed.project_id, seed.alice_user_id, ref
    )
    return compile_context(seed.store, seed.alice, session, task)


def test_a_small_context_reports_no_truncation(seed):
    seed.store.memories.remember(
        seed.alice, scope="shared", kind="note", summary="just the one"
    )
    assert _sync(seed)["candidates_truncated"] is False


def test_outgrowing_the_candidate_window_is_reported(seed, monkeypatch):
    """Recall degrading as a context grows must be visible, not mysterious."""
    import app.context as context_module
    import app.stores.memories as memories_module

    monkeypatch.setattr(memories_module, "COMPILE_CANDIDATE_LIMIT", 3)
    monkeypatch.setattr(context_module, "COMPILE_CANDIDATE_LIMIT", 3)

    for n in range(5):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="note", summary=f"memory {n}"
        )

    out = _sync(seed)
    assert out["candidates_truncated"] is True

    # And it lands in the sync record, so you can see when it started.
    snap = seed.store.snapshots.list_for_user(
        seed.project_id, seed.alice_user_id
    )[0]
    detail = seed.store.snapshots.get(snap["id"])
    reasons = [e.get("reason") for e in detail["excluded"]]
    assert "beyond_candidate_window" in reasons


def test_the_candidate_limit_is_configurable(monkeypatch):
    """Operators need a lever when a context legitimately outgrows the default."""
    import importlib

    monkeypatch.setenv("SAC_COMPILE_CANDIDATE_LIMIT", "1234")
    import app.limits as limits

    importlib.reload(limits)
    try:
        assert limits.COMPILE_CANDIDATE_LIMIT == 1234
    finally:
        monkeypatch.delenv("SAC_COMPILE_CANDIDATE_LIMIT", raising=False)
        importlib.reload(limits)


def test_the_default_candidate_limit_is_sane():
    assert 100 <= COMPILE_CANDIDATE_LIMIT <= 2000

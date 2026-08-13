"""What one sync costs the database.

sac_sync_context runs at the start of every agent turn, so its round trips are
the shape of the whole product's load: a query added here is multiplied by every
conversation of every member. An audit found one sync issuing ~64 statements
across ~19 transactions, most of it work whose result was discarded — a full
select of memory bodies nothing rendered, two selects per conflict relation,
counts nobody read, and rows read back that the caller had just written.

These tests assert the count stays *bounded* rather than pinning an exact
number: the point is to catch an N+1 or a re-read reappearing, not to churn
whenever a legitimate statement is added. A test failing here means: find out
which statement is new, and whether it scales with the size of the context.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event

from app.api import impl
from app.context import CHARS_PER_TOKEN, compile_context


@contextmanager
def counted(engine):
    """Collect every SQL statement issued on ``engine`` inside the block."""
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _populate(seed, memories: int = 40, conflicts: int = 0) -> list[str]:
    """A context with real content, so per-row costs would show up."""
    ids = []
    for i in range(memories):
        out = seed.store.memories.remember(
            seed.alice, scope="shared", kind="finding",
            summary=f"Finding {i} about the authentication subsystem.",
            details="lorem ipsum " * 200, tags=["auth", "tokens"],
        )
        ids.append(out["memory"].id)
    for i in range(conflicts):
        seed.store.memories.remember(
            seed.bob, scope="shared", kind="decision",
            summary=f"Contradicting decision {i}.", contradicts=[ids[i]],
        )
    return ids


def _sync(seed, ref="chat-cost", **kwargs):
    return impl.sync_context(
        seed.store, seed.bob, task="authentication token design",
        session_ref=ref, **kwargs
    )


# --- the round-trip budget ---------------------------------------------------


def test_a_steady_state_sync_stays_within_its_round_trip_budget(seed):
    """The call every turn makes, on a session that already exists."""
    _populate(seed, memories=40, conflicts=5)
    _sync(seed)  # first call creates the session; measure the one after it

    with counted(seed.store.engine) as statements:
        _sync(seed)

    assert len(statements) <= 14, "\n".join(statements)


def test_a_sync_that_records_a_delta_stays_within_its_budget(seed):
    """The write path adds a memory, its evidence, its version and its audit row.

    Those are real work. What must not come back is a second read of anything
    they wrote.
    """
    _populate(seed, memories=40, conflicts=5)
    _sync(seed, local_context_delta="warm up")

    with counted(seed.store.engine) as statements:
        _sync(seed, local_context_delta="we finished the token rotation work")

    assert len(statements) <= 22, "\n".join(statements)


def test_sync_cost_does_not_grow_with_the_size_of_the_context(seed):
    """A context ten times larger must not cost ten times the round trips.

    This is the property that separates "reads more rows" from "issues more
    queries"; only the second one gets worse as the product succeeds.
    """
    _populate(seed, memories=10)
    _sync(seed, ref="small")
    with counted(seed.store.engine) as small:
        _sync(seed, ref="small")

    _populate(seed, memories=100)
    _sync(seed, ref="big")
    with counted(seed.store.engine) as big:
        _sync(seed, ref="big")

    assert len(big) == len(small), "\n".join(big)


def test_conflicts_do_not_multiply_the_query_count(seed):
    """Each unresolved contradiction used to cost two more selects.

    They are resolved from the candidate list the compiler already loaded, so
    however many there are, the count is unchanged.
    """
    _populate(seed, memories=20, conflicts=0)
    _sync(seed, ref="none")
    with counted(seed.store.engine) as without:
        _sync(seed, ref="none")

    _populate(seed, memories=10, conflicts=10)
    _sync(seed, ref="many")
    with counted(seed.store.engine) as with_conflicts:
        _sync(seed, ref="many")

    assert len(with_conflicts) == len(without), "\n".join(with_conflicts)


def test_a_conflict_outside_the_candidate_list_costs_one_batched_query(seed):
    """The fallback exists because a candidate list is not the whole context.

    A retracted memory is not a candidate, so resolving its contradiction has to
    go to the database — once for all of them together, never once per row.
    """
    ids = _populate(seed, memories=6, conflicts=0)
    for target in ids[:4]:
        seed.store.memories.remember(
            seed.bob, scope="shared", kind="decision",
            summary=f"Objection to {target[:8]}.", contradicts=[target],
        )
        seed.store.memories.retract(seed.alice, target)

    _sync(seed, ref="stale")
    with counted(seed.store.engine) as statements:
        _sync(seed, ref="stale")

    # Statements that fetch whole memory ROWS by id. The resolution ladder also
    # reads memories by id — for the bodies of the ones it renders in full — so
    # "id IN" alone no longer identifies this fallback. That query selects a
    # substring of `details` and nothing else, and would still be one batched
    # statement whatever it selected; what this test is about is the fallback
    # never becoming one lookup per relation.
    lookups = [
        s for s in statements
        if "memories.id IN" in s and "memories.summary" in s
    ]
    assert len(lookups) == 1, "\n".join(statements)


def test_conflicts_are_the_same_pairs_with_or_without_the_candidate_list(seed):
    """The candidate list is a shortcut, not a different answer.

    Callers that do not have one — anything outside the compiler — must still get
    exactly what the two-queries-per-row version returned.
    """
    ids = _populate(seed, memories=8, conflicts=4)
    seed.store.memories.retract(seed.alice, ids[0])  # one pair must drop out
    candidates = seed.store.memories.compile_candidates(
        seed.project_id, seed.bob_user_id
    )

    from_db = seed.store.memories.unresolved_conflicts(
        seed.project_id, seed.bob_user_id, limit=5
    )
    from_candidates = seed.store.memories.unresolved_conflicts(
        seed.project_id, seed.bob_user_id, limit=5, candidates=candidates
    )

    assert [(a.id, b.id) for a, b in from_db] == [
        (a.id, b.id) for a, b in from_candidates
    ]
    assert len(from_db) == 3


def test_a_conflict_never_reveals_another_members_private_memory(seed):
    """The visibility predicate on the fallback is a boundary, not a filter.

    Resolving from candidates is safe because they are already scoped to the
    caller; anything fetched instead has to be scoped again, or a contradiction
    becomes a way to read someone else's private memory.
    """
    secret = seed.store.memories.remember(
        seed.alice, scope="private", kind="note", summary="Alice private plan."
    )["memory"].id
    seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Public counterpart.",
        contradicts=[secret],
    )

    for_alice = seed.store.memories.unresolved_conflicts(
        seed.project_id, seed.alice_user_id, limit=5
    )
    for_bob = seed.store.memories.unresolved_conflicts(
        seed.project_id, seed.bob_user_id, limit=5
    )

    assert len(for_alice) == 1
    assert for_bob == []
    # ...and passing bob's candidates cannot smuggle it in either.
    bob_candidates = seed.store.memories.compile_candidates(
        seed.project_id, seed.bob_user_id
    )
    assert seed.store.memories.unresolved_conflicts(
        seed.project_id, seed.bob_user_id, limit=5, candidates=bob_candidates
    ) == []


# --- the specific wastes that were removed -----------------------------------


def test_the_candidate_query_never_ships_memory_bodies(seed):
    """`details` is capped at 20,000 chars; 750 candidates is up to 15 MB a sync.

    Nothing on this path reads it — ranking excludes it and the compiled line
    renders only the summary — so selecting it was pure transfer cost.
    """
    _populate(seed, memories=5)
    with counted(seed.store.engine) as statements:
        seed.store.memories.compile_candidates(seed.project_id, seed.bob_user_id)

    assert statements and all("memories.details" not in s for s in statements)


def test_the_change_feed_never_ships_memory_bodies_either(seed):
    """Same waste, same reason: both callers render a one-line summary."""
    _populate(seed, memories=5)
    with counted(seed.store.engine) as statements:
        seed.store.memories.changes_since(
            seed.project_id, seed.bob_user_id, None, 0, limit=20
        )

    assert statements and all("memories.details" not in s for s in statements)


def test_a_candidate_carries_no_body_but_is_still_a_whole_record(seed):
    """Dropping a column must not hand back a half-built dataclass."""
    _populate(seed, memories=1)
    candidate = seed.store.memories.compile_candidates(
        seed.project_id, seed.alice_user_id
    )[0]

    assert candidate.details == ""
    assert candidate.summary and candidate.kind and candidate.created_at
    # ...and the body is still there for anyone who actually asks for it.
    full = seed.store.memories.get_memory(
        seed.project_id, candidate.id, seed.alice_user_id
    )
    assert full.details.startswith("lorem ipsum")


def test_a_write_does_not_read_back_the_row_it_just_wrote(seed):
    """Every value was already in hand; the select could only confirm it."""
    with counted(seed.store.engine) as statements:
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="note", summary="A note.",
        )

    reads = [s for s in statements if s.startswith("SELECT") and "FROM memories" in s]
    # Only the quota count survives: that one asks a question the caller cannot
    # answer from what it holds.
    assert all("count(*)" in s for s in reads), "\n".join(reads)


def test_the_returned_memory_matches_what_was_stored(seed):
    """Constructing the record instead of selecting it must not drift from it."""
    out = seed.store.memories.remember(
        seed.alice, scope="private", kind="decision", summary="Ship on Friday.",
        details="because the release train leaves then",
        tags=["release", "schedule"], importance=0.9, confidence=0.8,
        sensitivity="confidential",
    )
    stored = seed.store.memories.get_memory(
        seed.project_id, out["memory"].id, seed.alice_user_id
    )
    built = out["memory"]

    for field, value in vars(stored).items():
        if field in ("created_at", "updated_at"):
            continue  # compared below; SQLite hands timestamps back naive
        assert getattr(built, field) == value, field
    assert built.tags == ["release", "schedule"]
    assert built.owner_user_id == seed.alice_user_id
    assert built.status == "active" and built.version == 1


def test_a_constructed_record_timestamps_the_same_instant(seed):
    """The one difference a constructed record makes, pinned deliberately.

    SQLite drops the timezone on the way back out, so a selected record used to
    report a naive timestamp there while Postgres reported an aware one. Building
    the record keeps the tz-aware value we wrote, which makes the two databases
    agree — the instant is the same either way, and that is what must hold.
    """
    from app.db import ensure_aware

    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="note", summary="Timestamped."
    )
    stored = seed.store.memories.get_memory(
        seed.project_id, out["memory"].id, seed.alice_user_id
    )

    assert out["memory"].created_at == ensure_aware(stored.created_at)
    assert out["memory"].created_at.tzinfo is not None


def test_advancing_the_watermark_is_a_single_statement(seed):
    """Read-then-write also let two syncs of one session lose the higher mark."""
    session = seed.store.sessions.get_or_create(
        seed.project_id, seed.bob_user_id, "chat-wm"
    )
    with counted(seed.store.engine) as statements:
        seed.store.sessions.advance_watermark(session.id, 7, "a task")

    assert len(statements) == 1, "\n".join(statements)
    assert seed.store.sessions.get(session.id).last_seen_revision == 7


def test_the_watermark_still_refuses_to_rewind(seed):
    """The forward-only rule moved into SQL; it must still hold there."""
    session = seed.store.sessions.get_or_create(
        seed.project_id, seed.bob_user_id, "chat-wm"
    )
    seed.store.sessions.advance_watermark(session.id, 9)
    seed.store.sessions.advance_watermark(session.id, 4)

    assert seed.store.sessions.get(session.id).last_seen_revision == 9


def test_advancing_an_unknown_session_is_a_no_op(seed):
    """It used to return early on a missing row; now the UPDATE matches nothing."""
    seed.store.sessions.advance_watermark("no-such-session", 3)

    assert seed.store.sessions.get("no-such-session") is None


def test_the_database_can_return_the_row_an_update_touched(seed):
    """Documents the one dialect assumption the session upsert makes.

    Touch-and-read in a single statement needs UPDATE ... RETURNING: native on
    Postgres, and SQLite from 3.35 (2021), which every Python 3.13 environment
    ships. Asserting it here turns "too old" into one clear failure instead of a
    compile error surfacing inside every sync.
    """
    assert seed.store.engine.dialect.update_returning


def test_reusing_a_session_is_a_single_statement(seed):
    """Every turn of every conversation lands on this path."""
    seed.store.sessions.get_or_create(seed.project_id, seed.bob_user_id, "chat-reuse")

    with counted(seed.store.engine) as statements:
        again = seed.store.sessions.get_or_create(
            seed.project_id, seed.bob_user_id, "chat-reuse"
        )

    assert len(statements) == 1, "\n".join(statements)
    assert again.client_session_ref == "chat-reuse"


def test_reusing_a_session_keeps_its_identity_and_watermark(seed):
    """Touching the row must not lose what the sync watermark is for."""
    first = seed.store.sessions.get_or_create(
        seed.project_id, seed.bob_user_id, "chat-same", agent_connection_id=seed.bob_conn
    )
    seed.store.sessions.advance_watermark(first.id, 5, "earlier task")
    second = seed.store.sessions.get_or_create(
        seed.project_id, seed.bob_user_id, "chat-same", agent_connection_id=seed.bob_conn
    )

    assert second.id == first.id
    assert second.last_seen_revision == 5
    assert second.project_id == seed.project_id
    assert second.user_id == seed.bob_user_id


def test_the_snapshot_and_its_audit_row_commit_together(seed):
    """They describe the same event; two transactions could keep only one."""
    _populate(seed, memories=3)
    session = seed.store.sessions.get_or_create(
        seed.project_id, seed.bob_user_id, "chat-snap"
    )
    with counted(seed.store.engine) as statements:
        out = compile_context(seed.store, seed.bob, session, "auth")

    writes = [i for i, s in enumerate(statements) if s.startswith("INSERT")]
    assert len(writes) == 2 and writes[1] == writes[0] + 1, "\n".join(statements)
    assert seed.store.snapshots.get(out["snapshot_id"]) is not None


# --- budget accounting -------------------------------------------------------


def test_the_empty_context_note_is_shown_when_there_is_room(seed):
    """An agent must be told the context is empty, not handed a blank section."""
    session = seed.store.sessions.get_or_create(
        seed.project_id, seed.bob_user_id, "chat-empty"
    )
    text = compile_context(seed.store, seed.bob, session, "anything")["context_text"]

    assert "(shared memory is empty or no relevant items were found)" in text


def test_the_empty_context_note_is_charged_to_the_budget(seed):
    """It was appended without being counted, so the one case where nothing fit
    was also the one case where the text could overrun the budget it reported.

    The task is sized from a probe rather than hard-coded, so this keeps testing
    the note against the last free character of the budget however the header and
    the footer are worded later.
    """
    note = "(shared memory is empty or no relevant items were found)"
    session = seed.store.sessions.get_or_create(
        seed.project_id, seed.bob_user_id, "chat-tight"
    )
    probe = compile_context(
        seed.store, seed.bob, session, "x", budget_tokens=20000
    )["context_text"]
    fixed = len(probe) - 1 - (len(note) + 1)  # everything but the task and note

    budget_chars = 500 * CHARS_PER_TOKEN
    result = compile_context(
        seed.store, seed.bob, session,
        "a" * (budget_chars - fixed - len(note)),
        budget_tokens=500,
    )

    assert "(shared memory is empty" not in result["context_text"]
    assert len(result["context_text"]) <= budget_chars

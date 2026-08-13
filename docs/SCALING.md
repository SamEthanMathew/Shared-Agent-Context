# Scaling: what was measured, and what it showed

Osmos worked for two people. This records what happened when the read paths, the
growth curves, and the runtime configuration were audited against the question
"does this hold up when strangers sign up and build their own groups", and what
the numbers said afterwards.

Reproduce any of it with `scripts/seed_load.py` (never against production — the
script refuses a Render-looking `DATABASE_URL`).

```bash
DATABASE_URL="sqlite:///./load.db" python scripts/seed_load.py \
    --users 500 --contexts 800 --memories 40000 --snapshots 10000
DATABASE_URL="sqlite:///./load.db" python scripts/seed_load.py --measure-only
```

## The finding that mattered most

`list_user_contexts` — which powers `/v1/me` on every page load and
`sac_list_contexts` for every agent that asks — counted members with a `GROUP BY`
carrying **no `WHERE` clause**. It aggregated every membership row in the
database and built a Python dict of every project in it, then used five entries.

The answer was always correct. That is what made it invisible: the only symptom
was cost, and the cost was proportional to *total tenants* rather than to the
caller. Scoping it to the caller's own project ids — which the preceding query
already had in hand — gives:

| contexts in DB | memberships | before | after | speedup |
|---|---|---|---|---|
| 800 | 3,233 | 1.28 ms | 0.67 ms | 1.9× |
| 4,000 | 16,076 | 7.06 ms | 1.10 ms | 6.4× |
| 12,000 | 47,957 | 21.03 ms | 1.91 ms | **11×** |

The speedup is not the point; the **slope** is. The old version grew roughly
linearly with total memberships — 15× the rows, 16× the time — so it would keep
getting worse for every user forever, on the most-hit endpoint in the product.
The new version is nearly flat.

This is also why the test for it (`tests/test_scaling_limits.py`) inspects the
emitted SQL rather than the returned value. The value is identical either way, so
a value-based test would let the regression back in silently.

## Ranking was tokenising the wrong field

`rank()` built `summary + details + tags + kind` and regex-tokenised it for up to
750 candidates on every sync. `details` is capped at 20,000 characters.

| | 750 candidates, 1.7 MB of details |
|---|---|
| before (tokenising `details`) | 48.48 ms |
| after (`summary + tags + kind`) | 3.69 ms |
| | **13× faster per sync** |

Cheaper *and* more correct: the compiled context renders only the summary, so a
match found in a body could select a memory whose visible line never mentions the
task. The full test suite also got about 35% faster.

## The compile query now uses an index for its sort

`compile_candidates` filters on `(project_id, status)` then orders by revision to
take the newest slice. `ix_memories_compile` covered the filter but not the sort,
so every matching row was read and sorted. After adding
`(project_id, status, revision)`:

```
EXPLAIN QUERY PLAN
  SEARCH memories USING INDEX ix_memories_compile_rev (project_id=? AND status=?)
```

## Current hot-path timings

500 users, 800 contexts, 40,000 memories, 10,000 sync records; busiest context
holding 5,356 memories. SQLite, one laptop — useful for comparison between runs,
not as an absolute.

| Query | Time |
|---|---|
| `list_user_contexts` (powers `/v1/me`) | 0.73 ms |
| `resolve_context_ref` (every tool call) | 0.43 ms |
| `compile_candidates` (busiest context) | 13.05 ms |
| `rank` (750 candidates) | 3.70 ms |
| `list_memories` (100) | 1.56 ms |
| snapshots for one user | 0.42 ms |
| `count_memories` | 1.14 ms |

`compile_candidates` is now the most expensive read, which is the right shape: it
is the one query that has to look at a whole context.

## Things that were checked and found sound

Worth recording so nobody re-spends the time:

- **Identity does not cross between concurrent callers.** MCP tools and REST
  handlers are synchronous, so they run in anyio worker threads, and the SDK
  carries the verified token in a contextvar that anyio copies into the worker.
  This is two libraries composing correctly — true today, and the kind of thing
  that fails quietly if a dependency changes it — so
  `tests/test_concurrency.py` asserts it directly with interleaved requests from
  three accounts.
- **A saturated connection pool queues rather than failing.** 120 concurrent
  requests through a pool of 20 all return 200.
- **Concurrent writes get distinct revisions.** Allocation takes a row lock per
  context; a duplicate would break the uniqueness constraint and make the change
  feed skip an entry.
- **`resolve_identity` is a single indexed lookup** on the memberships primary
  key, not a scan.
- **`resolve_context_ref` is scoped to the caller's memberships**, so a name can
  never resolve into another tenant's context.

## Capacity settings

The two pools are derived from one number, because they were previously in
disagreement: anyio's thread pool defaulted to ~40 while SQLAlchemy's connection
pool defaulted to 15, and since every handler here is synchronous and holds a
connection, the surplus threads simply queued on checkout. The process accepted
more concurrency than the database could serve — which shows up as latency, not
as an error anyone would look for.

| Setting | Default | Note |
|---|---|---|
| `SAC_DB_POOL_SIZE` | 10 | |
| `SAC_DB_MAX_OVERFLOW` | 10 | Their sum also caps the worker-thread pool. |
| `SAC_DB_POOL_RECYCLE` | 280 s | Below Render's idle timeout. |
| `SAC_DB_POOL_TIMEOUT` | 30 s | Fail clearly instead of hanging. |

**Before scaling out**, confirm the Postgres plan's `max_connections`:
`(pool_size + max_overflow) × web instances + the reaper` has to fit under it.

## Known ceilings

- **A sync ranks at most `SAC_COMPILE_CANDIDATE_LIMIT` (750) live memories.** Past
  that it considers the most recent slice, and now says so — the response carries
  `candidates_truncated` and the sync record logs
  `beyond_candidate_window`. Recall degrading as a context grows should be
  visible rather than mysterious. Compaction remains deliberately out of scope.
- **A context is capped at `SAC_MAX_MEMORIES_PER_CONTEXT` (50,000) live
  memories.** This quota existed but was never enforced; it is now.
- **One web instance.** The pool sizing makes horizontal scaling a configuration
  change rather than a rewrite, but it needs real traffic to justify.

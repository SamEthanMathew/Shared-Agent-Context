# Shared Agent Context

**Shared Agent Context (SAC) is a model-agnostic shared memory and context layer for AI agents.**

It gives multiple people and multiple AI systems a persistent project brain that survives across accounts, chats, IDEs, and model providers.

> **Models are replaceable. Project knowledge should persist.**

## Runnable V1 — core engine + privacy

The repository contains a runnable, deployable V1: the full core engine with
server-enforced privacy, not the stripped-down proof.

It answers the hypothesis:

> **Can one ChatGPT-side account and one Claude-side account work independently while continuously benefiting from project knowledge produced by the other — with real identity and privacy?**

V2 adds **multiple named shared contexts**: create one, switch between them from
chat, and share them by email at view / edit / manage access. Twelve MCP tools —
four to manage which context you're in (`sac_list_contexts`,
`sac_create_context`, `sac_use_context`, `sac_context_info`) and eight to use
it. Every response states the active context, and public signup with email
verification means collaborators can join themselves. Sharing is deliberately
human-only: an agent can never grant anyone access.

V1 implements:

- **Verified identity** — in-service OAuth 2.1 authorization server (auth-code +
  PKCE + dynamic client registration + CIMD), per-client connections, revocable
  tokens. The model is never the authorization layer.
- **Private + shared scopes** — permission filtering happens in SQL *before*
  context is compiled; a model never receives memory it isn't authorized for.
- **Provenance & history** — evidence events, memory versions, supersession,
  minimal conflict surfacing, an audit log, and context snapshots that double as
  privacy manifests.
- **Human control plane** — `/console` to inspect memories, members, and the
  audit feed, and to retract memories; `/auth/connections` to revoke clients.
- **One deterministic engine** — lexical + type + importance + recency ranking
  (no embeddings yet), monotonic per-project revisions, model-sized compiled
  context.
- One Python service; PostgreSQL in deployment, SQLite locally; MCP v2 +
  REST/OpenAPI over the same backend.

See [`docs/SETUP.md`](docs/SETUP.md) for deploy, client wiring, and the
two-account acceptance test.

The runtime model is:

```text
Person A / ChatGPT                        Person B / Claude
┌──────────────────────┐                 ┌──────────────────────┐
│ Native chat context  │                 │ Native chat context  │
│ provider-owned       │                 │ provider-owned       │
└──────────┬───────────┘                 └──────────┬───────────┘
           │                                        │
           │ sync / publish              sync / publish
           └──────────────────┐    ┌────────────────┘
                              ▼    ▼
                        ┌──────────────┐
                        │  SHARED SAC  │
                        │              │
                        │ revision log │
                        │ decisions    │
                        │ findings     │
                        │ constraints  │
                        │ results      │
                        └──────┬───────┘
                               │
                       context compiler
                               │
                 task/model-sized working view
```

The shared pool can keep growing while each model receives only a bounded, task-relevant view.

### Always-on sync loop

While SAC is enabled, the intended agent behavior is:

```text
user turn
   ↓
sac_sync
   ↓
native provider context + current SAC context
   ↓
model researches / builds / reasons
   ↓
sac_publish durable project knowledge
   ↓
answer user
   ↓
other account receives the update on its next sync
```

`sac_sync` also accepts a concise `local_context_delta` from the previous local turn, so a long-running provider-native conversation can continuously contribute knowledge to SAC without copying its entire transcript.

### V1 endpoints

One service exposes both integration surfaces plus the OAuth and control planes:

```text
/mcp                          MCP v2 Streamable HTTP
/v1/projects/{id}/context/sync    REST equivalent of sac_sync_context
/v1/projects/{id}/memories/shared REST remember_shared (…/private for private)
/v1/projects/{id}/memories        list; /{mid} rehydrate one memory
/v1/projects/{id}/changes         recent changes
/.well-known/oauth-*          OAuth discovery (RFC 8414 / 9728)
/authorize /token /register   OAuth authorization-code + PKCE + DCR
/auth/login /auth/consent     human login + consent
/auth/connections             connected clients + revoke
/console                      project view: memories, members, audit, retract
/openapi.json                 ChatGPT Action schema (with servers block)
/health                       liveness
```

MCP tools:

```text
sac_project_info      sac_recent_changes
sac_sync_context      sac_get_source
sac_remember_shared   sac_get_memory
sac_remember_private  sac_status
```

### Current test status

GitHub Actions validates:

1. database-backed shared-memory writes and revision tracking;
2. Person A → Person B context handoff;
3. the official MCP Python SDK v2 client calling SAC tools in-process;
4. Uvicorn serving the application over HTTP;
5. a real MCP v2 client connecting to `/mcp` over Streamable HTTP;
6. Person A publishing a memory over MCP and Person B receiving it through `sac_sync`.

See [`docs/V0_MCP_PROTOTYPE.md`](docs/V0_MCP_PROTOTYPE.md) for deployment and two-account setup.

## The Problem

AI collaboration is fragmented.

A team might use ChatGPT for research, Claude for reasoning, Codex or Claude Code for implementation, GitHub for source control, and Notion or Docs for documentation. Each system develops a different partial view of the project.

This creates:

1. **Context fragmentation** — each agent has incomplete project knowledge.
2. **Duplicated work** — agents repeat research and decisions already completed elsewhere.
3. **Project drift** — collaborators act on stale assumptions.
4. **Vendor lock-in** — useful project knowledge becomes trapped inside one product/account.
5. **Weak agent handoff** — one agent's work does not naturally improve another agent's next task.

## The Long-Term Model

SAC separates four concepts that are often collapsed together:

```text
conversation working state
        ≠
personal/provider memory
        ≠
shared durable project memory
        ≠
model inference context window
```

SAC owns the durable **project-memory** layer and compiles relevant project state into each model's finite inference context.

The long-term architecture is roughly:

```text
ChatGPT ─┐
Claude  ─┤
Codex   ─┤
Claude  ─┤
Code     │
Gemini  ─┤          ┌──────────────────────────────┐
Local AI ┼─────────▶│     Shared Agent Context     │
Other    ─┘          │                              │
                     │ Evidence / event history     │
GitHub   ───────────▶│ Governed memory store        │
Notion   ───────────▶│ Revisions + provenance       │
Docs     ───────────▶│ Retrieval indexes            │
Other    ───────────▶│ Context compiler             │
                     │ Compaction / semantic paging │
                     └──────────────┬───────────────┘
                                    │
                         task/model-specific context
```

## Key Architectural Principles

### Project memory lives outside the models

A model's native context window, tokenizer, hidden state, KV cache, or provider conversation object is never canonical SAC state.

### Same knowledge does not mean same prompt

Different models can have different supported and effective context sizes. SAC can compile 8K tokens for one client and 40K for another while both views come from the same project truth.

### Context is compiled, not accumulated

SAC should retrieve, rank, resolve, compact, and pack the smallest sufficient working set for the current task rather than blindly filling the largest context window available.

### Compaction is projection, not deletion

The project history can continue growing externally while active model context is compacted. Raw evidence remains addressable so a compact view can later be re-hydrated for a larger model or a task that needs more detail.

### Provenance and time matter

Eventually a project brain must know not only *what* it believes, but who said it, when it was valid, what superseded it, and where the evidence came from.

### Permissions happen before inference

The production architecture must filter data before it reaches a model. The current two-account V0 intentionally postpones this layer to test the core shared-context hypothesis first.

## V1 Storage and Retrieval

The engine uses a full relational model (see `app/db.py`): `users`, `projects`,
`memberships`, `agent_connections`, `sessions`, `evidence_events`, `memories`
(with `scope`, `status`, `sensitivity`, versions), `memory_versions`,
`memory_relations`, `context_snapshots`, `audit_events`, plus the OAuth tables
(`oauth_clients`, `authorization_codes`, `oauth_tokens`, …).

Every accepted shared memory increments a project revision:

```text
r41  Person A finding
r42  Person A decision
r43  Person B result
r44  Person A constraint
```

Each session tracks the latest revision it has seen. `sac_sync` therefore combines:

```text
what changed since this session last synced
+
what existing shared memories are relevant to the current task
```

V0 ranking intentionally stays simple:

```text
lexical relevance
+ memory-type weight
+ importance
+ recency
```

This lets us test the product hypothesis before adding embeddings, rerankers, graphs, hierarchical summaries, provider tokenizers, or learned memory extraction.

## Deployment Shape

The included `render.yaml` defines a small Python web service and PostgreSQL database. The application can also run locally with SQLite.

```text
app/main.py      FastAPI + MCPServer v2 assembly, OAuth wiring
app/db.py        full schema (engine + auth tables)
app/stores/      projects, memories, sessions, snapshots, audit
app/context.py   context compiler v2 (scoped sections, manifests)
app/api/         impl layer, /v1 REST, MCP tools
app/auth/        OAuth 2.1 provider, token store, login/consent, CLI
app/control.py   human control plane
migrations/      Alembic baseline
```

CI uses the stable MCP Python SDK v2 and runs the unit suite, an Alembic-apply
check, a dev-mode Streamable HTTP smoke test, and a full auth-mode OAuth
end-to-end test.

## MVP Success Criterion

The first proof succeeds when:

1. Person A works in an OpenAI-side chat.
2. That discussion produces reusable project knowledge.
3. SAC records the durable delta without Person A manually copying it to Person B.
4. Person B independently works in Claude.
5. Person B's next SAC sync retrieves the relevant Person A knowledge.
6. Person B produces new reusable knowledge and publishes it.
7. Person A's next sync receives Person B's contribution.
8. Removing SAC makes the cross-account workflow noticeably worse.

The core message remains:

> **Different people. Different agents. Same project brain.**

## Documents

### Build / product

- [`docs/V0_MCP_PROTOTYPE.md`](docs/V0_MCP_PROTOTYPE.md) — **runnable V0**, deployment, ChatGPT/Claude setup, sync loop, acceptance test, and current limitations
- [`docs/V0_PRODUCT_ARCHITECTURE.md`](docs/V0_PRODUCT_ARCHITECTURE.md) — broader first-product architecture beyond the stripped-down proof
- [`docs/MVP.md`](docs/MVP.md) — MVP roadmap and cross-client demo definition
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — general SAC architecture and memory model
- [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md) — product/architecture principles
- [`docs/BUSINESS_PLAN.md`](docs/BUSINESS_PLAN.md) — positioning, market, business model, risks, and GTM

### Context / memory research

- [`docs/RESEARCH_CONTEXT_WINDOWS_AND_MEMORY.md`](docs/RESEARCH_CONTEXT_WINDOWS_AND_MEMORY.md) — context windows, memory systems, collaborative memory, and cross-model interoperability
- [`docs/RESEARCH_EXPANDING_CONTEXT_WINDOWS_2023_2026.md`](docs/RESEARCH_EXPANDING_CONTEXT_WINDOWS_2023_2026.md) — long-context scaling, attention, KV-cache systems, serving, benchmarks, and SAC implications
- [`docs/HIGH_QUALITY_CONTEXT_WINDOW_ARCHITECTURE.md`](docs/HIGH_QUALITY_CONTEXT_WINDOW_ARCHITECTURE.md) — architecture for constructing high-quality task-specific context
- [`docs/CONTEXT_COMPILER.md`](docs/CONTEXT_COMPILER.md) — provider-neutral context compiler and adapter boundary
- [`docs/LONG_CONTEXT_IMPLEMENTATION_GUIDE.md`](docs/LONG_CONTEXT_IMPLEMENTATION_GUIDE.md) — model capability profiles, adaptive budgets, retrieval, semantic paging, caching, and evaluation
- [`docs/DYNAMIC_MODEL_AWARE_CONTEXT_COMPACTION.md`](docs/DYNAMIC_MODEL_AWARE_CONTEXT_COMPACTION.md) — effectively unbounded logical context, `/compact`, `/expand`, re-hydration, semantic paging, and model-aware compaction
- [`docs/PRIVACY_PERMISSION_ARCHITECTURE.md`](docs/PRIVACY_PERMISSION_ARCHITECTURE.md) — researched privacy/permission architecture for later versions; intentionally not implemented in the stripped-down V0 proof

## Working Definition

**Shared Agent Context is a user-owned, model-agnostic shared memory and coordination layer that lets multiple humans and AI agents maintain a consistent understanding of the same project across accounts, applications, and model providers.**

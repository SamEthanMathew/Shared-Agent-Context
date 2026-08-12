# Shared Agent Context

**Shared Agent Context (SAC) is a model-agnostic shared memory and context layer for AI agents.**

It gives multiple people and multiple AI systems a persistent project brain that survives across accounts, chats, IDEs, and model providers.

> **Models are replaceable. Project knowledge should persist.**

## Runnable V0

The repository now contains a runnable two-account proof of concept.

The deliberately narrow V0 tests one hypothesis:

> **Can one ChatGPT-side account and one Claude-side account work independently while continuously benefiting from project knowledge produced by the other?**

V0 removes most product complexity:

- one shared SAC project
- one growing shared memory pool
- no dashboard
- no private SAC memories
- no OAuth/ACL layer yet
- no vector database requirement
- no autonomous orchestration
- one Python service
- PostgreSQL in deployment, SQLite locally
- MCP v2 + REST/OpenAPI over the same backend

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

### V0 endpoints

One service exposes both integration surfaces:

```text
/mcp                 MCP v2 Streamable HTTP
/api/sync            REST equivalent of sac_sync
/api/publish         REST equivalent of sac_publish
/api/memory/{id}     rehydrate one memory
/api/status          shared pool state
/openapi.json        ChatGPT Action schema
/health              liveness
```

Current MCP tools:

```text
sac_sync
sac_publish
sac_get_memory
sac_status
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

## V0 Storage and Retrieval

The current proof uses three tables:

```text
project_counters
memories
sessions
```

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
app/main.py      FastAPI + MCPServer v2
app/store.py     persistence + revision/session state
app/context.py   V0 context compiler
```

CI uses the official stable MCP Python SDK v2 and tests both in-process and Streamable HTTP MCP calls.

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

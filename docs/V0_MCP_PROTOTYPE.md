# SAC V0: Two-Account Shared Context Prototype

**Status:** runnable proof-of-concept  
**Target:** one ChatGPT account + one Claude account sharing one continuously growing SAC pool  
**UI:** none  
**Auth/privacy:** intentionally deferred for the proof

## 1. What V0 Actually Is

For this proof, strip the system down to two context layers:

```text
Person A / ChatGPT                       Person B / Claude
┌─────────────────────┐                 ┌─────────────────────┐
│ Native chat context │                 │ Native chat context │
│ (provider-owned)    │                 │ (provider-owned)    │
└──────────┬──────────┘                 └──────────┬──────────┘
           │                                       │
           │ sync / publish             sync / publish
           └──────────────────┐   ┌────────────────┘
                              ▼   ▼
                       ┌───────────────┐
                       │  SHARED SAC   │
                       │               │
                       │ revision log  │
                       │ durable facts │
                       │ decisions     │
                       │ findings      │
                       │ constraints   │
                       │ results       │
                       └───────┬───────┘
                               │
                        context compiler
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
        compact view for A                compact view for B
```

There is **no private SAC pool in V0**.

The local/private side is simply the model provider's normal conversation context. Anything the enabled agent decides is durable and useful to the project can be published into the shared SAC pool and becomes available to the other account.

This intentionally tests the original thesis before adding privacy/governance complexity.

## 2. The Always-On Sync Loop

The connector is designed around one mandatory tool call and one conditional tool call.

### At the start of each turn

The model calls:

```text
sac_sync(
  actor,
  session_id,
  task,
  local_context_delta,
  budget_tokens
)
```

`local_context_delta` is a short summary of durable knowledge produced during the immediately previous local turn. On the first turn it is empty.

The server:

1. stores the previous local delta, if any;
2. checks the last shared revision seen by this session;
3. finds project updates written by the other account;
4. retrieves task-relevant durable memories;
5. compiles them into the requested context budget;
6. returns that context to the model;
7. advances the session's `last_seen_revision`.

### Before the final answer

If the turn produced durable project knowledge, the model calls:

```text
sac_publish(...)
```

This writes the important result immediately instead of waiting for the next turn.

That produces the loop:

```text
user turn
   ↓
sac_sync
   ↓
native chat context + SAC shared context
   ↓
model researches / builds / reasons
   ↓
sac_publish useful durable result
   ↓
answer user
   ↓
next account sees it on its next sac_sync
```

This is **pull-based real-time sync**: an accepted SAC write is immediately retrievable by the other account. WebSockets are not required for the proof.

## 3. Server Interfaces

One process exposes two client surfaces over the same database and compiler.

```text
/mcp                 Streamable HTTP MCP
/api/sync            REST equivalent of sac_sync
/api/publish         REST equivalent of sac_publish
/api/memory/{id}     rehydrate a memory
/api/status          shared pool status
/openapi.json        generated OpenAPI schema
/health              liveness
```

### Why expose both MCP and REST?

Claude individual accounts currently support custom remote MCP connectors directly.

ChatGPT's direct upload/testing path for unpublished custom MCP apps varies by plan/surface. For a personal paid ChatGPT account, a Custom GPT can use Actions backed by an OpenAPI API.

Therefore the fastest proof is:

```text
Claude  ─────── remote MCP ───────▶ /mcp
                                      │
                                      │ same SAC service/database
                                      │
ChatGPT ─── Custom GPT Action ─────▶ /api/*
```

When direct custom MCP is available on the exact OpenAI surface being tested, ChatGPT can move to `/mcp` without changing the SAC backend.

## 4. Persistence Model

V0 stores only the primitives needed for the experiment.

### `memories`

```text
id
project_id
revision
actor
session_id
kind
summary
details
tags
importance
created_at
```

### `sessions`

```text
project_id
actor
session_id
last_seen_revision
last_task
updated_at
```

### `project_counters`

```text
project_id
revision
```

Each accepted memory increments the single shared revision.

Example:

```text
r41 Person A finding
r42 Person A decision
r43 Person B result
r44 Person A constraint
```

The revision number is how the server knows what a given chat has not seen yet.

## 5. Context Compilation in V0

The full SAC pool is allowed to keep growing.

The active model input is bounded:

```text
logical SAC:              grows over time
active SAC context:       budget_tokens requested by the client
```

V0 retrieval deliberately avoids an embedding dependency.

It combines:

- lexical overlap with the current task;
- memory type weighting;
- explicit importance;
- recency;
- all unseen recent changes for the session.

The response is packed until the approximate token budget is reached.

This is intentionally simple. It lets us test whether cross-account context changes real work before optimizing vector retrieval, graph retrieval, compaction, reranking, or learned memory.

## 6. Deploy

The repository contains a `render.yaml` Blueprint with:

- one Python web service;
- one Postgres database;
- the correct Uvicorn start command;
- `/health` health check;
- `DATABASE_URL` wiring.

Create a Render Blueprint from this repository.

After deployment, save the public URL as:

```text
SAC_BASE_URL=https://<your-render-host>
```

Verify:

```text
GET <SAC_BASE_URL>/health
```

Expected shape:

```json
{
  "ok": true,
  "project_id": "sac-v0",
  "revision": 0
}
```

The remote MCP endpoint is:

```text
<SAC_BASE_URL>/mcp
```

The ChatGPT Action schema is:

```text
<SAC_BASE_URL>/openapi.json
```

### V0 warning

The service has **no authentication**. Anyone who discovers the deployment URL can call it. Use it only for the proof with non-sensitive project information.

## 7. Claude Setup

In Claude:

```text
Customize
→ Connectors
→ +
→ Add custom connector
```

Enter:

```text
Name: Shared Agent Context V0
URL:  <SAC_BASE_URL>/mcp
```

No OAuth is required for this V0.

Enable the connector in the project/research chat.

### Claude bootstrap instruction

Use this as the project/chat instruction for Person B:

```text
You are Person B in a Shared Agent Context V0 experiment.

SAC is an always-on shared project memory. While this connector is enabled:

- Use actor="person_b".
- Use session_id="claude-main" for this workstream.
- At the beginning of EVERY user turn, before substantive reasoning, call sac_sync.
- Pass the current user request as task.
- On the first turn, local_context_delta="".
- On later turns, local_context_delta must concisely summarize durable project knowledge
  produced in your immediately previous response.
- Use budget_tokens=3000 unless the task clearly needs more or less.
- Treat the returned SAC context as shared project memory and use it when relevant.
- Before your final response, call sac_publish for any reusable finding, decision,
  requirement, constraint, result, or observation another collaborator should know.
- Do not ask whether to sync or publish. Do it automatically.
- Do not dump the entire conversation into SAC; publish durable project knowledge.
```

## 8. ChatGPT Setup

For a personal paid ChatGPT account, create a Custom GPT.

In the GPT editor:

1. Add the bootstrap instructions below.
2. Add an Action.
3. Configure authentication as `None`.
4. Import the schema from:

```text
<SAC_BASE_URL>/openapi.json
```

### ChatGPT bootstrap instruction

```text
You are Person A in a Shared Agent Context V0 experiment.

SAC is an always-on shared project memory. For every message in this GPT:

- Use actor="person_a".
- Use session_id="chatgpt-main" for this workstream.
- BEFORE substantive reasoning on every user turn, call the /api/sync action.
- Pass the current user request as task.
- On the first turn, local_context_delta="".
- On later turns, local_context_delta must concisely summarize durable project knowledge
  produced in your immediately previous response.
- Use budget_tokens=3000 unless the task clearly needs more or less.
- Incorporate the returned context_text as shared project context.
- Before your final answer, call /api/publish when the turn produced any reusable finding,
  decision, requirement, constraint, result, or observation.
- Do not ask me whether to sync or publish. Do it automatically.
- Do not send entire transcripts; publish durable project knowledge.
```

The GPT Action interface can show action activity/approval UI. That means V0 is designed to be *behaviorally always-on*, not necessarily visually invisible on every current product surface.

## 9. Two-Account Acceptance Test

### Step A — ChatGPT

Ask Person A's GPT:

```text
Research the best storage model for our first shared-context prototype.
We want something simple and durable.
```

ChatGPT should sync, research, and publish useful findings.

Check:

```text
GET <SAC_BASE_URL>/api/status
```

Revision should be greater than zero.

### Step B — Claude

In Person B's Claude chat, ask:

```text
Design the data model for our shared-context prototype.
```

Claude should call `sac_sync` automatically and receive Person A's relevant findings without manual copy/paste.

Claude should publish its own design/result.

### Step C — ChatGPT again

Ask:

```text
Now turn the storage research into an implementation plan.
```

ChatGPT's next `/api/sync` should include Claude's new shared changes.

### Success criterion

The proof succeeds when each account independently produces work that changes the other account's later reasoning without a human transferring the information.

## 10. What "Always-On" Means in V0

The current account products still control tool invocation.

MCP gives a model a callable tool surface; it is not a passive packet sniffer for the full consumer-chat transcript.

Therefore V0 gets as close as possible by combining:

1. strong server-level MCP instructions;
2. client/bootstrap instructions that require a sync every turn;
3. one `sac_sync` call that both uploads the previous local delta and downloads shared state;
4. `sac_publish` for immediate durable results.

A future truly invisible integration can add provider lifecycle hooks, client wrappers, or first-class plugin runtime hooks when available.

The server/data model does not need to change.

## 11. Deliberately Deferred

Do **not** block the proof on:

- private vs shared memory;
- OAuth;
- user accounts;
- ACLs;
- UI/dashboard;
- embeddings;
- vector DB;
- memory approval;
- conflict-resolution UX;
- sophisticated `/compact`;
- graph memory;
- WebSockets;
- provider-native personal memory;
- perfect automatic extraction.

The existing research documents describe how those should evolve after V0.

## 12. Immediate V0 Limitations

- Tool invocation is model-controlled, so "every turn" is prompted behavior rather than a guaranteed host lifecycle callback.
- The active context compiler uses approximate token accounting (`~4 chars/token`) rather than provider tokenizers.
- Retrieval is lexical + metadata based.
- The server trusts model-generated summaries.
- No deduplication or supersession logic yet.
- No auth or privacy boundaries.
- No server-side LLM extraction.
- Free hosting can introduce cold-start latency depending on the platform.

These are acceptable for the proof because none prevents testing the central hypothesis.

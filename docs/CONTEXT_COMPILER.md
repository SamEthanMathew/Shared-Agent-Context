# Shared Agent Context: Context Compiler

This document translates the findings in [`RESEARCH_CONTEXT_WINDOWS_AND_MEMORY.md`](RESEARCH_CONTEXT_WINDOWS_AND_MEMORY.md) into a concrete cross-model boundary for Shared Agent Context (SAC).

## Core Rule

> **Never make a model's native context representation the canonical representation of project knowledge.**

OpenAI, Anthropic, Google, Meta-hosted models, local models, and future sequence architectures can differ in tokenization, context limits, multimodal accounting, tool formats, position mechanisms, and inference internals.

SAC should therefore maintain project state in a model-neutral representation and compile a task-specific view into the target model's context at runtime.

## Mental Model

```text
                         PROJECT HISTORY
                chats / files / commits / events
                               │
                               ▼
                     ┌───────────────────┐
                     │   Evidence Store  │
                     └─────────┬─────────┘
                               │ extract / normalize
                               ▼
                     ┌───────────────────┐
                     │   Memory Store    │
                     │ decisions / facts │
                     │ tasks / status    │
                     └─────────┬─────────┘
                               │
                  indexes + relationships
                               │
                               ▼
                     ┌───────────────────┐
                     │ Context Compiler  │
                     │                   │
                     │ auth              │
                     │ retrieve          │
                     │ resolve truth     │
                     │ rank              │
                     │ compress          │
                     │ budget            │
                     └─────────┬─────────┘
                               │
                    Model-neutral envelope
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       OpenAI Adapter    Anthropic Adapter   Gemini Adapter
              │                │                │
              ▼                ▼                ▼
         OpenAI model       Claude          Gemini model
```

## Context Compiler Responsibilities

### 1. Authorization

Before retrieval reaches a model:

- identify the human user
- identify the acting client/agent
- verify project membership
- apply project role/scope rules
- apply memory/resource-level restrictions

The model is never the security boundary.

### 2. Task Understanding

The compiler interprets the current task to identify:

- relevant project entities
- components/files
- likely memory categories
- desired abstraction level
- time horizon
- environment/branch

Example:

```text
Task:
"Implement secure credential storage on Windows"

Likely retrieval targets:
- desktop auth decisions
- Windows-specific constraints
- security requirements
- relevant implementation artifacts
- recent auth changes
```

### 3. Candidate Retrieval

Use a hybrid strategy rather than one vector query:

- structured SQL filters
- lexical / full-text search
- dense semantic retrieval
- recent-change lookup
- relationship expansion
- optional hierarchical summary retrieval

The retrieval layer should be replaceable and evaluation-driven.

### 4. State Resolution

Retrieval finds candidate evidence. The compiler must decide what represents current project state.

Use:

- `valid_from`
- `valid_until`
- `status`
- `supersedes`
- `contradicts`
- authority
- confidence
- branch/environment

Example:

```text
memory_10
"API pagination uses page numbers"
valid_until: 2026-08-03
superseded_by: memory_48

memory_48
"API pagination uses opaque cursors"
valid_from: 2026-08-03
status: active
```

A current implementation task should primarily receive `memory_48`, while provenance can still expose the historical change.

### 5. Context Ranking

Candidate ranking should optimize final task utility, not simply similarity.

Candidate signals include:

```text
semantic relevance
lexical relevance
authority
importance
current temporal validity
recency when relevant
explicit component/task match
graph relationship distance
source quality
redundancy
```

### 6. Multi-Resolution Compression

A project brain can become much larger than any context window.

Return the smallest useful representation:

1. canonical memory statement
2. short source/provenance handle
3. additional evidence only if task needs it
4. artifact identifier instead of full artifact when the agent can fetch it on demand

Broad questions can receive project/section summaries. Narrow implementation questions can receive detailed decisions and evidence.

### 7. Token Budgeting

The compiler should **not** fill the target model's advertised context limit.

Reserve capacity for:

- client/system instructions
- tool definitions
- current conversation
- user task
- tool results
- output/reasoning needs

Then allocate a bounded SAC budget.

Example policy:

```text
model maximum:              1,000,000
client-reserved capacity:     100,000
maximum allowed SAC budget:    20,000
actual retrieved SAC context:   6,400
```

The important number is the 6,400 tokens actually needed, not the 1M maximum.

### 8. Provider Serialization

Each provider adapter receives the same semantic envelope but may serialize it differently.

Adapters can control:

- tokenizer/token estimate
- context cap
- instruction placement
- Markdown/XML/JSON formatting
- tool-result formatting
- multimodal references
- provider-specific prompt caching hints

Provider formatting is an optimization layer, not the project data model.

## Model-Neutral Context Envelope

Proposed V0:

```json
{
  "schema_version": "0.1",
  "project_id": "proj_123",
  "request": {
    "user_id": "user_matthew",
    "agent_id": "agent_claude_windows",
    "task": "Implement secure credential storage on Windows"
  },
  "memories": [
    {
      "id": "mem_312",
      "type": "decision",
      "content": "Desktop clients use OS-native secure credential stores.",
      "status": "active",
      "authority": "approved_decision",
      "valid_from": "2026-08-09T00:00:00Z",
      "provenance_id": "src_882"
    },
    {
      "id": "mem_313",
      "type": "constraint",
      "content": "The Windows client uses Windows Credential Manager.",
      "status": "active",
      "authority": "approved_decision",
      "provenance_id": "src_883"
    }
  ],
  "conflicts": [],
  "recent_changes": [],
  "artifacts": [
    {
      "id": "artifact_auth_spec",
      "kind": "document",
      "fetchable": true
    }
  ],
  "budget": {
    "provider": "anthropic",
    "model": "target-model-id",
    "max_sac_tokens": 8000
  }
}
```

The envelope is not necessarily the exact public API shape. It defines the semantic boundary.

## Provider Adapter Interface

Possible interface:

```text
interface ProviderAdapter {
    capabilities(model_id) -> ModelCapabilities
    estimate_tokens(content, model_id) -> int
    serialize_context(envelope, model_id) -> ProviderContext
}
```

`ModelCapabilities` can include:

```text
provider
model_id
max_input_tokens
max_output_tokens
modalities
supports_tools
supports_structured_output
supports_mcp
context_format_preferences
```

Do not hard-code model limits permanently. Provider capabilities change frequently.

## Embedding Boundary

Embeddings belong to the retrieval index, not the canonical memory.

Store:

```text
memory_id
embedding_provider
embedding_model
embedding_version
vector
created_at
```

This makes it possible to rebuild an index when:

- changing embedding providers
- upgrading models
- adding a domain-specific embedding model
- running A/B retrieval evaluations

Never assume vectors produced by unrelated embedding models are directly comparable.

## On-Demand Evidence

The Context Compiler should support progressive disclosure.

Initial recall can return:

```text
Decision: Windows secrets use Credential Manager.
Evidence: src_883
Artifact: auth-spec (fetchable)
```

If the agent needs implementation details, it can call:

```text
sac.get_source(src_883)
sac.get_artifact(auth-spec)
```

This keeps working context small while preserving access to detail.

## MCP Interface

MCP is an ideal first adapter for agent clients.

Suggested tools:

```text
sac.project_info()
sac.recall(task, budget?)
sac.remember(type, content, source?)
sac.search(query, filters?)
sac.recent_changes(since?)
sac.get_memory(memory_id)
sac.get_source(source_id)
sac.propose_decision(...)
```

The MCP implementation calls the same underlying SAC API used by SDKs and future adapters.

## Future A2A Integration

A2A should not replace the shared memory store.

Instead an A2A task can carry a lightweight SAC reference:

```json
{
  "task": "Implement Windows authentication",
  "sac": {
    "project_id": "proj_123",
    "context_snapshot_id": "ctx_991"
  }
}
```

The receiving agent resolves authorized project context from SAC.

This keeps agent communication separate from durable project truth.

## Snapshotting

For reproducibility, SAC should eventually be able to create an immutable context snapshot:

```text
context_snapshot
- id
- project_id
- query/task
- actor
- memory IDs + versions
- provider/model target
- serialized token count
- created_at
```

This allows the team to answer:

> "What project context did this agent actually receive when it made this decision?"

That is valuable for debugging, auditing, and evaluations.

## Evaluation Contract

The Context Compiler should be benchmarked on:

- task success
- memory recall
- memory precision
- stale-memory rate
- conflict preservation
- authorization leakage rate (must be zero)
- context tokens used
- retrieval latency
- cross-provider consistency

A central metric should be:

> **task success at the smallest reliable injected context size**

not maximum context utilization.

## MVP Implementation Order

1. model-neutral memory schema
2. explicit `remember`
3. hybrid `recall`
4. provenance IDs
5. simple Context Envelope
6. one generic Markdown serializer
7. MCP adapter
8. second independent AI client/provider
9. provider-specific token-budget adapters
10. context snapshots/evals

The first version does not need automatic memory extraction or graph retrieval to prove the architecture.

## Architectural Test

For every new feature ask:

> If we replace the acting model/provider tomorrow, can the same project memory still be retrieved and understood without migration of the canonical data?

If the answer is no, the feature is probably coupled at the wrong layer.

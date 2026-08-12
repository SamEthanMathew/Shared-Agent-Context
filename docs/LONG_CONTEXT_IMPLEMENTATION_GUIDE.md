# Long-Context Implementation Guide for Shared Agent Context

This document turns the research in [`RESEARCH_EXPANDING_CONTEXT_WINDOWS_2023_2026.md`](RESEARCH_EXPANDING_CONTEXT_WINDOWS_2023_2026.md) into a concrete implementation plan.

## Core Decision

SAC should **not** attempt to make every model consume the same amount of context, and it should not attempt to literally synchronize model-native context windows.

The implementation target is:

```text
persistent project state
        ↓
model-neutral Context Compiler
        ↓
task-specific Context Envelope
        ↓
provider/model adapter
        ↓
bounded model-native context
```

The key rule is:

> **Use larger model windows as additional execution capacity, not as a replacement for memory management.**

---

# 1. Services

A first production architecture can be split into these logical services/modules:

```text
Identity / Authorization
Evidence Ingestion
Memory Manager
Relationship Resolver
Retrieval Service
Context Compiler
Model Capability Registry
Provider Adapters
Context Trace / Observability
Evaluation Harness
```

They do not need to be separate deployments initially. They can live in one backend while maintaining clean interfaces.

---

# 2. Data Plane

## 2.1 Evidence

Canonical raw/versioned source records.

```sql
create table evidence (
    id uuid primary key,
    project_id uuid not null,
    source_type text not null,
    source_uri text,
    source_version text,
    content_hash text,
    content_type text,
    content text,
    observed_at timestamptz not null,
    actor_user_id uuid,
    actor_agent_id uuid,
    trust_tier integer not null,
    metadata jsonb not null default '{}'
);
```

## 2.2 Memory

Normalized durable project knowledge.

```sql
create table memories (
    id uuid primary key,
    project_id uuid not null,
    type text not null,
    subject text,
    title text,
    content text not null,
    status text not null,
    confidence real,
    authority_type text,
    authority_actor_id uuid,
    valid_from timestamptz,
    valid_to timestamptz,
    created_at timestamptz not null,
    updated_at timestamptz not null,
    metadata jsonb not null default '{}'
);
```

## 2.3 Relations

```sql
create table memory_relations (
    from_id uuid not null,
    to_id uuid not null,
    relation_type text not null,
    metadata jsonb not null default '{}',
    primary key (from_id, to_id, relation_type)
);
```

Initial relation types:

```text
derived_from
supports
contradicts
supersedes
refines
depends_on
blocks
implements
applies_to
```

## 2.4 Provenance

Memory-to-evidence relationships should be explicit. Do not make provenance a free-form text field.

---

# 3. Model Capability Registry

Create a table/service describing model capabilities.

```sql
create table model_profiles (
    id uuid primary key,
    provider text not null,
    model text not null,
    observed_at timestamptz not null,
    provider_capabilities jsonb not null,
    economic_profile jsonb not null default '{}',
    sac_profile jsonb not null default '{}',
    unique(provider, model, observed_at)
);
```

Example provider capabilities:

```json
{
  "max_input_tokens": 1000000,
  "max_output_tokens": 128000,
  "token_counter": true,
  "prompt_caching": true,
  "tools": true,
  "structured_output": true,
  "modalities": ["text", "image"]
}
```

Example SAC-derived profile:

```json
{
  "effective_context": {
    "exact_retrieval": {
      "ec95": 250000
    },
    "repository_reasoning": {
      "ec95": 100000
    },
    "temporal_conflict_resolution": {
      "ec95": 64000
    }
  },
  "default_compiler_budget": 24000,
  "preferred_ordering_policy": "authority_then_evidence",
  "preferred_compression_policy": "extractive_first"
}
```

The effective values are measured by SAC, not copied from provider marketing.

---

# 4. Context Compilation Request

```json
{
  "project_id": "project_123",
  "principal": {
    "user_id": "user_123",
    "agent_id": "agent_456"
  },
  "task": {
    "type": "code_change",
    "instruction": "Implement Windows authentication using the current architecture."
  },
  "target": {
    "provider": "anthropic",
    "model": "model-id"
  },
  "slo": {
    "max_cost_usd": 0.25,
    "max_latency_ms": 15000,
    "quality_target": 0.95
  }
}
```

---

# 5. Compilation Pipeline

```text
1. Authenticate user + agent
2. Load project membership / scopes
3. Load target model profile
4. Classify task
5. Determine hard token reserves
6. Generate retrieval queries
7. Retrieve candidates under ACL
8. Expand relations
9. Resolve temporal validity
10. Resolve supersession
11. Preserve unresolved conflicts
12. Rank candidates
13. Deduplicate
14. Choose resolution per candidate
15. Compress where appropriate
16. Allocate token budget
17. Order context sections
18. Build canonical envelope
19. Validate ACL + provenance + token budget
20. Serialize through provider adapter
21. Execute model call
22. Record actual usage + outcome
23. Feed results into evaluation/profile system
```

---

# 6. Task Classification

The compiler needs an initial task classifier.

Useful task classes:

```text
code_change
code_debug
architecture_design
research
planning
writing
summarization
decision_support
status_query
artifact_search
multi_document_reasoning
```

Each task class can have a default memory/retrieval profile.

Example:

```yaml
code_change:
  memory_types:
    - decision
    - requirement
    - constraint
    - artifact_summary
    - task_state
  retrieval:
    code_weight: high
    recent_changes_weight: high
    project_background_weight: low
  compression:
    code: extractive
    discussions: abstractive
```

---

# 7. Retrieval

Use hybrid candidate generation.

## Lexical

PostgreSQL full-text search or BM25-compatible search.

Useful for:

- exact names
- identifiers
- filenames
- error messages
- APIs

## Dense semantic

pgvector initially.

Useful for:

- paraphrases
- conceptual similarity
- intent-level matches

## Structured

Filter by:

- memory type
- subsystem
- owner
- project branch/environment
- status
- time

## Graph

Expand from high-scoring nodes through relations.

## Recent changes

Always have a dedicated recent-change channel for agentic workflows.

---

# 8. Authorization Rule

Authorization happens before content is sent to any reranking/compression model that is not permitted to see it.

```python
def retrieve_candidates(project, principal, query):
    allowed_scope = acl_service.scope(project, principal)

    return retrieval.search(
        query=query,
        project=project,
        acl=allowed_scope,
    )
```

Never retrieve globally and redact afterward.

---

# 9. Truth Resolution

The retrieval service finds information.

The truth resolver determines what currently applies.

Pseudo-logic:

```python
def resolve_memory(candidates, task_time):
    active = [m for m in candidates if m.valid_at(task_time)]

    active = remove_superseded(active)

    conflicts = find_unresolved_conflicts(active)

    canonical = choose_by_authority_when_resolvable(active)

    return canonical, conflicts
```

Do not erase unresolved contradictions.

The model should receive them explicitly.

---

# 10. Ranking

Start deterministic.

```python
score = (
    semantic_similarity * W_SEMANTIC
    + lexical_score * W_LEXICAL
    + authority_score * W_AUTHORITY
    + task_type_score * W_TYPE
    + graph_score * W_GRAPH
    + relevant_recency * W_RECENCY
    - stale_penalty * W_STALE
    - duplicate_penalty * W_DUP
)
```

Log every component so future learning-to-rank experiments have training data.

---

# 11. Multi-Resolution Expansion

Represent content at several resolutions.

```python
class Resolution(Enum):
    LABEL = 0
    CANONICAL = 1
    STRUCTURED = 2
    EXCERPT = 3
    FULL_SOURCE = 4
```

Start at low resolution.

Increase resolution when:

- the task depends directly on the item
- the agent needs exact wording
- confidence is low
- conflicting sources exist
- code implementation is required

This prevents token waste.

---

# 12. Budget Selection

```python
def calculate_budget(model, task, slo):
    supported = model.max_input_tokens
    effective = model.effective_context(task.type)

    ceiling = min(supported, effective)

    reserves = (
        model.system_reserve
        + task.output_reserve
        + task.tool_reserve
        + model.safety_margin
    )

    available = ceiling - reserves

    target = min(
        available,
        model.default_compiler_budget(task.type)
    )

    return apply_slo_constraints(target, slo)
```

Do not use `provider_max` as the default target.

---

# 13. Packing Algorithm

Each candidate should have:

```text
utility score
minimum resolution
maximum resolution
estimated token cost at each resolution
required/optional flag
```

Simple initial packing:

```python
context = []
budget = compiler_budget

for item in required_items:
    rendered = item.render(item.minimum_required_resolution)
    context.append(rendered)
    budget -= token_count(rendered)

optional = sorted(optional_items, key=lambda x: x.utility_per_token, reverse=True)

for item in optional:
    rendered = best_resolution_that_fits(item, budget)

    if rendered:
        context.append(rendered)
        budget -= token_count(rendered)
```

Later this can become a learned or optimization-based packer.

---

# 14. Context Envelope Sections

Canonical order before provider adaptation:

```text
authority
principal + permissions
current task
project identity
active decisions
requirements
constraints
required evidence
supporting evidence
recent changes
conflicts / uncertainty
working state
available tools
output contract
provenance manifest
```

Provider adapters may reorder within allowed bounds based on evaluation.

---

# 15. Prompt Cache Planning

Split envelope components into stability classes.

```text
STATIC
organization policy
project identity
long-lived project rules

SEMI-STABLE
architecture decisions
repository map
approved requirements

DYNAMIC
recent changes
current evidence
conversation state
current task
```

Provider adapter produces a cache plan:

```json
{
  "stable_prefix": ["policy", "project", "architecture"],
  "dynamic_suffix": ["recent_changes", "evidence", "task"]
}
```

The exact serialization differs by provider.

---

# 16. Semantic Paging

Agents should have tools for just-in-time expansion.

```text
sac_recall(task)
sac_expand(memory_id, resolution)
sac_get_evidence(evidence_id)
sac_related(memory_id)
sac_recent_changes(since)
sac_search(query)
```

This creates an application-level equivalent of virtual memory.

The initial call gets a small useful working set.

The agent pages in detail only when needed.

---

# 17. Context Trace Schema

```json
{
  "context_id": "ctx_481",
  "project_id": "project_123",
  "principal": {},
  "target": {},

  "candidate_counts": {
    "retrieved": 84,
    "included": 14,
    "permission_filtered": 3,
    "superseded": 7,
    "stale": 9,
    "duplicates": 10,
    "low_relevance": 41
  },

  "tokens": {
    "policy": 1312,
    "task": 486,
    "memory": 4271,
    "evidence": 10844,
    "tools": 1880,
    "estimated_total": 18793,
    "provider_actual_total": 19104,
    "provider_cached": 7021
  },

  "included_memory_ids": [],
  "included_evidence_ids": [],
  "compiler_version": "0.1"
}
```

Keep this trace for evaluation and debugging.

---

# 18. Feedback Loop

After task execution, record outcome signals.

Examples:

- user accepted/rejected answer
- code tests passed
- PR merged
- generated artifact accepted
- agent requested missing context
- model cited wrong/stale evidence

Then associate outcome with the context trace.

```text
context build
    ↓
model execution
    ↓
task outcome
    ↓
quality metrics
    ↓
update model/task context profile
```

This is how SAC eventually learns effective-context policies.

---

# 19. Effective Context Evaluation

For each model/task profile, sweep context length.

```python
for length in [8000, 32000, 64000, 128000, 256000, 512000, 1000000]:
    result = benchmark(model, task_family, length)
    record(result)
```

Vary:

- evidence position
- distractor density
- number of relevant facts
- lexical overlap
- superseded facts
- conflicting authority

Generate a performance curve rather than one score.

---

# 20. Context Value Curves

The compiler should eventually estimate marginal value.

Example conceptual curve:

```text
quality
  │                ______
  │              _/
  │            _/
  │         __/
  │      __/
  │_____/________________ tokens
      8K  32K  64K  128K
```

Sometimes quality can fall after excessive context due to noise.

So the optimization problem becomes:

```text
choose token budget where marginal quality gain
no longer justifies marginal cost/latency/risk
```

---

# 21. Security Implementation

Each compiled block should carry internal metadata:

```json
{
  "id": "mem_123",
  "trust_tier": 2,
  "authority": "approved_decision",
  "acl": ["project:123"],
  "instructional": false,
  "source": "ev_456"
}
```

Provider serialization can visibly delimit untrusted evidence.

Never let content-derived strings change their own authority classification.

---

# 22. Memory Write States

Do not make every extracted memory active immediately.

Use:

```text
proposed
active
rejected
superseded
expired
quarantined
```

Agent-generated claims should often enter `proposed` first.

High-risk categories require approval.

---

# 23. MVP Repository Structure

Suggested eventual code layout:

```text
src/
  api/
  auth/
  evidence/
  memory/
  relations/
  retrieval/
    lexical/
    vector/
    structured/
    graph/
  compiler/
    task_classifier/
    truth_resolver/
    reranker/
    compressor/
    budgeter/
    packer/
    envelope/
  providers/
    openai/
    anthropic/
    google/
    local/
  model_registry/
  tracing/
  evals/
  mcp/
```

---

# 24. First Engineering Milestones

## Milestone A: deterministic compiler

Build a fully deterministic pipeline with no learned ranking.

Goal:

- understandable
- debuggable
- testable

## Milestone B: two-provider cross-context demo

User A writes a decision through Provider A.

User B retrieves it through Provider B.

Both receive identical canonical project truth.

## Milestone C: stale-state test

Create decision A.

Later supersede it with decision B.

Ensure all providers receive B and not A unless historical context is requested.

## Milestone D: permission test

Create a project memory visible only to subset X.

Ensure an unauthorized agent cannot retrieve it, including through summaries.

## Milestone E: context efficiency benchmark

Compare:

```text
full transcript
vs
plain vector RAG
vs
SAC deterministic compiler
```

Measure:

- correctness
- tokens
- latency
- cost

---

# 25. What Not to Build First

Do not start with:

- custom long-context model training
- RoPE extension
- custom attention kernels
- distributed KV infrastructure
- graph database migration
- learned context packer
- complex multi-agent orchestration

Those are interesting but do not validate the product thesis.

The first product thesis is:

> **independent users and heterogeneous agents can share accurate, governed project knowledge.**

---

# 26. Long-Term Compiler Objective

Eventually the compiler should solve:

```text
Given:
- task
- user/agent permissions
- project state
- available models
- quality requirement
- latency requirement
- cost constraint

Choose:
- model
- retrieval strategy
- evidence depth
- context size
- compression strategy
- context ordering
- cache plan
- just-in-time paging plan

such that task success is maximized
subject to policy and SLO constraints.
```

That makes SAC an adaptive context operating layer rather than a passive memory database.

---

# Final Rule

The practical implementation principle is:

> **Never ask "How much context can this model hold?" first. Ask "What is the smallest governed evidence set this task needs?" Then use the model's available context window as the upper bound for how richly SAC can represent that evidence.**

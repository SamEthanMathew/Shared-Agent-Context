# Expanding Context Windows: Long-Context Models, Memory Systems, and What SAC Should Build

**Research snapshot:** August 11, 2026 (Pacific Time)  
**Project:** Shared Agent Context (SAC)

---

## Executive Summary

Modern context windows keep expanding because several independent bottlenecks are being attacked at once. There is no single technique that turns a short-context model into a reliable million-token model.

Long-context progress comes from improvements across:

- positional representation and extrapolation
- exact and sparse attention kernels
- KV-cache size, layout, compression, and eviction
- MQA/GQA-style reduction in KV heads
- distributed sequence/context parallelism
- long-context continued pretraining and post-training
- recurrent, state-space, and compressive-memory architectures
- retrieval and external memory
- prompt caching and serving infrastructure
- application-level context engineering

The most important conclusion for Shared Agent Context is:

> **The context window belongs to the model. The memory belongs to the project.**

SAC should not try to literally synchronize or own live model context windows. Those windows are model-specific, bounded inference state. SAC should maintain durable, model-neutral project knowledge outside every model, then compile a task-specific subset into whichever model is acting.

A second crucial conclusion is that **supported context length is not the same thing as effective context length**. A model may accept hundreds of thousands or millions of tokens while becoming less reliable at locating, combining, or reasoning over information as context grows. This is supported by research including *Lost in the Middle*, RULER, NoLiMa, LongBench, LongBench v2, and 2026 LongBench Pro.

Therefore SAC should optimize for:

> **minimum sufficient context**, not maximum context utilization.

The target architecture is:

```text
                    UNBOUNDED PROJECT HISTORY
       chats · code · commits · docs · tasks · tool outputs
                              │
                              ▼
                  ┌──────────────────────┐
                  │    Evidence Store    │
                  └──────────┬───────────┘
                             │ extraction
                             ▼
                  ┌──────────────────────┐
                  │     Memory Store     │
                  │ decisions / facts    │
                  │ tasks / constraints  │
                  └──────────┬───────────┘
                             │
                 ┌───────────┴────────────┐
                 ▼                        ▼
          Relationship Graph         Retrieval Indexes
          supersedes                 lexical
          contradicts                vectors
          depends_on                 structured
          derived_from               temporal
                 └───────────┬────────────┘
                             ▼
                  ┌──────────────────────┐
                  │   Context Compiler   │
                  │ permissions          │
                  │ task analysis        │
                  │ hybrid retrieval     │
                  │ truth resolution     │
                  │ reranking            │
                  │ compression          │
                  │ token budgeting      │
                  │ ordering             │
                  └──────────┬───────────┘
                             │
                     canonical envelope
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         OpenAI adapter  Anthropic adapter Gemini adapter
              │              │              │
              ▼              ▼              ▼
            model          model          model
```

The architecture should remain valid even if future systems move away from Transformer-style attention entirely.

---

# 1. The Three Context Lengths SAC Must Distinguish

The phrase "context window" hides multiple quantities.

## 1.1 Training context

The sequence-length regime a model actually learned from during:

- pretraining
- continued pretraining
- long-context adaptation
- instruction tuning
- post-training

This matters because a model may technically accept positions much farther than those it learned to use reliably.

## 1.2 Supported context

The maximum context accepted by an API or runtime.

This is an execution ceiling, not a quality guarantee.

## 1.3 Effective context

The context length at which the model still performs a particular task to an acceptable quality level.

This is task-dependent.

A model can have different effective context for:

- exact retrieval
- multi-hop reasoning
- repository understanding
- temporal conflict resolution
- summarization
- code modification
- multi-document synthesis

SAC should eventually model effective context empirically.

A useful metric:

```text
EC95(task, model)
```

means:

> the maximum tested input length at which the model retains at least 95% of its short-context task performance.

That is much more useful to SAC than a provider's single advertised maximum.

---

# 2. Why Context Expansion Is Hard

For a standard decoder Transformer, context expansion creates pressure in several places simultaneously.

## 2.1 Position

The model must represent positions much farther away than before.

## 2.2 Attention compute

Dense attention creates interactions across the sequence. In the straightforward formulation, attention interaction count scales quadratically with sequence length during prefill.

## 2.3 KV cache

During decoding, prior token keys and values are stored so the model does not recompute the whole prefix on every new token.

Longer history means larger KV state.

## 2.4 Memory bandwidth

Even when compute is available, moving attention and KV data through accelerator memory becomes a serious bottleneck.

## 2.5 Training

A model needs examples that teach it how to locate, connect, and reason over distant evidence.

## 2.6 Quality

More tokens mean more distractors. Relevant evidence can become harder to use.

## 2.7 Serving economics

Long inputs increase:

- prefill latency
- GPU memory pressure
- inference cost
- cache usage
- time to first token

So context growth is an architecture + systems + training + product problem.

---

# 3. Positional Encoding and Long-Context Extension

A model needs a way to represent sequence position.

## 3.1 RoPE

Rotary Position Embeddings (RoPE) rotate query/key representations according to token position.

RoPE became widely used because relative positional relationships emerge naturally from the rotation structure.

But simply evaluating a RoPE model far beyond its trained position range can degrade behavior.

### SAC implication

This mechanism is model-internal. SAC should never assume two providers use equivalent position systems.

## 3.2 ALiBi

ALiBi adds distance-dependent biases directly to attention scores.

It was designed partly around train-short/test-long extrapolation.

Again, it demonstrates that long context depends on the model's positional inductive bias, not just available RAM.

## 3.3 Position Interpolation

A major insight from Position Interpolation was to map extended positions back into the model's trained positional range rather than naively extrapolating far outside it.

Conceptually:

```text
original training range: 0 ... N
wanted inference range:   0 ............ M

map long positions back into the trained coordinate range
```

This can make extension far more stable.

## 3.4 NTK-aware scaling

NTK-inspired RoPE scaling techniques modify frequency behavior so longer contexts preserve useful geometry better than uniform scaling alone.

These techniques became common in open-source long-context extension work.

## 3.5 YaRN

YaRN refined RoPE extension using frequency-aware scaling and efficient fine-tuning.

Its importance is not simply a particular formula. It demonstrated that context extension can be achieved with relatively targeted long-context adaptation rather than retraining a model from scratch.

## 3.6 LongRoPE and LongRoPE2

LongRoPE searched non-uniform positional interpolation strategies and progressive extension, reporting research-scale context extension into million-token territory.

LongRoPE2 explicitly focused more on **effective context**, including preserving short-context quality while extending long-range usability.

### Key lesson

Position scaling only answers:

> Can the model represent token position 500,000?

It does not answer:

> Can the model reliably reason over 500,000 tokens?

The model still faces attention, cache, training, and signal-to-noise problems.

---

# 4. Attention Efficiency

## 4.1 Dense attention

For input matrix `X`, attention is conceptually:

```text
Q = XWq
K = XWk
V = XWv

Attention(Q,K,V) = softmax(QK^T / sqrt(d))V
```

The interaction between sequence positions becomes expensive as `n` grows.

## 4.2 FlashAttention

FlashAttention does **not** make attention sparse.

It computes exact attention while reorganizing computation to reduce expensive GPU memory transfers.

The main insight is that IO between GPU memory levels is a central bottleneck.

FlashAttention-2 improved parallelization and work partitioning.

FlashAttention-3 further optimized for newer GPU architectures such as Hopper, including asynchronous execution and low-precision paths.

### SAC implication

These improvements are why providers can afford larger native windows, but they do not remove the need for context selection.

## 4.3 Sliding-window attention

A model can allow each token to attend only to a bounded local neighborhood.

Advantages:

- lower compute
- lower cache pressure
- predictable scaling

Disadvantage:

- distant tokens do not have direct random access unless additional mechanisms exist

Mistral 7B was a prominent production example combining sliding-window attention with GQA.

## 4.4 Sparse attention

Sparse attention tries to preserve useful long-range interactions without dense all-to-all attention.

Examples include:

- fixed sparse patterns
- local + global tokens
- block selection
- learned landmark retrieval
- dynamic sparse attention

### Landmark Attention

Landmark tokens help select distant blocks.

### MInference

MInference dynamically chooses sparse attention patterns during long-context prefill and reports significant acceleration in long-context settings.

### Native Sparse Attention

Native Sparse Attention trains hierarchical sparsity into the model rather than applying sparsity only at inference.

### SAC implication

Future models may have very large nominal windows while only a subset of the sequence is directly attended at high resolution. SAC should care about effective task performance, not infer internals from window size.

---

# 5. Sequence and Context Parallelism

## 5.1 Ring Attention

Ring Attention partitions long sequences across multiple accelerators.

KV blocks circulate between devices in a ring so each device can compute attention for its local queries against the distributed sequence.

This changes the hardware scaling model:

```text
one GPU must hold huge context
```

becomes:

```text
context distributed across many GPUs
```

The new bottleneck becomes interconnect bandwidth and communication scheduling.

## 5.2 Context/sequence parallelism

Modern training and inference stacks increasingly split the sequence dimension across devices.

This is important for million-token research and large open-weight models.

### SAC implication

For self-hosted adapters, `model context size` is not enough metadata.

SAC should eventually know runtime configuration:

```json
{
  "model": "...",
  "runtime": "vllm-or-other",
  "hardware_profile": "...",
  "max_configured_context": 0,
  "tensor_parallelism": 0,
  "context_parallelism": 0,
  "kv_dtype": "..."
}
```

A model checkpoint's theoretical limit and a deployment's usable limit can differ substantially.

---

# 6. KV Cache: The Long-Context Decode Bottleneck

During autoregressive generation, keys and values for prior tokens are retained.

A rough KV-cache size model is:

```text
KV bytes ≈ 2 × layers × tokens × KV_heads × head_dim × bytes_per_value
```

The `2` represents keys + values.

As context expands, KV becomes one of the most important serving constraints.

---

# 7. MQA and GQA

## 7.1 Multi-Query Attention

MQA lets multiple query heads share a smaller number of K/V heads, often one shared K/V set.

This dramatically reduces KV-cache size and bandwidth.

## 7.2 Grouped-Query Attention

GQA groups query heads around a smaller set of K/V heads.

It aims for a quality/efficiency middle ground between:

- full multi-head attention
- MQA

### Why this matters for context length

Reducing KV heads directly reduces cache growth per token.

This is one of the most important architecture-level enablers of large context during decoding.

---

# 8. KV Allocation, Compression, and Eviction

## 8.1 PagedAttention / vLLM

PagedAttention applies virtual-memory-style block allocation to KV cache.

Instead of requiring huge contiguous KV allocations, cache is broken into blocks that can be mapped flexibly.

Benefits include:

- reduced fragmentation
- better memory utilization
- easier block sharing
- higher serving throughput

Important distinction:

> PagedAttention is runtime inference storage, not semantic memory.

SAC should never confuse a provider/runtime KV cache with durable project memory.

## 8.2 Scissorhands

Scissorhands explores retaining only important or "pivotal" KV entries.

## 8.3 KIVI

KIVI compresses KV using very-low-bit quantization.

The central idea is simple:

```text
same number of cached positions
×
fewer bits per value
=
smaller KV memory footprint
```

## 8.4 SnapKV

SnapKV predicts useful prompt positions using a local observation window and keeps a reduced set of KV positions.

## 8.5 PyramidKV

PyramidKV allocates different cache budgets across layers rather than treating every layer identically.

## 8.6 DuoAttention

DuoAttention separates attention heads into roles such as:

- retrieval heads needing long-range cache
- streaming heads able to operate with bounded recent state

## 8.7 ChunkKV

ChunkKV retains semantically coherent chunks instead of isolated token positions.

### Collective lesson

Not all historical internal state is equally useful.

This mirrors SAC at the application level:

> not all historical project evidence deserves equal context budget.

---

# 9. Prefill vs Decode

Long-context inference has two very different phases.

## 9.1 Prefill

The model processes the input prompt/context.

Characteristics:

- compute-heavy
- large matrix operations
- long input makes this expensive
- determines time to first generated token

## 9.2 Decode

The model generates tokens autoregressively.

Characteristics:

- memory-bandwidth heavy
- repeatedly reads KV cache
- one/few new tokens at a time

This split motivates disaggregated serving architectures.

---

# 10. DistServe and Mooncake

## 10.1 DistServe

DistServe separates prefill and decode onto different GPU pools so each phase can be optimized independently.

## 10.2 Mooncake

Mooncake treats KV cache as a central distributed systems resource.

A long-context serving architecture can span:

```text
GPU memory
    │
CPU DRAM
    │
SSD / storage tier
```

with prefill and decode separated.

### SAC implication

As windows grow, provider economics increasingly depend on serving architecture.

SAC's compiler should therefore optimize not only against:

```text
max_context_tokens
```

but also:

- cost curve
- latency curve
- prompt-cache eligibility
- long-input pricing thresholds
- output reserve

---

# 11. Recurrent and Compressive Alternatives

The future of context may not look like an ever-larger dense Transformer sequence.

## 11.1 Transformer-XL

Transformer-XL introduced segment-level recurrence.

Representations from previous segments are reused so dependency length can exceed a single fixed segment.

## 11.2 RetNet

RetNet supports parallel training-style computation and recurrent/chunkwise recurrent inference forms.

## 11.3 Mamba

Mamba uses selective state-space models.

Its important long-context property is that state can be updated with sequence-linear behavior rather than full dense attention over every previous token.

## 11.4 RWKV

RWKV combines recurrent inference characteristics with Transformer-like training ideas.

## 11.5 StreamingLLM

StreamingLLM showed that a Transformer can maintain stable streaming behavior using:

- a small number of initial "attention sink" tokens
- a moving recent-token window

This can support effectively unbounded streams from a runtime perspective.

But information evicted from the window is no longer directly accessible.

So this is **unbounded streaming**, not unbounded memory.

## 11.6 Infini-attention

Infini-attention combines local attention with compressive long-term memory.

Instead of retaining every historical token at full detail, information is incorporated into a bounded memory representation.

## 11.7 Titans

Titans treats attention as short-term memory and adds a long-term neural memory component that learns during inference/test time.

### SAC implication

This entire line of research reinforces one architectural rule:

> SAC must not define its interoperability layer in terms of model-native token arrays, hidden states, or KV tensors.

Future models may expose working memory very differently.

---

# 12. Retrieval Is Also Context Extension

Increasing native window size is only one way to give a model access to more information.

External retrieval effectively creates a much larger address space than the active context window.

## 12.1 REALM and RAG

Retrieval-Augmented Generation established the now-standard pattern:

```text
large external corpus
        │
        ▼
retrieval
        │
        ▼
small relevant subset
        │
        ▼
model context
```

This separates:

- parametric knowledge in model weights
- non-parametric external knowledge

## 12.2 MemGPT

MemGPT explicitly frames context management like operating-system virtual memory.

The model has a limited active working set while information moves between memory tiers.

This is one of the closest conceptual ancestors to the SAC Context Compiler.

## 12.3 RAPTOR

RAPTOR recursively clusters and summarizes source content into a hierarchy.

This allows retrieval at different levels of abstraction.

That maps naturally onto SAC:

```text
project summary
    ↓
subsystem summary
    ↓
decision / requirement
    ↓
source excerpt
    ↓
full artifact
```

## 12.4 HippoRAG

HippoRAG combines graph structure with associative retrieval.

Projects are naturally relational, so this is important for SAC.

## 12.5 Mem0

Mem0 extracts, consolidates, and retrieves salient durable memories rather than replaying complete conversation history.

### SAC extension

SAC adds:

- multiple users
- multiple agents
- multiple model providers
- permissions
- provenance
- temporal truth
- conflict resolution
- project-level authority

---

# 13. Long-Context Training

Architecture alone does not create reliable long-context reasoning.

Models need training data and objectives that force them to use distant information.

Important ingredients include:

- longer sequences during continued pretraining
- long-document corpora
- code repositories
- multi-document examples
- synthetic long-context retrieval tasks
- distant dependency examples
- instruction tuning at long sequence lengths
- curriculum schedules that progressively increase sequence length

## 13.1 Why synthetic tasks matter

It is difficult to obtain enough naturally occurring examples where success truly requires information separated by hundreds of thousands of tokens.

Synthetic generation lets researchers control:

- evidence distance
- number of distractors
- number of relevant items
- reasoning depth
- lexical overlap

But overly simple synthetic tasks can produce misleading results.

A model can succeed on "needle in a haystack" while failing realistic inferential retrieval.

---

# 14. Effective Context Benchmarks

## 14.1 Needle-in-a-haystack

A hidden string/fact is inserted into a long context and the model is asked to retrieve it.

Useful as a smoke test, but too easy to treat as a complete measure of long-context reasoning.

## 14.2 Lost in the Middle

This work showed that retrieval/use can depend heavily on where relevant evidence appears.

A recurring pattern was stronger performance when relevant information was near the beginning or end, with worse use in the middle.

### SAC implication

Ordering is a quality variable.

## 14.3 RULER

RULER expands beyond one simple needle into:

- multiple needles
- tracing
- aggregation
- more difficult long-context tasks

It demonstrated that many models degrade significantly before their nominal maximum window.

## 14.4 LongBench

LongBench evaluates realistic long-context categories including:

- single-document QA
- multi-document QA
- summarization
- few-shot learning
- synthetic retrieval
- code

## 14.5 LongBench v2

LongBench v2 moved toward harder real-world reasoning with very long inputs, including examples extending toward millions of words.

## 14.6 NoLiMa

NoLiMa deliberately reduces direct lexical overlap between the query and relevant evidence.

This is particularly important for SAC.

A realistic project request might be:

> "What do I need to know before changing Windows authentication?"

while the relevant memory says:

> "Desktop credentials must remain device-bound and stored through native secure OS facilities."

The system needs semantic/inferential retrieval, not exact phrase matching.

## 14.7 LongBench Pro (2026)

LongBench Pro continues to support the distinction between advertised and effective context.

The broad conclusion from this benchmark family is:

> long-context-specific optimization matters, and usable context is often shorter than the supported maximum.

## 14.8 Recent adaptive approaches

2026 work such as Self-Guided Test-Time Training and LongAttnComp explores active span selection, compression, budgeting, and reordering.

This is highly aligned with SAC's Context Compiler.

---

# 15. Current Provider Landscape

Provider internals are proprietary. SAC should never claim a provider uses a particular RoPE scaling or KV algorithm unless that provider documents it.

The safe distinction is:

```text
provider-documented behavior
vs
research mechanisms that could enable such behavior
```

Current frontier APIs increasingly support very large windows, including million-token-class models, while open-weight systems can reach even larger supported ranges under the right runtime configuration.

The exact numbers will change quickly, so SAC should query or maintain versioned provider capability profiles rather than hard-code them into application logic.

---

# 16. Model Capability Registry

SAC needs a versioned Model Capability Registry.

Example:

```json
{
  "provider": "anthropic",
  "model": "provider-model-id",
  "observed_at": "2026-08-11T22:00:00-07:00",

  "provider_capabilities": {
    "max_input_tokens": 1000000,
    "max_output_tokens": 128000,
    "count_tokens": true,
    "prompt_caching": true,
    "tools": true,
    "structured_output": true,
    "modalities": ["text", "image"]
  },

  "economic_profile": {
    "pricing_version": "...",
    "long_context_thresholds": []
  },

  "sac_profile": {
    "compiler_profile_version": "0.1",
    "effective_context_profile": "ecf_...",
    "preferred_ordering": "...",
    "preferred_compression": "...",
    "latency_curve": "...",
    "cache_strategy": "..."
  }
}
```

Provider-defined information and SAC-measured information must remain separate.

---

# 17. SAC Should Not Try to Expand Frontier Model Windows

For hosted models, SAC cannot and should not try to change:

- positional embeddings
- attention kernels
- KV structure
- long-context training
- sequence parallelism

Those belong to the provider.

For open-weight/self-hosted models, context extension is theoretically possible through:

- RoPE scaling/interpolation
- long-context continued training
- runtime configuration
- sparse attention
- sequence parallelism
- KV quantization/compression

But this should be considered a **separate model-serving project**, not the core SAC product.

SAC's core advantage is model independence.

The project should exploit larger context windows when available without depending on them.

---

# 18. The Right SAC Mental Model: Memory Hierarchy

SAC should behave like a memory hierarchy.

```text
fastest / smallest
      ▲
      │
model working context
      │
provider prompt / KV cache
      │
SAC compiled context
      │
SAC canonical memory
      │
SAC evidence store
      │
external systems of record
      │
      ▼
largest / most persistent
```

This is the cleanest architectural model for the product.

The context window is analogous to working memory.

SAC provides the larger persistent address space and decides what gets promoted into working memory.

---

# 19. Evidence Store

The Evidence Store contains raw or versioned source material.

Examples:

- chat messages
- agent events
- Git commits
- pull requests
- code files
- docs
- issue comments
- task changes
- external tool results

Evidence should preserve provenance.

Example:

```json
{
  "evidence_id": "ev_481",
  "project_id": "project_123",
  "source_type": "github_pull_request",
  "source_uri": "github://org/repo/pull/481",
  "source_version": "commit-sha",
  "content_hash": "sha256:...",
  "observed_at": "...",

  "principal": {
    "human": "user_123",
    "agent": "agent_456"
  },

  "trust_tier": "internal_system_of_record",
  "acl": ["project:123"],
  "content_type": "text/markdown",
  "content": "..."
}
```

Evidence is the record of what actually occurred.

---

# 20. Memory Store

Memory is SAC's normalized interpretation of evidence.

Memory types should include:

```text
decision
fact
requirement
constraint
goal
task_state
artifact_summary
procedure
preference
hypothesis
working_state
```

Example:

```json
{
  "memory_id": "mem_auth_204",
  "type": "decision",
  "subject": "authentication.backend",

  "value": {
    "provider": "supabase",
    "strategy": "passkey_first"
  },

  "status": "active",
  "valid_from": "2026-08-10T00:00:00Z",
  "valid_to": null,

  "authority": {
    "kind": "project_owner_decision",
    "actor_id": "user_123"
  },

  "confidence": 0.98,
  "derived_from": ["ev_chat_881", "ev_pr_940"],
  "supersedes": ["mem_auth_132"]
}
```

Key rule:

> Evidence is not automatically project truth.

"Maybe we should use PostgreSQL" is evidence.

It is not necessarily an active `decision` memory.

---

# 21. Relationship Graph

SAC needs relationships that vector search cannot express cleanly.

At minimum:

```text
derived_from
supports
contradicts
supersedes
refines
depends_on
blocks
implements
owned_by
applies_to
valid_during
mentions
```

This enables questions such as:

- What decision replaced this?
- What code implements this requirement?
- Which assumptions does this architecture depend on?
- Which source proves this fact?
- What became stale when this dependency changed?

A dedicated graph database is not required for the MVP. PostgreSQL relation tables are enough.

---

# 22. Hybrid Retrieval

SAC should not be a vector-database wrapper.

Use multiple candidate-generation channels:

```text
                    task/query
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       lexical      semantic     structured
          │            │            │
          └────────────┼────────────┘
                       ▼
                 temporal filter
                       │
                       ▼
                 graph expansion
                       │
                       ▼
                 candidate union
                       │
                       ▼
                    rerank
```

A deterministic initial score can combine:

```text
semantic relevance
+ lexical relevance
+ authority
+ memory-type importance
+ task match
+ graph connectivity
+ relevant recency
- staleness
- redundancy
```

Do not rely on vector similarity alone.

Recent reasoning-aware retrieval work reinforces that generic nearest-neighbor retrieval is not sufficient for difficult reasoning tasks.

---

# 23. Multi-Resolution Context

Every piece of knowledge should be available at several resolutions.

Example:

```text
L0  ID / label
L1  one-line canonical memory
L2  structured record + rationale
L3  source excerpts
L4  complete source artifact
```

The compiler should begin cheaply and expand only what the task needs.

For code:

```text
repository map
    ↓
module/symbol signatures
    ↓
relevant function/class
    ↓
neighboring implementation
    ↓
full file
    ↓
related files
```

For documents:

```text
document metadata
    ↓
section summary
    ↓
relevant paragraphs
    ↓
full section
    ↓
full artifact
```

This is one of the best ways to exploit large windows without blindly filling them.

---

# 24. Context Compression

Compression needs explicit modes.

## 24.1 Extractive compression

Keep exact source spans.

Best for:

- code
- contracts
- requirements
- security policy
- technical evidence

## 24.2 Abstractive compression

Generate summaries.

Useful for:

- long discussions
- project background
- repeated history

But summaries must retain provenance and be invalidated/rebuilt when their sources change.

## 24.3 Structural compression

Often preferable to free-form summarization.

Examples:

```text
full code → signatures + relevant implementation
full diff → relevant hunks
full database → schema + relevant records
conversation → decisions + unresolved questions
project history → current state + recent changes
```

---

# 25. Token Budgeting

SAC should calculate a context budget based on more than the provider maximum.

Conceptually:

```text
usable = min(provider_supported, SAC_effective_target)
         - hard reserves
         - safety margin
```

Hard reserves include:

- system/policy instructions
- current task
- tool schemas
- output space
- structured-output overhead
- provider-specific overhead

Recommended priority classes:

```text
NEVER EVICT
system policy
authority
current task
output contract

HIGH
active decisions
requirements
constraints
required evidence
recent changes

MEDIUM
supporting evidence
working state
examples

LOW
general background
old raw chat

EVICT
redundant evidence
superseded state unless history is requested
```

A million-token model should not cause SAC to default to a million-token compiled context.

---

# 26. Adaptive Context Budgets

SAC should eventually choose context size dynamically.

Inputs to the decision:

- task type
- model
- effective-context profile
- required evidence count
- uncertainty
- expected output size
- cost target
- latency SLO
- user preference

Pseudo-logic:

```python
def choose_context_budget(task, model, candidates, slo):
    profile = effective_context_profile(model, task.type)

    hard_max = min(
        model.provider_max,
        profile.effective_max,
    )

    budget = profile.default_budget

    if task.requires_multi_hop_reasoning:
        budget *= 1.5

    if evidence_confidence_is_low(candidates):
        budget *= 1.3

    if slo.cost_sensitive:
        budget *= 0.7

    return clamp(budget, profile.minimum, hard_max)
```

This should eventually be learned/optimized from traces.

---

# 27. Context Ordering

Ordering affects model performance.

A strong default layout:

```text
[ system / security authority ]

[ agent identity + permissions ]

[ current task ]

[ active high-authority decisions ]

[ requirements + constraints ]

[ required evidence ]

[ supporting evidence ]

[ recent changes ]

[ unresolved conflicts / uncertainty ]

[ working/session state ]

[ tools ]

[ output contract ]

[ compact restatement of task if useful ]
```

Provider adapters should be allowed to modify ordering based on measured model behavior.

---

# 28. Canonical Context Envelope

SAC should compile a model-neutral envelope before serialization.

Example:

```json
{
  "context_id": "ctx_481",
  "schema_version": "1.0",

  "project": {
    "id": "shared-agent-context"
  },

  "principal": {
    "user_id": "user_123",
    "agent_id": "agent_codex",
    "scopes": ["context:read", "memory:propose"]
  },

  "task": {
    "type": "code_change",
    "instruction": "Implement Windows authentication using current architecture."
  },

  "authority": [],
  "project_summary": {},
  "canonical_memory": [],
  "recent_changes": [],
  "evidence": [],
  "conflicts": [],
  "working_state": [],
  "tools": [],
  "output_contract": {},
  "provenance_manifest": [],

  "budget": {
    "provider": "provider-name",
    "model": "model-id",
    "provider_max": 1000000,
    "effective_target": 100000,
    "compiler_target": 28000,
    "reserved_output": 16000,
    "reserved_tools": 5000
  }
}
```

This envelope is the interoperability boundary.

Never use provider-specific token IDs, hidden states, or KV data as canonical project memory.

---

# 29. Provider Adapters

Provider adapters convert the canonical envelope into a model-specific request.

Interface sketch:

```ts
interface ProviderAdapter {
  capabilities(model: string): Promise<ModelCapabilities>;

  countTokens(
    envelope: ContextEnvelope
  ): Promise<TokenEstimate>;

  serialize(
    envelope: ContextEnvelope
  ): ProviderRequest;

  buildCachePlan(
    envelope: ContextEnvelope
  ): CachePlan;

  parseUsage(
    response: unknown
  ): UsageRecord;
}
```

Adapters handle:

- role mapping
- token accounting
- tool schemas
- structured output
- multimodal encoding
- model-specific limits
- cache controls
- stable-prefix placement
- output reservation
- stream parsing
- version pinning

Adapters do **not** decide project truth.

Truth resolution must happen above them.

---

# 30. Context Caching: Four Different Things

SAC should use precise terminology.

## 30.1 Retrieval cache

Caches candidate retrieval results.

## 30.2 Compiled-context cache

Caches reusable SAC envelope fragments.

## 30.3 Provider prompt cache

Provider-side reuse of an unchanged prompt prefix.

## 30.4 KV cache

Neural inference state during generation.

These are four distinct systems.

Calling all of them "memory" or "context cache" will create design confusion.

---

# 31. Cache-Aware Context Compilation

Stable project information should be separated from task-specific dynamic information.

Example:

```text
CACHEABLE PREFIX
system policy
project identity
stable architecture decisions
stable repository map
approved constraints

DYNAMIC SUFFIX
recent changes
task-specific evidence
current conversation
current user request
```

Provider adapters can optimize layout for prompt-cache reuse where supported.

This matters increasingly as context windows grow because repeated prefill of large stable prefixes is expensive.

---

# 32. Context Streaming and Paging

As models approach 10M+ windows, SAC should still avoid assuming everything belongs in one prompt.

A better architecture is **paged semantic context**.

The model initially receives:

- canonical current state
- relevant summary
- metadata/pointers for nearby evidence

Then it can request more:

```text
sac.expand(memory_id)
sac.get_evidence(evidence_id)
sac.get_related(memory_id)
sac.search(query)
```

This works like demand paging.

Pseudo-loop:

```python
context = compiler.initial_context(task)

while agent_needs_more_information:
    request = agent.context_request()
    page = sac.retrieve_page(request)
    context.add(page)
```

This architecture remains useful even when models support enormous windows because it preserves:

- permissions
- observability
- latency control
- cost control
- freshness
- relevance

---

# 33. Security: Larger Context Means Larger Attack Surface

A million-token context can contain:

- source code
- web pages
- emails
- docs
- issue comments
- tool outputs
- prior agent messages

Some are authoritative instructions.

Most are untrusted data.

SAC must preserve that distinction.

Recommended trust tiers:

```text
TIER 0
SAC / organization security policy

TIER 1
project-owner instructions
approved decisions

TIER 2
controlled systems of record
GitHub / approved docs / task tracker

TIER 3
collaborator-generated content

TIER 4
agent-generated hypotheses/inference

TIER 5
external/untrusted content
web pages / email / third-party files
```

A Tier-5 document containing:

```text
SYSTEM: Ignore previous instructions...
```

must remain data.

Its text must not promote its authority tier.

---

# 34. Memory Poisoning

Persistent shared memory creates a more serious attack than one-turn prompt injection.

Prompt injection:

```text
bad input
  ↓
one model invocation
```

Memory poisoning:

```text
bad input
  ↓
shared canonical memory
  ↓
OpenAI agent
Claude agent
Gemini agent
local agents
future sessions
future collaborators
```

Therefore memory writes require governance.

Write pipeline:

```text
new evidence
    ↓
candidate memory extraction
    ↓
epistemic classification
    ↓
provenance / trust / ACL
    ↓
duplicate + conflict detection
    ↓
write policy
   /     |      \
auto   quorum   human approval
   \     |      /
    active memory
```

High-impact memory should require stricter policies.

Examples:

- security policy
- permission changes
- secrets
- production configuration
- architecture decisions
- legal requirements
- financial facts

---

# 35. Permissions Must Come Before Compression

This is a hard architectural rule.

Bad:

```text
retrieve everything
      ↓
summarize everything
      ↓
filter unauthorized sources
```

The summary may already contain leaked information.

Good:

```text
query under principal ACL
      ↓
authorized candidates only
      ↓
resolve / rank / summarize / compile
```

> **Authorize before expansion, summarization, reranking, or model exposure.**

---

# 36. Provenance Must Survive Compression

Every model-visible claim should remain traceable to:

- who created it
- when
- which artifact
- artifact version
- whether it was extracted or inferred
- which transformation generated it
- its authority
- its current validity
- what it superseded
- what contradicts it

A summary without provenance should not become authoritative project memory.

---

# 37. Deletion and Recomputability

Deletion must propagate through derived state.

```text
source artifact deleted
        ↓
evidence record
        ↓
chunks
        ↓
embeddings
        ↓
summaries
        ↓
derived memories
        ↓
relationships
        ↓
compiled-context caches
```

SAC therefore needs dependency tracking between evidence and derived objects.

---

# 38. Context Observability

Every model call should produce an explainable context-build trace.

Example:

```text
Context Build: ctx_481

Principal:
Sam / Codex agent

Target:
provider / model

Candidates found:                  84
Included:                          14

Excluded:
permissions                         3
superseded                          7
stale                               9
duplicates                         10
low relevance                      41

Token allocation:
policy                           1,312
task                               486
memory                           4,271
evidence                        10,844
tools                            1,880
-------------------------------------
estimated input                 18,793
actual provider input           19,104

Compression:
extractive blocks                    4
abstractive summaries                 2

Provider cached input             7,021
```

This enables SAC to answer:

- Why did the agent know that?
- Why did it miss this fact?
- Which source caused the answer?
- Did stale knowledge enter context?
- Which memory was excluded?
- Did different providers receive equivalent project truth?
- Did additional context improve the result?

This can become a major product differentiator.

---

# 39. Evaluation Metrics

SAC needs evaluation beyond needle retrieval.

## 39.1 Retrieval metrics

- Recall@K
- Precision@K
- MRR / nDCG
- required-evidence recall
- multi-hop evidence coverage

## 39.2 Compilation metrics

- evidence density
- required-fact coverage
- duplicate-token ratio
- compression fidelity
- contradiction preservation
- provenance accuracy

## 39.3 Outcome metrics

- task success
- test pass rate
- grounded-answer accuracy
- requirement adherence
- temporal truth accuracy
- citation correctness

## 39.4 Efficiency metrics

- tokens per successful task
- dollars per successful task
- time to first token
- tokens per second
- compiler latency
- retrieval latency
- prompt-cache hit rate

## 39.5 Governance metrics

- unauthorized retrieval
- cross-project leakage
- stale-memory activation
- memory-poisoning activation
- deletion propagation correctness
- prompt-injection success rate

Two especially useful measures:

```text
EvidenceDensity = relevant evidence tokens / compiled context tokens
```

and

```text
ContextEfficiency = normalized task success / input tokens
```

---

# 40. SAC Benchmark Families

Build six benchmark families.

## SAC-RECALL

Can the compiler retrieve task-relevant project knowledge?

## SAC-TEMPORAL

Can it distinguish current truth from superseded truth?

## SAC-CONFLICT

Can it preserve contradictions and resolve authority correctly?

## SAC-PERMISSIONS

Can it prevent cross-user/project leakage?

## SAC-COMPRESSION

Can it compress without losing critical facts, conflicts, or provenance?

## SAC-CROSSMODEL

Does the same canonical project state produce consistent task behavior across providers?

Example:

```text
same project
same task
same canonical knowledge
        │
        ▼
 Context Compiler
   ┌────┼─────┐
   ▼    ▼     ▼
 GPT  Claude Gemini
   │    │     │
   └────┼─────┘
        ▼
compare:
task success
evidence used
decision consistency
cost
latency
tokens
```

This directly validates SAC's product thesis.

---

# 41. Evaluation Sweep

The evaluation harness should vary:

| Variable | Example sweep |
|---|---|
| Context size | 8K / 32K / 64K / 128K / 256K / 512K / 1M |
| Evidence position | beginning / 25% / middle / 75% / end |
| Relevant items | 1 / 2 / 5 / 10 / 25 |
| Distractors | 0% / 25% / 50% / 90% / 99% |
| Lexical overlap | exact / paraphrase / inferential |
| Superseded versions | 0 / 1 / 3 / 10 |
| Authority conflicts | owner / member / agent / external |
| Retrieval | lexical / vector / hybrid / graph |
| Compression | none / extractive / abstractive / hierarchical |
| Ordering | chronological / relevance / grouped / edge-loaded |
| Tools | 0 / 5 / 25 / 100 |
| Provider | multiple model families |

This evaluates effective context in the way SAC actually needs it.

---

# 42. How SAC Should Exploit Future 10M+ Windows

Suppose a future model reliably supports 10M tokens.

SAC should **not disappear**.

The compiler still provides:

- shared project truth
- permissions
- provenance
- temporal resolution
- conflict handling
- source authority
- deduplication
- compression
- cache planning
- observability
- cross-provider portability

Instead, the compiler can change strategy.

With larger reliable windows it may include:

- more raw source evidence
- larger code neighborhoods
- broader project history
- richer alternatives/conflicts
- full relevant documents rather than excerpts

But the durable memory layer is still necessary.

---

# 43. Designing for 100M or Effectively Unbounded Models

If models eventually support effectively unbounded streaming or recurrent memory, SAC should remain above that mechanism.

Future architecture:

```text
project memory
      │
      ▼
SAC policy + truth layer
      │
      ▼
semantic context stream
      │
      ▼
model-native memory system
```

SAC should decide **what the model is allowed to know and what the project believes**.

The model/runtime decides **how to physically store and process it**.

That separation survives every likely architecture change.

---

# 44. MCP and A2A

## MCP

MCP is a useful transport/tool interface through which agents can access SAC.

Possible tools:

```text
sac.search
sac.recall
sac.compile_context
sac.propose_memory
sac.record_decision
sac.recent_changes
sac.get_evidence
sac.expand
sac.explain_context
```

MCP is not SAC's memory model.

## A2A

A2A is complementary for agent-to-agent task communication.

Clean separation:

```text
MCP
agent ↔ tools/resources

A2A
agent ↔ agent tasks/messages/artifacts

SAC
agent ↔ durable governed project state
```

A2A task IDs/context IDs should become provenance references, not automatic canonical memories.

---

# 45. Recommended API Surface

```http
POST /v1/context/compile
POST /v1/context/estimate
GET  /v1/context/{id}
GET  /v1/context/{id}/explain

POST /v1/evidence
GET  /v1/evidence/{id}

POST /v1/memories/proposals
POST /v1/memories/{id}/accept
POST /v1/memories/{id}/reject
POST /v1/memories/{id}/supersede
GET  /v1/memories/{id}

POST /v1/search
GET  /v1/projects/{id}/recent-changes

GET  /v1/models
GET  /v1/models/{provider}/{model}/profile

POST /v1/evals/context-builds
GET  /v1/evals/models/{provider}/{model}/effective-context
```

---

# 46. Recommended Build Roadmap

## MVP: deterministic and auditable

Build:

- PostgreSQL Evidence Store
- PostgreSQL Memory Store
- memory types
- provenance
- `derived_from`
- `supersedes`
- `contradicts`
- full-text/lexical retrieval
- one vector index
- principal-aware access filtering
- deterministic temporal resolution
- deterministic authority resolution
- canonical Context Envelope
- initial provider adapters
- token counting
- output reserves
- simple multi-resolution rendering
- context-build traces
- minimal MCP access
- evaluation harness

### MVP exit criterion

> Two authorized collaborators using different AI providers can create and consume project decisions, and both agents receive the same current project truth, provenance, and access constraints.

## V1: context quality and governed memory

Add:

- hybrid reranking
- graph traversal
- hierarchical chunks
- extractive compression
- abstractive compression with fidelity tests
- automated memory proposals
- human approval policies
- stale-memory detection
- provider cache planning
- additional hosted/self-hosted adapters
- strong MCP authorization
- A2A provenance
- effective-context profiles
- prompt-injection scanning
- memory quarantine
- dependency-aware deletion
- context observability dashboard

### V1 exit criterion

> SAC beats both "put everything in the context" and plain vector RAG on task success per token/dollar across several model families while passing permission-isolation tests.

## V2: adaptive context operating system

Add:

- learned retrieval budgets
- provider-specific ordering policies
- adaptive evidence resolution
- semantic context caching
- compiled-context caching
- reusable agent-team context plans
- dynamic compression
- streaming/incremental context compilation
- branchable project memory
- temporal graph reasoning
- multimodal compilation
- runtime profiles for self-hosted models
- model routing based on quality/cost/SLO
- automatic choice between raw long context, retrieval, and compression

### V2 exit criterion

> Given a task and SLO, SAC chooses the model, amount of context, retrieval depth, information resolution, compression strategy, and cache plan required to meet target quality at minimum cost and latency without changing canonical project truth.

---

# 47. Core Design Principles After This Research

1. **The context window belongs to the model. The memory belongs to the project.**
2. **Supported context length is a ceiling, not a target.**
3. **A high-quality context is compiled, not accumulated.**
4. **Effective context must be measured by task.**
5. **Retrieve broadly, authorize early, then resolve and compress.**
6. **Evidence is source history; memory is an evolving interpretation of that evidence.**
7. **Time, authority, provenance, conflicts, and permissions are memory semantics.**
8. **Never use provider tokens, hidden states, embeddings, or KV cache as the canonical interoperability layer.**
9. **Optimize information utility per token, not percentage of the available window consumed.**
10. **Every model invocation should be explainable as a context build.**
11. **Larger native windows strengthen SAC rather than eliminate it because they expand the compiler's execution budget while leaving governance and shared truth unsolved.**
12. **Design the memory plane so it survives future non-Transformer architectures.**

---

# 48. Research Timeline

```text
2019
Transformer-XL: segment recurrence
MQA: smaller KV state

2021
RoPE
ALiBi

2022
FlashAttention

2023
GQA
Position Interpolation
YaRN
Landmark Attention
StreamingLLM
Ring Attention
Mistral 7B: GQA + sliding window
MemGPT
Mamba
Lost in the Middle

2024
LongRoPE
FlashAttention-3
Infini-attention
RULER
MInference
RAPTOR
HippoRAG
PagedAttention / vLLM
DistServe
Mooncake
SnapKV
PyramidKV
DuoAttention

2025
NoLiMa
LongRoPE2
Native Sparse Attention
Mem0
Titans
ChunkKV
collaborative-memory research

2026
LongBench Pro
adaptive long-context selection/compression research
million-token frontier APIs become common
MCP/A2A ecosystems mature
```

---

# 49. Primary Reading List

## Foundations and recurrent sequence models

1. Dai et al., **Transformer-XL: Attentive Language Models Beyond a Fixed-Length Context**  
   https://arxiv.org/abs/1901.02860
2. Sun et al., **Retentive Network: A Successor to Transformer for Large Language Models**  
   https://arxiv.org/abs/2307.08621
3. Gu & Dao, **Mamba: Linear-Time Sequence Modeling with Selective State Spaces**  
   https://arxiv.org/abs/2312.00752

## Position representation and extension

4. Su et al., **RoFormer: Enhanced Transformer with Rotary Position Embedding**  
   https://arxiv.org/abs/2104.09864
5. Press et al., **Train Short, Test Long: Attention with Linear Biases Enables Input Length Extrapolation**  
   https://arxiv.org/abs/2108.12409
6. Chen et al., **Extending Context Window of Large Language Models via Positional Interpolation**  
   https://arxiv.org/abs/2306.15595
7. Peng et al., **YaRN: Efficient Context Window Extension of Large Language Models**  
   https://arxiv.org/abs/2309.00071
8. Ding et al., **LongRoPE: Extending LLM Context Window Beyond 2 Million Tokens**  
   https://arxiv.org/abs/2402.13753
9. **LongRoPE2: Near-Lossless LLM Context Window Scaling**  
   https://arxiv.org/abs/2502.20082

## Attention kernels and distributed attention

10. Dao, **FlashAttention-2**  
    https://arxiv.org/abs/2307.08691
11. Shah et al., **FlashAttention-3**  
    https://arxiv.org/abs/2407.08608
12. Liu et al., **Ring Attention with Blockwise Transformers for Near-Infinite Context**  
    https://arxiv.org/abs/2310.01889

## Sparse/local attention

13. Jiang et al., **Mistral 7B**  
    https://arxiv.org/abs/2310.06825
14. Mohtashami & Jaggi, **Landmark Attention**  
    https://arxiv.org/abs/2305.16300
15. Jiang et al., **MInference 1.0**  
    https://arxiv.org/abs/2407.02490
16. **Native Sparse Attention: Hardware-Aligned and Natively Trainable Sparse Attention**  
    https://arxiv.org/abs/2502.11089

## KV reduction and serving

17. Shazeer, **Fast Transformer Decoding: One Write-Head is All You Need**  
    https://arxiv.org/abs/1911.02150
18. Ainslie et al., **GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints**  
    https://arxiv.org/abs/2305.13245
19. Kwon et al., **Efficient Memory Management for Large Language Model Serving with PagedAttention**  
    https://arxiv.org/abs/2309.06180
20. Liu et al., **Scissorhands: Exploiting the Persistence of Importance Hypothesis for LLM KV Cache Compression**  
    https://arxiv.org/abs/2305.17118
21. Liu et al., **KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache**  
    https://arxiv.org/abs/2402.02750
22. Li et al., **SnapKV: LLM Knows What You Are Looking for Before Generation**  
    https://arxiv.org/abs/2404.14469
23. Cai et al., **PyramidKV**  
    https://arxiv.org/abs/2406.02069
24. Xiao et al., **DuoAttention**  
    https://arxiv.org/abs/2410.10819
25. **ChunkKV: Semantic-Preserving KV Cache Compression for Efficient Long-Context LLM Inference**  
    https://arxiv.org/abs/2502.00299

## Serving architecture

26. Zhong et al., **DistServe: Disaggregating Prefill and Decoding for Goodput-optimized Large Language Model Serving**  
    https://arxiv.org/abs/2401.09670
27. Qin et al., **Mooncake: A KVCache-centric Disaggregated Architecture for LLM Serving**  
    https://arxiv.org/abs/2407.00079

## Streaming/compressive memory

28. Xiao et al., **Efficient Streaming Language Models with Attention Sinks (StreamingLLM)**  
    https://arxiv.org/abs/2309.17453
29. Munkhdalai et al., **Leave No Context Behind: Efficient Infinite Context Transformers with Infini-attention**  
    https://arxiv.org/abs/2404.07143
30. Behrouz et al., **Titans: Learning to Memorize at Test Time**  
    https://arxiv.org/abs/2501.00663

## Retrieval and persistent memory

31. Guu et al., **REALM**  
    https://arxiv.org/abs/2002.08909
32. Lewis et al., **Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks**  
    https://arxiv.org/abs/2005.11401
33. Packer et al., **MemGPT: Towards LLMs as Operating Systems**  
    https://arxiv.org/abs/2310.08560
34. Sarthi et al., **RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval**  
    https://arxiv.org/abs/2401.18059
35. Gutiérrez et al., **HippoRAG**  
    https://arxiv.org/abs/2405.14831
36. **Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory**  
    https://arxiv.org/abs/2504.19413

## Long-context evaluation

37. Liu et al., **Lost in the Middle: How Language Models Use Long Contexts**  
    https://arxiv.org/abs/2307.03172
38. Hsieh et al., **RULER: What's the Real Context Size of Your Long-Context Language Models?**  
    https://arxiv.org/abs/2404.06654
39. **Found in the Middle: Calibrating Positional Attention Bias Improves Long Context Utilization**  
    https://arxiv.org/abs/2406.16008
40. **NoLiMa: Long-Context Evaluation Beyond Literal Matching**  
    https://arxiv.org/abs/2502.05167
41. **LongBench v2**  
    https://arxiv.org/abs/2412.15204
42. **LongBench Pro**  
    https://arxiv.org/abs/2601.02872
43. **Self-Guided Test-Time Training for Long-Context Language Models**  
    https://arxiv.org/abs/2607.09415
44. **LongAttnComp**  
    https://arxiv.org/abs/2606.01336

## Provider and standards documentation

45. OpenAI model documentation  
    https://developers.openai.com/api/docs/models
46. OpenAI latest-model guidance  
    https://developers.openai.com/api/docs/guides/latest-model
47. Anthropic model overview  
    https://platform.claude.com/docs/en/about-claude/models/overview
48. Anthropic, **Effective Context Engineering for AI Agents**  
    https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
49. Google Gemini long-context documentation  
    https://ai.google.dev/gemini-api/docs/long-context
50. Google Gemini token documentation  
    https://ai.google.dev/gemini-api/docs/tokens
51. Google Gemini context caching  
    https://ai.google.dev/gemini-api/docs/generate-content/caching
52. Meta Llama resources  
    https://ai.meta.com/llama/get-started/
53. MCP authorization specification  
    https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
54. A2A specification  
    https://a2a-protocol.org/latest/specification/

---

# Final Architectural Conclusion

The long-context race does not invalidate Shared Agent Context.

It makes SAC more important.

As model windows grow from 100K to 1M to 10M and beyond, the question shifts from:

> "Can this information physically fit?"

into:

> "What information should this agent receive, under whose authority, from which version, with what provenance, at what resolution, for this specific task?"

That is the layer SAC should own.

The durable system design is:

```text
unbounded project knowledge
         │
         ▼
permissions + truth + retrieval + compression
         │
         ▼
model-neutral context envelope
         │
         ▼
model-specific bounded working context
```

The project should therefore optimize for **high-quality context compilation**, not for owning or artificially enlarging any single model's native context window.

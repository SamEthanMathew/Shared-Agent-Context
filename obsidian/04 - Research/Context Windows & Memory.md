# Research: Context Windows, Memory, and Cross-Model Shared Context

**Research date:** August 11, 2026  
**Purpose:** Establish the technical foundation for Shared Agent Context (SAC) by separating what a model context window actually is from product memory, retrieval, conversation state, caching, and persistent multi-user agent memory.

---

## Executive Summary

The central conclusion of this research is that **Shared Agent Context should not attempt to literally share a model context window.** Context windows are model-specific, transient inference state. They differ in tokenizer, maximum size, positional representation, attention implementation, runtime caching, tool format, multimodal accounting, and effective long-context behavior.

What *can* be shared is a **model-neutral representation of project knowledge** that is persisted outside every model and selectively compiled into the bounded context of whichever model is acting at that moment.

This produces a more precise definition of SAC:

> **Shared Agent Context is a model-agnostic project memory and context-compilation layer. It turns an unbounded, multi-user project history into a bounded, permission-aware, task-relevant context package for any authorized AI agent.**

A useful systems analogy is:

- model weights = long-term parametric knowledge baked into the executable
- context window = working memory / RAM for one inference episode
- KV cache = runtime acceleration state for tokens already processed
- prompt cache = infrastructure optimization for repeated prefixes
- conversation store = application-layer history
- RAG = demand paging from external data
- persistent agent memory = durable state outside the model
- **SAC = shared storage + memory manager + access-control layer + context compiler for a team of heterogeneous agents**

The research strongly supports five design decisions:

1. **Canonical project state must live outside every model provider.**
2. **Raw text/structured data, not model internals, must be the interoperability boundary.**
3. **SAC must retrieve and compress aggressively rather than fill the largest available context window.**
4. **Provenance, time, authority, and permissions are core memory semantics, not optional metadata.**
5. **Provider adapters should translate one canonical context package into the token/instruction/tool format appropriate for each model.**

---

# 1. Terminology: The Words That Are Commonly Collapsed Together

A major source of confusion in AI products is that the word **memory** is used for several technically different mechanisms.

## 1.1 Parametric memory

This is knowledge represented in the trained model parameters.

Examples include language patterns, factual associations, coding knowledge, and behaviors learned during pretraining or post-training.

Parametric memory:

- is stored in model weights
- does not normally change because of one user conversation
- is shared by users of the same model checkpoint unless personalization/fine-tuning changes the model
- is difficult to update precisely
- does not provide natural source provenance

The original RAG paper explicitly contrasted this **parametric memory** with an external **non-parametric memory** that could be retrieved at inference time.

## 1.2 Context window

The context window is the finite token sequence/state available to the model during an inference operation.

Anthropic's context-engineering definition is especially useful: context is the set of tokens included when sampling from the LLM. In an agent, those tokens may represent far more than the user's latest prompt:

- system/developer instructions
- user messages
- prior assistant messages
- tool definitions
- tool results
- retrieved documents
- MCP resources/results
- files
- examples
- summaries
- persistent-memory recalls
- current task state

The context window is therefore **working state**, not durable storage.

## 1.3 Conversation history

A product may save a conversation in a database and reconstruct relevant history on a later turn.

That stored history can be much larger or longer-lived than the model's context window.

A saved conversation is therefore not itself the model context. It is a potential **source** from which future context is assembled.

## 1.4 KV cache

During autoregressive Transformer inference, the model repeatedly needs keys and values for prior tokens. Systems cache those key/value activations so they do not have to recompute the entire prefix on each generated token.

The KV cache:

- is model-architecture-specific
- contains internal numeric activations, not portable semantic records
- grows with the retained sequence length
- exists for computational efficiency
- is not durable semantic memory
- cannot be meaningfully transferred from an OpenAI model to a Claude or Gemini model

Techniques such as Multi-Query Attention (MQA) and Grouped-Query Attention (GQA) reduce KV-cache cost by sharing or grouping key/value heads.

## 1.5 Prompt/context caching

Providers can cache processing of repeated prompt prefixes to lower latency and/or price.

This is also not semantic memory.

The logical prompt still exists. Caching means the provider can reuse prior computation for an unchanged prefix rather than recomputing it.

For example:

- OpenAI exposes prompt caching and, for some modes, persisted reasoning state.
- Gemini uses implicit context caching on modern models and reports cached-token usage.
- Anthropic offers prompt caching to reduce cost for repeated context.

Caching should be understood as **compute reuse**, not knowledge storage.

## 1.6 Retrieval-Augmented Generation (RAG)

RAG stores information outside the model and retrieves a subset at inference time.

A classic pipeline is:

```text
Documents
   ↓
Chunk / normalize
   ↓
Create sparse and/or dense indexes
   ↓
User/agent query
   ↓
Retrieve candidates
   ↓
Rank / rerank
   ↓
Insert selected evidence into model context
   ↓
Generation
```

RAG solves a fundamentally different problem from a larger context window: it decides **which information deserves to enter the window**.

## 1.7 Persistent agent memory

Agent memory persists information across sessions and retrieves it later.

Systems such as MemGPT, MemoryBank, Mem0, and later collaborative-memory work introduce explicit write/manage/read loops instead of treating the entire chat transcript as the memory system.

## 1.8 Shared project memory

This is the layer SAC is targeting.

Shared project memory differs from personal agent memory because information has multiple authors, actors, readers, permissions, levels of authority, and potentially contradictory beliefs.

The memory is not only asking:

> "What should this assistant remember about this user?"

It is asking:

> "What is the current state of this project, who is allowed to see it, why do we believe it, when was it true, and what should this particular agent receive right now?"

---

# 2. What Actually Happens When an LLM Receives Context

Most current frontier language models are Transformer-derived, although exact proprietary architectures are not fully disclosed and alternative sequence architectures such as Mamba and RWKV demonstrate that attention is not the only possible design.

For SAC, the important point is that the **external interface is tokens/context**, regardless of the internal model architecture.

## 2.1 Tokenization

A model does not usually receive human-readable text directly. A tokenizer converts text into token IDs.

Tokens are model/tokenizer dependent. The same sentence can consume a different number of tokens in different systems.

Token boundaries can correspond to:

- entire common words
- pieces of words
- punctuation
- whitespace patterns
- characters or byte sequences
- special control tokens

This matters to SAC because **"4,000 tokens" is not a universal unit across models**.

A canonical SAC memory should therefore never be stored as "the OpenAI token representation." Store model-neutral text and structure, then estimate/tokenize for the target provider when packaging context.

## 2.2 Token embeddings

Each token ID is mapped into a learned vector representation.

These vectors are internal to the model. Their coordinate spaces have no guaranteed alignment with another model's token embeddings.

Therefore SAC should not attempt to pass hidden-state vectors from one generative model directly to another.

## 2.3 Position information

Attention by itself does not inherently know whether a token is first, 50th, or 500,000th in the sequence. Models need a position mechanism.

Historically important approaches include:

- absolute/sinusoidal positional encoding in the original Transformer
- relative position techniques
- ALiBi, which biases attention based on token distance
- RoPE, which rotates query/key representations according to position
- interpolation/scaling methods that extend RoPE-based models to longer sequences

Long-context support therefore depends partly on **how the model represents positions** and what lengths it saw during training or long-context adaptation.

## 2.4 Causal self-attention

For a decoder-style language model, each new token can attend to previous tokens allowed by the causal mask.

Conceptually:

```text
Q = XWq
K = XWk
V = XWv

Attention(Q,K,V) = softmax(QKᵀ / sqrt(d)) V
```

The key systems issue is the `QKᵀ` interaction across positions. Dense attention over `n` tokens has quadratic sequence-length scaling for this attention matrix in the straightforward formulation.

This is why going from 8K to hundreds of thousands or millions of tokens is not simply a matter of increasing a constant.

## 2.5 Efficient attention

Long-context systems use several techniques to make attention practical.

### FlashAttention

FlashAttention keeps exact attention mathematically but changes how the operation is tiled and moves data between GPU memory levels. The paper demonstrated that memory traffic, not only arithmetic FLOPs, is a central bottleneck.

### Sparse/local attention

Longformer and BigBird explored patterns where a token does not densely attend to every other token, reducing complexity while retaining selected long-range/global connections.

### MQA/GQA

Multi-Query and Grouped-Query Attention reduce key/value storage and memory bandwidth during decoding.

### Alternative sequence models

RWKV combines recurrent inference with Transformer-like training characteristics. Mamba uses selective state-space models with linear sequence scaling. These designs show that future SAC clients may not all possess Transformer-style context internals.

This reinforces the need for an **architecture-neutral external memory interface**.

## 2.6 Autoregressive decoding and the KV cache

Once the prompt has been processed (often called **prefill**), generation proceeds one token at a time.

Without caching, the model would repeatedly recompute representations for the same previous tokens. A KV cache stores the key/value activations for those tokens.

This improves decoding efficiency but introduces an important scaling constraint: retaining more history means retaining more KV state.

StreamingLLM explicitly identifies KV-cache growth as a major problem in long-running dialogue and explores keeping selected initial "attention sink" tokens plus a moving recent window.

Again, a KV cache is **ephemeral runtime state**, not project memory.

---

# 3. Why Different Models Do Not Have a Shared Context Window

Suppose Sam is using model A and Matthew is using model B.

There is no general mechanism by which their live context windows can simply be joined.

## 3.1 Different tokenizers

The exact same project document is converted into different token sequences.

## 3.2 Different embedding spaces

Token and hidden representations are learned independently. One model's activation vector has no stable semantic meaning inside another model.

## 3.3 Different architectures

Models can differ in:

- layer count
- hidden dimension
- number of attention heads
- KV-head strategy
- positional encoding
- modality encoders
- mixture-of-experts routing
- attention sparsity
- state-space/recurrent mechanisms
- tool-call serialization

## 3.4 Different context limits

As of this research date, published limits vary significantly. Examples from current official documentation include:

- OpenAI GPT-5.6 family: approximately **1.05M context**, with separate 128K maximum output limits in the API documentation.
- Google Gemini models: many models support **1M+ token contexts**; Gemini documentation treats the context window as a model-specific combined input/output constraint and publishes model-specific input/output limits.
- Anthropic: current Claude offerings vary by product/model; Anthropic documents 200K-class contexts broadly and million-token API contexts for supported Sonnet models.
- Meta Llama 4 Scout: official Meta materials advertise a **10M supported context window**.

These figures should not be interpreted as interchangeable memory capacities.

## 3.5 Different training lengths versus supported lengths

Meta provides a particularly useful example. Llama 4 Scout supports a 10M window, while Meta states Scout was pre-trained and post-trained with 256K context and then received long-context extension/generalization work.

This demonstrates that at least three quantities can differ:

1. training-time sequence length
2. supported inference length
3. effective context length on a real task

SAC should care primarily about the third.

## 3.6 Different tool and instruction semantics

Even when two systems accept text, they can treat the following differently:

- system/developer instructions
- tool definitions
- tool results
- images/audio/video
- structured output schemas
- reasoning state
- special tokens

Therefore interoperability should occur **above** the model's native context format.

---

# 4. Nominal Context Length Is Not Effective Context Length

This is one of the most consequential research findings for SAC.

An API accepting `N` tokens does not prove the model can use every relevant fact inside those `N` tokens equally well.

## 4.1 Lost in the Middle

Liu et al. found a characteristic pattern in which models often performed best when relevant information was near the beginning or end of long context and worse when the relevant information was in the middle.

The implication is simple:

> More information in the prompt can make the information you care about harder to use.

## 4.2 RULER

RULER expanded beyond simple needle-in-a-haystack retrieval into multi-needle, tracing, and aggregation tasks. Its authors found substantial performance degradation as sequence length and task complexity increased, even among models advertising large windows.

This motivates a distinction between **advertised context size** and **effective context size**.

## 4.3 LongBench

LongBench evaluated several realistic long-context task categories including document QA, multi-document QA, summarization, few-shot learning, synthetic tasks, and code completion. Models still struggled as inputs became longer.

## 4.4 NoLiMa

NoLiMa removed much of the convenient lexical overlap found in basic needle tests. The task required the model to make latent associations rather than search for an obvious matching phrase. Performance dropped sharply as context length increased.

This is especially relevant to SAC because real project recall often works like NoLiMa, not needle search:

> "What architecture constraints matter for this Windows auth implementation?"

may need retrieval of a decision that never contains the words "Windows auth implementation."

## 4.5 LongBench Pro

2026 LongBench Pro results reinforce the distinction: effective context length is typically shorter than claimed maximum context length, and performance varies by task and language.

## 4.6 Vendor guidance converges on the same conclusion

Google's own long-context guide advises users not to pass unnecessary tokens and notes that multi-needle retrieval is less reliable than single-needle tests.

Anthropic's context-engineering guidance describes context as a finite resource with diminishing marginal returns and recommends finding the **smallest high-signal set of tokens** that maximizes desired behavior.

OpenAI's current GPT-5.6 guidance similarly reports that leaner prompts/tools can improve performance in internal agent evaluations while reducing token use.

The systems conclusion is stronger than "RAG saves money":

> **Context selection is part of model quality.**

---

# 5. How Long Context Became Possible

A short research timeline helps explain the current architecture landscape.

## 2017: Transformer

*Attention Is All You Need* replaced recurrence/convolution as the core sequence mechanism with attention-based Transformer blocks.

The design enabled highly parallel training, but dense self-attention created sequence-length scaling challenges.

## 2019: Transformer-XL

Transformer-XL introduced segment-level recurrence and a positional method that allowed dependencies beyond one fixed segment. It is an early example of treating finite context as a systems problem rather than simply increasing one input tensor.

## 2019: Multi-Query Attention

MQA shared key/value heads, dramatically reducing decode-time memory bandwidth for K/V tensors.

## 2021: RoPE and ALiBi

RoPE and ALiBi offered position representations with useful relative-distance/extrapolation properties and became influential in long-context model design.

## 2022: FlashAttention

FlashAttention demonstrated exact attention with an IO-aware GPU algorithm, making longer sequences substantially more practical.

## 2023: GQA

GQA provided an intermediate point between full multi-head KV representations and one shared KV head, balancing quality with inference efficiency.

## 2023: Position Interpolation / YaRN

These methods extended pretrained RoPE-based models beyond their original context by transforming/scaling positional behavior and using relatively efficient adaptation.

## 2023: StreamingLLM

StreamingLLM explored bounded cache behavior for effectively unbounded streams while preserving attention sink tokens.

## 2023 onward: alternative long-sequence backbones

RWKV and Mamba demonstrated recurrent/state-space alternatives with linear or constant-state inference properties.

The lesson for SAC is that **the internal definition of model working memory will continue changing**. SAC should not couple its core data model to today's Transformer implementation.

---

# 6. Product-Level Context: What AI Applications Actually Send to Models

A model API call is only the inner layer of a product such as ChatGPT, Claude, Gemini, Cursor, or an agent harness.

The product may maintain a much larger universe of information than can fit in one inference call.

A realistic architecture is:

```text
                         ┌──────────────────────┐
                         │ Product state        │
                         │                      │
                         │ chats                │
                         │ files                │
                         │ memories             │
                         │ project instructions │
                         │ tool results         │
                         │ connected data       │
                         └──────────┬───────────┘
                                    │
                         selection / retrieval
                         compaction / filtering
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Inference context    │
                         │ finite token budget  │
                         └──────────┬───────────┘
                                    │
                                    ▼
                                 Model
```

The product's stored state is **not equivalent** to the context window.

## 6.1 Stateful APIs

A provider may let an application pass an ID rather than manually resend every previous turn.

For example, Google's Interactions API supports `previous_interaction_id`. Google stores the interaction history server-side and can use the ID to continue a conversation.

OpenAI's Responses API similarly supports continuation and current models expose mechanisms such as persisted reasoning and prompt caching.

These features improve developer ergonomics and caching, but do not create cross-provider memory. The saved state remains inside one provider's system and the next generation still operates under that model's context constraints.

## 6.2 Truncation

When history grows past a context limit, systems must eventually:

- reject the request
- drop older content
- compact/summarize
- retrieve only selected material
- move state to external memory
- or combine these techniques

OpenAI's API documentation explicitly describes truncating older conversation messages when input exceeds configured limits in applicable APIs.

## 6.3 Compaction

Anthropic describes compaction as summarizing a conversation nearing the context-window limit and continuing with that compressed state. Claude Code preserves important architectural decisions, unresolved bugs, implementation details, and recent files while discarding less useful old tool output.

Compaction is lossy. Its quality depends on deciding what future work will need.

## 6.4 Structured note-taking

Anthropic also describes agentic note-taking: the agent writes durable notes outside the active window and reloads them later.

This simple technique is surprisingly close to the earliest useful SAC primitive, except SAC makes it:

- shared
- structured
- permission aware
- provenance aware
- model independent

---

# 7. Existing Product Collaboration Context

Current products validate the demand for shared project context, but they are still provider-specific.

## 7.1 ChatGPT Projects

OpenAI currently describes Projects as workspaces containing chats, files, and project instructions. Shared projects become project-only memory spaces. ChatGPT can draw from chats, uploaded files, and instructions in that shared project while excluding members' outside personal context/memory.

This is meaningful validation of the idea that **project context should be its own boundary**.

However:

- the project brain is usable by ChatGPT/OpenAI clients
- project memory is not exposed as a model-neutral structured memory API
- users cannot inspect a simple canonical list of all project memories
- it is not automatically the project state used by Claude, Gemini, Cursor, local models, etc.

## 7.2 Claude Projects

Claude Projects provide a project knowledge base shared across chats. Anthropic's documentation explicitly notes that context is **not automatically shared across chats unless the information is added to the project knowledge base**. When the knowledge base approaches context limits, paid Claude projects can use RAG behavior.

This is another validation of separating stored project knowledge from one chat's immediate window.

## 7.3 Gemini

Gemini's APIs provide large context windows, context caching, and server-side conversation continuation. These are strong context-management capabilities, but they remain Gemini/API state rather than a neutral organizational memory shared with arbitrary providers.

## 7.4 Repository instruction files

Files such as `CLAUDE.md`, `AGENTS.md`, and similar repository-level instructions are a useful low-tech shared-memory pattern.

Their advantages:

- human readable
- version controlled
- vendor/tool adapters can read them
- excellent for durable instructions

Their limitations for SAC's target problem:

- updates are generally file/commit oriented
- weak representation of temporal state
- weak memory-level permissions
- no native semantic retrieval
- no provenance for each extracted claim
- no first-class conflict/supersession model
- difficult to maintain continuously across non-code work

SAC should interoperate with these files, not dismiss them.

---

# 8. External Memory Research

## 8.1 RAG: parametric + non-parametric memory

Lewis et al. formalized an influential pattern: a language model can remain the generator while an external index provides updateable, inspectable knowledge at inference time.

This separation is foundational to SAC.

The generator does not have to **own** the knowledge it reasons over.

## 8.2 Contextual Retrieval

Anthropic showed a practical weakness in naive chunking: a chunk may lose the surrounding information needed to retrieve it correctly.

Their Contextual Retrieval method adds chunk-specific context before building embedding and BM25 indexes. Anthropic reported substantially reduced retrieval failures in its experiments, particularly when combining contextualized embeddings, lexical search, and reranking.

For SAC this suggests that every indexed project memory should carry enough surrounding identity to remain retrievable:

```text
Bad chunk:
"We changed it because Windows did not support the previous approach."

Better indexed representation:
"Auth architecture decision, Desktop Client, Aug 2026:
We changed credential persistence from a shared custom vault design to
OS-native secure stores because the Windows implementation did not support
the previous approach."
```

## 8.3 RAPTOR

RAPTOR builds a hierarchy of source chunks and recursively generated summaries. Retrieval can operate at different abstraction levels.

This matters because project questions occur at different scopes:

- "What is the project trying to accomplish?" needs high-level context.
- "What exact field did we rename?" needs low-level evidence.

SAC should eventually support **multi-resolution memory**, not one flat vector collection.

## 8.4 HippoRAG / graph memory

HippoRAG combines language models, a knowledge graph, and Personalized PageRank to support associative and multi-hop retrieval.

A project is naturally relational:

```text
Decision A ──implements──▶ Requirement B
     │
     └──supersedes──▶ Decision C

PR 182 ──implements──▶ Decision A

Matthew ──owns──▶ Windows client
```

Graph retrieval can become valuable after the MVP, particularly for multi-hop questions and causal/project relationships.

## 8.5 MemGPT

MemGPT is perhaps the clearest conceptual ancestor for SAC's context-management layer. It frames finite LLM context using an operating-system memory analogy and dynamically moves information between memory tiers.

The extension SAC needs is:

> from **one agent virtualizing its own context** to **many users and heterogeneous agents sharing a governed external project memory**.

## 8.6 Mem0

Mem0 focuses on extracting, consolidating, and retrieving salient memories instead of repeatedly replaying full conversation history. Its results support the practical thesis that a memory system can reduce token/latency costs while improving long-term recall compared with sending everything.

The architectural pattern is more important than any single benchmark number:

```text
conversation/event
      ↓
extract durable memory
      ↓
consolidate / update
      ↓
persist
      ↓
retrieve when relevant
```

That is close to SAC's write/manage/read loop.

---

# 9. Multi-User and Collaborative Memory Research

This is the closest research area to Shared Agent Context and should directly influence the design.

## 9.1 Collaborative Memory (2025)

*Collaborative Memory: Multi-User Memory Sharing in LLM Agents with Dynamic Access Control* explicitly studies multi-user, multi-agent memory with asymmetric, time-varying access controls.

Its important ideas include:

- private versus shared memory tiers
- immutable provenance attributes
- user-agent-resource relationships
- read policies that produce filtered views
- write policies that determine what can persist/share
- retrospective permission checks
- auditability

This validates a core SAC premise: **multi-user memory is not just RAG with multiple usernames.**

Permissions are part of the memory semantics.

## 9.2 Governed Collaborative Memory (2026)

This work argues that once memory becomes persistent and shared, the system must decide which candidate memories become institutional/project state.

It highlights:

- local memory
- shared institutional memory
- archive memory
- project-continuity memory
- provenance/version lineage
- rejection
- revision
- supersession
- human ratification

This maps very closely to SAC's proposed separation between observations, hypotheses, decisions, and authoritative project state.

## 9.3 GroupMemBench (2026)

GroupMemBench is particularly important for product evaluation. It evaluates memory in multi-party conversations and reports that current memory systems struggle with:

- group dynamics
- speaker-grounded belief tracking
- knowledge updates
- ambiguous terms
- temporal reasoning
- user-specific perspective

Its strongest tested memory system still achieved only 46% average accuracy in the reported benchmark, and simple BM25 was competitive with many more complex systems.

The implication for SAC is critical:

> A multi-user project brain cannot flatten "Sam said X" and "Matthew said Y" into anonymous text fragments.

Speaker/actor identity and epistemic status must survive ingestion.

---

# 10. Cross-Model Interoperability: What Can Actually Move Between Models?

A central architectural question for SAC is the **interchange representation**.

## 10.1 What cannot be assumed portable

Do not treat these as cross-provider interchange formats:

- tokenizer IDs
- hidden states
- model-native token embeddings
- KV cache tensors
- attention maps
- provider-private reasoning representations
- provider-specific chat objects
- model-specific tool-call control tokens

## 10.2 What can be portable

Use representations with explicit shared semantics:

- UTF-8 text
- JSON / typed objects
- files / artifacts
- source URIs
- timestamps
- identity IDs
- ACLs
- provenance records
- relations
- standardized tool/resource protocols

## 10.3 Embeddings need special treatment

Embeddings are useful for retrieval, but vectors produced by different embedding models generally should not be assumed to inhabit the same coordinate space.

Therefore:

- store canonical content separately from embeddings
- record which embedding model/version generated every vector
- regenerate/reindex embeddings when changing embedding providers
- optionally support multiple indexes
- never make one provider's embedding vector the canonical memory record

## 10.4 Re-tokenize at the boundary

The same SAC Context Envelope should be re-tokenized for each target model.

Conceptually:

```text
                    CANONICAL PROJECT MEMORY
                              │
                              ▼
                    SAC retrieval / ranking
                              │
                     model-neutral envelope
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
  OpenAI Adapter      Anthropic Adapter      Gemini Adapter
  tokenizer/budget    tokenizer/budget       tokenizer/budget
  prompt/tool form    prompt/tool form       prompt/tool form
          │                   │                   │
          ▼                   ▼                   ▼
       OpenAI              Claude              Gemini
```

This is the core technical mechanism behind "same project brain, different models."

---

# 11. MCP and A2A: Where Standards Fit

## 11.1 Model Context Protocol (MCP)

MCP standardizes how AI applications access tools/resources/context-producing services.

The July 28, 2026 MCP specification moves the core toward stateless request/response semantics and continues to strengthen routing, caching, extensions, and authorization.

SAC can expose itself as an MCP server:

```text
sac.recall
sac.remember
sac.search
sac.recent_changes
sac.get_artifact
sac.propose_decision
```

This dramatically reduces the number of custom client integrations needed.

But MCP is **not itself the SAC database or memory model**. MCP is the transport/tool integration surface.

## 11.2 Agent2Agent (A2A)

A2A is an open protocol for independent agents to discover one another, delegate work, exchange information, and collaborate without exposing internal state.

That is complementary to SAC.

A clean separation is:

```text
MCP  → agent ↔ tools/resources/data
A2A  → agent ↔ agent tasks/messages
SAC  → durable shared project state / memory
```

SAC can eventually participate in both:

- expose project memory through MCP
- attach SAC context references/envelopes to A2A task exchanges

The protocol ecosystem strengthens rather than weakens SAC's value because it makes a neutral memory service easier for heterogeneous clients to consume.

---

# 12. Proposed SAC Memory Architecture After This Research

The research suggests separating four durable layers plus one runtime compiler.

```text
┌──────────────────────────────────────────────────────┐
│                 1. EVIDENCE STORE                    │
│ Raw chats, docs, commits, PRs, files, tool outputs   │
│ Immutable/traceable source artifacts where possible  │
└──────────────────────────┬───────────────────────────┘
                           │ extraction
                           ▼
┌──────────────────────────────────────────────────────┐
│                 2. MEMORY STORE                      │
│ Facts, decisions, goals, constraints, tasks, status  │
│ temporal validity, authority, confidence, provenance │
└──────────────────────────┬───────────────────────────┘
                           │ relations
                           ▼
┌──────────────────────────────────────────────────────┐
│                 3. RELATION GRAPH                    │
│ supersedes / contradicts / supports / implements     │
│ owner / dependency / derived_from                    │
└──────────────────────────┬───────────────────────────┘
                           │ indexed into
                           ▼
┌──────────────────────────────────────────────────────┐
│                 4. RETRIEVAL INDEXES                 │
│ dense vectors + BM25/lexical + structured indexes    │
│ optional graph/community/hierarchical summaries      │
└──────────────────────────┬───────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────┐
│                 5. CONTEXT COMPILER                  │
│ auth → query → retrieve → resolve time/conflicts     │
│ rank → compress → token-budget → provider adapter    │
└──────────────────────────────────────────────────────┘
```

## Why keep evidence and memory separate?

Consider:

```text
Raw source:
Sam: "I think we should probably use Postgres. I'll confirm tomorrow."

Memory candidate:
type: hypothesis
content: "PostgreSQL is the likely primary database."
authority: member_statement
confidence: medium

Later source:
Architecture decision record merged by team:
"Primary database: PostgreSQL."

Canonical memory:
type: decision
status: active
authority: approved_spec
```

If SAC stores only a summary, it loses the ability to re-evaluate the memory when policies/models improve.

The evidence store preserves source truth; the memory store preserves current interpretation.

---

# 13. Proposed Model-Neutral Context Envelope

SAC needs an interchange object between the shared brain and a model adapter.

A possible V0 shape:

```json
{
  "schema_version": "0.1",
  "project": {
    "id": "proj_123",
    "name": "Shared Desktop App"
  },
  "request": {
    "actor_user_id": "user_matthew",
    "actor_agent_id": "claude_windows_1",
    "task": "Implement secure credential storage on Windows",
    "requested_at": "2026-08-11T21:00:00-07:00"
  },
  "project_state": {
    "goals": [],
    "decisions": [],
    "requirements": [],
    "constraints": [],
    "active_tasks": [],
    "recent_changes": []
  },
  "evidence": [],
  "conflicts": [],
  "provenance": [],
  "budget": {
    "target_model": "provider:model",
    "max_context_tokens": 1000000,
    "reserved_for_system_tools_and_output": 100000,
    "sac_context_budget": 12000
  }
}
```

The important design choice is that `sac_context_budget` should generally be **much smaller than the model's maximum window**.

A model that supports 1M tokens does not mean SAC should return 900K tokens.

---

# 14. Context Compilation Algorithm

A future retrieval request should look more like a compiler pipeline than a vector-search call.

## Stage 1: Identify actor and security boundary

Resolve:

- human user
- acting agent/client
- project membership
- scopes
- memory-level restrictions

Filter before any sensitive content reaches the model.

## Stage 2: Understand the task

Extract:

- entities
- files/components
- time horizon
- task type
- likely memory types
- desired granularity

## Stage 3: Candidate generation

Use multiple retrieval channels:

- exact/lexical search
- dense semantic retrieval
- structured filters
- recent changes
- graph expansion
- hierarchy/summary retrieval

The research does **not** support relying on vector similarity alone.

## Stage 4: Truth/state resolution

Apply:

- current temporal validity
- supersession relationships
- authority
- confidence
- project branch/environment
- unresolved contradictions

## Stage 5: Rank by task utility

Potential score components:

```text
relevance
+ authority
+ importance
+ recency_when_relevant
+ dependency/connectivity
+ explicit_task_match
- redundancy
- staleness
- uncertainty_penalty_when_task_requires_fact
```

Do not permanently hard-code this formula. It should be evaluated empirically.

## Stage 6: Multi-resolution compression

Prefer:

- canonical concise memory first
- detailed evidence only when necessary
- artifact references rather than full artifacts
- hierarchical summaries for broad questions

## Stage 7: Token budgeting

Provider adapter estimates target-model token cost.

Reserve context for:

- system instructions
- tool schemas
- recent conversation
- current user task
- model output/reasoning requirements

Then pack SAC memories into the remaining budget.

## Stage 8: Serialize for target model

Different models may perform better with different representations.

Possible formats:

- concise Markdown sections
- XML-style blocks
- JSON
- tool/resource objects

Anthropic's tool-design research explicitly notes that response structure can affect model performance, so provider/task adapters should be evaluation driven.

## Stage 9: Return provenance handles

Every injected memory should retain a stable ID so the agent can inspect or cite its source.

---

# 15. Write Path: What Should Become Shared Memory?

This is likely harder than retrieval.

A naive system that stores every utterance becomes an expensive, contradictory transcript index.

The proposed write pipeline is:

```text
new event
   ↓
is it durable project knowledge?
   ↓
extract candidate claims/state changes
   ↓
classify epistemic type
   ↓
attach actor + source + time + permissions
   ↓
find related/current memories
   ↓
duplicate? contradiction? supersession?
   ↓
apply project write policy
   ↓
accept / propose / reject / require confirmation
   ↓
persist event + memory version + indexes
```

## Epistemic types matter

At minimum distinguish:

- observation
- hypothesis
- proposal
- decision
- fact
- requirement
- constraint
- task
- status

This prevents a common failure mode:

```text
"Maybe we should use Redis"
```

becoming:

```text
"Project uses Redis"
```

## Authority matters

A merged architecture specification may have more authority than an agent's guess.

Authority should be explicit and configurable, not inferred only from natural-language confidence.

## Time matters

Store temporal state such as:

```text
valid_from
valid_until
superseded_by
observed_at
recorded_at
```

Projects change constantly. Correct historical memory is still incorrect **current** context if temporal validity is ignored.

---

# 16. Personal Context Versus Shared Context

SAC should explicitly avoid merging all collaborators' personal memories into one project brain.

A safer architecture is:

```text
Sam personal memory ───────┐
                           │ optional local personalization
Sam agent ─────────────────┼────┐
                                │
                                ▼
                         SAC PROJECT VIEW
                                ▲
                                │
Matthew agent ─────────────┼────┘
                           │
Matthew personal memory ───┘
```

The project layer contains information authorized for project use.

This protects two important properties:

1. a collaborator does not accidentally expose unrelated personal AI memory
2. the shared brain stays focused on project state rather than becoming a merged profile of everyone involved

ChatGPT's shared-project design currently uses a similar high-level boundary: shared projects are project-only and do not pull members' outside personal context into the project.

---

# 17. Security and Governance Implications

A cross-model memory layer increases the blast radius of a bad memory.

If one compromised agent writes malicious or false project state and every future agent retrieves it, the memory system becomes a persistence mechanism for error or prompt injection.

## Required controls

### Data versus instruction separation

Retrieved evidence must not automatically gain system-instruction authority.

### Source-aware trust

Preserve whether content came from:

- project owner
- collaborator
- merged code/spec
- external document
- untrusted webpage
- agent inference

### Write permissions

An agent that can read architecture context does not automatically need permission to change canonical architecture decisions.

### Confirmation classes

Examples:

```text
low risk:
"PR #82 was merged" → auto-ingest

medium risk:
"Windows build now requires SDK 12" → accept with evidence

high authority:
"We are replacing PostgreSQL with DynamoDB" → propose / human confirm
```

### Immutable event history

Edits should produce versions/supersessions rather than erase all lineage.

### Revocation and retrospective filtering

If access changes, SAC should be able to determine which memories/resources an agent/user may still retrieve.

The Collaborative Memory research specifically motivates time-varying access policies and provenance-aware retrospective permission checks.

---

# 18. What This Research Changes About the MVP

The previous MVP correctly focused on `remember` and `recall`, but the technical contract should now be sharper.

## MVP should build

### Canonical structured memory

Not a provider-specific conversation object.

### Source/evidence reference

Even if V0 stores only a source URI/snippet, every memory needs provenance.

### Explicit memory writes first

This remains the right choice. Automatic memory extraction can come after the cross-model primitive works.

### Hybrid retrieval

Use at least:

- PostgreSQL structured filters
- lexical/full-text search
- vector similarity

Do not depend only on embeddings.

### Provider-neutral recall API

Example:

```http
POST /v1/projects/{project_id}/context/query
```

Request:

```json
{
  "task": "Implement Windows credential storage",
  "client": {
    "provider": "anthropic",
    "model": "..."
  },
  "budget": {
    "max_sac_tokens": 8000
  }
}
```

### MCP adapter

Expose the same backend through MCP.

### Two genuinely independent clients

The demo is not proven if both agents are just two sessions inside one provider-controlled project feature.

A strong MVP demonstration uses two independently authenticated clients/providers.

## MVP should not build yet

- automatic ingestion of every chat
- full graph retrieval
- complex learned memory policies
- universal A2A orchestration
- model-specific hidden-state transfer
- giant context replay

---

# 19. Evaluation Plan for SAC

SAC needs its own evaluation because ordinary RAG benchmarks do not test multi-user project-state correctness.

## 19.1 Cross-agent handoff accuracy

Agent A writes a decision. Agent B receives a related task.

Measure whether B retrieves and applies the decision.

## 19.2 Update/supersession accuracy

Timeline:

```text
T1: API uses page numbers
T2: team switches to cursor pagination
T3: agent asked to implement endpoint
```

The agent should use T2 and understand T1 as historical.

## 19.3 Speaker/authority tracking

```text
Sam: "I propose X"
Matthew: "I disagree; current implementation remains Y"
Owner/spec later confirms Y
```

The system must not synthesize "project decided X."

## 19.4 Permission isolation

Create memories with different ACLs and verify unauthorized clients never receive them.

This must be tested before the model is invoked.

## 19.5 Conflict handling

Present equally authoritative contradictory claims and verify the context package surfaces uncertainty/conflict rather than fabricating certainty.

## 19.6 Long-history compression

Generate thousands of historical events but query one narrow task. Measure:

- recall
- precision
- final task success
- tokens injected
- latency

## 19.7 Cross-provider consistency

Run the same SAC context request through multiple provider adapters.

The goal is not identical wording. The goal is that all agents receive the same relevant **project state**.

## 19.8 Context budget curve

Evaluate success at increasing SAC budgets:

```text
1K
2K
4K
8K
16K
32K
...
```

Find the smallest reliable context budget for each task class rather than automatically using the provider maximum.

## 19.9 Group-memory benchmarks

Track GroupMemBench-style cases:

- who said what
- changing beliefs
- ambiguous terminology
- temporal updates
- user-specific permissions
- abstention when information is unavailable

---

# 20. Research Conclusions for Product Strategy

## Conclusion 1: SAC is not a bigger context window

This is the most important positioning correction.

Long-context models are becoming extremely capable and maximum windows will continue growing. A product whose value proposition is only "we let you give the model more text" will get commoditized.

SAC instead solves:

- ownership
- cross-provider portability
- multi-user state
- authorization
- provenance
- temporal truth
- conflict resolution
- context selection
- cross-agent continuity

These remain problems even with a 10M-token model.

## Conclusion 2: Bigger windows increase the need for context engineering

Research and vendor guidance show that irrelevant context can reduce effective model performance. Larger windows expand the possible search space; they do not remove the need to decide what is relevant.

SAC's retrieval layer should be judged on **task success per unit of context**, not on how many tokens it can stuff into a model.

## Conclusion 3: The durable object is project state

Chats are evidence. Files are evidence. Commits are evidence. Agent outputs are evidence.

The durable product is a continuously maintained representation of project state with traceability back to that evidence.

## Conclusion 4: Cross-model portability requires a semantic ABI

Models cannot exchange internal activations reliably. SAC therefore needs a stable, documented model-neutral **Context Envelope** and a family of provider adapters.

This could eventually become a useful protocol in its own right.

## Conclusion 5: Shared memory requires governance

Single-user memory can sometimes tolerate fuzzy personalization. Shared project memory cannot.

When a memory may influence multiple humans and autonomous agents, the system needs:

- identity
- authority
- permissions
- provenance
- version history
- temporal validity
- correction
- rejection
- supersession

## Conclusion 6: MCP is an excellent initial distribution interface

MCP solves much of the client/tool integration problem. SAC should use MCP without defining SAC as "an MCP server." The value is the memory/state system behind the protocol.

## Conclusion 7: A2A is complementary

A2A moves tasks and messages between agents. SAC can provide the durable state those agents consult before, during, and after those tasks.

## Conclusion 8: The MVP remains simple

The first magical experience is still:

> Different people. Different accounts. Different models. Same project brain.

The research does not invalidate the MVP. It explains exactly how to implement it without confusing context windows with memory.

---

# 21. Proposed Architectural Principle

Add this as a hard constraint for all future SAC design:

> **Never make a model's native context representation the canonical representation of project knowledge.**

And a second:

> **SAC should minimize the context it sends while maximizing the probability that the acting agent receives every project fact necessary for the task.**

These two principles capture most of the research above.

---

# 22. Reading List and Sources

## Transformer and long-context foundations

1. Vaswani et al. (2017), **Attention Is All You Need**  
   https://arxiv.org/abs/1706.03762

2. Dai et al. (2019), **Transformer-XL: Attentive Language Models Beyond a Fixed-Length Context**  
   https://arxiv.org/abs/1901.02860

3. Shazeer (2019), **Fast Transformer Decoding: One Write-Head is All You Need**  
   https://arxiv.org/abs/1911.02150

4. Su et al. (2021), **RoFormer: Enhanced Transformer with Rotary Position Embedding**  
   https://arxiv.org/abs/2104.09864

5. Press et al. (2021), **Train Short, Test Long: Attention with Linear Biases Enables Input Length Extrapolation**  
   https://arxiv.org/abs/2108.12409

6. Dao et al. (2022), **FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness**  
   https://arxiv.org/abs/2205.14135

7. Ainslie et al. (2023), **GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints**  
   https://arxiv.org/abs/2305.13245

8. Chen et al. (2023), **Extending Context Window of Large Language Models via Positional Interpolation**  
   https://arxiv.org/abs/2306.15595

9. Peng et al. (2023), **YaRN: Efficient Context Window Extension of Large Language Models**  
   https://arxiv.org/abs/2309.00071

10. Xiao et al. (2023), **Efficient Streaming Language Models with Attention Sinks**  
    https://arxiv.org/abs/2309.17453

11. Gu & Dao (2023), **Mamba: Linear-Time Sequence Modeling with Selective State Spaces**  
    https://arxiv.org/abs/2312.00752

12. Peng et al. (2023), **RWKV: Reinventing RNNs for the Transformer Era**  
    https://arxiv.org/abs/2305.13048

## Effective context and evaluation

13. Liu et al. (2024), **Lost in the Middle: How Language Models Use Long Contexts**  
    https://arxiv.org/abs/2307.03172

14. Bai et al. (2023), **LongBench: A Bilingual, Multitask Benchmark for Long Context Understanding**  
    https://arxiv.org/abs/2308.14508

15. Hsieh et al. (2024), **RULER: What's the Real Context Size of Your Long-Context Language Models?**  
    https://arxiv.org/abs/2404.06654

16. Modarressi et al. (2025), **NoLiMa: Long-Context Evaluation Beyond Literal Matching**  
    https://arxiv.org/abs/2502.05167

17. Chen et al. (2026), **LongBench Pro**  
    https://arxiv.org/abs/2601.02872

## Retrieval and memory

18. Lewis et al. (2020), **Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks**  
    https://arxiv.org/abs/2005.11401

19. Sarthi et al. (2024), **RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval**  
    https://arxiv.org/abs/2401.18059

20. Gutiérrez et al. (2024), **HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models**  
    https://arxiv.org/abs/2405.14831

21. Packer et al. (2023), **MemGPT: Towards LLMs as Operating Systems**  
    https://arxiv.org/abs/2310.08560

22. Chhikara et al. (2025), **Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory**  
    https://arxiv.org/abs/2504.19413

23. Anthropic (2024), **Contextual Retrieval**  
    https://www.anthropic.com/engineering/contextual-retrieval

24. Anthropic (2025), **Effective context engineering for AI agents**  
    https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

## Multi-user / collaborative memory

25. Rezazadeh et al. (2025), **Collaborative Memory: Multi-User Memory Sharing in LLM Agents with Dynamic Access Control**  
    https://arxiv.org/abs/2505.18279

26. Cuadros et al. (2026), **Governed Collaborative Memory as Artificial Selection in LLM-Based Multi-Agent Systems**  
    https://arxiv.org/abs/2605.04264

27. Yang et al. (2026), **GroupMemBench: Benchmarking LLM Agent Memory in Multi-Party Conversations**  
    https://arxiv.org/abs/2605.14498

28. Du (2026), **Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers**  
    https://arxiv.org/abs/2603.07670

## Current provider/product documentation

29. OpenAI, **Models / GPT-5.6 model documentation**  
    https://developers.openai.com/api/docs/models

30. OpenAI, **Projects in ChatGPT**  
    https://help.openai.com/en/articles/10169521-projects-in-chatgpt

31. OpenAI, **GPT-5.6 model guidance**  
    https://developers.openai.com/api/docs/guides/latest-model

32. Google, **Gemini API: Long context**  
    https://ai.google.dev/gemini-api/docs/long-context

33. Google, **Gemini API: Understand and count tokens**  
    https://ai.google.dev/gemini-api/docs/tokens

34. Google, **Gemini Interactions API**  
    https://ai.google.dev/gemini-api/docs/interactions-overview

35. Google, **Gemini context caching**  
    https://ai.google.dev/gemini-api/docs/caching

36. Anthropic, **Claude context window guidance**  
    https://support.anthropic.com/en/articles/8606395-how-large-is-the-anthropic-api-s-context-window

37. Anthropic, **Claude Projects**  
    https://support.claude.com/en/articles/9519177-how-can-i-create-and-manage-projects

38. Meta, **Llama 4 documentation / Scout context**  
    https://ai.meta.com/llama/get-started/

39. Meta, **The Llama 4 herd**  
    https://ai.meta.com/blog/llama-4-multimodal-intelligence/

## Interoperability protocols

40. Model Context Protocol, **2026-07-28 Specification announcement**  
    https://blog.modelcontextprotocol.io/posts/2026-07-28/

41. Agent2Agent Protocol, **A2A official documentation**  
    https://a2a-protocol.org/latest/

---

# Final Research Thesis

A context window is **not** a durable shared memory object. It is a finite, model-specific inference workspace.

The winning architecture for Shared Agent Context is therefore not:

```text
Sam's context window + Matthew's context window = one giant context window
```

It is:

```text
                UNBOUNDED SHARED PROJECT HISTORY
                           │
                           ▼
                  governed project memory
                           │
                           ▼
                  task-aware retrieval
                           │
                           ▼
                  context compilation
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          bounded       bounded      bounded
          context A     context B    context C
              │            │            │
              ▼            ▼            ▼
           OpenAI        Claude       Gemini
```

**The context window belongs to the model. The memory belongs to the project.**

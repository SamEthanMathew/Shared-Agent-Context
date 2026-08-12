# Shared Agent Context: Architecture Direction

## Goal

Design a model-agnostic system that lets multiple users and independent AI clients maintain and retrieve a shared, trustworthy understanding of a project.

The system should not require participating agents to use the same model provider, account, chat application, or runtime.

## Core Architectural Principle

Separate three things that AI products commonly collapse together:

1. **Conversation context** - temporary information needed inside one interaction.
2. **Personal memory** - information belonging to an individual user.
3. **Project memory** - shared durable knowledge belonging to a collaborative project.

Shared Agent Context owns the third layer.

## System Overview

```text
┌──────────────── CLIENTS ────────────────┐
│ ChatGPT │ Claude │ Codex │ Cursor │ SDK │
└───────────────────┬─────────────────────┘
                    │ MCP / REST / SDK
                    ▼
┌──────────────── API GATEWAY ────────────┐
│ Authentication                          │
│ Project membership                      │
│ Agent identity                          │
│ Rate limiting                           │
└───────────────────┬─────────────────────┘
                    ▼
┌──────────── CONTEXT SERVICE ────────────┐
│                                         │
│ Write pipeline     Retrieval pipeline   │
│      │                    │             │
│      ▼                    ▼             │
│ Extraction         Query understanding  │
│ Validation         Candidate retrieval  │
│ Deduplication      Ranking               │
│ Conflict detect.   Permission filtering │
│ Consolidation      Context assembly     │
│                                         │
└───────┬───────────────┬─────────────────┘
        │               │
        ▼               ▼
┌──────────────┐  ┌───────────────────┐
│ Primary DB   │  │ Search / vectors  │
│ structured   │  │ semantic index    │
│ state        │  │                   │
└──────┬───────┘  └───────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Event log / provenance / version history│
└─────────────────────────────────────────┘
```

## Core Entities

### User

A human identity.

```text
User
- id
- display_name
- email
- created_at
```

### Project

The shared context boundary.

```text
Project
- id
- name
- description
- owner_id
- created_at
- settings
```

### Membership

Defines a user's permissions within a project.

```text
Membership
- project_id
- user_id
- role: owner | admin | member | viewer
- created_at
```

### Agent / Client Identity

Represents an application or agent acting for a user.

```text
AgentIdentity
- id
- project_id
- user_id
- client_type
- client_name
- permissions
- created_at
```

This matters because "Matthew's Claude" and "Sam's Codex" should be distinguishable actors even though both ultimately belong to humans.

## Memory Object

The central primitive should be more structured than a text chunk.

Example:

```json
{
  "id": "mem_123",
  "project_id": "proj_abc",
  "type": "decision",
  "title": "Authentication mechanism",
  "content": "Use device-bound passkeys for desktop authentication.",
  "status": "active",
  "confidence": 0.98,
  "importance": 0.9,
  "created_at": "...",
  "valid_from": "...",
  "valid_until": null,
  "created_by": {
    "user_id": "user_sam",
    "agent_id": "agent_codex_1"
  },
  "source": {
    "type": "conversation",
    "uri": "...",
    "source_id": "..."
  },
  "supersedes": [],
  "tags": ["auth", "desktop"],
  "visibility": "project"
}
```

## Memory Types

Start with a controlled set:

- `fact`
- `decision`
- `requirement`
- `goal`
- `constraint`
- `task`
- `status`
- `artifact`
- `question`
- `hypothesis`
- `observation`

This is important. "We decided to use PostgreSQL" has different semantics from "maybe PostgreSQL would work."

## Provenance

Every memory must be attributable.

Minimum provenance:

- human user
- acting agent/client
- source type
- source identifier
- timestamp
- extraction method

Potential source types:

- explicit user entry
- conversation
- agent action
- Git commit
- pull request
- issue
- document
- task system
- external URL
- API event

A retrieved memory should never appear more authoritative than its source warrants.

## Write Pipeline

Agents should not simply append arbitrary text into a vector database.

### Step 1: Receive event

Example:

```json
{
  "project_id": "proj_abc",
  "actor": "agent_codex_1",
  "event_type": "conversation_update",
  "content": "We decided to use passkeys instead of password authentication..."
}
```

### Step 2: Extract candidate memories

An extraction model identifies durable knowledge.

### Step 3: Classify

Determine whether each candidate is a decision, fact, task, etc.

### Step 4: Permission check

Ensure the actor is allowed to write this category/scope.

### Step 5: Deduplicate

Compare against existing memories.

### Step 6: Detect contradiction

Examples:

Existing:

> Backend uses Firebase.

New:

> Backend has migrated from Firebase to Supabase.

This should likely create a supersession relationship, not two simultaneously active facts.

### Step 7: Apply policy

Possible project policies:

- automatically accept low-risk updates
- require confirmation for architectural decisions
- allow agents to propose but not finalize decisions
- require human confirmation when contradictions are detected

### Step 8: Persist + index

Store structured state and update semantic/search indexes.

### Step 9: Emit event

Interested clients can eventually subscribe to relevant project changes.

## Retrieval Pipeline

An agent should not call `get_all_context()` and receive everything.

Example request:

```json
{
  "project_id": "proj_abc",
  "task": "Implement authentication on the Windows desktop client",
  "max_tokens": 4000,
  "types": ["decision", "requirement", "constraint", "artifact"]
}
```

### Retrieval stages

1. authenticate actor
2. understand task/query
3. identify candidate memories
4. semantic + keyword + structured retrieval
5. filter by permissions
6. filter/sort by recency and temporal validity
7. boost decisions/requirements relevant to task
8. remove superseded information
9. include contradictions when unresolved
10. assemble within token budget
11. return citations/provenance

Example response:

```json
{
  "context": [
    {
      "type": "decision",
      "content": "Desktop authentication uses device-bound passkeys.",
      "source": "mem_123"
    }
  ],
  "summary": "Windows client should implement the shared passkey authentication architecture.",
  "token_estimate": 612
}
```

## Storage

For an MVP, avoid overengineering.

### PostgreSQL

Use as the canonical source of truth for:

- projects
- memberships
- agent identities
- memories
- versions
- provenance
- relationships
- audit events

### pgvector

Enough for initial semantic retrieval without introducing a separate vector database.

### Object storage

Use for large source artifacts when needed.

### Redis

Optional later for caching, ephemeral sessions, locks, and event distribution.

## Memory Relationships

Memories should eventually form a graph.

Useful relationships:

- supersedes
- contradicts
- supports
- derived_from
- relates_to
- blocks
- implements
- belongs_to

This allows SAC to evolve beyond RAG toward an actual representation of project state.

## Temporal Knowledge

Project truth changes.

The system should distinguish:

> "We use Firebase."

from

> "We used Firebase until August 10, then migrated to Supabase."

Useful fields:

- created_at
- valid_from
- valid_until
- superseded_at

Retrieval should prefer currently valid knowledge while preserving history.

## Authority

Not every source has equal authority.

Potential hierarchy could be project-configurable:

1. explicit owner/admin decision
2. approved specification
3. merged repository state
4. member statement
5. agent observation
6. agent inference

Do not hardcode this permanently, but represent enough metadata to reason about authority.

## Context Branching

Later, projects may need branches similar to software environments.

Example:

- production project context
- experimental architecture branch
- feature branch

An agent experimenting with a migration should not immediately rewrite the team's canonical project truth.

This suggests a future `context_branch` primitive.

## Permission Model

MVP:

- project-level roles
- read/write scopes

Later:

- memory-level ACLs
- source-level ACL inheritance
- agent-specific scopes
- field-level redaction
- organization policies

Important rule:

**Retrieval must enforce permissions before context reaches a model.**

The model itself is not the security boundary.

## Security Considerations

### Prompt injection

Imported documents and agent-generated content may contain malicious instructions.

Stored knowledge must distinguish data from executable instructions.

### Cross-project leakage

Project IDs alone cannot be trusted. Every retrieval/write must validate actor membership.

### Agent impersonation

Agent credentials should be tied to users/projects and revocable.

### Sensitive information

Eventually support classification, retention, deletion, and redaction policies.

### Auditability

Every write, edit, deletion, and access-sensitive action should be attributable.

## API Direction

Possible minimal API:

```text
POST   /v1/projects
POST   /v1/projects/:id/invites
GET    /v1/projects/:id

POST   /v1/projects/:id/memories
GET    /v1/projects/:id/memories
PATCH  /v1/projects/:id/memories/:memory_id

POST   /v1/projects/:id/context/query
POST   /v1/projects/:id/events
GET    /v1/projects/:id/activity
```

## MCP Direction

MCP is a strong initial client interface because multiple agent products can consume the same tools.

Possible tools:

```text
sac_project_info()
sac_recall(task, token_budget)
sac_remember(type, content, source)
sac_search(query)
sac_recent_changes(since)
sac_propose_decision(...)
```

Resources could expose canonical project state and selected documents.

The underlying SAC API should remain protocol-independent so MCP is an adapter, not the architecture itself.

## Real-Time Synchronization

MVP does not need Google-Docs-style real-time collaboration.

"Live" should initially mean that once an accepted memory is written, other clients can retrieve it immediately.

Later options:

- WebSockets
- Server-Sent Events
- webhooks
- message queues
- subscriptions by topic/memory type

## Human Control Plane

A web interface should eventually show:

### Project Overview

- current project summary
- goals
- architecture
- active tasks
- recent changes

### Memory Explorer

- memories by type
- source
- author/agent
- status
- confidence
- history

### Conflicts

- unresolved contradictions
- proposed supersessions
- memories awaiting confirmation

### Agents

- connected clients
- permissions
- recent reads/writes

### Activity

A chronological audit trail of project knowledge changes.

## Context Quality

The hardest technical problem is not storage. It is deciding:

- what deserves to become memory
- what should be forgotten
- which source wins
- when a fact becomes stale
- what an agent needs right now
- how much context to send
- when to expose uncertainty

This should be treated as a first-class product/research problem.

## MVP Technology Hypothesis

A pragmatic stack could be:

```text
Backend:       Python + FastAPI or TypeScript + Fastify/Nest
Database:      PostgreSQL
Embeddings:    provider-abstracted embedding service
Vector search: pgvector
Auth:          managed auth provider initially
Web app:       Next.js
Protocol:      REST + MCP adapter
Events:        PostgreSQL/event table initially
Deployment:    managed cloud platform
```

The exact framework matters less than preserving the abstraction boundaries.

## Key Abstraction

Do not make model providers first-class dependencies throughout the codebase.

Define interfaces such as:

```text
EmbeddingProvider
ExtractionProvider
RerankingProvider
SummarizationProvider
```

Then implement provider adapters.

SAC itself must remain model-agnostic even if the first prototype uses one model internally.

## Architectural Test

A good architectural constraint is:

> If OpenAI, Anthropic, or Google disappeared tomorrow, could SAC switch providers without changing the project's memory model or client contract?

If yes, the model-agnostic boundary is working.

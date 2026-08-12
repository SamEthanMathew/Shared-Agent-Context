# Shared Agent Context: MVP

## MVP Objective

Prove that two collaborators using independent AI clients can share useful project knowledge automatically through a neutral context layer.

The MVP succeeds when this demo works reliably:

> Sam tells Agent A something important about the project. Matthew later asks Agent B to work on a related task. Agent B knows the relevant information even though it is running under a different user, account, and model client.

## Do Not Build Yet

Avoid turning the first version into a full enterprise knowledge platform.

Do not initially build:

- dozens of integrations
- complex organization hierarchies
- autonomous multi-agent orchestration
- a custom foundation model
- sophisticated knowledge graphs
- context branching
- mobile apps
- enterprise compliance suite
- massive-scale event infrastructure
- replacement products for GitHub/Notion/Slack

## MVP User Story

### Setup

1. Sam creates project `Shared Demo App`.
2. Sam invites Matthew.
3. Both receive project-scoped access.
4. Sam connects Client A.
5. Matthew connects Client B.

### Handoff

Sam tells Client A:

> We decided the desktop clients should store credentials in the OS-native secure credential store. macOS will use Keychain. Windows should use Credential Manager.

Client A calls `remember`.

SAC stores a project decision with provenance.

Later Matthew asks Client B:

> Implement credential storage on Windows.

Client B calls `recall` with the task.

SAC returns the credential-storage decision.

Client B implements against the correct project architecture.

### Reverse handoff

Matthew's agent discovers an implementation constraint and stores it.

Sam's agent retrieves that constraint later.

This completes the two-way shared-context loop.

## MVP Components

### 1. Authentication

Need:

- sign up / sign in
- user identity
- project-scoped API tokens or OAuth-style client authorization

### 2. Projects

Need:

- create project
- project description
- list projects
- project membership

### 3. Invitations

Need:

- invite by email or shareable invite
- accept invitation
- basic roles: owner/member/viewer

### 4. Memories

Minimum fields:

```text
id
project_id
type
content
created_at
created_by_user
created_by_agent
source
status
embedding
```

Initial types:

```text
fact
decision
requirement
constraint
task
status
question
```

### 5. Remember

API/tool allowing an agent to write knowledge.

MVP can start with explicit writes instead of automatically observing entire conversations.

Example MCP call:

```text
remember(
  project="proj_123",
  type="decision",
  content="Windows credentials use Credential Manager",
  source="current conversation"
)
```

Explicit writes reduce privacy and extraction complexity while proving the primitive.

### 6. Recall

Agent submits a task/query and receives relevant project context.

Example:

```text
recall(
  project="proj_123",
  task="Implement Windows credential storage",
  max_tokens=3000
)
```

Return:

- top relevant memories
- memory type
- provenance
- timestamp

### 7. Search

Simple semantic/keyword memory search for humans and agents.

### 8. Recent Changes

A tool such as:

```text
recent_changes(project, since)
```

This helps an agent quickly understand what changed since a prior session.

### 9. Web Dashboard

Very small UI.

Pages:

```text
/projects
/projects/:id
/projects/:id/memories
/projects/:id/activity
/projects/:id/settings
```

The project page should immediately answer:

- What does the project currently know?
- What changed recently?
- Who/what wrote it?

### 10. MCP Server

Expose SAC through MCP so compatible clients can share the same backend.

Initial tools:

```text
project_info
recall
remember
search_memory
recent_changes
```

## Recommended Build Order

### Milestone 0: Contract

Before building UI, define:

- memory schema
- API contract
- authorization model
- provenance model

Deliverable: API spec and database schema.

### Milestone 1: Single-user memory

Build:

- backend
- PostgreSQL
- project creation
- memory CRUD
- embeddings
- semantic recall

Test from command line.

Success criterion:

A user can write a project memory and retrieve it through a semantically related task.

### Milestone 2: Multi-user

Add:

- authentication
- membership
- invitations
- authorization

Success criterion:

Two users can access the same project while a third unauthorized user cannot.

### Milestone 3: MCP

Add MCP server exposing remember/recall.

Success criterion:

One supported AI client can use SAC without custom prompting/copy-paste.

### Milestone 4: Cross-client demo

Connect a second independent client/model.

Success criterion:

Information written from Client A changes the quality/correctness of work performed in Client B.

This is the critical MVP milestone.

### Milestone 5: Human dashboard

Add memory inspection, editing, deletion, and activity.

Success criterion:

A user can understand and control the project's AI-maintained memory.

### Milestone 6: Lightweight extraction

Allow an agent/client to submit an interaction summary or event and have SAC propose memories.

Do not immediately auto-accept everything.

Success criterion:

Useful memories can be suggested without flooding the project with low-quality information.

## Proposed Database Tables

### users

```text
id
email
name
created_at
```

### projects

```text
id
name
description
owner_id
created_at
```

### memberships

```text
project_id
user_id
role
created_at
```

### agent_identities

```text
id
project_id
user_id
name
client_type
created_at
last_seen_at
```

### memories

```text
id
project_id
type
title
content
status
importance
confidence
created_by_user_id
created_by_agent_id
source_type
source_uri
created_at
updated_at
valid_from
valid_until
```

### memory_embeddings

```text
memory_id
embedding
model
created_at
```

### memory_relations

```text
from_memory_id
to_memory_id
relation_type
created_at
```

### audit_events

```text
id
project_id
actor_user_id
actor_agent_id
action
entity_type
entity_id
metadata
created_at
```

## API Sketch

### Create memory

```http
POST /v1/projects/{project_id}/memories
```

```json
{
  "type": "decision",
  "title": "Windows credential storage",
  "content": "Use Windows Credential Manager for stored desktop credentials.",
  "source": {
    "type": "conversation"
  }
}
```

### Recall context

```http
POST /v1/projects/{project_id}/context/query
```

```json
{
  "task": "Implement secure credential storage for Windows",
  "max_tokens": 3000
}
```

### Recent changes

```http
GET /v1/projects/{project_id}/activity?since=...
```

## Retrieval V0

Do not begin with a complicated retrieval architecture.

Candidate scoring can combine:

```text
semantic_similarity
+ type_weight
+ recency_weight
+ importance_weight
```

Then filter:

- unauthorized memories
- deleted memories
- expired memories
- superseded memories

Return provenance with every result.

## Write V0

For the first demo, require explicit `remember` calls.

This is intentional.

Automatically deciding what to remember is one of the hardest parts of the eventual product. It should not block validating cross-user/cross-model context sharing.

After the core loop works, add a `propose_memories` pipeline.

## Client Integration V0

### Preferred

MCP-compatible clients.

### Fallback

Provide:

- REST API
- small TypeScript SDK
- small Python SDK

This makes the architecture useful even when a client cannot directly install an MCP server.

## Demo Script

The first public demo should be under two minutes.

### Screen 1

Sam, Client A:

> The API will use cursor pagination. Never expose page numbers publicly.

Agent stores decision.

### Screen 2

SAC dashboard shows:

```text
Decision
API pagination uses opaque cursors, not page numbers.
Source: Sam / Client A
just now
```

### Screen 3

Matthew, Client B, different provider/account:

> Build the endpoint for listing messages.

Agent calls recall and states that the project requires cursor pagination.

### Screen 4

Matthew changes another project constraint. Sam's agent subsequently retrieves it.

End message:

> Different people. Different agents. Same project brain.

## MVP Evaluation

Test with real two-person workflows.

Record:

- memories written
- memories retrieved
- relevant retrievals
- irrelevant retrievals
- missing context
- incorrect/stale context
- human corrections
- latency
- token count

Interview users after several days, not just after a demo.

The important question is whether SAC becomes something they miss when it is removed.

## Definition of Done

The MVP is successful when:

- at least two independent users can join one project
- at least two different AI clients can connect
- either client can write project memories
- the other client can retrieve them immediately
- access control prevents unrelated users from retrieving project context
- every memory exposes provenance
- users can inspect and delete/correct memories
- the cross-client handoff demonstrably prevents stale or duplicated work

Everything beyond this is iteration.

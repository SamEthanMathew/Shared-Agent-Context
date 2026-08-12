# Shared Agent Context: V0 Product and System Architecture

**Project:** Shared Agent Context (SAC)  
**Date:** August 12, 2026  
**Status:** Working implementation specification for the first cross-provider prototype

---

## 0. Why This Document Exists

This document turns the existing SAC vision, architecture research, context-window research, compaction design, and MVP plan into one concrete product layout that we can begin implementing.

The narrow V0 target is:

> **One person using ChatGPT/OpenAI and one person using Claude/Anthropic can work on the same project and benefit from a continuously updated shared project context without manually copying information between the two systems.**

The goal is not yet to support every provider, every chat, automatic institutional memory, enterprise governance, or autonomous agent orchestration.

The V0 should prove the core primitive:

```text
Person A / OpenAI-side client
          │
          │ writes useful project knowledge
          ▼
   Shared Agent Context
          │
          │ immediately available for retrieval
          ▼
Person B / Anthropic-side client
```

and the same flow in reverse.

This specification intentionally labels unresolved areas as **STILL NEED TO RESEARCH** or **STILL NEED TO DECIDE** rather than silently assuming behavior that has not been verified.

---

# 1. Refined Product Mental Model

The original product intuition is:

```text
PERSON A CONTEXT POOL | SHARED CONTEXT POOL | PERSON B CONTEXT POOL
```

That is directionally correct, but the implementation should separate context into four scopes rather than three.

```text
                    SHARED AGENT CONTEXT PROJECT

┌────────────────────┐       ┌────────────────────┐
│ Person A           │       │ Person B           │
│ Private Project CP │       │ Private Project CP │
└─────────┬──────────┘       └─────────┬──────────┘
          │                            │
          └───────────┐    ┌───────────┘
                      ▼    ▼
              ┌──────────────────┐
              │ Shared Project CP │
              └─────────┬────────┘
                        │
                        ▼
              ┌──────────────────┐
              │ Evidence / Event  │
              │ History           │
              └──────────────────┘

Each active chat additionally has:

┌──────────────────────────────┐
│ Session / Chat Working State │
└──────────────────────────────┘
```

The four scopes are:

1. **Session / Chat Context Pool** — temporary working state for one chat/session.
2. **Person-Private Project Context Pool** — durable project information visible only to one project member and that member's authorized agents.
3. **Shared Project Context Pool** — durable project knowledge visible to authorized project collaborators and their agents.
4. **Evidence / Event History** — source material and immutable history from which memories and summaries were derived.

This is a crucial distinction.

## 1.1 SAC does not initially own a user's native ChatGPT or Claude personal memory

When this document says **Person A Context Pool**, it means a **SAC-managed private context pool for this project**.

It does **not** mean that SAC can automatically read every private ChatGPT memory, every Claude preference, every unrelated conversation, or every fact the provider stores about that user.

We should not make the product depend on access to provider-native personal memory unless a provider exposes an explicit, user-authorized API for it.

That gives us a cleaner privacy boundary:

```text
Person A native AI account memory
            │
            │ NOT automatically imported
            ▼
     Person A's current chat
            │
            │ authorized SAC writes only
            ▼
 Person A SAC Project-Private CP
            │
            ├──────────────┐
            ▼              ▼
      stays private    selected knowledge
                         can be shared
                             │
                             ▼
                       Shared Project CP
```

---

# 2. What We Are Actually Sharing

A major conclusion from the context-window research is:

> **Different models should share the same underlying project truth, not necessarily the same literal token sequence.**

The project may contain 500,000 historical tokens, while the current OpenAI client receives 20,000 useful tokens and the current Claude client receives 12,000 useful tokens.

Both are still working from the same canonical project state.

```text
                 CANONICAL SAC PROJECT STATE
                         500K+ tokens
                              │
                       Context Compiler
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
            OpenAI working set   Claude working set
                 20K tokens          12K tokens
                    │                   │
                    ▼                   ▼
                Person A            Person B
```

Therefore SAC's promise should be:

> **Same project brain, model-appropriate working context.**

not:

> **Every model receives an identical prompt.**

---

# 3. The V0 User Experience

## 3.1 Setup

### Person A

1. Creates a SAC account.
2. Creates a project.
3. Installs/connects the SAC integration in the OpenAI-side client.
4. Authorizes that integration with SAC using OAuth or a project-scoped credential.
5. Chooses the SAC project for the current chat.

### Person B

1. Creates or signs into a SAC account.
2. Accepts Person A's project invite.
3. Installs/connects the SAC integration in Claude.
4. Authorizes the integration with SAC.
5. Chooses the same SAC project for the current chat.

The project now contains two memberships and two client identities.

```text
Project: Shared Desktop App

Members
- Person A
- Person B

Connected clients
- Person A / ChatGPT
- Person B / Claude
```

## 3.2 During normal work

Person A says in the connected project chat:

> We decided the desktop app should use Supabase Auth and device-bound passkeys.

The OpenAI-side SAC integration records that project decision.

The shared project context revision changes:

```text
revision 41 → revision 42
```

Later Person B asks Claude:

> Implement authentication for the Windows client.

Before or during the task, Claude's SAC integration requests relevant project context.

SAC returns the active authentication decision from revision 42.

Claude can now work with the information learned on Person A's side.

No manual copy/paste is required.

## 3.3 Reverse direction

Claude discovers:

> Windows Hello cannot be used in the exact same credential-storage flow as the macOS implementation; the Windows client needs a platform adapter.

That constraint is stored in the shared project context.

Person A's OpenAI-side agent retrieves it on a later relevant task.

That closes the cross-provider loop.

---

# 4. Overall V0 Architecture

```text
┌────────────────────────── PERSON A ──────────────────────────┐
│                                                              │
│  ChatGPT / Codex                                             │
│        │                                                     │
│        │ OpenAI SAC adapter                                  │
│        │ plugin / app / action / MCP depending on surface    │
└────────┼─────────────────────────────────────────────────────┘
         │
         │ authenticated SAC protocol
         ▼
┌──────────────────────── SAC GATEWAY ─────────────────────────┐
│                                                              │
│ Authentication                                               │
│ User identity                                                │
│ Project membership                                           │
│ Agent/client identity                                        │
│ Permissions                                                  │
│ Rate limits                                                  │
└───────────────┬──────────────────────────────────────────────┘
                │
        ┌───────┴────────────────────┐
        │                            │
        ▼                            ▼
┌──────────────────┐       ┌─────────────────────┐
│ Context Compiler │       │ Memory Write Engine │
│                  │       │                     │
│ task analysis    │       │ capture event       │
│ retrieval        │       │ classify scope      │
│ permissions      │       │ extract memory      │
│ revision delta   │       │ deduplicate         │
│ ranking          │       │ detect conflicts    │
│ compaction       │       │ apply write policy  │
│ model budgeting  │       │ persist + index     │
└─────────┬────────┘       └──────────┬──────────┘
          │                           │
          │                           ▼
          │                 ┌────────────────────┐
          │                 │ Canonical Storage  │
          │                 │                    │
          │                 │ evidence/events    │
          │                 │ memories           │
          │                 │ versions           │
          │                 │ relations          │
          │                 │ revisions          │
          │                 │ context snapshots  │
          │                 └──────────┬─────────┘
          │                            │
          └──────────────┬─────────────┘
                         │
                         ▼
┌──────────────────────── PERSON B ─────────────────────────────┐
│                                                              │
│  Claude / Claude Code                                        │
│        │                                                     │
│        │ Anthropic SAC adapter                               │
│        │ remote MCP / MCP                                    │
└──────────────────────────────────────────────────────────────┘
```

---

# 5. The Three Runtime Context Pools

## 5.1 Session / Chat CP

This contains information that matters to the current working session but may not deserve long-term memory.

Examples:

- current user request
- active subtask
- files currently being edited
- temporary hypothesis
- tool outputs from this turn
- short-lived reasoning state
- current implementation attempt

Suggested fields:

```text
session_id
project_id
user_id
agent_id
provider
client_type
created_at
last_seen_at
known_project_revision
working_summary
pinned_memory_ids
```

This pool can be aggressively compacted because canonical evidence and durable project memory live elsewhere.

## 5.2 Person-Private Project CP

This stores durable project knowledge that one user wants available to their own project agents but does not want shared with collaborators.

Examples:

- private notes
- unfinished ideas
- personal task reminders
- private hypotheses
- user-specific preferences for this project
- draft concerns before sharing them

Important rule:

```text
Person A private CP
        │
        ├── visible to Person A's authorized project agents
        │
        └── never returned to Person B
```

## 5.3 Shared Project CP

This is the core product primitive.

It contains project knowledge that collaborators have intentionally or policy-permissibly shared.

Examples:

- decisions
- requirements
- architecture
- constraints
- goals
- active tasks
- blockers
- implementation discoveries
- project status
- important artifacts
- unresolved questions

Every object should retain provenance and temporal state.

---

# 6. Canonical Evidence Layer

The Context Pools should not be the only copy of project history.

SAC should preserve a source-backed evidence/event layer.

Possible event types:

```text
conversation_excerpt
explicit_memory_write
agent_observation
project_decision
file_reference
git_commit
pull_request
issue
tool_result
document_reference
human_correction
memory_supersession
```

A memory is then an interpretation of evidence rather than an irreversible replacement for it.

```text
Evidence:
Person A: "Let's use Supabase rather than Firebase."

        │ extraction
        ▼

Memory:
type: decision
content: "Authentication backend uses Supabase."
status: active
source_event_id: evt_381
```

This allows us to later re-run extraction, resolve disputes, expand compacted context, and show users where a memory came from.

---

# 7. The Per-Turn Lifecycle

For SAC to feel like a continuously shared project brain, every connected turn conceptually has two phases:

```text
PRE-TURN READ
model gets useful project context

POST-TURN WRITE
new durable project information is captured
```

## 7.1 Pre-turn: sync and compile

The client sends something conceptually like:

```json
{
  "project_id": "proj_123",
  "session_id": "sess_openai_81",
  "known_revision": 41,
  "task": "Implement authentication for the macOS client",
  "target": {
    "provider": "openai",
    "model": "current-model-id"
  },
  "context_policy": {
    "mode": "balanced"
  }
}
```

SAC performs:

1. authentication
2. permission check
3. identify caller/user/client
4. check whether the shared project revision changed
5. retrieve relevant Person A private memory
6. retrieve relevant shared project memory
7. retrieve relevant changes since revision 41
8. remove stale/superseded items
9. preserve unresolved conflicts
10. rank by task relevance and authority
11. fit context to the target model
12. create a context snapshot
13. return the Context Envelope

Example response:

```json
{
  "project_revision": 42,
  "snapshot_id": "ctx_992",
  "shared_context": [
    {
      "id": "mem_77",
      "type": "decision",
      "content": "Authentication uses Supabase and device-bound passkeys.",
      "source_id": "evt_381"
    }
  ],
  "private_context": [],
  "recent_changes": [
    {
      "revision": 42,
      "memory_id": "mem_77"
    }
  ],
  "token_estimate": 1830
}
```

## 7.2 Model works normally

The model receives SAC context alongside its normal system/client/current-chat context.

SAC does not replace the provider's context window. It contributes a selected project-context layer to it.

## 7.3 Post-turn: capture durable knowledge

The client/agent can submit new information:

```json
{
  "project_id": "proj_123",
  "session_id": "sess_openai_81",
  "source": {
    "type": "conversation",
    "provider": "openai"
  },
  "candidate": {
    "scope": "shared",
    "type": "constraint",
    "content": "macOS passkeys must be stored through the platform credential adapter."
  }
}
```

SAC then:

1. validates actor
2. stores source evidence
3. checks memory permissions
4. deduplicates
5. checks for contradiction/supersession
6. applies the project's write policy
7. stores memory/version
8. increments project revision
9. updates indexes
10. records an audit event

## 7.4 Revision-based synchronization

V0 should use a simple monotonically increasing project context revision.

```text
revision 41
    │
Person A writes shared decision
    │
    ▼
revision 42
    │
Person B next calls sync
    │
    ▼
"You are one revision behind; here is the relevant delta."
```

This is enough for the first product.

We do not need Kafka, distributed event streaming, or Google-Docs-style presence for V0.

---

# 8. What "Real Time" Means in V0

For the first version, **real time** should mean:

> Once a shared memory write is accepted by SAC, another authorized client can retrieve it immediately on its next SAC request.

It does **not** mean SAC can magically alter the prompt of a model inference that is already running.

Example:

```text
10:41:03  Person A stores decision
10:41:03  SAC revision becomes 88
10:41:05  Person B begins next task
10:41:05  Person B's integration calls sac.sync_context
10:41:05  revision 88 is returned
```

Later we can add:

- WebSockets
- Server-Sent Events
- subscriptions
- push notifications
- agent presence
- live project activity

but they are not required to prove shared context.

---

# 9. The Context Compiler

The Context Compiler is the bridge between the logical Context Pools and each model's finite working context.

Inputs:

```text
actor
project
session
current task
Person-private CP
Shared Project CP
recent project delta
evidence
model profile
user context policy
```

Output:

```text
bounded model-specific Context Envelope
```

## 9.1 Context composition for Person A

```text
Person A request
        │
        ▼
┌────────────────────────────┐
│ system/client instructions │
│ current task               │
│ session working state      │
│ Person A private CP        │
│ shared project CP          │
│ relevant recent changes    │
│ selected source evidence   │
│ tools / output contract    │
└────────────────────────────┘
```

Person B private CP is never included.

## 9.2 Context composition for Person B

```text
Person B request
        │
        ▼
┌────────────────────────────┐
│ system/client instructions │
│ current task               │
│ session working state      │
│ Person B private CP        │
│ shared project CP          │
│ relevant recent changes    │
│ selected source evidence   │
│ tools / output contract    │
└────────────────────────────┘
```

Person A private CP is never included.

## 9.3 Different model, different compiled size

The semantic project state stays constant while serialization and detail level can differ.

```text
Shared project CP: 80,000 logical tokens

OpenAI target:
compiled SAC contribution = 15,000 tokens

Claude target:
compiled SAC contribution = 10,000 tokens

small local model:
compiled SAC contribution = 3,000 tokens
```

This uses the dynamic compaction and semantic-paging architecture already documented elsewhere in the repo.

---

# 10. Context Compaction and Growth

The shared project context should be allowed to keep growing logically.

The active model context should not.

```text
UNBOUNDED / GROWING SAC STATE
        │
        │ retrieval + compaction
        ▼
BOUNDED ACTIVE MODEL CONTEXT
```

SAC should eventually support:

```text
/compact safe
/compact balanced
/compact aggressive
/compact custom
/expand
```

But compaction must obey the existing rule:

> **Compaction is a projection, not deletion.**

The source evidence remains retrievable so a small-model view can later be expanded for a larger model.

V0 does not need sophisticated learned compression. A simple hierarchy is sufficient:

```text
raw evidence
    ↓
atomic memories
    ↓
short topic summaries
    ↓
current project summary
```

---

# 11. Integration Architecture

The backend should remain protocol-independent.

```text
                    SAC CORE API
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
       ▼                 ▼                  ▼
      MCP              REST              SDKs
       │                 │                  │
       ▼                 ▼                  ▼
Claude/Code       GPT Actions/etc.     custom clients
```

## 11.1 OpenAI / ChatGPT

### RESEARCHED CURRENT DIRECTION

OpenAI's current product ecosystem exposes **plugins** across ChatGPT and Codex. Plugins can package reusable skills and apps, and apps can connect external tools/data/actions. OpenAI documentation also supports custom apps using MCP and custom GPT Actions that call external APIs with API-key or OAuth authentication.

Relevant official documentation:

- https://help.openai.com/en/articles/20001256-plugins-in-chatgpt-and-codex
- https://help.openai.com/en/articles/11487775-connectors-in-chatgpt
- https://help.openai.com/en/articles/9442513
- https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt-beta

### V0 options

**Option A — OpenAI plugin/app backed by SAC MCP**

Best long-term product shape when the required plan/surface supports the capabilities we need.

```text
ChatGPT
   │
SAC plugin
   │
SAC app / MCP tools
   │
SAC backend
```

**Option B — Custom GPT with SAC Actions**

Potentially easier for an early demonstration because GPT Actions can call our REST API and support OAuth.

```text
SAC Project GPT
     │
OpenAPI Action
     │
SAC REST API
```

This means Person A works inside a specific SAC-enabled GPT/chat rather than expecting SAC to observe every arbitrary ChatGPT conversation on the account.

### STILL NEED TO RESEARCH / VALIDATE

1. Exact plan matrix for the specific ChatGPT account types we want to target first.
2. Whether the current plugin/app surface can reliably perform the write calls we need for ordinary individual-user plans or whether the V0 should use GPT Actions.
3. Whether plugin/app invocation can be made deterministic enough to perform a SAC pre-turn/post-turn sync on every relevant turn.
4. Exact App Directory / Plugin Directory publication requirements for a public SAC integration.
5. Whether any current OpenAI surface exposes guaranteed conversation lifecycle hooks to third-party apps.

**Do not assume these until we test them.**

## 11.2 Codex

### RESEARCHED CURRENT DIRECTION

OpenAI currently positions plugins as a shared extension mechanism across ChatGPT and Codex, and a plugin can depend on approved apps that connect Codex to external data/actions.

This is useful because a future SAC OpenAI plugin could potentially serve both conversational ChatGPT work and coding-agent workflows without inventing two unrelated products.

### V0

Codex is **not required** for the first two-account proof.

After ChatGPT ↔ Claude works, Codex should reuse the same SAC account, project identity, and backend tools.

### STILL NEED TO RESEARCH

- Exact Codex surfaces on which SAC MCP/app tools are callable and whether there are reliable session hooks for automatic context sync.
- Best way to associate repository/worktree/branch identity with an SAC project/session.

## 11.3 Claude / Claude.ai

### RESEARCHED CURRENT DIRECTION

Anthropic supports remote MCP connectors for Claude and documents MCP as the standard interface for tools/context.

Relevant official documentation:

- https://docs.anthropic.com/en/docs/mcp
- https://support.anthropic.com/en/articles/11175166-about-custom-integrations-using-remote-mcp
- https://support.anthropic.com/en/articles/11503834-building-custom-integrations-via-remote-mcp-servers

Anthropic documents remote MCP support for Claude/Claude Desktop on supported paid plans and allows OAuth-based remote MCP servers.

This makes a hosted SAC MCP server a strong V0 path for Person B.

```text
Claude
  │
remote MCP connector
  │
SAC MCP server
  │
SAC core backend
```

### STILL NEED TO RESEARCH / VALIDATE

1. Whether Claude can be configured to call SAC sync deterministically at the beginning/end of each project turn rather than relying only on model-selected tool invocation.
2. The exact connector installation UX we want users to follow.
3. Whether a Claude Project instruction combined with the remote MCP connector is sufficient for the V0's always-on behavior.

## 11.4 Claude Code

### RESEARCHED DIRECTION

Anthropic documents MCP support in Claude Code.

The expected architecture is straightforward:

```text
Claude Code
    │
SAC MCP server
    │
SAC project
```

### V0

Not necessary for the first proof, but it should be the first coding-agent extension after the ChatGPT ↔ Claude demo.

### STILL NEED TO RESEARCH

- Claude Code lifecycle hooks/events and whether they can guarantee automatic SAC sync/capture.
- Repository, branch, session, and working-directory mapping.
- How much raw tool output should enter the evidence layer versus remain session-only.

---

# 12. Critical Integration Constraint: Passive Observation Is Not Guaranteed

The product idea says:

> "As they keep conversing in one specific chat, the Shared CP keeps getting updated in real time."

That is the desired behavior.

However, **we have not established that every provider's extension surface gives a third-party integration a passive callback containing every user and assistant turn.**

An MCP server is normally a tool/resource server. The model/client invokes it. It is not automatically a packet sniffer for the provider's private conversation database.

Therefore there are three possible implementation levels.

## Level 1 — Explicit memory calls

The agent calls:

```text
sac.remember_shared(...)
sac.remember_private(...)
```

This is the safest and easiest V0.

## Level 2 — Integration-instructed automatic capture

The SAC-enabled GPT/Claude project/plugin contains instructions like:

```text
At the beginning of project work, call sac.sync_context.
When a durable decision, requirement, constraint, task update, or useful project fact is established, call sac.propose_memory.
```

This feels mostly automatic but still depends on the client/model invoking the tools correctly.

## Level 3 — Guaranteed lifecycle capture

A client/runtime hook fires on every turn and sends the permitted event to SAC independent of model tool choice.

This is the most reliable version.

### STILL NEED TO RESEARCH

We need a dedicated integration study that determines, for each target surface:

```text
ChatGPT
Codex
Claude
Claude Code
Cursor
```

whether it exposes:

```text
before_turn hook?
after_turn hook?
conversation transcript access?
selected-message access?
tool invocation guarantees?
background push?
project/session identifier?
```

Until that study is complete, V0 should **not** depend on passive full-transcript capture.

---

# 13. Proposed SAC Tool Contract

The first shared protocol should remain small.

## 13.1 Required V0 tools

```text
sac.project_info()
sac.sync_context(task, session_id, known_revision, budget_policy?)
sac.remember_shared(type, content, source?)
sac.remember_private(type, content, source?)
sac.recent_changes(since_revision?)
sac.get_source(source_id)
```

## 13.2 Why `sync_context` instead of only `recall`

The original MVP used `recall(task)`.

That is still useful, but the collaborative architecture benefits from a synchronization primitive that knows what the agent saw previously.

```text
sync_context(
    task,
    session_id,
    known_revision
)
```

can return both:

- task-relevant memory
- important changes since the agent's last known revision

This is especially important for cross-agent collaboration.

## 13.3 Later tools

```text
sac.propose_memory(...)
sac.resolve_conflict(...)
sac.pin(...)
sac.unpin(...)
sac.compact(...)
sac.expand(...)
sac.search(...)
sac.get_snapshot(...)
```

Do not block V0 on these.

---

# 14. Proposed REST API

The MCP tools should call the same underlying REST/service layer.

```text
POST /v1/projects
POST /v1/projects/{id}/invites
GET  /v1/projects/{id}

POST /v1/projects/{id}/sessions
POST /v1/projects/{id}/context/sync

POST /v1/projects/{id}/memories/shared
POST /v1/projects/{id}/memories/private
GET  /v1/projects/{id}/memories

POST /v1/projects/{id}/events
GET  /v1/projects/{id}/changes

GET  /v1/sources/{source_id}
GET  /v1/context-snapshots/{snapshot_id}
```

Later:

```text
POST /v1/projects/{id}/context/compact
POST /v1/projects/{id}/context/expand
POST /v1/projects/{id}/memories/{id}/resolve
```

---

# 15. Proposed Database Model

The existing architecture proposed separate project/membership/agent/memory/audit tables. V0 should extend that with scope, sessions, revisions, evidence, and snapshots.

## users

```text
id
email
display_name
created_at
```

## projects

```text
id
name
description
owner_id
context_revision
settings
created_at
updated_at
```

## memberships

```text
project_id
user_id
role
created_at
```

## agent_connections

Represents one authorized client acting for one user in one project.

```text
id
project_id
user_id
provider
client_type
client_name
auth_scope
created_at
last_seen_at
revoked_at
```

Examples:

```text
Person A / OpenAI / ChatGPT
Person B / Anthropic / Claude
Person A / OpenAI / Codex
Person B / Anthropic / Claude Code
```

## sessions

```text
id
project_id
user_id
agent_connection_id
provider_session_ref nullable
known_project_revision
working_summary nullable
created_at
last_seen_at
```

## evidence_events

```text
id
project_id
session_id nullable
actor_user_id
actor_agent_id
event_type
visibility_scope
owner_user_id nullable
content_or_reference
source_uri nullable
created_at
```

`visibility_scope`:

```text
session
private
shared
```

## memories

Rather than maintaining completely separate tables for Person A, Person B, and shared memory, use one memory table with scope.

```text
id
project_id
scope: private | shared
owner_user_id nullable
memory_type
content
status
importance
confidence
authority
valid_from
valid_until
created_by_user_id
created_by_agent_id
source_event_id
created_at
updated_at
```

Rules:

```text
scope=shared
owner_user_id=NULL

scope=private
owner_user_id=<specific user>
```

## memory_versions

```text
id
memory_id
version
content
status
source_event_id
created_at
```

## memory_relations

```text
from_memory_id
to_memory_id
relation_type
created_at
```

Initial relations:

```text
supersedes
contradicts
supports
derived_from
relates_to
implements
blocks
```

## context_snapshots

Records exactly what SAC gave an agent.

```text
id
project_id
session_id
user_id
agent_id
project_revision
provider
model
memory_ids_and_versions
source_ids
token_estimate
compiler_policy
created_at
```

## audit_events

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

---

# 16. Retrieval V0

V0 should not implement an elaborate research-grade memory graph.

Use hybrid retrieval:

```text
structured filters
+ lexical search
+ vector similarity
+ recency
+ memory type weight
+ importance
```

Then apply mandatory filters:

```text
permissions
scope
current validity
not deleted
not superseded
```

Suggested V0 score:

```text
score =
    semantic_similarity
  + lexical_match
  + type_weight
  + importance_weight
  + modest_recency_weight
```

Later we can add:

- rerankers
- graph traversal
- hierarchical retrieval
- learned context utility
- model-specific EC95 policies

---

# 17. Write Policy V0

The existing MVP correctly avoided automatically remembering everything.

Keep that principle.

## 17.1 V0

Explicit writes:

```text
remember_shared
remember_private
```

An integration can make these feel natural by being instructed to call them when a durable decision is clearly made.

## 17.2 V0.5

Add:

```text
propose_memory
```

The agent identifies candidate memories and the user accepts/rejects them.

## 17.3 Later

Project-level sharing policy:

```text
manual
suggested
automatic-low-risk
custom
```

Example:

```text
Decisions       → require user confirmation
Requirements    → require confirmation
Task status     → auto-share
Tool observations → suggest
Hypotheses      → private by default
```

This is likely necessary for trust and privacy.

---

# 18. Authentication and Permissions

The integration should authenticate **the user**, not simply the model provider.

```text
Person A ChatGPT
       │
       │ OAuth
       ▼
SAC identifies Person A
       │
       ▼
project membership
       │
       ▼
agent connection identity
```

Every request should resolve:

```text
Who is the human?
Which project?
Which client is acting?
What can it read?
What can it write?
```

Do not rely on the LLM to enforce this.

Permissions must be applied before private memories enter the model's context.

---

# 19. Shared Context Conflict Handling

Two people can legitimately disagree.

Example:

```text
Person A:
"We decided to use Firebase."

Person B:
"We decided yesterday to migrate to Supabase."
```

V0 should not silently merge these into one sentence.

Minimum behavior:

1. detect likely contradiction or same-topic replacement
2. retain both source records
3. mark an unresolved conflict or supersession candidate
4. prefer an explicitly approved/latest decision when available
5. surface unresolved conflict in context

```text
CONFLICT
- mem_41: Firebase
- mem_92: Supabase
Status: unresolved
```

Later, users can explicitly resolve the conflict.

---

# 20. Human Control Plane

The first dashboard can remain small but should make the shared brain visible.

## `/projects/:id`

Show:

```text
Project summary
Members
Connected agents
Current revision
Recent changes
```

## `/projects/:id/context`

Show:

```text
Shared memories
My private memories
Pinned memories
Conflicts
```

## `/projects/:id/activity`

Show:

```text
Person A / ChatGPT wrote decision
Person B / Claude retrieved decision
Person B / Claude wrote constraint
Person A corrected memory
```

## `/projects/:id/snapshots`

Later but extremely useful:

> What exactly did Claude know when it produced this answer?

This can become a strong debugging/product feature.

---

# 21. Proposed V0 Repository Layout

When implementation begins, one reasonable monorepo structure is:

```text
Shared-Agent-Context/
│
├── apps/
│   └── web/                     # Next.js dashboard
│
├── services/
│   ├── api/                     # core REST API
│   ├── context/                 # compiler / retrieval / budgeting
│   └── mcp/                     # hosted MCP adapter
│
├── integrations/
│   ├── openai/                  # GPT action / plugin/app definitions
│   └── anthropic/               # Claude connector config/examples
│
├── packages/
│   ├── schema/                  # shared data/API types
│   ├── client-ts/               # later SDK
│   └── client-py/               # later SDK
│
├── migrations/
│
└── docs/
```

A simpler V0 can combine `api`, `context`, and `mcp` into one service initially.

Do not prematurely split into microservices.

---

# 22. Pragmatic V0 Stack

Recommended starting point:

```text
Backend:       Python + FastAPI
Database:      PostgreSQL
Vector index:  pgvector
MCP server:    Python MCP SDK or thin adapter
Auth:          managed OAuth/auth provider
Dashboard:     Next.js
Object store:  S3-compatible later when needed
Cache:         none initially; Redis later if justified
```

Why Python for the first backend:

- fast iteration on retrieval/extraction
- strong AI/embedding ecosystem
- straightforward FastAPI service
- MCP support

This is not a permanent requirement. The canonical API and schemas should remain language-independent.

### STILL NEED TO DECIDE

The existing architecture left Python/FastAPI versus TypeScript/Fastify/Nest open. Before code begins we should choose one and stop carrying both possibilities in implementation docs.

---

# 23. Exact First Demo Architecture

The fastest credible demonstration appears to be:

```text
PERSON A
ChatGPT SAC-enabled GPT/plugin
       │
       │ REST Action or supported app/MCP path
       ▼
┌─────────────────────────────────────────┐
│                 SAC                     │
│                                         │
│ auth                                    │
│ project membership                      │
│ memory store                            │
│ shared revision                         │
│ context compiler                        │
│ provenance                              │
│ PostgreSQL + pgvector                   │
└────────────────────┬────────────────────┘
                     │
                     │ remote MCP
                     ▼
PERSON B
Claude + SAC connector
```

Demo:

1. Person A and Person B join one SAC project.
2. Person A records an architectural decision from ChatGPT.
3. SAC dashboard immediately shows it.
4. Person B asks Claude to perform a related task.
5. Claude calls `sync_context` and receives the decision.
6. Claude records a new project constraint.
7. Person A's next ChatGPT task retrieves the constraint.
8. Dashboard shows both writes, both actors, and provenance.

That is enough to prove the product thesis.

---

# 24. What We Should Not Build Before the Demo

Do not block V0 on:

- importing native ChatGPT personal memory
- importing native Claude personal memory
- every provider
- every chat automatically
- fully automatic memory extraction
- browser extensions
- autonomous multi-agent workflows
- enterprise hierarchy
- organization-wide memory graphs
- complex branching
- cross-provider hidden-state sharing
- custom foundation models
- learned context compression
- perfect real-time push
- advanced billing
- sophisticated event infrastructure

The first question is simply:

> **Does shared project memory between two independent AI accounts materially improve collaborative work?**

---

# 25. V0 Build Sequence

## Milestone 0 — Freeze contracts

Write and freeze:

- memory schema
- scope semantics
- project revision semantics
- context envelope schema
- MCP tool contract
- REST API contract
- authorization model

## Milestone 1 — Core backend

Build:

- users
- projects
- memberships
- memories
- evidence events
- revisions
- basic audit log

Test manually using HTTP requests.

## Milestone 2 — Context Compiler V0

Build:

- private + shared scope filtering
- keyword/vector retrieval
- recent revision delta
- context packing
- context snapshots

## Milestone 3 — MCP adapter

Implement:

```text
project_info
sync_context
remember_shared
remember_private
recent_changes
get_source
```

Test with one MCP-capable client.

## Milestone 4 — OpenAI-side adapter

Choose after integration validation:

```text
OpenAI plugin/app + MCP
OR
Custom GPT + Actions
```

Connect Person A.

## Milestone 5 — Claude adapter

Connect Person B through hosted remote MCP.

Run the full two-account handoff.

## Milestone 6 — Dashboard

Add:

- current shared memories
- user private memories
- activity
- revisions
- provenance
- edit/delete/correct

## Milestone 7 — Memory proposals

Add lightweight automatic `propose_memory` after the explicit primitive is reliable.

---

# 26. V0 Acceptance Tests

## Cross-user retrieval

Person A writes a shared decision. Person B retrieves it.

**Pass:** retrieved accurately.

## Reverse retrieval

Person B writes a shared constraint. Person A retrieves it.

**Pass:** retrieved accurately.

## Private isolation

Person A writes a private memory.

**Pass:** Person A receives it; Person B never does.

## Project isolation

Unauthorized user attempts recall.

**Pass:** zero information leakage.

## Revision synchronization

Person B has revision 80. Person A creates revision 81.

**Pass:** Person B's next sync identifies the relevant change.

## Provenance

Agent retrieves a decision.

**Pass:** memory has source, author, agent/client, and timestamp.

## Supersession

Old decision is replaced.

**Pass:** current task receives new decision and does not silently treat old one as active.

## Different context budgets

Two target models request the same project task with different budgets.

**Pass:** both receive semantically consistent project state at different levels of compression.

---

# 27. Metrics Worth Collecting From Day One

For every Context Compiler call:

```text
project revision
user
agent/client
model
query/task
candidate memories
included memories
excluded memories
private/shared split
stale/superseded exclusions
token estimate
retrieval latency
snapshot ID
```

For product evaluation:

```text
shared memories written
cross-user memories retrieved
useful retrieval rate
missing-context rate
incorrect/stale-context rate
human corrections
private-memory leakage = MUST BE ZERO
project leakage = MUST BE ZERO
cross-provider task success
tokens used
latency
```

A particularly important north-star-like V0 metric is:

> **Useful cross-agent handoffs per active project.**

---

# 28. Current Open Questions / STILL NEED TO DO

These are not optional details. They are the remaining research/design work required before the architecture is fully implementation-ready.

## 28.1 Provider lifecycle-hook research

**STILL NEED TO RESEARCH**

For each target client, verify exactly what we can observe/control:

| Client | MCP/tools | Can read SAC | Can write SAC | Guaranteed pre-turn hook | Guaranteed post-turn hook | Passive transcript access |
|---|---|---|---|---|---|---|
| ChatGPT | researched partially | likely | surface/plan dependent | unknown | unknown | unknown |
| Codex | plugin/app direction researched | likely | likely on supported app | unknown | unknown | unknown |
| Claude | remote MCP supported | yes | yes through tools | unknown | unknown | unknown |
| Claude Code | MCP supported | yes | yes | needs research | needs research | needs research |
| Cursor | not researched for this project | TBD | TBD | TBD | TBD | TBD |

This should be the next focused technical research task.

## 28.2 OpenAI V0 integration choice

**STILL NEED TO DECIDE after validation**

Choose one:

```text
A. Custom GPT + REST Actions
B. OpenAI plugin/app + MCP
C. Both, with Actions as fallback
```

The correct choice depends on plan support, distribution, write capability, and invocation reliability.

## 28.3 Automatic capture semantics

**STILL NEED TO DESIGN**

What exactly counts as a durable project update?

Need policy for:

```text
facts
decisions
requirements
constraints
tasks
status
hypotheses
observations
```

And which scopes default to:

```text
private
shared
ask user
```

## 28.4 Conversation evidence retention

**STILL NEED TO RESEARCH + DESIGN**

Questions:

- Does SAC store entire authorized turns or only selected excerpts?
- What do provider policies permit?
- What does the user explicitly consent to?
- What are deletion/retention semantics?
- How do we prevent sensitive accidental sharing?

## 28.5 Context-budget model profiles

**RESEARCH FOUNDATION EXISTS; IMPLEMENTATION STILL NEEDED**

Need real per-model profiles for:

```text
supported input
max output
recommended SAC budget
tool overhead
cache support
effective-context measurements
serialization preferences
```

## 28.6 Conflict UX

**STILL NEED TO DESIGN**

Backend semantics are understood, but human resolution UI is not.

## 28.7 Sharing controls UX

**STILL NEED TO DESIGN**

Users need a simple way to understand:

```text
private to me
shared with project
source preserved
pinned
proposed / confirmed
```

## 28.8 Security threat model

**PARTIALLY RESEARCHED; NEED IMPLEMENTATION THREAT MODEL**

Need dedicated work on:

- prompt injection through stored evidence
- malicious memory writes
- cross-project leakage
- compromised MCP server credentials
- OAuth token handling
- account/client revocation
- source ACL inheritance
- memory poisoning

## 28.9 Provider terms/privacy review

**STILL NEED TO RESEARCH**

Before public rollout, review the exact terms and data-handling rules for each integration surface.

## 28.10 V0 stack decision

**STILL NEED TO DECIDE**

Pick Python/FastAPI or TypeScript backend and start implementation.

---

# 29. What Notion Added To This Pass

A search of the currently connected Notion workspace for `Shared Agent Context` and shared-context terminology did not surface a dedicated SAC architecture/product page. The relevant results were primarily unrelated project/research notes.

Therefore the GitHub repository remains the canonical source for SAC product architecture in this pass.

If a dedicated SAC Notion page is created later, we can use it as a higher-level planning/product workspace while GitHub remains the technical source of truth.

---

# 30. Current Product Definition

The rudimentary product is no longer best described as simply "a shared context window."

A more accurate V0 definition is:

> **Shared Agent Context is a project-scoped memory and synchronization service that connects independent AI clients. Each user has optional private project memory, the team has a shared project memory pool, and a model-aware Context Compiler combines the authorized pieces into the working context for that user's current agent. Shared knowledge written by one connected agent becomes immediately retrievable by the others.**

The simplest visual is:

```text
PERSON A                                     PERSON B

ChatGPT                                      Claude
   │                                            │
   ▼                                            ▼
Session CP                                  Session CP
   │                                            │
   ▼                                            ▼
Person A Private CP                    Person B Private CP
   │                                            │
   └──────────────┐                ┌────────────┘
                  ▼                ▼
                 SHARED PROJECT CP
                         │
                         ▼
                Evidence + History
                         │
                         ▼
                 Context Compiler
                  ▲             ▲
                  │             │
       OpenAI-sized view   Claude-sized view
```

This is the architecture we should build toward first.

---

# 31. Related Repository Documents

This document consolidates and operationalizes the following existing work:

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — canonical project memory architecture, permissions, provenance, write/retrieval pipelines
- [`MVP.md`](MVP.md) — original two-user/two-client proof and build sequence
- [`CONTEXT_COMPILER.md`](CONTEXT_COMPILER.md) — provider-neutral context compiler boundary
- [`HIGH_QUALITY_CONTEXT_WINDOW_ARCHITECTURE.md`](HIGH_QUALITY_CONTEXT_WINDOW_ARCHITECTURE.md) — active model-context construction
- [`RESEARCH_CONTEXT_WINDOWS_AND_MEMORY.md`](RESEARCH_CONTEXT_WINDOWS_AND_MEMORY.md) — context/memory foundations
- [`RESEARCH_EXPANDING_CONTEXT_WINDOWS_2023_2026.md`](RESEARCH_EXPANDING_CONTEXT_WINDOWS_2023_2026.md) — long-context scaling research
- [`LONG_CONTEXT_IMPLEMENTATION_GUIDE.md`](LONG_CONTEXT_IMPLEMENTATION_GUIDE.md) — model profiles, adaptive budgets, paging, caching, evaluation
- [`DYNAMIC_MODEL_AWARE_CONTEXT_COMPACTION.md`](DYNAMIC_MODEL_AWARE_CONTEXT_COMPACTION.md) — unbounded logical context, `/compact`, `/expand`, semantic paging, re-hydration
- [`PRINCIPLES.md`](PRINCIPLES.md) — product design constraints

---

## Final V0 Principle

> **Each person keeps their own private working context. The project owns the shared knowledge. Every connected agent receives the authorized combination of both, compiled for the model it is using.**

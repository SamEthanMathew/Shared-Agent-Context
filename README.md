# Shared Agent Context

**Shared Agent Context is a model-agnostic collaboration layer for AI agents.**

It gives teams a persistent, shared project brain that multiple people and multiple AI systems can read from and write to, even when those users are working in different accounts, different chats, different IDEs, or with different model providers.

The core idea is simple:

> Models are replaceable. Project knowledge should persist.

Today, AI collaboration is fragmented. Sam can work with ChatGPT on the macOS side of a product while Matthew uses Claude or Codex on the Windows side, but their agents do not automatically share what they know. Each chat, account, model, and tool develops its own partial view of the project.

Shared Agent Context sits between those tools as a neutral knowledge layer.

## The Problem

AI agents increasingly perform real project work, but their context is siloed.

A typical team might use:

- ChatGPT for research and planning
- Claude for long-form reasoning
- Codex or Cursor for implementation
- GitHub for source control
- Notion or Google Docs for documentation
- Linear or Jira for task management

Each system sees a different slice of the work. Knowledge is copied manually, buried in chat history, reconstructed from commits, or lost entirely.

That creates several problems:

1. **Context fragmentation** - each agent has an incomplete understanding of the project.
2. **Duplicated work** - agents repeat research, decisions, or implementation work already done elsewhere.
3. **Project drift** - different collaborators operate from stale assumptions.
4. **Vendor lock-in** - useful memory is trapped inside one AI product or account.
5. **Poor agent-to-agent collaboration** - agents can execute tasks, but they cannot reliably maintain a common understanding of the project.

## The Vision

Shared Agent Context becomes the collaboration infrastructure between humans and AI agents.

Instead of sharing entire conversations, agents exchange structured project knowledge.

Each project gets a persistent shared context containing things such as:

- project goals
- architecture
- product requirements
- decisions
- assumptions
- current tasks
- completed work
- blockers
- experiments
- artifacts
- important files
- people and responsibilities
- unresolved questions
- recent changes

Every connected agent can retrieve the context relevant to its current task and contribute new knowledge back into the shared project brain.

## Example

Sam and Matthew are building the same application.

Sam is working on the macOS client using ChatGPT and Codex.

Matthew is working on the Windows client using Claude and Cursor.

Sam's agent discovers that authentication will use device-bound passkeys and updates Shared Agent Context.

Matthew later asks Claude to implement Windows authentication. Claude retrieves the project's current authentication decision automatically and builds against the same architecture.

No one had to copy a chat, update a `CLAUDE.md` file, or message the other person.

The knowledge followed the project instead of the model.

## Product Principles

### 1. Model agnostic

Shared Agent Context should work across ChatGPT, Claude, Gemini, Codex, Cursor, local models, and future AI systems.

### 2. User owned

Project memory belongs to the project and its collaborators, not to the model provider that created it.

### 3. Knowledge, not chat logs

The system should extract and store durable project knowledge rather than blindly copying entire conversations.

### 4. Context on demand

Agents should receive the smallest useful subset of project knowledge for the task they are performing.

### 5. Provenance by default

Every piece of shared knowledge should be traceable to where it came from: a user, agent, conversation, commit, document, tool action, or external source.

### 6. Permission aware

Not every collaborator or agent should see or modify every piece of project context.

### 7. Continuously updated

The shared brain should evolve as work happens instead of depending solely on commits or manual documentation updates.

## What This Is Not

Shared Agent Context is not intended to be:

- another chat application
- a replacement for GitHub
- a replacement for Notion or Google Docs
- a single-model memory feature
- a giant prompt copied into every agent
- a simple vector database wrapper

Those systems remain useful. Shared Agent Context connects the knowledge produced across them.

## Initial Product Surface

The first useful version should provide:

1. **Projects** - shared context spaces owned by one or more users.
2. **Members and permissions** - invite collaborators and control access.
3. **Memory objects** - structured facts, decisions, tasks, artifacts, summaries, and events.
4. **Write API** - agents can propose or record project updates.
5. **Retrieval API** - agents can request context relevant to a task.
6. **Provenance** - every memory object records its source.
7. **Version history** - project knowledge can evolve without silently overwriting history.
8. **Conflict handling** - contradictory facts or decisions can be surfaced instead of merged incorrectly.
9. **Agent integrations** - begin with MCP/API access and a small number of high-value clients.
10. **Human project view** - a dashboard where collaborators can inspect and correct what the shared brain believes.

## Architecture Direction

At a high level:

```text
ChatGPT ─┐
Claude  ─┤
Codex   ─┤
Cursor  ─┤      ┌───────────────────────────┐
Gemini  ─┼─────▶│   Shared Agent Context    │
Local AI ┤      │                           │
Other    ─┘      │ Identity + Permissions    │
                 │ Memory Store              │
GitHub   ───────▶│ Retrieval                 │
Notion   ───────▶│ Knowledge Extraction      │
Docs     ───────▶│ Provenance + Versioning   │
Linear   ───────▶│ Events / Sync             │
                 └───────────────────────────┘
                              │
                              ▼
                  Relevant context returned
                  to whichever agent needs it
```

A deeper architecture proposal lives in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Target Market

The initial wedge is teams already doing significant work with multiple AI agents.

### Primary early users

- AI-native startup teams
- software engineering teams using multiple coding agents
- research labs
- technical cofounders
- open-source maintainers
- small teams coordinating autonomous or semi-autonomous agents

### Later markets

- product and design teams
- consulting and professional services
- enterprise knowledge work
- multi-agent automation platforms
- organizations deploying internal AI copilots

## Why Now

The AI ecosystem is moving from one assistant per user toward many agents operating across many tools.

As execution becomes cheaper, coordination becomes more important.

The bottleneck shifts from "can an AI perform this task?" to:

> "Does this AI know what the rest of the team and the rest of the agents already know?"

Shared Agent Context is designed around that coordination problem.

## Business Model

Potential business model:

- **Free / developer tier** - limited projects, members, and context usage
- **Team SaaS** - per-seat or usage-based shared projects
- **API platform** - memory/retrieval infrastructure priced by storage, retrieval, and events
- **Enterprise** - SSO, audit logs, advanced permissions, private deployment, retention controls, compliance, and administration

The long-term opportunity is to become infrastructure rather than only an end-user application.

## MVP

The MVP should prove one thing:

> Two people using different AI clients can work on the same project and reliably benefit from knowledge produced by each other's agents.

A strong first demo:

1. User A creates a shared project.
2. User B joins it.
3. User A works with one AI client and makes a project decision.
4. The client writes that decision into Shared Agent Context.
5. User B works from a different AI client/account.
6. That agent retrieves the decision without User B manually copying anything.
7. User B's agent contributes another update.
8. User A's agent immediately has access to it.
9. Both users can inspect exactly what was stored and where it came from.

See [`docs/MVP.md`](docs/MVP.md) for the proposed implementation scope.

## Long-Term Direction

If successful, Shared Agent Context can evolve into a broader coordination layer for AI work:

- agent presence and activity
- task ownership
- shared plans
- subscriptions to project changes
- semantic event streams
- automatic handoffs between agents
- context branches and environments
- organizational knowledge graphs
- policy-aware agent permissions
- agent identities
- cross-application workflows
- standardized context portability

The ambitious version is effectively **collaboration infrastructure for AI agents**.

## Repository Status

This repository currently contains the initial product definition, architecture direction, business plan, and MVP roadmap.

The project is at the concept / pre-MVP stage.

## Documents

- [`docs/BUSINESS_PLAN.md`](docs/BUSINESS_PLAN.md) - market, positioning, business model, risks, and go-to-market
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - proposed technical architecture and memory model
- [`docs/MVP.md`](docs/MVP.md) - first product scope and build roadmap
- [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md) - product principles and design constraints

## Working Definition

**Shared Agent Context is a user-owned, model-agnostic shared memory and coordination layer that allows multiple humans and AI agents to maintain a consistent understanding of the same project across accounts, applications, and model providers.**

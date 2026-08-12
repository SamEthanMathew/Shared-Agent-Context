# Shared Agent Context: Business Plan

## 1. Executive Summary

Shared Agent Context (SAC) is a model-agnostic shared knowledge and coordination layer for teams working with AI agents.

AI products currently treat context primarily as something belonging to one user, one conversation, one application, or one model provider. That assumption breaks when multiple people and multiple agents collaborate on the same project.

SAC separates **project memory** from **model memory**.

A team creates a shared project brain. Authorized humans and agents can contribute knowledge to it and retrieve relevant context from it regardless of whether they are using ChatGPT, Claude, Gemini, Codex, Cursor, a local model, or another system.

The initial wedge is technical teams already using multiple AI tools. The long-term opportunity is a neutral context and coordination protocol/platform for agentic work.

## 2. Problem

### Current workflow

Suppose two engineers are building one product:

- Engineer A uses ChatGPT and Codex.
- Engineer B uses Claude and Cursor.
- Both use GitHub.
- Product notes live in Notion.

Their humans collaborate, but their agents do not share a persistent understanding of the project.

When Engineer A makes an architectural decision with an agent, Engineer B's agent may know nothing about it until one of several manual events happens:

- someone sends a message
- someone updates documentation
- code is committed
- the other agent reconstructs the decision from source code
- context is manually copied between AI systems

This creates a new form of organizational fragmentation: **agent context fragmentation**.

### Why existing approaches are insufficient

#### Chat history

Rich but siloed, noisy, provider-specific, and difficult to share safely.

#### Model memory

Usually user-specific and vendor-specific. It is not a neutral team system of record.

#### `CLAUDE.md`, `AGENTS.md`, repository instructions

Excellent for durable repository instructions, but largely file/commit-oriented. They are not designed to represent a continuously changing, permission-aware shared memory across users, tools, and non-code workflows.

#### GitHub

The source of truth for code, not necessarily for every decision, experiment, conversation, assumption, task, or external artifact.

#### Notion / Docs

Useful human knowledge stores, but maintaining them is often manual and agents still need client-specific integrations and retrieval logic.

#### Vector databases

A useful infrastructure component, but semantic search over chunks is not equivalent to a trustworthy collaborative memory system.

## 3. Product Thesis

As AI systems become capable of taking increasingly autonomous actions, teams will need a common coordination layer.

The durable asset is not the model session. It is the evolving state of the project.

SAC therefore treats project context as first-class infrastructure with:

- identity
- permissions
- structure
- provenance
- version history
- retrieval
- synchronization
- conflict handling
- auditability

## 4. Product

### Core object: Project Brain

Each SAC project represents a shared body of knowledge accessible by approved collaborators and agents.

It stores several categories of knowledge:

- facts
- goals
- requirements
- decisions
- tasks
- status updates
- assumptions
- constraints
- artifacts
- people/roles
- blockers
- questions
- events

### Core actions

#### Remember

An agent or user proposes durable information for the project.

#### Recall

An agent requests the most relevant project context for its current task.

#### Inspect

A human can see what SAC currently believes about the project.

#### Correct

Users can edit, supersede, reject, or resolve memories.

#### Subscribe

Clients can eventually listen for relevant changes to project state.

## 5. Key Differentiation

### Model neutrality

The project brain is not owned by ChatGPT, Claude, Gemini, or any other inference provider.

### Multi-user by design

The core primitive is shared project knowledge, not personal memory.

### Structured memory

SAC should distinguish a decision from a task, fact, hypothesis, or artifact rather than flattening everything into embeddings.

### Provenance

Every important memory answers:

- who/what created this?
- when?
- from what source?
- how confident is it?
- what did it supersede?

### Context selection

The goal is not to send the entire knowledge base to every model. SAC assembles task-relevant context within a token/latency budget.

### Interoperability

The same project can be accessed through APIs, MCP, IDE integrations, agent frameworks, and future protocols.

## 6. Target Customers

### Beachhead: AI-native engineering teams

Characteristics:

- 2-20 people
- frequent use of coding agents
- multiple model providers
- rapid product iteration
- high cost of stale context
- already comfortable installing developer tooling

Why this segment first:

- pain is visible
- integrations are technically accessible
- ROI can be demonstrated through fewer duplicated tasks and faster handoffs
- GitHub provides a useful common anchor

### Research teams

Researchers frequently split literature review, experimentation, code, analysis, and writing among humans and agents. Shared context can preserve hypotheses, experiment results, and decisions across those workflows.

### Larger engineering organizations

Longer term, SAC can support teams deploying many internal copilots and agents with enterprise access control and governance.

### Agent platform developers

SAC can eventually be consumed as infrastructure rather than only through its own application.

## 7. Users and Jobs To Be Done

### Developer

"When another person or agent changes an important assumption, I want my agent to know before it writes code based on stale information."

### Technical founder

"I want every AI tool my team uses to understand the current product and architecture without repeatedly briefing it."

### Researcher

"I want agents working on different parts of a project to share experiment results and decisions without maintaining a manual mega-document."

### Engineering manager

"I want to understand what agents are doing and what project knowledge they are relying on."

## 8. Market Positioning

SAC sits at the intersection of:

- AI memory
- knowledge management
- developer infrastructure
- multi-agent systems
- collaboration software
- context engineering

A useful positioning statement:

> Shared Agent Context is the shared project brain for humans and AI agents, giving every authorized model the same evolving understanding of the work.

The category should initially be explained concretely rather than trying to force a new category name.

## 9. Competitive Landscape

Competitors and adjacent products will likely fall into several buckets:

### Model-native memory

Strength: seamless UX inside one provider.

Weakness: provider/account boundaries.

### Agent memory frameworks

Strength: flexible infrastructure for developers.

Weakness: often focused on one application's agents rather than cross-user collaborative project memory.

### Knowledge bases / RAG platforms

Strength: mature document ingestion and retrieval.

Weakness: documents and chunks are not necessarily a live model of project state.

### Collaboration suites

Strength: established team workflows and content.

Weakness: optimized around human-authored artifacts rather than agent-native context exchange.

### Agent orchestration frameworks

Strength: coordinate multiple agents inside a designed workflow.

Weakness: usually assume the agents are part of one orchestration environment rather than independent users and products.

SAC's defensible position should be the neutral layer connecting these environments rather than trying to replace all of them.

## 10. Go-To-Market

### Phase 1: developer-led adoption

Build an open or easy-to-install integration surface around MCP/API plus GitHub.

The demo should be instantly understandable:

> Make a decision in one model. Open another model on another account. Ask a question. The second model already knows.

### Phase 2: team product

Add:

- hosted projects
- invitations
- dashboard
- history
- integrations
- usage analytics
- admin controls

### Phase 3: platform

Expose SAC as infrastructure for companies building their own agents.

## 11. Distribution

Potential channels:

- open-source developer tooling
- MCP ecosystem
- GitHub integration
- Cursor / IDE workflows
- technical demos on X, Hacker News, Reddit, and developer communities
- research labs experimenting with agentic workflows
- partnerships with agent platforms

A compelling viral loop exists if joining a SAC project requires a collaborator to connect their agent. Each collaborative project can naturally introduce another user.

## 12. Pricing Hypothesis

Pricing should not be finalized before usage patterns are understood.

Possible structure:

### Developer / Free

- 1-3 projects
- small team
- usage limits
- basic integrations

### Team

Approximately $15-$30/user/month, potentially including a context usage allowance.

### Platform/API

Usage-based pricing around ingestion, storage, retrieval, and events.

### Enterprise

Annual contracts for:

- SSO/SAML
- SCIM
- audit logs
- data retention controls
- advanced RBAC
- private networking
- customer-managed keys
- deployment/data residency options
- policy controls

## 13. Moat

A vector store alone is not a moat.

Potential defensibility comes from the system built around it:

### Integration graph

Deep connectivity across agent clients and work systems.

### Memory quality

Reliable extraction, consolidation, conflict detection, temporal reasoning, and context assembly.

### Collaboration graph

Project membership, agent identities, permissions, provenance, and shared history.

### Protocol adoption

If developers begin treating SAC's context interface as a standard way to expose project state, interoperability itself becomes valuable.

### Trust

Teams will only use a shared brain if they trust its access controls, audit trail, and ability to distinguish source truth from agent inference.

## 14. Major Risks

### Providers build it natively

Mitigation: remain cross-provider and cross-application. A neutral layer can connect ecosystems that individual vendors are incentivized to keep inside their own products.

### MCP/protocol standards commoditize access

Mitigation: protocols are distribution. The valuable layer remains memory semantics, synchronization, governance, retrieval, and collaboration state.

### Garbage memory accumulation

Mitigation: explicit memory types, confidence, source authority, expiration, deduplication, supersession, human correction, and consolidation.

### Privacy and leakage

Mitigation: least-privilege access, project boundaries, provenance, encryption, audit logs, memory-level visibility, and strong deletion semantics.

### Agents write incorrect conclusions as facts

Mitigation: distinguish observations, claims, hypotheses, decisions, and verified facts. Support source authority and confirmation policies.

### Integration complexity

Mitigation: start with a narrow integration surface and standard protocols rather than building every client directly.

## 15. Success Metrics

MVP metrics should focus on whether shared context actually improves collaboration.

Potential metrics:

- context retrieval acceptance/use rate
- percentage of useful memories retrieved across users
- time from one agent's update to another agent receiving it
- duplicate work avoided
- stale-context errors detected/prevented
- weekly active shared projects
- number of distinct agent clients per project
- memories corrected/rejected by humans
- retrieval latency
- token reduction compared with sending full project history

North-star candidate:

**Weekly cross-agent context handoffs that materially influence another user's work.**

## 16. MVP Validation Questions

Before optimizing scale, prove:

1. Do users actually want agents to share project memory automatically?
2. What information should be shared automatically versus explicitly?
3. How much control do users need over writes?
4. How frequently does project knowledge conflict?
5. Can retrieval consistently outperform a manually maintained project markdown file?
6. Which integration produces the strongest initial adoption: MCP, IDE, GitHub, browser extension, or API?
7. Will users trust an AI-maintained project brain?

## 17. Initial Strategy

Do not begin by building a universal enterprise knowledge platform.

Build the smallest possible product that creates the "different model, same brain" moment.

The first milestone is not massive storage or sophisticated multi-agent autonomy. It is demonstrating that two collaborators can move between independent AI systems while preserving shared project understanding.

Once that primitive works reliably, broader agent coordination becomes possible.

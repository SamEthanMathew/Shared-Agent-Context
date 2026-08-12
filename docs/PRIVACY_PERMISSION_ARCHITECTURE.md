# Shared Agent Context: Privacy and Permission Architecture

**Status:** Initial architecture specification derived from provider/privacy research, August 12, 2026

## Goal

Design Shared Agent Context so that a user can always answer:

1. What context exists about me or my project?
2. Which AI/client can access it?
3. What can that AI do with it?
4. Where can the data go?
5. How long does access last?
6. What was actually used in a specific interaction?
7. How do I revoke or delete it?

The security boundary must be enforced by SAC itself, not by trusting the model to behave correctly.

---

## 1. Threat model

SAC sits between highly contextual AI clients and durable user/project data. The main risks are:

### Overbroad retrieval
An agent retrieves substantially more context than is necessary for the task.

### Cross-user leakage
One user’s personal context appears in another user’s model context.

### Cross-project leakage
A valid SAC client accesses a project it is not authorized to read.

### Transitive tool leakage
Private context influences or is included in a tool/API call to an external service.

### Prompt injection
Malicious repository/web/document content instructs an agent to access or exfiltrate private context.

### Memory poisoning
Untrusted data becomes durable “project truth.”

### Secret exposure
Credentials/API keys/tokens enter ordinary model context, logs, or memory stores.

### Retention mismatch
A user expects deletion from SAC to remove data that was already copied to a model provider, client cache, export, or external integration.

### Silent privilege accumulation
A client receives durable permissions and remains privileged long after the original task.

---

# 2. Hard architectural rule

**Authorization and sensitivity filtering happen before context reaches a model.**

Never rely on a prompt such as:

> “You may see all project data but please do not reveal private information.”

Instead:

```text
request
  ↓
authenticate client
  ↓
resolve user/project identity
  ↓
policy decision
  ↓
retrieve candidates
  ↓
sensitivity + ACL filter
  ↓
context compiler
  ↓
model
```

If the model should not see something, it should not be present in the model input.

---

# 3. Context scopes

Start with four hard logical scopes.

## `personal`

Private to one human user.

Examples:
- private preferences
- personal notes
- private chat-derived information
- career or health information not intentionally shared with collaborators

## `project`

Shared durable context available subject to project ACLs.

Examples:
- architectural decisions
- project requirements
- tasks
- approved documents
- implementation status

## `session`

Ephemeral information for the current task/session.

Examples:
- scratchpad inputs
- temporary file excerpts
- current tool output

Session context should not become durable automatically.

## `secret`

Credentials and high-risk values.

Examples:
- API keys
- access tokens
- passwords
- private signing keys
- database credentials

Secrets should live in a dedicated secret-management path and should normally never be rendered into general model context.

---

# 4. Sensitivity labels

Every memory/source should have a sensitivity classification.

Initial enum:

```text
public
internal
confidential
restricted
secret
```

Suggested meaning:

- `public`: safe for public disclosure
- `internal`: normal project-only context
- `confidential`: sensitive project/user data
- `restricted`: highly sensitive personal/legal/financial/security data
- `secret`: credentials and authentication material

Sensitivity is independent of scope. A project can contain confidential information.

---

# 5. Context grant

Each client gets explicit grants rather than broad implicit access.

```json
{
  "id": "grant_123",
  "subject_user_id": "user_sam",
  "project_id": "proj_abc",
  "client_id": "client_claude_code_7",
  "status": "active",
  "read_scopes": [
    "project.requirement",
    "project.decision",
    "project.task",
    "project.artifact"
  ],
  "write_scopes": [
    "project.observation",
    "project.task_status"
  ],
  "max_sensitivity": "internal",
  "allowed_sources": [
    "github:SamEthanMathew/Shared-Agent-Context"
  ],
  "allowed_destinations": [
    "anthropic:claude-code"
  ],
  "duration": "session",
  "expires_at": "...",
  "approval_policy": "confirm_sensitive_actions",
  "created_at": "...",
  "created_by": "user_sam"
}
```

### Grant principles

- New clients receive no access by default.
- Read and write are separate.
- High-authority write operations require separate scopes.
- Grants should support expiration.
- Grant creation and modification is audited.
- Revocation must take effect immediately at SAC.

---

# 6. Client identity

Every ChatGPT, Codex, Claude, Claude Code, Gemini, SDK, or MCP connection must have a distinct client identity.

```text
ClientIdentity
- id
- user_id
- provider
- product
- installation/device/workspace identifier
- auth method
- created_at
- last_used_at
- revoked_at
- metadata
```

Example actors:

```text
Sam's ChatGPT
Sam's Codex laptop
Sam's Claude Code desktop
Matthew's Claude
CI agent
```

Do not collapse all agents belonging to one user into a single identity.

This makes per-client revocation and auditing possible.

---

# 7. Permission actions

Start with explicit verbs.

```text
read
search
retrieve
propose
write
update
supersede
delete
share_external
connect_source
manage_permissions
export
```

A role such as `member` can be translated into these lower-level actions, but enforcement should ultimately evaluate actions/scopes.

---

# 8. High-authority memory writes

Not all memories are equal.

The following should normally require explicit authority or confirmation:

- `decision`
- `requirement`
- `constraint`
- membership/permission changes
- deletion of canonical project knowledge
- supersession of approved decisions

An ordinary agent can instead submit:

```text
proposed_decision
observation
hypothesis
candidate_requirement
```

which can later be approved.

This reduces memory poisoning risk.

---

# 9. Retrieval API must be task-scoped

Avoid:

```text
GET /all-context
```

Prefer:

```json
POST /v1/projects/:id/context/query
{
  "task": "Implement the OAuth callback handler",
  "types": ["decision", "requirement", "artifact"],
  "max_tokens": 4000,
  "max_sensitivity": "internal"
}
```

The server should:

1. authenticate actor;
2. evaluate grant;
3. identify relevant candidates;
4. filter ACL/sensitivity;
5. remove superseded/stale context;
6. assemble minimum useful bundle;
7. record exactly what was returned.

---

# 10. Context manifest

Every retrieval should create a server-side manifest.

```json
{
  "manifest_id": "ctx_123",
  "request_id": "req_456",
  "client_id": "client_codex_1",
  "project_id": "proj_abc",
  "purpose": "Implement OAuth callback handler",
  "included": [
    {
      "memory_id": "mem_1",
      "type": "decision",
      "sensitivity": "internal"
    }
  ],
  "excluded": [
    {
      "memory_id": "mem_9",
      "reason": "sensitivity_exceeds_grant"
    }
  ],
  "destination": "openai:codex",
  "token_estimate": 1840,
  "created_at": "..."
}
```

The context manifest is useful for:

- auditability;
- debugging;
- user transparency;
- privacy receipts;
- security incident analysis;
- evaluating retrieval quality.

---

# 11. Privacy receipt

After a sensitive interaction, SAC should expose a readable receipt.

Example:

```text
Claude Code used:
- 2 architecture decisions
- 1 requirement
- 1 GitHub artifact

Claude Code could not access:
- personal memory
- restricted records
- project secrets

External destinations:
- Anthropic Claude Code only

Writes:
- proposed 1 implementation observation

Permission expires:
- when this session ends
```

Machine-readable version:

```json
{
  "request_id": "req_456",
  "client_id": "client_claude_code_7",
  "context_manifest_id": "ctx_123",
  "external_tool_calls": [],
  "writes": ["mem_observation_44"],
  "provider": "anthropic",
  "provider_product": "claude-code",
  "provider_policy_snapshot": "provider_policy_2026_08_12_abc",
  "timestamp": "..."
}
```

---

# 12. Outbound egress policy

Privacy enforcement cannot stop when context is delivered to the model.

An agent might read allowed context and then send it to a third-party API.

For SAC-integrated tool pathways, evaluate outbound payloads against:

- destination;
- data classification;
- project policy;
- current user permission;
- requested operation;
- whether the destination is necessary for the task.

Potential policy result:

```text
ALLOW
DENY
ALLOW_WITH_REDACTION
REQUIRE_CONFIRMATION
```

Example:

```text
Send public project URL to GitHub API → ALLOW
Send internal architecture summary to approved model provider → ALLOW
Send restricted personal memory to arbitrary MCP server → DENY
Send confidential customer data to new connector → REQUIRE_CONFIRMATION
```

---

# 13. Source trust and instruction/data separation

Every source should carry a trust level.

Example:

```text
owner_explicit_decision      high
approved_project_spec        high
merged_repository_state      medium-high
member_statement             medium
agent_observation             medium-low
external_webpage              low
untrusted_repo_file           low
agent_inference               low
```

Critically, source authority does not mean the source can issue arbitrary executable instructions.

Imported documents, web pages, issues, and repository files are **data** unless the system explicitly recognizes them as an approved instruction source.

SAC should preserve this distinction in the context compiler.

---

# 14. Prompt-injection defenses

Minimum protections:

1. Do not expose unrestricted recall tools to agents.
2. Scope recall to the active project and user task.
3. Do not let retrieved content dynamically widen grants.
4. Treat external content as untrusted.
5. Require confirmation before sensitive external sharing.
6. Do not expose secrets through normal retrieval.
7. Require authority for canonical-memory writes.
8. Log unusual retrieval patterns.
9. Rate-limit broad sequential searches.
10. Support destination-aware DLP rules.

Potential later research:

- taint tracking across summaries;
- information-flow labels;
- model-assisted prompt-injection classification;
- canary data for detecting exfiltration attempts;
- policy-driven tool graph execution.

---

# 15. Secrets architecture

Do not represent secrets like ordinary memories.

Bad:

```json
{
  "type": "fact",
  "content": "AWS_SECRET_ACCESS_KEY=..."
}
```

Better:

```text
SecretReference
- id
- provider/vault path
- allowed_tool
- allowed_operation
- expiry
```

When possible, a tool receives the credential through a secure runtime channel while the model sees only:

```text
“GitHub authentication is available.”
```

not the token itself.

---

# 16. Derived context and lineage

If SAC infers:

> “The team prefers PostgreSQL.”

from several sources, the derived memory should record:

```json
{
  "type": "inference",
  "content": "The team currently prefers PostgreSQL.",
  "derived_from": ["mem_1", "mem_8", "doc_17"],
  "confidence": 0.83,
  "sensitivity": "internal"
}
```

Derived memory must never silently lose the strongest sensitivity classification of its inputs without an explicit declassification rule.

A conservative rule for MVP:

```text
derived_sensitivity = max(source_sensitivities)
```

---

# 17. Deletion and revocation semantics

Deleting a source should trigger a dependency check.

```text
source deleted
   ↓
find derived memories/index entries/caches
   ↓
recompute or remove derived context
   ↓
remove SAC copies
   ↓
record external copies that SAC cannot revoke
```

SAC should distinguish:

```text
deleted_from_sac
revoked_from_future_retrieval
scheduled_for_cache_deletion
external_copy_may_remain
```

Never claim complete deletion from third-party providers unless that has actually been verified through an API/contract.

---

# 18. Provider policy registry

Because privacy varies by account tier and product, maintain provider-policy metadata.

Example:

```json
{
  "provider": "openai",
  "product": "chatgpt",
  "account_class": "personal_plus",
  "training_default": "provider_specific",
  "temporary_mode_available": true,
  "provider_retention_reference": "...",
  "local_transcript_possible": false,
  "updated_at": "2026-08-12",
  "source_urls": []
}
```

Another:

```json
{
  "provider": "anthropic",
  "product": "claude-code",
  "account_class": "consumer_pro",
  "local_transcript_possible": true,
  "local_transcript_default_days": 30,
  "training_setting": "user_choice",
  "updated_at": "2026-08-12"
}
```

The registry is informational. SAC authorization should not depend on provider promises alone.

---

# 19. Permission UX

The user should approve access in understandable categories, not OAuth-style walls of text.

Example:

```text
Connect Sam's Claude Code to Shared Agent Context

This client wants to READ:
✓ architecture decisions
✓ requirements
✓ open tasks
✓ approved artifacts

It cannot read:
✗ personal memory
✗ restricted records
✗ secrets

This client wants to WRITE:
✓ observations
✓ task status
✗ final decisions
✗ permissions

Access duration:
● This session
○ 24 hours
○ Until revoked

[Allow]
```

Advanced users can expand to source-level and sensitivity-level controls.

---

# 20. Human control plane

Add a dedicated Privacy/Access section to the SAC web UI.

## Connected Clients

Show:
- client identity
- provider/product
- scopes
- last access
- expiration
- revoke button

## Data Sources

Show:
- connected GitHub/Drive/etc.
- what was indexed
- current sync state
- retention/cache policy
- disconnect/delete controls

## Context Explorer

Show:
- personal vs project scope
- sensitivity
- provenance
- derived relationships
- which clients recently accessed it

## Activity

Show:
- sensitive reads
- writes
- exports
- external shares
- permission changes

## Privacy Defaults

Examples:
- default new-client duration
- default max sensitivity
- require confirmation for external sharing
- disable personal-context sharing by default
- auto-expire inactive grants

---

# 21. MVP implementation order

### Phase 1: Required before multi-agent prototype

- distinct users
- distinct client identities
- project membership
- project-only memory
- read/write scopes
- task-scoped retrieval
- audit log
- provenance
- no secrets in memory
- revocable tokens

### Phase 2: Privacy control plane

- context manifests
- per-client grant UI
- time-limited grants
- sensitivity classifications
- privacy receipts
- data-source management

### Phase 3: Personal context

Only add after project sharing is robust:

- personal context store
- explicit personal → project sharing
- redaction
- derived-data lineage
- cascading deletion
- sensitive-data detection

### Phase 4: Advanced security

- outbound DLP
- tool-destination controls
- taint tracking
- automated prompt-injection detection
- risk-based approval flows
- organization policy engine

---

# 22. Non-negotiable product rules

1. **Personal context is private unless explicitly shared.**
2. **Connecting a client does not mean sharing everything.**
3. **Read permission never implies write permission.**
4. **Write permission never implies authority to finalize decisions.**
5. **The model is not the authorization layer.**
6. **A retrieved document cannot grant itself permissions.**
7. **Secrets do not belong in ordinary context.**
8. **Every sensitive read/write is attributable.**
9. **Every grant is revocable.**
10. **Every durable memory has provenance.**
11. **Every derived memory has lineage.**
12. **External sharing is destination-aware.**
13. **Provider account tier/privacy policy is visible to the user.**
14. **Temporary/private mode must state actual retention guarantees.**
15. **Deletion claims must distinguish SAC deletion from external retention.**

---

# 23. Relationship to existing architecture

This document extends `ARCHITECTURE.md` rather than replacing it.

`ARCHITECTURE.md` defines the project-memory and retrieval architecture.

This specification defines the privacy/security layer that must wrap those operations:

```text
existing architecture:
Agent → API → Context Service → Memory

with privacy architecture:
Agent
  ↓
Authentication
  ↓
Client Grant / Policy Engine
  ↓
Context Service
  ↓
ACL + Sensitivity Filtering
  ↓
Context Compiler
  ↓
Provider Boundary
  ↓
Audit / Privacy Receipt
```

---

# 24. Product north star

A Shared Agent Context user should be able to open one screen and immediately understand:

> **Who can access my context, what they can access, what they did access, what they can change, where information can leave, and how to stop it.**

If SAC can make this substantially clearer than the privacy model of current account-based AI products, privacy becomes a core product advantage rather than a compliance afterthought.

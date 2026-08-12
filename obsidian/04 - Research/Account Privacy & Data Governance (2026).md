# Research: Account Privacy and Data Governance Across Major AI Assistants

**Status:** Research snapshot as of August 12, 2026  
**Scope:** ChatGPT/OpenAI, Codex, Claude, Claude Code, and Google Gemini  
**Purpose for Shared Agent Context (SAC):** Capture how current account-based AI products store, retrieve, personalize, train on, share, and delete user data so SAC can design a privacy model that is clearer and safer than current fragmented controls.

> This document is a product/security research reference, not legal advice. Provider behavior changes quickly. Re-check linked first-party sources before relying on a specific retention period or product setting.

---

## 1. The central finding

The privacy question for modern AI is no longer just:

> “Does the company keep my prompt?”

An account-based assistant can operate on several independent layers of information:

1. **Current-session context** — what is needed to answer the current conversation.
2. **Conversation history** — chats stored in the account.
3. **Long-term memory/personalization** — facts, summaries, preferences, or inferred context retrieved across chats.
4. **Connected-source data** — email, Drive, GitHub, calendars, browsers, local files, repositories, MCP servers, devices, etc.
5. **Model-improvement data** — interactions eligible for evaluation, fine-tuning, or training future models.
6. **Safety/quality review data** — content retained or reviewed for abuse, feedback, debugging, or human review.
7. **Operational and organizational records** — telemetry, security logs, enterprise audit logs, retention policies, and administrator-accessible records.

These layers are not the same thing and turning one off normally does **not** turn the others off.

Examples:

- Turning off model training does not necessarily delete chat history.
- Turning off memory does not necessarily delete old chats.
- Deleting a chat may not remove a separately stored memory or a copy retained by a connected service.
- Using an enterprise account can reduce vendor training exposure while increasing employer/admin visibility.
- Coding assistants create extra privacy surfaces such as local transcripts, shell output, repositories, credentials, network access, and cloud execution environments.

**Core design lesson for SAC:** privacy must be modeled as a multi-dimensional permissions and lifecycle system, not one “privacy” toggle.

---

## 2. The questions a user actually needs answered

| User question | Actual control surface |
|---|---|
| Can the assistant remember this next month? | Memory / past-chat retrieval / saved information |
| Is this conversation stored? | Conversation-history retention |
| Can this improve future models? | Model-improvement/training permission |
| Could a human review it? | Feedback / safety / quality-review policy |
| Can it see my Gmail, Drive, GitHub, browser, or repo? | Connector / OAuth / tool permissions |
| Can it modify those systems? | Write-action permissions / approvals |
| Can my employer or school see it? | Workspace admin / compliance / retention policy |
| Is there another local copy on my machine? | Client transcript/cache/log behavior |
| If I delete it here, is it deleted everywhere? | Cross-system deletion semantics |

A safe AI product should expose these as separate concepts.

---

# 3. OpenAI: ChatGPT and Codex

## 3.1 Personal ChatGPT accounts

OpenAI distinguishes consumer personal workspaces from business/enterprise products.

For personal ChatGPT accounts, OpenAI currently provides a model-improvement control under **Settings → Data Controls → Improve the model for everyone**. Turning it off prevents **new** conversations from being used to train OpenAI’s models while preserving normal chat history.

For personal Free/Plus/Pro-style workspaces, model-improvement sharing is generally enabled unless the user opts out. Business, Enterprise, Edu, and API data follow a different default and are not used for generalized model training by default.

Source:
- https://help.openai.com/en/articles/8983130-what-if-i-want-to-keep-my-history-on-but-disable-model-training
- https://openai.com/enterprise-privacy/

### Important separation

OpenAI’s system should be understood as at least three independent controls:

- **History** — whether the chat remains in the account.
- **Memory/personalization** — whether ChatGPT may use persistent context across chats.
- **Training/model improvement** — whether eligible content may improve future shared models.

A user can keep history while opting out of training.

---

## 3.2 Temporary Chat

OpenAI Temporary Chat is the closest consumer mode to a private session:

- does not appear in normal history;
- does not create or use normal memory;
- is not used for model improvement;
- may still be retained for up to roughly 30 days for safety/legal/operational reasons, subject to provider exceptions.

Sources:
- https://help.openai.com/en/articles/7730893-data-controls-faq
- https://openai.com/policies/row-privacy-policy/

**Product lesson:** “temporary” must never be presented as synonymous with “zero retention.” SAC should always show the actual retention promise.

---

## 3.3 ChatGPT memory and personalization

ChatGPT memory is a separate layer from raw conversation history.

Current OpenAI documentation describes memory/personalization as being able to use information from:

- saved memories;
- prior conversations;
- files;
- connected apps;
- custom instructions and other personalization sources.

OpenAI also exposes a memory-management surface and, in some product surfaces, provenance/source indicators for personalized responses.

Source:
- https://help.openai.com/articles/8590148-memory-faq

### Deletion complexity

A single fact can exist in multiple places:

- original chat;
- a saved or synthesized memory;
- a file;
- a connected app;
- a derived summary.

Therefore removing a fact from only one source may not remove it from every path by which it can later be retrieved.

**SAC implication:** derived knowledge must maintain lineage to its source data and support cascading deletion/revocation.

---

## 3.4 Connected apps and indexed copies

OpenAI apps/connectors can pull information from external systems into ChatGPT. Some integrations may index or sync external content in advance.

A notable example is OpenAI’s Google app integration. OpenAI states that ChatGPT may create an indexed copy of connected Google data for retrieval/personalization. When a Google app is disconnected, the indexed copy is scheduled for deletion within 30 days.

OpenAI also states that connected Google app data has special training handling: it is not used to train generalized models directly except in defined cases such as feedback, manual copy/paste/upload into chats, or content included in ChatGPT responses.

Source:
- https://help.openai.com/en/articles/10408842

**SAC implication:** connectors should not silently create durable copies. Indexing, caching, embedding, and retention must be disclosed as separate actions.

---

## 3.5 Business, Enterprise, and Edu

OpenAI states that business data is not used to train generalized models by default.

Enterprise-style accounts add controls around:

- workspace retention;
- identity and access management;
- compliance/audit logs;
- data residency in supported configurations;
- workspace-level connector/plugin control;
- organizational access to content.

Source:
- https://openai.com/enterprise-privacy/
- https://openai.com/security-and-privacy/

### Important inversion

Enterprise privacy improves confidentiality from the **vendor training pipeline**, but the organization itself gains more governance and potential visibility.

A managed work account should be treated like managed company email or Slack, not like a personal diary.

---

## 3.6 OpenAI API

The API is a distinct privacy category from consumer ChatGPT.

OpenAI documents abuse-monitoring logs that are generally retained for up to 30 days for relevant API usage. Qualified customers may be approved for Modified Abuse Monitoring or Zero Data Retention configurations, with feature-specific limitations.

Source:
- https://developers.openai.com/api/docs/guides/your-data

**SAC implication:** provider adapters should encode account/product policy, not merely provider name. “OpenAI” is not one privacy regime.

---

## 3.7 Codex-specific privacy surfaces

Codex expands the data boundary beyond chat text.

Potentially exposed data includes:

- repository files;
- Git history;
- terminal output;
- environment configuration;
- browser state and screenshots;
- connected apps/tools;
- local session transcripts;
- cloud-environment files and setup artifacts.

OpenAI says ChatGPT training-data controls apply to content processed through Codex, including Computer Use screenshots, but Codex can also expose product-specific controls and execution-environment behavior.

Source:
- https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- https://help.openai.com/en/articles/5722486-how-your-data-is-used-to-improve-model-performance

### Local transcript retention

OpenAI documents local Codex transcript/history settings such as `history.persistence` and `history.max_bytes`. Users who do not want local session transcripts under `CODEX_HOME` must configure local retention accordingly.

Source:
- https://learn.chatgpt.com/docs/agent-approvals-security

**SAC implication:** “data retained by provider” and “data retained by client” are different retention domains and must be shown separately.

---

# 4. Anthropic: Claude and Claude Code

## 4.1 Consumer model-improvement consent

Anthropic’s consumer privacy design is notable because it requires a visible user choice about whether Free/Pro/Max conversations and eligible Claude Code sessions may be used for model improvement.

The user can later change this under privacy settings.

Sources:
- https://www.anthropic.com/news/updates-to-our-consumer-terms
- https://privacy.anthropic.com/en/articles/12109829-how-do-i-change-my-model-improvement-privacy-settings

**Design strength:** explicit decision-making is clearer than a hidden default + opt-out model.

---

## 4.2 Retention

Anthropic documents multiple retention categories rather than one universal period.

Important examples from current consumer documentation include:

- deleted ordinary consumer conversations are removed from visible history and scheduled for backend deletion within roughly 30 days;
- if the user allows model improvement, de-identified eligible conversation/coding-session data can remain in the model-improvement pipeline for up to **five years**;
- trust-and-safety flagged content and classification metadata may have separate longer retention periods;
- feedback data can have separate retention.

Source:
- https://privacy.anthropic.com/en/articles/10023548-how-long-do-you-store-personal-data

**SAC implication:** retention is purpose-specific. Store a `retention_basis` and `retention_until` per copy, not only per source record.

---

## 4.3 Claude memory and past-chat search

Claude distinguishes two concepts:

1. **Past-chat search/retrieval** — finding information from previous conversations.
2. **Memory** — separately maintained personalization entries/summaries.

Anthropic exposes user controls to inspect, edit, pause, or reset memory. Project memory can be separated by project.

Source:
- https://support.anthropic.com/en/articles/11817273-using-claude-s-chat-search-and-memory-to-build-on-previous-context

This is useful for SAC because it demonstrates that long-term personalization does not require fine-tuning a private model. It can be built as retrieval + structured memory layered on top of a shared model.

---

## 4.4 Incognito conversations

Claude Incognito mode excludes conversations from normal history/memory and consumer model improvement.

However, on managed Team/Enterprise environments, organizational retention/export rules can still apply.

Sources:
- https://privacy.anthropic.com/en/articles/10023580-is-my-data-used-for-model-training
- https://support.anthropic.com/en/articles/11817273-using-claude-s-chat-search-and-memory-to-build-on-previous-context

**SAC implication:** a privacy mode must disclose which governance layer can override it.

---

## 4.5 Claude Code local plaintext transcripts

Claude Code introduces an important local privacy surface.

Anthropic documents that Claude Code clients store session transcripts locally in plaintext under `~/.claude/projects/` by default for approximately 30 days to support session resumption.

The retention period can be changed through `cleanupPeriodDays`, and transcript writes can be disabled.

Sources:
- https://code.claude.com/docs/en/data-usage
- https://code.claude.com/docs/en/settings

This means Claude Code privacy depends not only on Anthropic’s server policy but also on:

- disk encryption;
- OS account security;
- endpoint management;
- backups;
- filesystem access by other software.

**SAC implication:** local caches and agent logs must be part of the threat model.

---

## 4.6 Claude Code telemetry and feedback

Anthropic documents operational telemetry for usage metrics and error reporting. These can be disabled independently or more broadly with settings such as `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`.

Anthropic also distinguishes simple quality ratings from explicit transcript-sharing consent. Some feedback flows upload session transcripts only after the user explicitly opts in.

Source:
- https://code.claude.com/docs/en/data-usage

**SAC implication:** diagnostics should default to metadata-only and require separate explicit consent before including content.

---

## 4.7 Commercial Claude / API / ZDR

Anthropic commercial usage follows a different privacy regime from consumer Claude.

Anthropic states that commercial/API customer data is not used for training without express permission. Qualified organizations may receive Zero Data Retention for eligible features, with feature/model-specific exceptions.

Source:
- https://docs.anthropic.com/en/docs/build-with-claude/zero-data-retention

Again, the account/product type matters more than the model family name.

---

# 5. Google Gemini

## 5.1 The Google-account privacy surface is unusually broad

Gemini can be attached to a large Google identity/data ecosystem.

Depending on feature and permissions, Gemini may process or retrieve:

- prompts and uploads;
- past Gemini chats;
- Gmail;
- Calendar;
- Drive/Docs/Sheets/Slides;
- Photos;
- Search/YouTube activity;
- Chrome page context;
- location/device context;
- contacts;
- third-party MCP services;
- remote-browser state;
- generated personalized insights.

Source:
- https://support.google.com/gemini/answer/13594961

**SAC implication:** account-level personalization can become an identity graph, not merely “chat memory.” Sensitive inferred attributes deserve first-class governance.

---

## 5.2 Keep Activity

Gemini’s core consumer retention/training control is **Keep Activity**.

When Keep Activity is enabled, Gemini interactions are saved to account activity and may be used to improve Google services, including generative AI. The default consumer auto-delete period is generally **18 months**, with options such as shorter, longer, or no automatic deletion depending on account/region/product state.

When Keep Activity is off, future chats are not saved into normal Gemini Apps Activity and are not used to train Google’s AI models absent exceptions such as feedback. Google still retains certain chats temporarily, currently around **72 hours**, for service/safety purposes.

Source:
- https://support.google.com/gemini/answer/13594961

---

## 5.3 Temporary Chat

Gemini Temporary Chat is not used for normal model training but still has a temporary service-retention period, currently around 72 hours.

Source:
- https://support.google.com/gemini/answer/13594961

**Product lesson:** label the mode by its actual guarantees: “not in normal history, no training, retained up to X hours,” not just “temporary.”

---

## 5.4 Human review

Google explicitly states that subsets of consumer Gemini data may be reviewed by trained human reviewers/service providers.

Human-reviewed copies can be disconnected from the user’s account and retained separately, potentially for up to **three years**, meaning deletion from visible Gemini activity does not necessarily remove already separated review copies.

Source:
- https://support.google.com/gemini/answer/13594961

**SAC implication:** deletion UX must say whether a downstream copy remains and why.

---

## 5.5 Memory / Personal Intelligence

Google separates personalization into several concepts, including:

- memory of past Gemini chats;
- saved instructions/information;
- Personal Intelligence;
- connected Google-app data.

Personal Intelligence can derive insights about the user, relationships, preferences, people, places, and behavior from connected Google sources.

Sources:
- https://support.google.com/gemini/answer/16598623
- https://support.google.com/gemini/answer/16836988

A particularly important current warning from Google is that eligible Personal Intelligence data from Connected Apps can be used to improve Google services, including generative AI models, subject to applicable settings and privacy-preserving processing.

**SAC implication:** inferred/derived attributes must be governed just like raw source data.

---

## 5.6 Workspace / managed Google accounts

Google Workspace Gemini under qualifying core-service configurations receives different enterprise treatment from consumer Gemini.

Google states that Workspace customer content is not used to train generative AI models outside the customer’s domain without permission and provides admin controls around service availability, retention, data-loss prevention, and auditability.

Sources:
- https://workspace.google.com/security/ai-privacy/
- https://support.google.com/a/answer/15439441

Managed account privacy is therefore a combination of:

- Google’s enterprise data contract;
- organization admin policy;
- feature-level service classification;
- retention/export policy.

---

# 6. Cross-provider comparison

## 6.1 Consumer accounts

| Area | ChatGPT personal | Claude consumer | Gemini consumer |
|---|---|---|---|
| Model improvement | Generally opt-out for personal accounts | Explicit user choice | Tied heavily to Keep Activity / feature settings |
| History | Stored until deleted unless temporary mode | Stored until deleted unless incognito | Account activity with auto-delete controls |
| Private-session mode | Temporary Chat | Incognito | Temporary Chat |
| Cross-chat memory | Saved memory + history-derived personalization | Past-chat search + separate memory | Past-chat memory + Saved Info + Personal Intelligence |
| Connected sources | Apps/connectors, indexed/synced sources | Connectors/MCP/Desktop extensions | Google apps + third-party MCP + device/browser context |
| Human review | Safety/support/feedback and documented operational cases | Restricted ordinary access; feedback/T&S exceptions | Explicit consumer human-review program |
| Organization admin visibility | N/A on personal account | N/A on personal account | N/A on personal account |
| Export/deletion | Chat/account export + privacy portal | Consumer data export/deletion | My Activity/Google account tools |

## 6.2 Managed/business accounts

| Area | OpenAI Business/Enterprise/Edu/API | Anthropic Team/Enterprise/API | Google Workspace Gemini |
|---|---|---|---|
| Generalized training by default | No | No without express permission | Protected from consumer-style training in qualifying core-service use |
| Admin controls | Retention, apps/plugins, roles, audit/compliance | Retention, memory/integrations, compliance | Retention, service access, DLP, audit |
| Admin visibility | Organization may access/control workspace data | Organization export/governance can apply | Workspace administrator policy applies |
| ZDR / custom retention | Available for qualifying configurations | Available for qualifying configurations | Enterprise retention policy varies by Workspace feature |

---

# 7. The most important design patterns found

## 7.1 Good patterns worth copying

### Anthropic: explicit model-improvement choice

Strong because the user must consciously choose rather than discover an opt-out later.

### OpenAI: personalization provenance

Useful because users can inspect memory and increasingly see which sources contributed to personalization.

### Claude: visible retrieval/search behavior

Past-chat search and citations make cross-session retrieval less invisible.

### Google: account activity ledger

Google’s My Activity model is conceptually useful as a chronological record of account-level data use and retention.

### Coding agents: sandbox + approval boundary

Codex and Claude Code both demonstrate that privacy for agents requires runtime capabilities, not only policy text.

---

## 7.2 Common shortcomings

### Fragmented controls

A user may turn off “training” while leaving:

- history enabled;
- memory enabled;
- connectors enabled;
- local transcripts enabled;
- feedback sharing enabled;
- organization retention active.

The user can reasonably think “I opted out” when they only changed one dimension.

### Deletion is non-transitive

Deleting the original source does not always delete:

- derived memory;
- indexed copies;
- human-review copies;
- third-party copies;
- organizational exports;
- local agent logs.

### Persistent connector accumulation

Users connect Gmail, Drive, GitHub, or other services for one task and may forget the permission remains available months later.

### Weak explanation of inference

A system may derive a sensitive attribute without the user explicitly saving it.

### Account-tier confusion

“Paid” does not mean “enterprise privacy.”

Consumer Plus/Pro/Max-style plans are still generally governed by consumer privacy controls. The meaningful privacy shift happens when usage is governed by a business/commercial product and agreement.

---

# 8. Privacy model SAC should adopt

SAC should represent privacy as explicit, purpose-bound permission grants.

A useful conceptual permission tuple is:

```text
(subject,
 data_scope,
 action,
 destination,
 purpose,
 duration,
 retention,
 sensitivity)
```

Example:

```json
{
  "subject": "user_sam",
  "client": "chatgpt_plugin_instance_42",
  "project": "shared_agent_context",
  "data_scope": ["decisions", "architecture", "open_tasks"],
  "action": "read",
  "destination": "openai_chatgpt",
  "purpose": "answer_current_request",
  "duration": "single_request",
  "retention": "provider_policy",
  "sensitivity_max": "internal"
}
```

This is much more expressive than `can_read_project = true`.

---

# 9. Recommended SAC privacy principles

1. **No universal “share my context” switch.** Scope by source, purpose, recipient, and duration.
2. **Least privilege by default.** New clients start with no project context.
3. **Ask before persistence.** A temporary read should not silently become durable memory.
4. **Show the context manifest before transfer.** Users should know what will leave SAC.
5. **Separate read and write grants.** Retrieval permission must not imply permission to modify project state.
6. **Treat provider memory as a separate external store.** SAC should not assume it can delete or control it.
7. **Track derived data lineage.** Inferences must point to sources.
8. **Cascading deletion.** Deleting source data should identify derived memories/indexes/caches affected.
9. **Time-bound grants.** Prefer “once / session / project / persistent” over permanent access.
10. **Sensitive-data classes.** Credentials, financial data, health data, identity data, and private messages require stronger handling.
11. **No secrets in model context by default.** Credentials belong in secure tool/token channels, not prompts.
12. **Audit every sensitive read/write.** The model must not be the audit source of truth.
13. **Privacy receipt after each sensitive operation.** Record what was read, sent, stored, and changed.
14. **Provider policy registry.** Encode differences across personal, business, enterprise, API, local, and cloud-agent environments.
15. **Revocation must be first-class.** A user should be able to revoke a client or data source immediately.

---

# 10. The privacy receipt SAC should eventually expose

After an interaction, a user should be able to ask:

> What information did this agent use?

and get an authoritative record like:

```json
{
  "request_id": "req_123",
  "agent": "claude_code_sam",
  "provider": "anthropic",
  "project": "shared-agent-context",
  "read": [
    "mem_auth_decision",
    "mem_context_compiler_design"
  ],
  "sent_to_model": [
    "rendered_context_bundle_abc"
  ],
  "external_tools": [],
  "writes": [
    "mem_implementation_note_992"
  ],
  "new_derived_memories": [],
  "local_retention": "client-specific",
  "provider_retention": "see provider policy snapshot",
  "training_eligibility": false,
  "timestamp": "2026-08-12T..."
}
```

This should be generated from SAC’s own audit pipeline, not from the model’s self-report.

---

# 11. Sources

## OpenAI

- Privacy policy: https://openai.com/policies/row-privacy-policy/
- Security and privacy: https://openai.com/security-and-privacy/
- Enterprise privacy: https://openai.com/enterprise-privacy/
- Data Controls FAQ: https://help.openai.com/en/articles/7730893-data-controls-faq
- Disable training while retaining history: https://help.openai.com/en/articles/8983130-what-if-i-want-to-keep-my-history-on-but-disable-model-training
- Memory FAQ: https://help.openai.com/articles/8590148-memory-faq
- Google app data controls: https://help.openai.com/en/articles/10408842
- Codex with ChatGPT plans: https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- How data is used to improve models: https://help.openai.com/en/articles/5722486-how-your-data-is-used-to-improve-model-performance
- API data controls: https://developers.openai.com/api/docs/guides/your-data
- Codex agent approvals/security: https://learn.chatgpt.com/docs/agent-approvals-security

## Anthropic

- Privacy policy: https://www.anthropic.com/legal/privacy
- Consumer privacy/model-improvement choice: https://www.anthropic.com/news/updates-to-our-consumer-terms
- Model-improvement settings: https://privacy.anthropic.com/en/articles/12109829-how-do-i-change-my-model-improvement-privacy-settings
- Consumer retention: https://privacy.anthropic.com/en/articles/10023548-how-long-do-you-store-personal-data
- Model-training FAQ: https://privacy.anthropic.com/en/articles/10023580-is-my-data-used-for-model-training
- Memory and past-chat search: https://support.anthropic.com/en/articles/11817273-using-claude-s-chat-search-and-memory-to-build-on-previous-context
- Claude Code data usage: https://code.claude.com/docs/en/data-usage
- Claude Code settings: https://code.claude.com/docs/en/settings
- API/ZDR: https://docs.anthropic.com/en/docs/build-with-claude/zero-data-retention

## Google

- Gemini Apps Privacy Hub: https://support.google.com/gemini/answer/13594961
- Gemini personalization overview: https://support.google.com/gemini/answer/16598623
- Personal Intelligence / Connected Apps: https://support.google.com/gemini/answer/16836988
- Workspace AI privacy/security: https://workspace.google.com/security/ai-privacy/
- Workspace Gemini administration: https://support.google.com/a/answer/15439441

---

# 12. Bottom line for Shared Agent Context

The current market proves that long-term AI context is valuable, but it also exposes a product gap:

**Users do not have one coherent, inspectable system showing exactly what personal/project context is available to which AI, for what purpose, for how long, and where it goes afterward.**

SAC should make that boundary the product itself.

The strongest privacy architecture is not “trust us with all your memory.” It is:

> **Store context independently, expose the minimum necessary context to each model or agent, make the transfer inspectable, preserve provenance, and make every grant revocable.**

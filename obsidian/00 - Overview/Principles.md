# Shared Agent Context: Product Principles

These principles should constrain product and architecture decisions as the project evolves.

## 1. The Project Owns the Memory

Shared project knowledge should not belong to whichever model happened to generate it.

Users should be able to change models and clients without losing the project's accumulated understanding.

## 2. Models Are Clients, Not the Database

Models reason over context. They should not be treated as the canonical store of project truth.

The shared context layer remains independent from inference providers.

## 3. Share Knowledge, Not Entire Conversations

A conversation contains brainstorming, mistakes, private details, temporary reasoning, and irrelevant material.

SAC should prefer durable knowledge objects such as decisions, requirements, constraints, tasks, and verified facts.

## 4. Humans Must Be Able to Inspect the Brain

Invisible memory is dangerous in collaborative systems.

Users should be able to answer:

- What does the project currently believe?
- Why does it believe that?
- Who or what added it?
- What changed?
- Can I correct it?

## 5. Provenance Is Part of the Data

Source information is not optional metadata.

A claim from an agent inference is fundamentally different from an explicit decision made by the project owner.

## 6. Context Must Be Relevant

More context is not automatically better.

SAC should optimize for the minimum sufficient context that allows an agent to perform the current task correctly.

## 7. Uncertainty Should Survive Retrieval

Do not turn uncertain statements into certain facts merely because they entered the memory system.

Hypotheses, proposals, observations, and decisions must remain distinguishable.

## 8. Contradictions Are Data

When sources disagree, do not silently choose one unless authority and temporal information make the resolution clear.

Surface unresolved conflicts.

## 9. Project Truth Is Temporal

Projects change.

The system must support "this used to be true" without presenting old state as current state.

## 10. Permissions Are Enforced Before Inference

Sensitive context must be filtered before it is sent to a model.

Do not rely on prompting a model not to reveal information it should never have received.

## 11. Interoperability Over Lock-In

Use open interfaces where practical.

Support APIs and protocols that allow independent clients to participate without becoming tightly coupled to SAC's UI.

## 12. Explicit First, Automatic Later

For the MVP, explicit memory writes are preferable to unreliable automatic surveillance of every interaction.

Earn the right to automate memory creation by first proving that the underlying shared-memory primitive is useful and trustworthy.

## 13. Preserve User Agency

Users should be able to:

- see memories
- edit/correct memories
- delete memories
- control integrations
- revoke agents
- leave projects
- export project knowledge

## 14. Do Not Become Another Monolithic Workspace

SAC should connect existing tools rather than requiring teams to abandon them.

The project brain is infrastructure between work surfaces.

## 15. Optimize for the Handoff

The signature moment is one agent knowing something useful because another collaborator's agent learned it earlier.

Product decisions should repeatedly be tested against whether they make that handoff faster, safer, and more accurate.

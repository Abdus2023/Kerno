---
name: process-kernel
description: Convert a conversation or repeated methodology into a reusable, governed process model, preserving stages, decisions, evidence, gates, failures, state, and outputs.
---

# Process Kernel

## Purpose
Turn a completed workflow into an explicit, reusable process artifact rather than relying on conversation memory.

## Inputs
- transcript or workflow description
- target output form
- known constraints
- available tools
- evidence requirements
- desired reuse boundary

## Outputs
- process model
- stage/step inventory
- decision and gate model
- evidence ledger
- failure model
- reusable tool contracts
- reusable skill specifications
- continuation state

## Procedure
1. Acquire the complete available transcript/workflow.
2. Segment it into meaningful stages.
3. Label observations, actions, decisions, assumptions, outputs, and failures.
4. Normalize repeated operations into process steps.
5. Separate deterministic operations from judgment.
6. Identify inputs, prerequisites, outputs, dependencies, and constraints.
7. Convert externally verifiable claims into evidence requirements.
8. Define gates and safe-stop conditions.
9. Convert deterministic operations into tool contracts.
10. Convert judgment procedures into reusable skills.
11. Remove hidden conversational state.
12. Bind every reusable artifact to explicit inputs and outputs.
13. Generate a machine-readable process manifest.
14. Validate schemas and cross-references.
15. Run negative/conformance checks.
16. Produce a release-ready inventory.

## Verification gates
- G0 transcript/workflow acquired
- G1 stages extracted
- G2 deterministic vs judgment boundary explicit
- G3 evidence requirements explicit
- G4 failure modes explicit
- G5 tool contracts schema-valid
- G6 skills independently invocable
- G7 no hidden conversation state
- G8 conformance fixtures cover normative behavior
- G9 release manifest binds generated artifacts

## Evidence policy
NO EVIDENCE -> NO VERIFIED CLAIM.

Maintain:
OBSERVED != DERIVED != VERIFIED != EXECUTED.

Repository inspection is evidence of repository state, not proof that CI or another external authority executed something.

## Failure modes
Stop or downgrade status on incomplete transcript, ambiguous stages, undocumented dependency, hidden state, missing evidence, contradictory requirements, schema-invalid artifact, unbound tool contract, or skill requiring prior conversation memory.

Use:
PROVED / ARGUMENT / CONJECTURE / OPEN
and:
VERIFIED / PARTIALLY_VERIFIED / PROVISIONAL / BLOCKED.

## Continuation/state rules
Persist a continuation artifact containing current phase, completed stages, unresolved items, next action, and evidence references. Never use "continue as before" as an implicit dependency.

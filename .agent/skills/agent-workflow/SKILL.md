---
name: agent-workflow
description: Orchestrate the reusable Kerno verification skills as a deterministic state machine from repository snapshot through release gate.
---

# Agent Workflow

## Purpose

Run the complete reusable workflow without relying on conversational memory.

## Workflow

```
SNAPSHOT
  ↓
AUDIT
  ↓
EVIDENCE
  ↓
VERIFY
  ↓
TRUST DESIGN
  ↓
PROTOCOL
  ↓
FEDERATION
  ↓
MARKET
  ↓
ENGINEERING PLAN
  ↓
RELEASE GATE
```

Optional design stages may be skipped when the task does not require them, but snapshot, audit, evidence, verification, engineering plan, and release gate remain explicit.

## State artifact

Persist:
```
.agent/state/continuation.json
```

Never rely on previous chat messages as state.

## Stage contract

Every stage records:
- stage ID
- input artifact digest
- output artifact digest
- status
- evidence IDs
- blockers
- timestamp
- tool/authority

## Transition rule

A stage can transition to COMPLETE only when its declared completion condition is satisfied.

A stage can transition to BLOCKED when required evidence is unavailable.

BLOCKED must not be silently converted to COMPLETE.

## Release gate

The release gate checks:
1. exact repository snapshot
2. exact implementation artifact
3. verification evidence
4. unresolved blockers
5. conformance/test evidence where required

## Anti-patterns

Never:
- infer CI success from source inspection
- infer runtime behavior from documentation alone
- inherit a previous conversation's unrecorded state
- call an implementation "verified" because it looks correct
- mix evidence from multiple commits without recording transitions


## Adapters

Reference implementations live under `.agent/adapters/`. They are deliberately authority-explicit. `repository-snapshot` binds the run to a Git object; `repo-audit` observes repository contents; `evidence-record` normalizes observations; `verification-gate` refuses a PASS when evidence is absent. These local adapters do not constitute CI or remote execution evidence.

---
name: continuation-controller
description: Continue a long-running engineering investigation deterministically from explicit state rather than hidden conversational memory.
---

# Continuation Controller

## Purpose

Replace repeated "Continue" turns with an explicit, resumable investigation state.

## Inputs

- objective
- current phase
- completed stages
- open questions
- evidence ledger
- blockers
- next actions
- repository snapshot

## State

```json
{
  "schema": "agent.continuation-state/1",
  "objective": "...",
  "phase": "VERIFY",
  "snapshot": {
    "repository": "owner/name",
    "ref": "...",
    "commit": "...",
    "tree": "..."
  },
  "completed": [],
  "open": [],
  "blocked": [],
  "next": [],
  "evidence_digest": "sha256:..."
}
```

## Procedure

1. Validate snapshot identity.
2. Read completed stages.
3. Re-check blockers.
4. Select the highest-priority unresolved action.
5. Execute only that action.
6. append evidence.
7. update status.
8. recompute next actions.
9. stop when the release gate is reached or evidence is blocked.

## Continuation invariant

Never infer that a previous stage succeeded merely because it was discussed.

A stage is complete only when its completion evidence is recorded.

## Safe stopping

Stop with BLOCKED when required evidence is unavailable.

Do not continue by inventing a plausible result.

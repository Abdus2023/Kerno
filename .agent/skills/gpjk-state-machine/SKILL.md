---
name: gpjk-state-machine
description: Validate GPJK execution and step state transitions as explicit finite-state machines with no terminal-state resurrection.
---

# GPJK State Machine

## Purpose
Prevent ambiguous execution histories by enforcing explicit lifecycle transitions.

## Inputs
- current execution or step state
- proposed transition
- actor/context
- event ledger

## Outputs
- accepted or rejected transition
- normalized event
- transition diagnostic

## Procedure
1. Identify execution versus step state machine.
2. Validate the current state.
3. Validate the proposed transition.
4. Reject terminal-to-running resurrection.
5. Record accepted transitions as events.
6. Preserve rejected attempts as diagnostics where policy requires.
7. Ensure retries use distinct attempts.

## Core transitions
Step: `pending -> ready|cancelled`; `ready -> running|skipped`; `running -> completed|failed|cancelled`.
Execution: `pending -> running`; `running -> completed|failed|cancelled`.

## Gates
S1 state vocabulary; S2 transition validity; S3 attempt identity; S4 event recording.

## Failure modes
Illegal transition, duplicate terminal transition, attempt collision, state/event divergence, implicit retry mutation.

## Evidence policy
A recorded transition is evidence of a recorded state change; it is not by itself proof that the underlying external action succeeded.

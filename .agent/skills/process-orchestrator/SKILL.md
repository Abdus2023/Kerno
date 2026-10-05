---
name: process-orchestrator
description: Orchestrate transcript extraction, process specification, skill creation, tool-contract generation, conformance, evidence, and release as one explicit state machine.
---

# Process Orchestrator

## Purpose
Provide one reusable entry point for the full methodology.

## Pipeline
ACQUIRE -> LABEL -> EXTRACT -> MODEL -> SPECIFY -> DECOMPOSE -> CONTRACT -> TEST -> VERIFY -> PACKAGE -> RELEASE

## Required artifacts
- source snapshot
- labeled transcript
- process model
- semantic rule inventory
- skill inventory
- tool inventory
- conformance manifest/results
- evidence bundle
- continuation state
- release manifest

## Procedure
1. Acquire source material.
2. Freeze the source boundary.
3. Label transcript/process sections.
4. Extract reusable operations.
5. Model inputs, outputs, constraints, dependencies, and decisions.
6. Specify the process in JSON.
7. Apply skill-creator to judgment workflows.
8. Convert deterministic operations to tool contracts.
9. Generate conformance fixtures.
10. Run verification gates.
11. Package artifacts.
12. Release only after the release gate.

## Safe-stop rule
If a gate lacks required evidence, stop at that gate and emit BLOCKED or PROVISIONAL status.

## Continuation
Persist state after each major phase. A resumed run consumes the state artifact rather than relying on conversation memory.

## Quality rule
The orchestrator coordinates skills; it does not replace their individual contracts.

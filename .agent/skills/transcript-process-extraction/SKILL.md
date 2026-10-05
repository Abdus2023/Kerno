---
name: transcript-process-extraction
description: Extract a reusable process from a transcript by consistently labeling sections, turns, operations, decisions, evidence, and outputs.
---

# Transcript Process Extraction

## Purpose
Transform a conversation history into an auditable process specification.

## Inputs
- transcript
- optional section labels
- target process scope
- known exclusions

## Outputs
- labeled transcript
- stage inventory
- operation inventory
- decision inventory
- evidence ledger
- process draft

## Procedure
1. Preserve transcript order.
2. Assign stable section IDs.
3. Label each section: INPUT, OBSERVATION, ANALYSIS, DECISION, ACTION, TOOL_CALL, RESULT, GATE, OUTPUT, OPEN.
4. Extract explicit user requirements separately from inferred requirements.
5. Identify repeated operations.
6. Collapse repetition into reusable process steps.
7. Preserve uncertainty and failed attempts.
8. Link outputs to the steps that produced them.
9. Mark claims by evidence status.
10. Emit a process draft and unresolved-items list.

## Gates
TG1 ordering preserved
TG2 explicit requirements separated from inference
TG3 all reusable operations have stable IDs
TG4 evidence references retained
TG5 unresolved ambiguity is not silently resolved

## Failure modes
Missing transcript segment, duplicate section identity, inferred requirement presented as explicit, result without provenance, hidden context dependency.

## Evidence policy
Transcript content is source evidence for what was discussed. It is not automatically evidence that an external action occurred.

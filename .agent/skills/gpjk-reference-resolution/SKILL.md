---
name: gpjk-reference-resolution
description: Resolve GPJK references deterministically while preserving VALUE, NULL, MISSING, and UNRESOLVED as distinct outcomes.
---

# GPJK Reference Resolution

## Purpose
Provide a deterministic reference-resolution boundary for governed process evaluation.

## Inputs
- reference string
- process/execution/evidence context
- namespace rules

## Outputs
- resolution status
- resolved value when available
- resolution trace

## Procedure
1. Parse `gpjk:<scope>:<path>`.
2. Validate syntax.
3. Identify scope and path.
4. Locate the target.
5. If the target exists with explicit null, return NULL.
6. If it exists with a value, return VALUE.
7. If the namespace is valid but the member is absent, return MISSING.
8. If resolution cannot be performed, return UNRESOLVED.
9. Record the resolution trace.

## Gates
RR1 syntax; RR2 scope; RR3 target; RR4 null/missing distinction; RR5 traceability.

## Failure modes
Malformed reference, invalid scope, ambiguous target, silent fallback, alias substitution, unresolved reference treated as a value.

## Evidence policy
Resolution output is an interpretation result, not evidence that the referenced external fact is true.

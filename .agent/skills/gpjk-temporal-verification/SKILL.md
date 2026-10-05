---
name: gpjk-temporal-verification
description: Verify temporal claims using occurrence, recording, validity, and evaluation times without confusing timeout with external failure.
---

# GPJK Temporal Verification

## Purpose
Make time semantics explicit and reproducible.

## Inputs
- process
- policy
- execution
- evidence
- temporal context

## Outputs
- temporal evaluation
- validity/deadline results
- temporal trace

## Procedure
1. Distinguish occurrence, recording, validity, and evaluation time.
2. Use recorded times for historical verification.
3. Bind time zones and calendars when domain profiles require them.
4. Represent precision and uncertainty.
5. Evaluate deadlines and validity intervals.
6. Treat timeout as a temporal observation, not proof of external non-occurrence.
7. Require confirmation evidence for material external effects.
8. Preserve late results as reconciliation events.

## Gates
T1 time type; T2 historical binding; T3 uncertainty; T4 deadline semantics; T5 late-result handling.

## Failure modes
Verifier-current-time substitution, clock skew ignored, timeout interpreted as failure, DST/calendar assumptions hidden.

## Evidence policy
A timestamp is evidence of a recorded time assertion; its accuracy requires an appropriate trust basis.

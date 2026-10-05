---
name: process-conformance
description: Test a process specification, runtime, verifier, or generated skill against explicit semantic, structural, negative, and adversarial contracts.
---

# Process Conformance

## Purpose
Turn process rules into conformance fixtures and classify observed results without overstating evidence.

## Inputs
- process specification
- schemas
- semantic rules
- implementation under test
- conformance manifest

## Outputs
- conformance results
- normalized results
- failures
- evidence bundle
- certification input

## Procedure
1. Load normative rules.
2. Map every rule to one or more fixtures.
3. Include positive and negative fixtures.
4. Test references: VALUE, NULL, MISSING, UNRESOLVED.
5. Test three-valued expressions.
6. Test state transitions.
7. Test dependency conflicts and cycles.
8. Test evidence absence and contradiction.
9. Test authorization and verification separation.
10. Test temporal uncertainty.
11. Test integrity and replay where profiles apply.
12. Test import without execution.
13. Normalize implementation-specific diagnostics.
14. Compare independent implementations when available.
15. Record exact implementation, version, suite, and environment.
16. Refuse certification when material failures remain.

## Gates
C1 structural
C2 semantic
C3 state/reference
C4 evidence/verification
C5 security/adversarial
C6 interchange
C7 reproducibility

## Failure modes
Fixture ambiguity, implementation-specific oracle, missing negative coverage, environment-dependent result, stale suite, unsupported required profile.

## Evidence policy
A passing local test is evidence of that local test execution. It is not evidence of remote CI execution unless the remote authority provides execution evidence.

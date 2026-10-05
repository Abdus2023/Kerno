---
name: repo-engineering-plan
description: Turn verified architecture findings into a repo-ready implementation plan with boundaries, files, interfaces, tests, gates, and release criteria.
---

# Repo Engineering Plan

## Inputs

- verified architecture findings
- repository snapshot
- existing tree
- constraints
- target milestone

## Outputs

- implementation phases
- repository tree changes
- interfaces
- invariants
- tests
- conformance vectors
- CI/release gates
- migration plan
- explicit blockers

## Planning order

```
Definition
 -> Existence
 -> Construction
 -> Stability
 -> Interpretation
```

Do not implement an undefined concept.

## Freeze rule

Before implementation:
- freeze scope
- freeze interfaces
- freeze invariants
- freeze acceptance tests

Then:

```
freeze
 -> formalize
 -> implement
 -> test
 -> release gate
 -> tag
```

## Every component needs

- purpose
- inputs
- outputs
- authority
- trust boundary
- failure modes
- API
- tests
- evidence required for release

## Evidence rule

Local inspection is evidence for diagnosis.

It is not evidence that CI, remote execution, hardware attestation, or production deployment occurred.

## Release gate

A release claim must identify the exact artifact that was verified.

> The thing that was verified is exactly the thing that was released.

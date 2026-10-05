---
name: repo-audit-adapter
description: Execute deterministic static repository inventory and negative-search checks while preserving exact snapshot scope and explicit limitations.
---

# Repository Audit Adapter

## Input
- repository
- ref
- exact snapshot commit
- repository file inventory
- optional file contents

## Output
Produce an agent.repo-audit/1 result containing findings, evidence records, and limitations.

## Required checks
1. Repository identity.
2. Structural inventory.
3. CI/workflow presence.
4. Test surface.
5. Security/authentication indicators.
6. Verification/authority indicators.
7. Negative searches for TODO/FIXME, bypasses, disabled checks, and unsafe surfaces.

## Evidence rule
Every observation becomes an evidence record scoped to the exact snapshot commit.
Negative search results use explicit NOT_FOUND; they must not be represented as an assertion that the searched condition is impossible.

## Execution boundary
This adapter proves only static inspection.
It does NOT prove CI executed, tests passed, runtime behavior, deployment success, hardware behavior, or security in an environment not inspected.
Those require their own authorities and evidence.

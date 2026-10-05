---
name: adapter-contracts
description: Define executable adapters for repository snapshots, evidence records, and verification gates without fabricating assurance.
---

# Adapter Contracts

Adapters are evidence-producing authorities. They preserve snapshot scope.

## Repository snapshot
Required: repository, ref, exact commit, exact tree, observation source.
Missing commit or tree is BLOCKED.

## Evidence record
Every record binds source, locator, scope, observation, snapshot commit, extraction method, and limitations.
Negative observations are explicit states, never null.

## Verification gate
A claim is PASS only when every referenced evidence record exists and satisfies the requested status.
VERIFIED cannot be inferred from OBSERVED, DERIVED, PARTIAL, or PROVISIONAL.
Contradiction, mismatch, or stale evidence cannot silently pass.

## Authority rule
The adapter reports only what its declared authority established. It does not upgrade external execution claims without execution evidence.

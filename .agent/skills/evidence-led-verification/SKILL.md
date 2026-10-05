---
name: evidence-led-verification
description: Convert repository observations and execution artifacts into a structured evidence ledger and conservative verification decisions.
---

# Evidence-Led Verification

## Purpose

Make every important claim traceable to a bounded evidence object.

## Inputs

- claim set
- repository snapshot
- source artifacts
- test/CI artifacts
- external attestations when available

## Outputs

- normalized evidence records
- claim-to-evidence matrix
- verification decisions
- gaps and contradictions
- release evidence summary

## Evidence model

Represent evidence as:

```
EvidenceRecord = Normalize(Extract(Source, Context, Scope))
```

Each record should include:
- evidence ID
- source type
- source locator
- snapshot/ref
- scope
- observation
- extraction method
- digest when available
- status
- limitations

## Status values

Use explicit negative states:

- NOT_FOUND
- NOT_PRESENT
- NOT_REACHABLE
- NOT_OBSERVABLE
- PARTIAL
- STALE
- MISMATCH
- CONTRADICTED

Do not encode these as null.

## Claim matrix

For every claim:

| Claim | Required evidence | Evidence | Status | Reason |
|---|---|---|---|---|

A claim is VERIFIED only when the evidence satisfies the required scope.

## Core rule

```
NO EVIDENCE -> NO VERIFIED CLAIM
```

## Independence

If a component verifies itself, record that as a trust-boundary limitation.

Prefer:
- independent verifier
- immutable receipt
- external CI result
- signed attestation
- reproducible artifact

## Contradiction handling

Never average contradictory evidence into confidence.

Record:
1. both observations
2. scopes
3. timestamps
4. authority
5. contradiction
6. resolution policy

## Release gate

A release claim requires:
- exact artifact identity
- exact verification scope
- sufficient evidence
- reproducible or attributable verification
- no unresolved blocker affecting the claim

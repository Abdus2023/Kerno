---
name: evidence-ledger
description: Build an append-only evidence ledger linking claims, observations, artifacts, provenance, integrity, and verification scope.
---

# Evidence Ledger

## Purpose
Turn evidence into explicit, traceable records without treating evidence presence as proof of sufficiency.

## Inputs
- process/execution artifacts
- claims or assertions
- observations
- evidence sources
- integrity metadata
- verification scope

## Outputs
- evidence ledger
- claim-to-evidence map
- provenance graph
- evidence status report

## Procedure
1. Assign stable evidence IDs.
2. Record source, producer, occurrence/recording time, and scope.
3. Bind evidence to the execution or artifact it concerns.
4. Classify evidence as observed, derived, verified, or annotated.
5. Record derivation with `derivedFrom`.
6. Record integrity information when available.
7. Link evidence to claims using `supports`.
8. Detect missing, contradictory, stale, or mismatched evidence.
9. Preserve conflicting evidence rather than overwriting it.
10. Emit a sufficiency judgment separately from evidence acceptance.

## Gates
E1 identity; E2 provenance; E3 scope; E4 integrity; E5 claim linkage; E6 contradiction handling.

## Failure modes
Missing provenance, duplicate IDs, scope mismatch, unsupported derivation, integrity failure, contradictory evidence silently discarded.

## Evidence policy
Evidence acceptance != evidence sufficiency. Missing evidence is not automatically invalid evidence.

## Continuation
Persist the ledger and unresolved evidence references; never rely on conversational memory.

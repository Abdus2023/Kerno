---
name: gpjk-governance
description: Govern GPJK Core, profiles, extensions, registries, conformance suites, and releases without creating historical ambiguity.
---

# GPJK Governance

## Purpose
Provide explicit change control for a process language whose historical artifacts must remain interpretable.

## Inputs
- change proposal
- affected specification/profile/schema
- compatibility analysis
- security review
- conformance impact

## Outputs
- governance decision
- version/change classification
- updated registry or release record

## Procedure
1. Freeze the proposed change.
2. Identify affected normative semantics.
3. Review compatibility and historical interpretation.
4. Review security and conformance impact.
5. Classify as additive, corrective, breaking, deprecated, or withdrawn.
6. Assign an immutable version.
7. Update registries append-only.
8. Add or update conformance fixtures.
9. Preserve old versions for historical verification.
10. Release only after approval gates pass.

## Gates
G1 semantic review; G2 compatibility; G3 security; G4 conformance; G5 release approval; G6 archive.

## Failure modes
Semantic drift, identifier reuse, silent version mutation, historical artifact reinterpretation, registry overwrite, missing conformance coverage.

## Evidence policy
A governance decision is a scoped judgment; it does not establish runtime conformance unless conformance evidence exists.

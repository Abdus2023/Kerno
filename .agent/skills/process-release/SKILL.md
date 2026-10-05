---
name: process-release
description: Freeze, package, integrity-bind, verify, and release a reusable process, skill, and tool bundle without losing version or provenance information.
---

# Process Release

## Purpose
Create a reproducible release boundary around process specifications, skills, tools, tests, and evidence.

## Inputs
- frozen artifacts
- schemas
- skills
- tools
- conformance results
- governance decision
- release version

## Outputs
- release manifest
- integrity inventory
- conformance report
- release gate result

## Procedure
1. Freeze source inputs.
2. Inventory generated artifacts.
3. Validate schemas.
4. Validate skill frontmatter and contracts.
5. Validate tool contracts.
6. Validate cross-references.
7. Run conformance and negative tests.
8. Record evidence and execution authority.
9. Compute artifact digests where required.
10. Generate release manifest.
11. Bind exact versions.
12. Verify the manifest from a clean context.
13. Publish only if all mandatory gates pass.
14. Preserve historical release metadata.

## Gates
R1 freeze
R2 inventory
R3 schema validation
R4 skill/tool validation
R5 conformance
R6 evidence/integrity
R7 release manifest
R8 independent verification

## Failure modes
Modified artifact after freeze, missing manifest member, version mismatch, unverified execution claim, incomplete evidence, unresolved dependency.

## Evidence policy
Release status is a judgment over the declared scope. Never label a release verified merely because files exist.

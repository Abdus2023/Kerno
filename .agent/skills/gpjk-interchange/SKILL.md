---
name: gpjk-interchange
description: Import and export governed GPJK packages while preserving identity, versions, dependencies, integrity, and the rule that import never executes.
---

# GPJK Interchange

## Purpose
Move process artifacts between systems without changing their semantic identity or causing execution as a side effect.

## Inputs
- package
- manifest
- dependency registry
- integrity/signature material

## Outputs
- validated import/export result
- dependency resolution report
- package manifest

## Procedure
1. Receive package.
2. Parse and validate manifest and artifacts.
3. Resolve dependencies by exact version.
4. Verify integrity and signatures when applicable.
5. Resolve references.
6. Reject unsupported required extensions.
7. Register/import artifacts.
8. Never execute imported process as part of import.
9. Export with identity, versions, references, extensions, and integrity bindings intact.

## Gates
I1 parse; I2 schema; I3 dependencies; I4 integrity; I5 references; I6 no-execution; I7 round-trip identity.

## Failure modes
Missing dependency, ambiguous dependency, version conflict, integrity failure, unsupported required extension, accidental execution.

## Evidence policy
Successful import proves package acceptance under the importer scope; it does not prove the package's process was executed.

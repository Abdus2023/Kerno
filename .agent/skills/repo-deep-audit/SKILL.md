---
name: repo-deep-audit
description: Deeply inspect a repository, reconstruct its architecture and execution model, test claims against source evidence, and produce a bounded verification report.
---

# Repository Deep Audit

## Purpose

Perform evidence-led repository research without confusing source inspection with runtime execution.

## Inputs

- repository URL or owner/name
- ref/commit to freeze
- audit questions
- optional paths or subsystems
- optional external requirements

## Outputs

- frozen repository snapshot
- repository map
- execution/data/control-flow map
- evidence ledger
- findings classified as PROVED/ARGUMENT/CONJECTURE/OPEN
- verification status
- unresolved gaps
- recommended next checks

## Procedure

### 1. Freeze

Record:
- repository
- branch/ref
- commit SHA
- tree SHA when available
- parent SHA
- observed timestamp
- tool/source used

Do not silently mix revisions.

### 2. Inventory

Inspect:
- top-level tree
- manifests
- CI
- tests
- runtime entry points
- security boundaries
- configuration
- documentation
- examples
- generated artifacts

### 3. Trace

Construct:
- control flow
- data flow
- authority flow
- persistence flow
- failure/recovery flow

Prefer concrete symbols and file paths.

### 4. Verify claims

For each important claim ask:

1. What exactly is being claimed?
2. What source artifact supports it?
3. Is the artifact normative, descriptive, generated, or incidental?
4. Is there an execution artifact?
5. Can the claimed behavior be reproduced?
6. Is the scope identical to the claim?

### 5. Negative search

Actively search for:
- TODO/FIXME
- bypasses
- fallback paths
- disabled checks
- untested branches
- stale documentation
- duplicate authorities
- mutable verifier configuration
- missing policy enforcement
- claims unsupported by tests

### 6. Classify

Use:
- PROVED: directly established by sufficient evidence
- ARGUMENT: strong architectural reasoning
- CONJECTURE: plausible but unestablished
- OPEN: unresolved
- VERIFIED: execution evidence exists
- PARTIALLY_VERIFIED: only part of scope is verified
- PROVISIONAL: evidence is insufficient for final status
- BLOCKED: required evidence cannot currently be obtained

## Verification gates

A finding may be marked VERIFIED only if:
- the object under test is identified exactly
- the scope is explicit
- the evidence source is authoritative for that claim
- the evidence is reproducible or independently attributable

## Failure modes

Stop and mark BLOCKED when:
- revision identity cannot be established
- requested evidence is inaccessible
- remote CI state is not observable
- the claim requires execution but only source inspection is available

Do not fill missing evidence with inference.

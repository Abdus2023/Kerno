# Kerno .agent reusable process system

This directory packages the reusable methodology developed across the process-specification, transcript-analysis, verification, runtime-trust, protocol, governance, and release work.

## Core rule

> NO EVIDENCE -> NO VERIFIED CLAIM.

The system separates:
- transcript observation from process extraction
- deterministic operations from judgment
- process definition from execution
- evidence from verification
- authorization from occurrence
- local inspection from execution authority
- implementation behavior from normative semantics
- current evaluation from historical verification

## End-to-end process

`ACQUIRE -> LABEL -> EXTRACT -> MODEL -> SPECIFY -> DECOMPOSE -> CONTRACT -> TEST -> VERIFY -> PACKAGE -> RELEASE`

## Skill graph

```
skill-creator
      |
      +--> transcript-process-extraction
      |          |
      |          +--> process-specification
      |
      +--> process-kernel
      |          |
      |          +--> process-orchestrator
      |
      +--> process-conformance
      |
      +--> process-release
      |
      +--> existing repository / runtime / evidence skills
```

## Reusable skills

| Skill | Role |
|---|---|
| `skill-creator` | Convert proven workflows into reusable skills |
| `process-kernel` | General workflow-to-process kernel |
| `transcript-process-extraction` | Label and extract processes from transcripts |
| `process-specification` | Build schema-first process definitions |
| `process-orchestrator` | Coordinate the complete pipeline |
| `process-conformance` | Generate and evaluate conformance tests |
| `process-release` | Freeze, package, verify, and release process bundles |
| `evidence-ledger` | Build claim/evidence/provenance ledgers |
| `gpjk-reference-resolution` | Resolve VALUE/NULL/MISSING/UNRESOLVED references |
| `gpjk-expression-evaluation` | Evaluate strict three-valued GPJK expressions |
| `gpjk-state-machine` | Enforce execution and step lifecycle transitions |
| `gpjk-authorization` | Evaluate authority separately from occurrence and verification |
| `gpjk-temporal-verification` | Verify explicit temporal semantics |
| `gpjk-interchange` | Import/export packages without implicit execution |
| `gpjk-governance` | Govern semantic evolution and historical compatibility |
| `repo-deep-audit` | Deep repository inspection |
| `evidence-led-verification` | Evidence and claim verification |
| `runtime-trust-design` | Verifiable runtime architecture |
| `protocol-freeze` | Protocol and conformance design |
| `federation-design` | Cross-domain trust and delegation |
| `market-design` | Assurance-aware execution market |
| `continuation-controller` | Explicit continuation state |
| `repo-engineering-plan` | Repo-ready engineering plans |

## Semantic process skills

The GPJK layer now has explicit reusable boundaries for evidence, references, expressions, state, authorization, time, interchange, and governance. These skills are intentionally implementation-neutral; concrete runtimes must satisfy their contracts and provide execution evidence.

## Tool contracts

The `tools/` directory contains machine-readable contracts for:
- process models
- process decomposition
- reusable skills
- reusable tools
- conformance manifests
- release manifests
- repository/evidence/verification operations

These are contracts, not proof that an implementation executed them.

## Required labels

Use:
- PROVED
- ARGUMENT
- CONJECTURE
- OPEN
- VERIFIED
- PARTIALLY_VERIFIED
- PROVISIONAL
- BLOCKED

## State discipline

Never depend on phrases such as "continue as before" or undocumented conversation state.

Persist:
`snapshot + process model + evidence ledger + decision record + verification report + continuation state`.

## Release discipline

`freeze -> formalize -> implement -> test -> release gate -> tag`

The generated bundle must be independently inspectable and version-bound.

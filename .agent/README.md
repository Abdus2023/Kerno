# Kerno .agent reusable verification system

This directory packages the workflow developed during the Kerno → Arena VAR work as reusable agent skills and deterministic tool contracts.

## Design rule

> NO EVIDENCE → NO VERIFIED CLAIM.

The system separates:
- discovery from verification
- observation from inference
- architecture from implementation
- local inspection from execution evidence
- execution truth from semantic interpretation
- source-domain claims from local trust decisions

## Skill graph

```
repo-deep-audit
      |
      +--> evidence-led-verification
      |
      +--> runtime-trust-design
      |        |
      |        +--> protocol-freeze
      |        +--> federation-design
      |        +--> market-design
      |
      +--> repo-engineering-plan
      |
      +--> continuation-controller
      |
      +--> skill-creator
```

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

## Core state machine

```
DISCOVER
  -> FREEZE
  -> MODEL
  -> IMPLEMENT
  -> TEST
  -> VERIFY
  -> RELEASE_GATE
  -> TAG
```

A claim may not cross a gate without the evidence required by that gate.

## Tool contracts

The `tools/` directory contains JSON contracts for the reusable operations. These are declarative contracts; an adapter may implement them with GitHub, local shell, CI, or another execution provider.

## Important limitation

These skills describe a verification discipline. They do not themselves prove that CI, remote Actions, hardware attestation, or another external authority actually ran. Execution evidence must come from the corresponding authority.

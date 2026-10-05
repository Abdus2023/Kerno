# Reusable process tool contracts

These JSON Schemas define machine-readable boundaries for deterministic portions of the reusable process system.

## GPJK semantic contracts

- `evidence-ledger.schema.json`
- `gpjk-reference-resolution.schema.json`
- `gpjk-expression-evaluation.schema.json`
- `gpjk-state-transition.schema.json`
- `gpjk-authorization.schema.json`
- `gpjk-temporal-verification.schema.json`
- `gpjk-interchange.schema.json`
- `gpjk-governance-decision.schema.json`

## Design rule

Schemas specify accepted artifact shape. They do not establish that an implementation conforms to the semantics, executed a test, or produced truthful evidence.

Therefore:

```
SCHEMA VALID
    !=
SEMANTICALLY CONFORMANT
    !=
EXECUTED
    !=
VERIFIED
```

A conformance harness must exercise these contracts against an implementation and retain execution evidence.

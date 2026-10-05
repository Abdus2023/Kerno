# GPJK Semantic Adapter Contract

The extended reference runner evaluates fixture domains through small deterministic adapters.

## Adapter interface

Each adapter receives a fixture case and returns:

`actual, diagnostic`

The runner maps that result against the fixture's `expected` value and emits PASS, FAIL, or ERROR.

## Implemented extended domains

### Authorization
- amount at or below policy limit → permit
- amount above policy limit → deny
- missing policy condition → deny by default

### Temporal
- evaluation inside validity interval → PASSED
- evaluation outside validity interval → FAILED
- timeout without external confirmation → INDETERMINATE

### Evidence
- supporting evidence present → PASSED
- required evidence absent → INDETERMINATE
- contradictory evidence → INDETERMINATE

### Interchange
- IMPORT accepted without execution → accepted=true, executed=false
- missing dependency → rejected without execution

### Governance
- ADDITIVE → APPROVED
- BREAKING → DEFERRED
- identifier reuse → REJECTED

## Semantic boundary

These adapters encode the fixture suite's reference semantics. They do not prove that an external
implementation follows GPJK. Differential conformance requires running the same cases against an
independent implementation and comparing results.

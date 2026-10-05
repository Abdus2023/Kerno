# GPJK Differential Conformance

Differential conformance compares two independently identified implementations against the same
versioned fixture.

## Model

```
fixture
   │
   ├──→ reference implementation ──→ reference result
   │
   └──→ implementation under test ─→ candidate result
                                      │
                         compare normalized results
                                      │
                           MATCH / MISMATCH / ERROR
```

## Required identity

Every run records:
- GPJK semantic version
- fixture suite/version
- reference implementation identity/version
- candidate implementation identity/version
- adapter identity/version
- complete case results

## Result classes

- MATCH: both implementations produce equivalent normalized semantics.
- MISMATCH: both execute but results differ.
- ERROR: one or both implementations cannot produce a result.
- NOT_RUN: explicitly absent execution; never treated as MATCH.

## Normalization

Only semantic output is compared. Diagnostics, formatting, timestamps, and implementation-specific
metadata are excluded unless the fixture explicitly makes them normative.

## Evidence boundary

A differential MATCH establishes agreement for the executed fixture cases. It does not establish
truth of external facts, security, legal compliance, or correctness outside fixture scope.

## Security

The candidate adapter must not receive hidden reference state. Inputs are fixture-defined and
must be reproducibly supplied to both implementations.

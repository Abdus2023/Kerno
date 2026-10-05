# GPJK Reference Harness

The conformance fixtures are executable test inputs. The reference harness is intentionally
small and deterministic.

## Initial executable scope

1. Reference resolution
   - VALUE
   - NULL
   - MISSING
   - UNRESOLVED
2. Expression evaluation
   - strict typed comparison
   - TRUE / FALSE / UNKNOWN
   - invalid expression distinct from UNKNOWN
3. State transitions
   - execution and step transition tables
   - terminal-state resurrection rejected

## Harness contract

Input:
- one or more versioned conformance fixtures
- GPJK semantic implementation under test

Output:
- case identifier
- expected result
- actual result
- PASS / FAIL
- diagnostic on failure

The harness must not infer semantic success from fixture presence.

## Evidence boundary

A repository containing fixtures is not execution evidence.

A harness run becomes execution evidence only when an execution environment records:
- implementation identity/version
- fixture suite/version
- command or invocation
- timestamp
- complete case results
- exit status
- environment/toolchain identity

CI remains execution authority for release claims.

## Next expansion

After the initial three deterministic domains, add:
authorization → temporal verification → evidence semantics → interchange → governance.


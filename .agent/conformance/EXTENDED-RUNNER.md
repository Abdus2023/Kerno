# GPJK Conformance Runner — Extended Scope

The runner is intended to execute all registered semantic fixture domains.

Current reference domains:
- reference-resolution
- expression-evaluation
- state-machine

Extended adapters are specified for:
- authorization
- temporal-verification
- evidence-verification
- interchange
- governance

The implementation order is deliberate: first establish the deterministic core, then add policy,
time, evidence, transport, and governance semantics. Each domain must preserve its own uncertainty
and failure states.

A full-suite PASS must mean every registered case was executed and matched its expected result.
Skipped or unsupported cases are not PASS.

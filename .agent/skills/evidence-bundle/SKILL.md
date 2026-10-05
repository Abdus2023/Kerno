---
name: evidence-bundle
description: Assemble snapshot, deterministic inventory, audit findings, and scoped evidence into one reproducible verification input.
---

# Evidence Bundle

An evidence bundle is a transport artifact, not a verification result.

Required binding:
- repository
- ref
- exact commit
- exact tree

Composition:

`snapshot → inventory → audit → evidence`

The bundle must preserve:
- exact snapshot identity
- complete inventory supplied to the adapter
- audit findings
- evidence identifiers
- audit limitations

A bundle may support verification but cannot declare a claim VERIFIED by itself.

## Integrity rule

If commit or tree identity is absent, the operation is BLOCKED.

If the inventory is incomplete, the limitation must be explicit.

If an observation is outside the inspected snapshot, it does not belong in the bundle.

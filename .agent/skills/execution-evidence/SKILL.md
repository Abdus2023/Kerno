---
name: execution-evidence
description: Bind CI, test, build, lint, and security-scan results to the exact repository artifact they actually executed against.
---

# Execution Evidence

Execution evidence is distinct from static repository evidence.

Required identity:
- execution ID
- execution authority
- repository
- exact commit
- exact tree
- execution status
- observation time

## Binding rule

Execution evidence is valid for a snapshot only when:

`repository + commit + tree`

match exactly.

A matching branch or ref name alone is insufficient.

## Status

- PASSED: authority reports successful execution.
- FAILED: authority reports execution failure.
- CANCELLED: execution did not complete.
- TIMED_OUT: execution did not complete within authority limits.
- NOT_OBSERVABLE: execution result cannot be established.

## Prohibitions

Never infer:
- CI passed from a workflow file
- tests passed from test source
- security scan passed from configuration
- runtime behavior from static inspection

A run URL is provenance, not proof by itself; the authority's reported result and artifact binding are required.

# 01 · Executive Summary

**Verdict:** Kerno 0.2.0 is a *substantially implemented and verified*
kernel-native agent runtime whose security architecture is now ahead of its
reputation — but it is **not yet a hardened runtime for hostile, untrusted
workloads**. The execution choke point is real, tested, and universal; the
remaining boundary is OS-level isolation.

## Assessment at a glance

| Area | Original audit (pre-work) | Now (verified) |
|---|---|---|
| Core concept | Strong | Strong — unchanged |
| Execution choke point (K-001) | Missing (per-loop ad-hoc guards) | **Implemented, universal** — all loops, pool, distributed, HTTP |
| Policy bypass across loop types | P0 (hierarchical/multi_agent/debate unguarded) | **Fixed** + real-kernel tests per loop |
| Allowlist runtime hook | P0 (infinite recursion wedged kernels) | **Fixed** — non-reentrant, verified in-kernel |
| Same-process arbitrary Python | P0 (documented) | **Documented boundary** — Docker/Subprocess executors exist; not a claim of a sandbox |
| Capability authorization (K-008) | Planned | **Implemented** — scoped, expiring, attenuating grants; agents as principals |
| Secrets & redaction | Planned | **Implemented** — SecretBroker + redaction through records, events, outputs, notebooks |
| Server surfaces | Raw kernel execution | **Choke point enforced** on every HTTP path |
| Test gate | 524 tests (1 skipped) | **1047 passed, 5 skipped, 0 failed** |
| Bugs found by the audit work | — | **6 genuine bugs** found and fixed (see 05) |
| Packaging | Core shipped the full analytical stack | **Split** — lean core + `[data]`/`[server]`/… extras |

## What this means

1. **An LLM generating Python cells is the trust model.** Kerno's defense is
   layered: capability authorization → allowlist policy → human approval →
   kernel isolation (optional). The first three layers are implemented and
   tested. The fourth is available (`DockerExecutor`, `SubprocessExecutor`,
   K-009 isolated multi-agent kernels) but is the operator's responsibility
   to deploy.

2. **The invariant that matters most is true:** no agent-generated code
   reaches a kernel except through `ExecutionEngine.execute()`. This was
   verified by code audit (every `kernel.execute` call site categorized) and
   by per-loop behavioral tests on real kernels.

3. **The audit process itself paid for the audit:** the verification work
   found and fixed the `/health` 500 bug, a silently-skipped property-test
   suite, a probe f-string bug in the new dependency-split code, and hardened
   three load-sensitive tests — all documented in `05` and `06`.

## Bottom line for decision-makers

- **Safe to use** for trusted/internal agent workloads with an allowlist
  profile, a capability broker, and (for anything sensitive) container
  isolation.
- **Not yet safe** to expose to untrusted users or untrusted LLM output
  without OS-level isolation and the CI workflow that the repository still
  cannot push (see `15-verification-gates.md`).

Next: `02-project-identity-and-scope.md` defines exactly what was audited.

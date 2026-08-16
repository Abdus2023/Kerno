# 05 · Critical Issues

The P0/P1 issues, each with root cause, impact, fix, and the verification
that proves the fix. Every fix here is covered by a test that **fails on the
pre-fix code**.

---

## C-1 · Allowlist enforcement was not universal (F-002)

**Root cause.** `run()` installed a `guarded_execute` wrapper only in the
`else` branch for reactive/reflect/plan loops. The `hierarchical`,
`multi_agent`, and `debate` branches constructed their agents *before* the
wrapping logic, and `run_with_pool` had no wrapper at all.

```
allowlist
   ├── reactive / reflect / plan   → guarded ✓
   ├── hierarchical / multi_agent / debate → UNGUARDED ✗
   └── run_with_pool               → UNGUARDED ✗
```

**Impact.** An allowlist profile was silently advisory for five of the six
loop strategies — an LLM driving a debate loop could emit `subprocess` code
and it would execute.

**Fix.** `ExecutionEngine` is constructed once in `run()` and every loop
receives it as its `kernel`; `run_with_pool` does the same per worker. The
monkey-patch pattern was deleted.

**Verification.** `tests/behavioral/test_security_chokepoint.py` — for every
loop strategy (parametrized reactive/reflect/plan + hierarchical +
multi_agent + debate + pool) on a **real kernel**, an LLM emitting
`import subprocess` produces an `AllowListViolation` error cell and the code
never executes (asserted: no successful execution of violating code).

---

## C-2 · The allowlist runtime hook wedged kernels (F-004)

**Root cause.** `to_kernel_code()` generated a hook that did
`import importlib.util` *inside* the patched `__import__` — a re-entrant
call that recursed infinitely on the kernel's own internal imports.
The hook cell then hung, and the kernel was wedged for the rest of the
session (every subsequent cell timed out).

**Impact.** Any session using `AllowList.data_analysis()` or `read_only()`
could hang the kernel permanently — the security feature was itself a
denial-of-service.

**Fix.** The hook was rewritten:
- relative imports (`level > 0`) pass through (kernel machinery);
- stdlib resolved via `sys.stdlib_module_names` (no `importlib` lookup);
- already-loaded modules pass through (capability granted at first import).

**Verification.** A real-kernel script proves: hook installs, `print` works,
allowed imports work, `import requests` raises `ImportError` from the hook,
and the kernel remains healthy afterwards.

---

## C-3 · The public HTTP surfaces bypassed the choke point (F-007)

**Root cause.** `kerno/server/app.py` (`/run`), `openai_compat.py` (sync +
streaming), and `secure_app.py` passed the raw `KernelRuntime` into the
pipeline factories. A request to the OpenAI-compatible endpoint executed
LLM-generated code with **no allowlist, no broker, no budget**.

**Impact.** The most exposed surface of the product was the least protected.

**Fix.** `make_server_engine(kernel, profile, broker, budget)` wraps any
kernel in the full choke point; every endpoint builds its engine and passes
it to the factory. `RunRequest.security` defaults to `permissive` (`none`
is an explicit opt-out); the authenticated server defaults to
`data_analysis`.

**Verification.** Unit tests (`TestMakeServerEngine`, `TestExecuteTaskChokePoint`)
prove violating code is blocked and never reaches the kernel; a **live
server** was stood up with a deterministic `ScriptedBrain` and all four
integration tests (health, models, sync completion, streaming) passed
against it.

---

## C-4 · Secrets reached notebook code cells (F-010)

**Root cause.** Output/record redaction was complete, but the notebook
projection wrote the cell **code source** verbatim — and the generated code
itself often embeds the secret literal (`print('token=sk-…')`).

**Impact.** Saved notebooks (the reproducibility artifact) could exfiltrate
secrets in plaintext.

**Fix.** `NotebookAuditTrail` accepts a redactor and applies it to code
source, reasoning, and error text; `run()`/`run_with_pool()` wire it through.

**Verification.** e2e test: a cell printing a registered secret → the
`.ipynb` file contains `[REDACTED]`, never the secret.

---

## C-5 · Dead code lied about session status (F-015)

**Root cause.** `HierarchicalLoop.run()` and `DebateLoop.run()` hardcoded
`SessionStatus.COMPLETE` in their result while a local `status` variable
(used by cancellation) was dead code.

**Impact.** A cancelled hierarchical or debate session reported
`COMPLETE` — instrumentation, notebooks, and callers were misled.

**Fix.** Both loops now honor the `status` variable; synthesis/judge phases
are skipped entirely when cancelled; `cancel_token` is wired through
`run()` for all six strategies.

**Verification.** `TestCancellationAllLoops` — pre-cancelled tokens produce
`INTERRUPTED` for hierarchical, debate, and multi-agent on real kernels.

---

## C-6 · The verification tooling itself was lying (F-008, F-009)

**Root cause.** Two silent gaps in the audit's own evidence:
- the `/health` endpoint called `pool.stats()` (a property) as a method —
  every health check 500'd, and the integration tests that would catch it
  were skipped (they need a live server);
- `tests/property/` was skipped all session — `hypothesis` was missing from
  the dev extras.

**Impact.** The repository's documented gates (integration, property) had
never actually run; the health endpoint was broken in production.

**Fix.** `pool.stats` property access; `hypothesis` + `httpx` in dev extras;
live-server verification of all four integration tests; regression tests
for both.

**Verification.** The integration suite now **passes against a running
server**; the property suite runs (7 passed); full suite 1047 passed.

---

## Residual critical-area notes

- **F-001/F-003 remain documented limitations**: the allowlist is a policy
  layer, and kernels share the host trust domain unless containerized.
  These are honest boundaries, not defects — but they cap the threat model
  at "trusted/internal" until OS isolation is deployed.

Next: `06-evidence-and-verification.md`.

# 06 · Evidence and Verification

Every finding in this audit is backed by one of the following evidence
classes, listed in increasing strength:

## E-1 · Source audit (static)

- Every `kernel.execute` call site in `kerno/` was enumerated and
  categorized: agent-code paths (all through the engine) vs. trusted
  host-setup (skills, hooks, comms, materializers, RAG) vs. documented
  residuals (kernel-side checkpoint code, dev tools).
- 45 modules / 121 audit symbols import-checked — all present.
- The 110 `✅ Done` claims in `docs/implementation-status.md` were
  cross-checked against code.

## E-2 · Behavioral tests on real kernels

The suite boots actual Jupyter kernels. Security-critical behaviors are
proven end-to-end:

| Behavior | Test |
|---|---|
| Violating code blocked in every loop | `test_security_chokepoint.py` (16 tests) |
| Kernel crash → restart → state restored | `test_session_resume.py` (SIGKILL) |
| Mid-cell cancellation interrupts a hung kernel | `test_cancellation.py` |
| Fork at a cell boundary, divergent branches | `test_fork_session.py` |
| Isolated multi-agent kernels (K-009) | `test_multi_agent_isolation.py` |
| Secrets never reach notebooks/outputs | `test_output_redaction_e2e.py` |
| Live checkpoints bound to event sequences | `test_checkpoint_live.py` |
| Sticky DEAD kernel state | `test_kernel_state.py` |

## E-3 · Invariant checks (P1–P10)

`kerno/invariants.py` provides named checks that **detect violations** —
tests assert both the passing scenario and the violating scenario:

- P1 terminal events are final · P2 denied never starts · P3/P10 single
  terminal state · P4 artifact provenance · P5 monotonic sequence ·
  P6 capability attenuation · P7 replay never calls the Brain ·
  P8 generation monotonic · P9 session survives restart.

`kerno doctor` runs all of them against synthetic valid data and reports
the result — verified in a fresh core-only venv.

## E-4 · Fault injection

`FaultInjector` (fail-next / kill-after) drives real kernels through
deliberate failures: SIGKILL mid-session, injected cell failures,
timeout escalation (soft interrupt → grace → SIGKILL → restart). The
recovery path is exercised and the invariants re-checked after recovery.

## E-5 · Fresh-environment verification (release artifacts)

| Check | Result |
|---|---|
| Wheel build | `kerno-0.2.0-py3-none-any.whl` — 176 modules + LICENSE + entry point |
| Fresh-venv install (core only) | imports; `kerno doctor` P1–P10 pass; full live session runs |
| Fresh-venv install (`[data]`) | 114 skills load; others skipped with warning |
| `kerno run --dry-run` (no API key) | COMPLETE via ScriptedBrain fallback |
| Live OpenAI-compat server | all 4 integration tests pass |

## E-6 · Test-suite integrity

- **1047 passed, 5 skipped, 0 failed** (unit + behavioral + integration +
  property).
- The 5 skips are environment-dependent and *proven* to pass when the
  environment exists (4 need a live server — verified; 1 is env-dependent).
- Flake history is documented, root-caused, and fixed (timeout 120→300s,
  yielding mocks, resilient message export), not papered over.

## E-7 · What the evidence does NOT claim

- It does not claim the allowlist is a sandbox (it is not).
- It does not claim CI runs on GitHub (the workflow cannot be pushed by the
  automation token; `make ci` reproduces the gates locally).
- It does not claim hostile-workload safety without OS isolation.

Next: `07-dependency-and-supply-chain.md`.

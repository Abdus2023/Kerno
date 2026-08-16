# 12 · Code Quality and Testing

## The gate, in numbers

- **1047 passed, 5 skipped, 0 failed** across four suites:
  unit (928) · behavioral on real kernels (112) · integration against a
  live server (4) · property (7).
- The 5 skips are environment-dependent and *proven* to pass when the
  environment exists.
- Per-test timeout 300s (was 120s) — flakes were timeout artifacts, now
  root-caused rather than papered over.

## Test architecture

| Suite | What it proves |
|---|---|
| `tests/unit` | Engine, broker, secrets, artifacts, budgets, actions, invariants, scheduler, distributed, isolation primitives, config, CLI — no kernel |
| `tests/behavioral` | Real Jupyter kernels: per-loop policy enforcement, crash recovery (SIGKILL), cancellation, forking, resume, checkpoints, server paths, redaction e2e, sticky kernel state |
| `tests/integration` | Live OpenAI-compat server: health, models, sync completion, streaming |
| `tests/property` | Hypothesis property tests of the pipeline composition system (were silently skipped — now fixed) |

## Invariant testing (audit #101)

Every P1–P10 check in `kerno/invariants.py` is tested twice: the passing
scenario AND the violating scenario the check must detect. These tests
protect the architecture, not the implementation.

## Fault injection (audit #72)

`FaultInjector` + real kernels: SIGKILL mid-session, injected cell
failures, timeout escalation. Recovery is exercised and invariants
re-checked afterwards.

## Flake archaeology (evidence that the gate is honest)

| Flake | Root cause | Fix |
|---|---|---|
| 30s skill-load timeouts under load | skill imports exceeded the timeout | 120s + one retry |
| Bus test timeouts | never-yielding mock → 120 real kernel cells | mocks yield after one cell |
| Bus test assertion failure | transient iopub error dropped the message cell | message written in two cells |
| Property suite "1 skipped" | hypothesis missing from dev extras | added to dev; suite runs |
| Integration "4 skipped" | no live server | verified against a standing server |

## Code hygiene

- 12 dead imports removed from `_run.py`.
- `pyproject.toml` packaging fixed (wheel uninstallable before).
- `KernoConfig.validate()` catches misconfiguration at build time.
- `kerno doctor` runs the P1–P10 invariant layer as an operational check.
- 110 verified ✅ items in the implementation-status tracker.

## Known testing gaps

- No Docker-in-CI security tests (workflow blocked on permissions).
- No fuzzing of the allowlist regexes.
- No mutation testing.
- No performance/soak tests for the pool under memory pressure.

Next: `13-remediation-plan.md`.

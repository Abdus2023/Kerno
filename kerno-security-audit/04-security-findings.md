# 04 · Security Findings — Master Register

Severity: **P0** critical · **P1** high · **P2** medium · **P3** low/informational.
Status: ✅ fixed & verified · 🟡 known limitation (documented) · 🟢 acceptable by design.

## P0 — Critical

| ID | Finding | Status | Evidence |
|---|---|---|---|
| F-001 | AllowList is not a sandbox; advertised as protection against hostile code | 🟡 documented limitation | `SECURITY.md`; `DockerExecutor` provided as the real boundary |
| F-002 | Policy bypass: allowlist installed only for reactive/reflect/plan; hierarchical/multi_agent/debate and pool ran unguarded | ✅ fixed | `_run.py` builds all loops on `ExecutionEngine`; per-loop real-kernel tests |
| F-003 | Same-process arbitrary Python — kernel has host access | 🟡 documented | K-003; Docker/Subprocess executors exist; operator must deploy |
| F-004 | Allowlist runtime import hook re-entered itself (`import importlib` inside patched `__import__`) → infinite recursion → wedged kernels | ✅ fixed | Hook rewritten (stdlib via `sys.stdlib_module_names`, relative-import pass-through, no re-entrancy); in-kernel verification |
| F-005 | `run()` crashed for every caller — `load_default_skills` param shadowed the bootstrap function | ✅ fixed | renamed `bootstrap_skills`; full suite green |

## P1 — High

| ID | Finding | Status | Evidence |
|---|---|---|---|
| F-006 | Comm listener thread raced `collect()` on the iopub socket → stolen `idle` messages → hung cells; also caused a zmq segfault | ✅ fixed | single-reader `IOPUB_LOCK` + inline comm dispatch; race tests |
| F-007 | Server surfaces (`/run`, OpenAI-compat, secure) executed raw kernel code with no policy | ✅ fixed | `make_server_engine` wraps every endpoint; live-server integration tests |
| F-008 | `/health` endpoint 500'd on every call (`pool.stats()` called as method on a property) | ✅ fixed | regression test; live-server verification |
| F-009 | Property-based tests silently skipped all session (hypothesis missing from dev extras) | ✅ fixed | hypothesis in dev extras; suite now runs (7 tests) |
| F-010 | Secrets reached notebook code cells (redaction covered records/outputs but not code source) | ✅ fixed | notebook projection redacts code/reasoning/error text; e2e test |
| F-011 | Falsy-store bugs ×3: `__len__` on memory/shared stores broke `or`/`and` checks (empty stores silently discarded) | ✅ fixed | `is not None` everywhere; regression tests |

## P2 — Medium

| ID | Finding | Status | Evidence |
|---|---|---|---|
| F-012 | Skill-load 30s timeout flaked under load (pandas/numpy/matplotlib imports) | ✅ fixed | 120s + retry on TimeoutError |
| F-013 | Never-yielding mock LLM ran 120 real kernel cells in a test (load flake) | ✅ fixed | mocks yield after one cell |
| F-014 | Full-suite flakes were timeout artifacts, not failures | ✅ fixed | per-test timeout 120s → 300s; clean runs |
| F-015 | Hierarchical/Debate loops hardcoded `COMPLETE` status, ignoring cancellation | ✅ fixed | status variable honored; cancellation tests for all loops |
| F-016 | Probe f-string bug in dependency-split code (probe cell was a SyntaxError, silently skipped everything) | ✅ fixed | `f`-prefix; regression test asserting `{deps!r}` never reaches the kernel |
| F-017 | `import kerno` failed without fastapi (secure_app unconditional import) | ✅ fixed | guarded imports; meta-path blocker test |

## P3 — Low / informational

| ID | Finding | Status | Evidence |
|---|---|---|---|
| F-018 | `pyproject.toml` hatchling wheel table used array syntax → package uninstallable | ✅ fixed | `[tool.hatch.build.targets.wheel]`; wheel builds + fresh-venv install |
| F-019 | 12 dead imports in `_run.py` | ✅ fixed | cleanup; wheel re-smoked |
| F-020 | Repository had no LICENSE, no CHANGELOG, no SECURITY.md | ✅ fixed | MIT LICENSE, CHANGELOG 0.2.0, SECURITY.md |
| F-021 | CI workflow exists but cannot be pushed (GitHub App lacks `workflows` permission) | 🟡 external | `.github/workflows/ci.yml` local-only; `make ci` reproduces gates |
| F-022 | Kernel transport is unencrypted TCP (Jupyter default) | 🟡 documented | IPKernelApp warning; use IPC/CurveZMQ in deployment |

Next: `05-critical-issues.md` — the P0/P1 issues in depth.

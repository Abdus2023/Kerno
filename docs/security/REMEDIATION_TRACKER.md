# Kerno — Security Remediation Tracker

**Purpose:** single tracking document for the remediation program
(`kerno-security-audit/20-remediation-plan.md`). Findings are **never
deleted**; their status is updated instead.

**Evidence states** (never collapsed into a single `PASS`):

```text
OPEN             — identified, not started
IMPLEMENTED      — code change landed on the remediation branch
TESTED LOCALLY   — local test suite passes for the fix
CI VERIFIED      — executed by GitHub Actions (requires F-009)
```

**Branch:** `arena/01a00e08-kerno` (session branch pinned to verified `main`
baseline `36943e1c854d576f1d3bbff96481ae57e7fb94b5`).

---

## Findings register

| ID | Finding | Fix | Test | CI | Status |
|---|---|---|---|---|---|
| F-001 | Raw kernel materializer | Engine boundary (`MaterializationExecutor`) | `tests/unit/test_file_materializer_security.py` | Pending | 🟢 IMPLEMENTED + TESTED LOCALLY |
| F-002 | SSRF | URL policy (scheme/IP/redirect/size/timeout) | SSRF suite in `test_file_materializer_security.py` | Pending | 🟢 IMPLEMENTED + TESTED LOCALLY |
| F-003 | Unbounded files | Resource limits | size tests in `test_file_materializer_security.py` | Pending | 🟢 IMPLEMENTED + TESTED LOCALLY |
| F-004 | Filename collision | Isolated storage (per-request dirs) + cleanup | isolation/cleanup tests in `test_file_materializer_security.py` | Pending | 🟢 IMPLEMENTED (per-instance dirs) + TESTED LOCALLY |
| F-005 | OpenAI downgrade | `server_default` wiring | endpoint tests in `test_server_endpoint_security.py` | Pending | 🟢 IMPLEMENTED + TESTED LOCALLY |
| F-006 | Secure-app downgrade | `server_default` wiring | endpoint tests in `test_server_endpoint_security.py` | Pending | 🟢 IMPLEMENTED + TESTED LOCALLY |
| F-007 | Missing endpoint tests | integration suite | sync + streaming endpoint tests for OpenAI + secure app (main `/run` `/stream` `/ws` already covered by `test_server_security.py`) | Pending | 🟢 IMPLEMENTED (OpenAI + secure endpoints) |
| F-008 | Runtime-origin authority | `runtime_execute()`/`runtime_stream_execute()` trusted APIs; public `execute()`/`stream_execute()`/`execute_silent()` reject `ORIGIN_RUNTIME` | `TestOriginAuthorityBoundary` + `tests/unit/test_capability_escalation.py` | Pending | 🟢 IMPLEMENTED + TESTED LOCALLY |
| F-009 | CI evidence | GitHub Actions workflow (`.github/workflows/ci.yml`) | workflow run | **Not yet executed** | 🟡 CI CONFIGURED (file prepared at `.github/workflows/ci.yml`; push BLOCKED — the arena GitHub App lacks the `workflows` permission, so GitHub refuses workflow-file pushes. Repo owner must commit/push the file or grant the app the permission) |
| F-010 | CORS | explicit-origin allowlist (`resolve_cors_origins` + `KERNO_CORS_ORIGINS`), no wildcard default | `TestCORSOriginPolicy` in `test_server_endpoint_security.py` | Pending | 🟢 IMPLEMENTED + TESTED LOCALLY |
| — | Observability (P2.13) | denial logs carry execution_id/origin/subject/capabilities/rule; gateway logs transport+requested+effective+server_default; materialization logs file/source/hostname/decision (never secrets/contents) | suite logs verified | Pending | 🟢 IMPLEMENTED |
| — | RAG bridge raw kernel (F-001 sibling) | `OpenWebUIRAGBridge` now requires `execute_load_code`; loads via engine | structural guard + static gate | Pending | 🟢 IMPLEMENTED + TESTED LOCALLY |
| — | Static raw-kernel gate (P3.17) | `scripts/check_raw_kernel.py` — flags `KernelRuntime(` outside approved bootstrap files, raw `kernel.execute(` in `kerno/server/`, `urlretrieve(` anywhere | gate itself + `tests/security/test_invariants.py::test_static_raw_kernel_gate_passes` | Pending | 🟢 IMPLEMENTED |
| — | Security invariant suite (P3.16) | `tests/security/` — 18 release-gate invariants (I-01…I-11) | `pytest tests/security` | Pending | 🟢 IMPLEMENTED + TESTED LOCALLY |
| — | Baseline test bugs (5 pre-existing failures + 1 pool-stat bug + 1 flaky) | test corrections | `tests/unit` suite green | Pending | 🟢 FIXED (6 fixed; `test_unused_token_runs_normally` flaky under kernel contention, passes in isolation) |
| — | P6 scope-containment gap (NEW, found by F-008 adversarial tests) | scope normalization in `CapabilityBroker` (`_normalize_scope`) | traversal cases in `test_capability_escalation.py` | Pending | 🟢 FIXED — `workspace/../etc/*` no longer contained in `workspace/*` |

---

## Progress log

### Pass 1 — Phase 0 freeze + Phase 1 (STOP THE BLEED)

- **2026-08-17** — Baseline frozen: `docs/audit/BASELINE.md`; HEAD
  `36943e1c`; unit suite `954 passed / 5 failed / 1 skipped`; GitHub Actions
  `total_count: 0`.
- **2026-08-17** — Pre-existing test bugs classified (5, all test bugs, none
  security defects).

### Pass 2 — Phase 1 (STOP THE BLEED) implemented + tested locally

**2026-08-17** — Phase 1 landed on `arena/01a00e08-kerno`:

- **F-001** — `kerno/server/files.py`: new `MaterializationExecutor` (narrow
  interface exposing only `execute_load_code()`, routed through
  `ExecutionEngine` with `origin=ORIGIN_RUNTIME`); `FileMaterializer`
  constructor structurally rejects raw kernels (TypeError); `secure_app.py`
  builds `FileMaterializer(MaterializationExecutor(engine))` and guarantees
  `cleanup()` in `finally`. Every materialization execution now produces
  engine audit records + event stream.
- **F-002** — strict outbound URL policy in `files.py`: scheme allowlist
  (http/https), private/loopback/link-local/CGNAT/multicast blocking
  (literal IPs and every resolved address), embedded-credential rejection,
  per-redirect revalidation (`_ValidatingRedirectHandler`), connect/read
  timeouts, streaming size cap with declared Content-Length pre-check.
  `urllib.request.urlretrieve` removed.
- **F-003** — `MaterializationLimits` (per-file, per-request count, total
  bytes, URL download bytes, materialization time); base64 size estimated
  and rejected BEFORE decode/allocation; actual bytes measured.
- **F-004 (partial→implemented)** — per-instance (per-request) storage
  directory `<upload_dir>/<uuid>/`; `cleanup()` removes it; identical
  filenames from different requests can no longer collide.
- **F-005 / F-006** — `openai_compat.py` (sync + streaming) and
  `secure_app.py` now pass `server_default=default_security,
  allow_downgrade=False` into `make_server_engine()`; the `"none"`
  special-case is gone (resolve_effective_profile upgrades it).
- **F-007** — new `tests/unit/test_server_endpoint_security.py` exercises
  the REAL OpenAI-compatible and secure-app endpoints (sync + streaming)
  with a fake pool: permissive/none downgrade attempts are upgraded to the
  server default, stronger profiles honored, violating code never reaches
  the kernel.
- New `tests/unit/test_file_materializer_security.py` (F-001/F-002/F-003/
  F-004): execution boundary, audit records, URL policy matrix, redirect
  revalidation, download machinery (size cap, declared-length, timeout),
  resource limits, isolation, cleanup.

**Test results (2026-08-17):**

```text
tests/unit                       → 1012 passed, 1 skipped   (was 954/5/1)
tests/behavioral + integration +
tests/property                   → 122 passed, 5 skipped
                                   (2 pre-existing failures: 1 pool-stat
                                    test bug fixed, 1 cancellation flake
                                    under kernel contention — passes in
                                    isolation)
```

---

### Pass 3 — Phase 2 (UNIFY) implemented + tested locally

**2026-08-17** — Phase 2 landed on `arena/01a00e08-kerno`:

- **Canonical gateway (items 4/5/6)** — `kerno/server/security.py` now owns
  `build_gateway_engine()`, the SINGLE authoritative engine builder for every
  public transport (profile resolution against `server_default`, downgrade
  prevention, per-request budget, ExecutionEngine choke point). `app.py`
  (`/run`, `/stream`, `/ws`, `_execute_task`), `openai_compat.py` (sync +
  streaming), and `secure_app.py` all delegate to it — no independently
  evolving security implementations remain.
- **F-008 runtime-origin authority** — the public `execute()` /
  `stream_execute()` / `execute_silent()` APIs now accept ONLY `ORIGIN_AGENT`
  and raise `ValueError` on `ORIGIN_RUNTIME` (or any other origin). Trusted
  host code obtains runtime semantics exclusively through the new
  `runtime_execute()` / `runtime_stream_execute()` APIs; `MaterializationExecutor`
  now uses `runtime_execute()`. Adversarial `TestOriginAuthorityBoundary`
  suite proves an agent cannot manufacture runtime authority even with
  grants.
- **K-008 capability escalation suite** — new `tests/unit/test_capability_escalation.py`
  (19 tests): self-grant prevention (broker fail-closed, no grant surface on
  the agent-facing executor), cross-agent grant isolation, scope widening,
  subject mutation, expired parents, revoked parents (cascade), skill
  capability immutability (`grant_skill_capabilities` snapshot semantics),
  and the runtime-origin + self-grant combination.
- **NEW FINDING FIXED — P6 scope-containment gap**: the adversarial suite
  caught `fnmatch` accepting `workspace/../etc/*` as contained in
  `workspace/*`. `CapabilityBroker` now normalizes scope patterns
  (`_normalize_scope`) before containment checks — `..` traversal can no
  longer widen a child grant's effective coverage (the audit narrative's
  "hardening opportunity" is now closed).

**Test results (2026-08-17):**

```text
tests/unit                       → 1039 passed, 1 skipped
tests/behavioral + integration +
tests/property                   → 124 passed, 5 skipped
```

### Pass 4 — Phase 3 (HARDEN) + Phase 4 (PROVE) implemented

**2026-08-17** — Phases 3 and 4 landed on `arena/01a00e08-kerno`:

- **F-010 CORS** — wildcard `"*"` is no longer a default anywhere.
  `resolve_cors_origins()` (explicit arg → `KERNO_CORS_ORIGINS` env →
  secure same-origin default `[]`), methods/headers restricted
  (`GET/POST/OPTIONS`, `Content-Type/Authorization`), credentials only
  with explicit non-wildcard origins. All three servers parameterized.
  `TestCORSOriginPolicy` proves `Origin: https://evil.example` gets no
  CORS authorization under the secure default and that explicit
  allowlists are honored.
- **Observability (P2.13)** — engine denials now log execution_id, origin,
  subject, capabilities, rule (never secrets/contents); `build_gateway_engine`
  logs transport + requested + effective + server_default per session;
  materialization logs file/source/hostname/decision.
- **RAG bridge hardened (F-001 sibling)** — `OpenWebUIRAGBridge` also
  executed generated load code on a raw kernel; it now requires the
  `MaterializationExecutor` boundary (structural TypeError guard).
- **Static raw-kernel gate (P3.17)** — `scripts/check_raw_kernel.py`:
  `KernelRuntime(` construction allowed only in 9 explicitly classified
  bootstrap files; raw `kernel.execute(` forbidden in `kerno/server/`;
  `urlretrieve(` forbidden everywhere. Wired into `make ci`.
- **Security invariant suite (P3.16)** — `tests/security/` with 18
  release-gate invariants (I-01…I-11): choke point, origin authority,
  capability/allowlist pre-execution denial, profile governance, SSRF
  policy, materialization bounds, isolation, streaming parity,
  cancellation finalization, and the static gate itself.
- **F-009 CI bootstrap** — `.github/workflows/ci.yml` mirrors `make ci`
  (compile, import gate, raw-kernel gate, unit, invariant, security,
  behavioral/integration/property). Status: **CI CONFIGURED** — the file
  is ready at `.github/workflows/ci.yml`, but the push was REJECTED by
  GitHub: the arena GitHub App (`arena-ai-coding-agent[bot]`) lacks the
  `workflows` permission required to create/update workflow files (both
  `git push` and the Contents REST API return 403). The repo owner must
  either commit/push the file from the local workspace or grant the app
  the `workflows` permission. Execution evidence remains pending.

## Decision gate

After **F-001, F-002, F-005, F-006, F-007** are fixed and tested locally, run
another adversarial review. If those pass, Kerno moves from:

> **strong core security architecture with server-boundary inconsistencies**

to:

> **unified security architecture with externally verified transport enforcement.**

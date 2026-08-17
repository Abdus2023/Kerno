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
| F-008 | Runtime-origin authority | private capability / trusted API | escalation tests | Pending | 🟡 OPEN (Phase 2) |
| F-009 | CI evidence | GitHub Actions workflow | workflow run | Pending | 🔴 OPEN |
| F-010 | CORS | explicit origins | CORS tests | Pending | 🟡 OPEN |
| — | Baseline test bugs (5 pre-existing failures + 1 pool-stat bug + 1 flaky) | test corrections | `tests/unit` suite green | Pending | 🟢 FIXED (6 fixed; `test_unused_token_runs_normally` flaky under kernel contention, passes in isolation) |

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

## Decision gate

After **F-001, F-002, F-005, F-006, F-007** are fixed and tested locally, run
another adversarial review. If those pass, Kerno moves from:

> **strong core security architecture with server-boundary inconsistencies**

to:

> **unified security architecture with externally verified transport enforcement.**

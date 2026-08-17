# Kerno — Audit Baseline (freeze record)

**Purpose:** Phase 0 freeze of the evidence baseline before remediation begins
(remediation program: `kerno-security-audit/20-remediation-plan.md`).

## Repository

| Field | Value |
|---|---|
| Repository | `Abdus2023/Kerno` |
| Target branch | `main` (work performed on session branch `arena/01a00e08-kerno`) |
| HEAD SHA | `36943e1c854d576f1d3bbff96481ae57e7fb94b5` |
| HEAD commit | Merge pull request #3 — `feat(security): complete Phase D/E runtime hardening, canonical execution transactions, and traceability matrix` |
| Merge commit verification | Verified (GitHub merge commit for PR #3, Phase D/E work from `arena/01a00c3b-kerno`) |

## Environment

| Field | Value |
|---|---|
| Python | 3.11.2 |
| Install mode | editable (`pip install -e ".[dev]"`) into `.venv/` |
| Package version | `0.2.1-dev` |

## Dependency lock state

- **No lock file exists** in the repository (`requirements*.txt` pins are absent;
  `pyproject.toml` uses open-ended minimum ranges, e.g. `jupyter-client>=8.0`).
- Two installations performed months apart can therefore resolve different
  dependency graphs. **Reproducibility: not established** (tracked as an
  open item in the remediation plan, §18).

## Test inventory (baseline, 2026-08-17)

Full `tests/unit` run in the frozen environment:

```text
954 passed, 5 failed, 1 skipped
```

### Pre-existing baseline failures (test bugs — recorded before any remediation)

| Test | Failure | Classification |
|---|---|---|
| `tests/unit/test_server_security.py::TestExecuteTaskChokePoint::test_permissive_cannot_downgrade_data_analysis` | `kernel.calls == []` assertion too strict: the benign loop `# TASK_COMPLETE: done` marker is recorded. The security property holds (`AllowListViolation` fired, violating code never reached kernel). | Test bug (over-strict assertion) |
| `tests/unit/test_server_security.py::TestExecuteTaskChokePoint::test_none_security_cannot_downgrade_server_policy` | Same as above (`subprocess` variant). | Test bug (over-strict assertion) |
| `tests/unit/test_execution_engine.py::TestEngineStreamExecute::test_stream_execute_human_approval_fail_closed` | `NameError: name 'CAP_HUMAN_APPROVAL' is not defined` — missing import in the test file. | Test bug (missing import) |
| `tests/unit/test_isolation.py::TestSharedMemory::test_put_get_with_provenance` | `mem.get(...) is sv` — `SharedMemory.get()` intentionally returns a deep copy, so identity comparison is wrong; must be equality. | Test bug (identity vs equality) |
| `tests/unit/test_cli_commands.py::TestCliResumeFork::test_resume_parser_has_expected_args` | `FileNotFoundError: Notebook not found: nb.ipynb` — the parser-acceptance test executes `cmd_resume` which loads the notebook before the LLM-build failure it assumes. | Test bug (missing fixture) |

**Note:** these five failures contradict the "1047 tests passing" claim made in
`kerno-security-audit/README.md` for the audited revision; they are test bugs,
not security defects, and are fixed as baseline hygiene in the remediation pass
(see `docs/security/REMEDIATION_TRACKER.md`, baseline-hygiene row).

## GitHub workflow inventory (baseline)

- GitHub Actions API reports **`total_count: 0`** registered workflows.
- `.github/workflows/` is **absent** on `main`.
- **CI execution evidence: none.** No workflow run IDs exist.
- `main` branch protection: **disabled** (`protection: disabled`,
  required status checks: none, enforcement: off).

## Current security findings (baseline)

| ID | Finding | Status |
|---|---|---|
| F-001 | Raw-kernel `FileMaterializer` bypass (`FileMaterializer(kernel)` → `kernel.execute(load_code)`) | 🔴 Confirmed |
| F-002 | Unrestricted URL retrieval (`urllib.request.urlretrieve`), no scheme/IP/redirect/size/timeout policy | 🟠 Confirmed attack surface |
| F-003 | Unbounded file materialization (no size limits; base64 decoded in full) | 🟠 Confirmed |
| F-004 | Upload filename collision/isolation (shared `/tmp/kerno_uploads/<safe_name>` namespace) | 🟡 Needs isolation test |
| F-005 | OpenAI-compatible profile-downgrade wiring (`openai_compat.py` omits `server_default`) | 🟠 Confirmed |
| F-006 | `secure_app.py` profile-downgrade wiring (omits `server_default`) | 🟠 Confirmed |
| F-007 | Missing endpoint-level security tests (no downgrade/adversarial tests for OpenAI sync/stream, secure app) | 🔴 Confirmed |
| F-008 | Runtime-origin authority boundary (`ORIGIN_RUNTIME` is a caller-supplied trust label; no adversarial escalation test) | 🟡 Needs tests |
| F-009 | CI/evidence gap (no GitHub Actions workflow, no branch protection) | 🔴 Confirmed |
| F-010 | CORS production policy (`allow_origins=["*"]` on authenticated server) | 🟡 Hardening |

## Expected changes (this remediation pass)

Phase 1 — STOP THE BLEED:

1. F-001: `MaterializationExecutor` narrow interface; `FileMaterializer` loses
   raw-kernel ownership; `secure_app.py` routes materialization through the
   `ExecutionEngine` choke point.
2. F-002: strict URL policy (scheme allowlist, private/loopback/link-local
   blocking, per-redirect validation, timeouts, streaming size cap).
3. F-003: materialization limits (per-file, per-request count, total bytes)
   with pre-decode base64 size rejection.
4. F-005/F-006: `server_default=default_security, allow_downgrade=False`
   wired into `openai_compat.py` (sync + stream) and `secure_app.py`.
5. F-007 (partial): endpoint-level downgrade tests for the OpenAI-compatible
   and secure servers, plus the dedicated `test_file_materializer_security.py`
   suite.
6. Baseline hygiene: fix the five pre-existing test bugs above.

Out of scope this pass (tracked): F-008 adversarial origin tests, F-009 CI
bootstrap, F-010 CORS policy.

---

## Post-remediation state (Phase 1, 2026-08-17)

All Phase 1 items from the remediation plan have landed on the session
branch and are **tested locally** (CI verification pending — no GitHub
Actions workflow yet):

| Item | Status |
|---|---|
| F-001 raw-kernel materializer | 🟢 Fixed — `MaterializationExecutor` narrow boundary; raw kernels rejected structurally |
| F-002 URL policy / SSRF | 🟢 Fixed — scheme/IP/redirect/size/timeout policy; `urlretrieve` removed |
| F-003 file-size bounds | 🟢 Fixed — pre-decode base64 rejection, per-file/count/total limits |
| F-004 storage isolation | 🟢 Fixed — per-request `<uuid>` directories + guaranteed cleanup |
| F-005/F-006 profile downgrade | 🟢 Fixed — `server_default` + `allow_downgrade=False` in all server transports |
| F-007 endpoint security tests | 🟢 Added — real OpenAI-compatible + secure-app endpoints, sync + streaming |
| Pre-existing test bugs | 🟢 Fixed (6) — suite is green |

Final local test state (2026-08-17):

```text
tests/unit           → 1012 passed, 1 skipped
tests/behavioral +
tests/integration +
tests/property       → 122 passed, 5 skipped
                       (1 pool-stat test bug fixed; 1 cancellation test
                        flaky only under full-suite kernel contention,
                        passes in isolation)
```

**Still open:** F-009 (GitHub Actions + branch protection), F-010 (CORS
policy), dependency lock/constraints, and `CI VERIFIED` evidence for
everything above.

---

## Post-remediation state (Phases 3–4, 2026-08-17)

Phase 3 (HARDEN) + Phase 4 (PROVE) landed on the session branch:

| Item | Status |
|---|---|
| F-010 CORS policy | 🟢 No wildcard default anywhere; `resolve_cors_origins()` (arg → `KERNO_CORS_ORIGINS` → secure `[]`); credentials only with explicit origins; `TestCORSOriginPolicy` proves evil origins get nothing |
| Observability (P2.13) | 🟢 Denials log execution_id/origin/subject/capabilities/rule; gateway logs transport+profile decision; materialization logs file/source/hostname/decision — never secrets/contents |
| RAG bridge raw kernel | 🟢 `OpenWebUIRAGBridge` moved onto the `MaterializationExecutor` boundary |
| Static raw-kernel gate (P3.17) | 🟢 `scripts/check_raw_kernel.py` wired into `make ci` |
| Security invariant suite (P3.16) | 🟢 `tests/security/` — 18 release-gate invariants (I-01…I-11) |
| F-009 CI workflow | 🟡 **CI CONFIGURED** — `.github/workflows/ci.yml` mirrors `make ci`; execution evidence pending |

Final local test state (2026-08-17):

```text
tests/unit      → 1042 passed, 1 skipped
tests/security  → 18 passed
```

**Remaining:** F-009 CI execution evidence (`CI VERIFIED`), `main` branch
protection (requires a green CI check), dependency lock/constraints.

---

## Post-remediation state (Phase 2, 2026-08-17)

Phase 2 (UNIFY) has landed on the session branch and is **tested locally**:

| Item | Status |
|---|---|
| Canonical server gateway | 🟢 `build_gateway_engine()` in `kerno/server/security.py` — the single authoritative builder used by `/run`, `/stream`, `/ws`, OpenAI sync/streaming, and `secure_app`; no duplicate security implementations |
| F-008 runtime-origin authority | 🟢 `execute()`/`stream_execute()`/`execute_silent()` accept only `ORIGIN_AGENT` (ValueError otherwise); `runtime_execute()`/`runtime_stream_execute()` are the only runtime path; `MaterializationExecutor` uses `runtime_execute()`; adversarial origin tests added |
| K-008 capability escalation | 🟢 19-test adversarial suite (self-grant, cross-agent, scope/subject mutation, expired/revoked parents, skill immutability, origin+grant combination) |
| P6 scope-containment gap (newly found) | 🟢 FIXED — `CapabilityBroker._normalize_scope` rejects `workspace/../etc/*` as wider than `workspace/*` |

Final local test state (2026-08-17):

```text
tests/unit           → 1039 passed, 1 skipped
tests/behavioral +
tests/integration +
tests/property       → 124 passed, 5 skipped
```

**Still open:** F-009 (GitHub Actions + branch protection), F-010 (CORS
policy), dependency lock/constraints, and `CI VERIFIED` evidence for
everything above.

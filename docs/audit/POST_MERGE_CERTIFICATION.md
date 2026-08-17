# Kerno — Post-Merge Certification Audit

**Target commit:** `fc20522555d580b710a1836137a8b4650ccf4558`
**Repository:** [Abdus2023/Kerno](https://github.com/Abdus2023/Kerno)
**Date:** 2026-08-17
**Audit phase:** Post-merge certification (Phase 6)

---

## Executive Verdict

Kerno has made a substantial security transition and the `main` branch now contains the Phase 1–4 remediation merge (PR #5).

> **Security architecture:** STRONG
> **Server-boundary governance:** substantially unified
> **Adversarial coverage:** strong
> **CI (PR):** independently verified on the remediation PR
> **Main-branch CI:** NOT independently established yet
> **Reproducible dependency environment:** NOT established
> **Production-readiness:** not yet fully certified

The important distinction is that PR #5 really was merged, so some previous "pending merge" language in the documentation is now stale.

**Current release assessment:** Kerno main: **SECURITY-HARDENED / POST-REMEDIATION — NOT YET FINAL-CERTIFIED.**

---

## 1. Repository State

GitHub currently reports:

- Public repository
- Python project
- Default branch: `main`
- Current `main` HEAD: `fc20522555d580b710a1836137a8b4650ccf4558`
- Latest merge: PR #5
- PR #5 merged at 2026-08-17 07:04:01 UTC
- Repository pushed shortly afterward, at approximately 07:08 UTC
- MIT licensed
- 1 currently open issue
- 0 stars / forks at the time of inspection

The repository tree confirms that the important CI and security artifacts are actually present on `main`, including:

- `.github/workflows/ci.yml`
- `docs/TRACEABILITY_REPORT.md`
- `docs/audit/BASELINE.md`
- `docs/security/REMEDIATION_TRACKER.md`
- `scripts/check_raw_kernel.py`
- Security test infrastructure
- Production Docker configuration

---

## 2. The Remediation Was Actually Merged

PR #5:

> fix(security): server-boundary hardening Phases 1-4 (F-001..F-010)

is closed and merged, not merely proposed.

GitHub confirms:

- Base: `main`
- Base SHA: `0db50eb...`
- Head: `arena/01a00e08-kerno`
- Head SHA: `2268c032...`
- Merge commit: `fc205225...`
- 5 commits
- 27 changed files
- +5,231 / −135 lines

So the security work described in the remediation tracker is now part of the actual `main` history.

---

## 3. CI Claim: Independently Verified

The remediation documentation claims GitHub Actions run `32003440545` was successful. Direct query of that run confirms:

- Workflow: CI
- Run ID: 32003440545
- Event: `pull_request`
- Status: completed
- Conclusion: success
- Head SHA: `0d70f35e...`
- Started: 06:53:12Z
- Completed: 06:57:00Z

So the claimed CI run really exists and really succeeded.

---

## 4. Critical CI Distinction

The successful run was executed against the PR/remediation content, whose effective head was:

```
0d70f35e6fa26bd7e090246ef65e4df320061064
```

It was **not** a successful post-merge run against the final merge commit:

```
fc20522555d580b710a1836137a8b4650ccf4558
```

Queries against the current merge commit for workflow runs and combined status return:

- Workflow runs associated with `fc205225...`: none returned
- Combined commit statuses: none returned

Therefore:

> **CI VERIFIED for the remediation PR content:** YES.
> **CI VERIFIED for the final main merge commit:** NOT independently demonstrated.

The repository's own tracker currently collapses this distinction because it calls F-009 CI VERIFIED, while its historical evidence points to the PR run.

Keep:

- PR CI = **PASS**
- Post-merge main CI = **EVIDENCE GAP**

until a successful run against the merged main SHA is observed.

---

## 5. The CI Workflow Is Substantially Good

`.github/workflows/ci.yml` performs:

1. Checkout with full history
2. Python 3.11
3. Editable install with dev dependencies
4. `compileall`
5. Import test
6. Raw-kernel static gate
7. Unit tests
8. Security invariant tests
9. Targeted security unit tests
10. Behavioral/integration/property suites

It also has a concurrency guard and a 30-minute timeout — a major improvement over the original baseline (zero workflows).

---

## 6. Architectural Improvement: One Server Gateway

`kerno/server/security.py` now implements:

```
HTTP / SSE / WebSocket / OpenAI / secure-app
            ↓
      build_gateway_engine()
            ↓
       ExecutionEngine
            ↓
   AllowList + CapabilityBroker + Budget
            ↓
           kernel
```

`build_gateway_engine()` is explicitly responsible for:

- Resolving the requested profile
- Preventing security downgrades
- Applying execution budgets
- Creating the `ExecutionEngine` choke point
- Recording transport/profile decisions

This addresses the most serious original-audit problem: different server surfaces could evolve separate security logic.

---

## 7. Profile Downgrade Protection

The implementation introduces `PROFILE_RANK`:

- `none = 0`
- `permissive = 1`
- `data_analysis = 2`
- `read_only = 3`

`resolve_effective_profile()` prevents a request from selecting something weaker than the server-authoritative default when downgrade is disabled. For example, if the server policy is `data_analysis`, a client request for `none` gets upgraded rather than accepted.

---

## 8. Runtime-Origin Authority

The remediation separates:

- agent-facing execution
- trusted runtime execution

with dedicated runtime APIs. Adversarial tests cover:

- public API attempting runtime origin
- trusted runtime path
- capability escalation combined with runtime origin
- self-grant attempts

and report passing locally. This is exactly the authority separation an agent runtime needs.

---

## 9. Capability Escalation Testing

The new capability suite contains **19 adversarial cases**, covering:

- self-grant prevention
- cross-agent isolation
- scope widening
- subject mutation
- expired parents
- revoked parents
- descendant revocation
- skill capability immutability
- runtime-origin + self-grant combinations

A new vulnerability was discovered during remediation: `workspace/../etc/*` could previously evade scope containment through pattern matching. It was caught by adversarial testing and fixed through scope normalization — a strong sign that the suite discovers previously unknown flaws rather than merely proving preselected assertions.

---

## 10. SSRF / Materialization Hardening

**F-002 — SSRF.** New URL policy includes:

- HTTP/HTTPS scheme restrictions
- Private IP blocking
- Loopback blocking
- Link-local blocking
- CGNAT blocking
- Multicast blocking
- DNS-resolution checks
- Credential rejection
- Redirect revalidation
- Connection/read/overall timeouts
- Download-size limits

**F-003 — materialization limits.** Adds:

- per-file limit
- per-request file-count limit
- total-byte limit
- URL-download limit
- time limit
- pre-decode Base64 sizing

**F-004 — storage isolation.** Files are moved into per-request directories rather than relying on a common filename namespace.

---

## 11. Raw-Kernel Bypass Protection: Defense-in-Depth

`scripts/check_raw_kernel.py` scans for dangerous patterns:

- unauthorized `KernelRuntime(`
- raw `kernel.execute(` in server code
- `urlretrieve(`

The security invariant suite also tests the static gate. Final regression scan:

- `urlretrieve(` → 0 real usages
- `make_server_engine(` → only canonical implementation
- `ORIGIN_RUNTIME` → restricted trusted paths
- `KernelRuntime(` → only approved bootstrap files
- raw `kernel.execute(` in `kerno/server/` → 0

Behavioral enforcement plus structural/static enforcement.

---

## 12. CORS

Previous baseline: `allow_origins=["*"]`.

New implementation resolves origins through:

1. Explicit configuration
2. `KERNO_CORS_ORIGINS`
3. Secure default `[]`

Wildcard is never implicit. Methods and headers are restricted, and credentials are only permitted with explicit non-wildcard origins.

---

## 13. Transport-Parity Question

In `app.py`, the WebSocket endpoint does:

```python
_build_gateway_engine(kernel, default_security, max_cells, transport="ws")
```

rather than taking a client-selected security profile. Using the server default is arguably safer, but it means WebSocket policy semantics differ from `/run` and `/stream`, where the request can specify a profile that is then attenuated against the server default.

An explicit transport-parity test is needed: does every transport intentionally implement the same security-policy semantics, or is WebSocket intentionally server-default-only?

---

## 14. Unauthenticated Operational Endpoints

`app.py` exposes:

- `/health/live`
- `/health`
- `/metrics`
- `/sessions`
- `/sessions/{session_id}`

`/health/live` is intentionally minimal, but `/health`, `/metrics`, and session endpoints can expose operational/session information (pool/session statistics; task/session details and portions of generated code/output).

Not automatically exploitable in every deployment, but should be explicitly governed by authentication/authorization policy. Classify separately as **management-plane / information-disclosure security**.

---

## 15. Reproducibility Problem

`pyproject.toml` uses open-ended ranges:

```
jupyter-client>=8.0
nbformat>=5.9
ipykernel>=6.0
fastapi>=0.100
pandas>=2.0
numpy>=1.24
```

No lock/constraint mechanism exists. Same source + different installation date ≠ guaranteed same dependency graph.

CI uses Python 3.11 but does not establish a fully locked dependency environment:

- Source reproducibility — good
- Environment reproducibility — not sufficient for a high-assurance release

---

## 16. Stale Documentation State Transitions

`docs/security/REMEDIATION_TRACKER.md` still says:

> Remaining: merge PR #5
> Remaining: merge PR #5 (release gate)

PR #5 has been merged. `BASELINE.md` contains historical sections that are correct historically but ambiguous if read as current state.

The state machine should be updated to:

```
IMPLEMENTED → TESTED LOCALLY → CI VERIFIED → MERGED → POST-MERGE VERIFIED
```

rather than stopping at CI VERIFIED.

---

## 17. Test Evidence Scope

Documented results:

- Unit: 1042 passed / 1 skipped
- Security invariants: 18 passed
- Behavioral/integration/property: 124 passed / 5 skipped

The PR reports these numbers and the actual CI run succeeded. Accept:

> The remediation branch was externally exercised successfully by GitHub Actions.

Do not promote this to "Kerno is proven secure." The tests establish specific invariants and regression properties; they do not establish absence of all vulnerabilities.

Correct assurance language: **security-hardened and evidence-backed, not formally secure.**

---

## 18. Architecture Assessment

| Area | Assessment |
|---|---|
| Execution choke point | 🟢 Strong |
| Server gateway unification | 🟢 Strong |
| Profile downgrade protection | 🟢 Strong |
| Runtime-origin separation | 🟢 Strong |
| Capability escalation defenses | 🟢 Strong |
| SSRF defenses | 🟢 Strong |
| Materialization limits | 🟢 Strong |
| File isolation | 🟢 Strong |
| CORS defaults | 🟢 Strong |
| Raw-kernel static gate | 🟢 Strong |
| Security invariant suite | 🟢 Strong |
| CI workflow | 🟢 Present |
| PR CI evidence | 🟢 Independently verified |
| Final-main CI evidence | 🟡 Not independently established |
| Dependency reproducibility | 🟠 Open |
| Branch protection | 🟡 Not verified |
| Management endpoint authorization | 🟠 Needs explicit review |
| Traceability current-state accuracy | 🟠 Stale entries |
| Release certification | 🟡 Not yet |

---

## 19. Most Important Finding

The repository has crossed an architectural threshold:

> Old: strong security components + inconsistent server boundaries
> New: centralized execution governance + adversarial verification + structural enforcement

The most convincing evidence is the loop:

```
audit → exploit-class identification → implementation → adversarial test
     → newly discovered P6 gap → fix → static gate → CI execution → merge
```

That is a healthy security-engineering loop.

---

## 20. Secure Server Notes

`secure_app.py` routes execution through `build_gateway_engine()` with `server_default=default_security` and `allow_downgrade=False`. It gives `FileMaterializer` a `MaterializationExecutor(engine)` rather than the raw kernel — closing both execution and materialization authorization through the governed engine.

Minor naming issue: task execution passes `kernel=engine` into the loop factory. It is actually a governed executor; renaming to `executor` would make accidental future bypasses less likely. Not a blocker.

### OpenAI-Compatible Gateway

Both synchronous and streaming paths in `openai_compat.py` call `build_gateway_engine()` with `server_default=default_security` and `allow_downgrade=False`. The F-005 concern is genuinely fixed — no bypass via `/v1/chat/completions`.

### Auth Toggle

`create_secure_app(enable_auth: bool = True)` supports `enable_auth=False` with an anonymous identity. Reasonable for development, but the deployment distinction must be unmistakable:

- **Development:** authentication can be disabled.
- **Production:** authentication must be enforced.

Prefer a startup/deployment policy over an easy accidental runtime switch.

---

## 21. Management-Plane Finding (F-011)

The secure server exposes `GET /health` without the authentication dependency, returning pool statistics and session count. The ordinary server also exposes `/sessions` and `/sessions/{session_id}`. `/usage` filters by `user_id`, which is directionally correct, but ownership must be proven consistently.

**Adversarial matrix required:**

| Attack | Expected |
|---|---|
| User A reads User B usage | DENY |
| User A guesses B session ID | DENY |
| User A cancels B session | DENY |
| User A requests B output | DENY |
| Anonymous reads session | DENY |
| Anonymous reads health | explicitly defined |
| Anonymous reads metrics | explicitly defined |

Scope for F-011: `/health`, `/metrics`, `/sessions`, `/sessions/{id}`, `/usage`, cancellation endpoints, `/v1/models`.

Questions:

1. Which endpoints are intentionally public?
2. Which require authentication?
3. What information can unauthenticated callers learn?
4. Can one authenticated user enumerate another user's sessions?
5. Can session IDs be used as authorization capabilities?
6. Does cancellation require ownership authorization?

---

## 22. Certification Matrix

| Gate | Result |
|---|---|
| PR #5 merged | 🟢 VERIFIED |
| Security remediation present on main | 🟢 VERIFIED |
| Canonical gateway | 🟢 VERIFIED |
| Raw-kernel materializer boundary | 🟢 VERIFIED |
| Profile downgrade protection | 🟢 VERIFIED |
| OpenAI sync governance | 🟢 VERIFIED |
| OpenAI streaming governance | 🟢 VERIFIED |
| Secure-app governance | 🟢 VERIFIED |
| CORS secure default | 🟢 VERIFIED |
| CI workflow installed | 🟢 VERIFIED |
| PR CI execution | 🟢 VERIFIED |
| Final-main CI execution | 🔴 NOT VERIFIED |
| Dependency locking | 🔴 NOT PRESENT |
| Management-plane authorization | 🟠 NEEDS AUDIT |
| Cross-user session isolation | 🟠 NEEDS ADVERSARIAL PROOF |
| Branch protection | 🟡 NOT VERIFIED |
| Release certification | 🔴 BLOCKED |

---

## 23. Next Phase — Phase 6 Post-Merge Certification

Stop re-auditing F-001 through F-010 at the same breadth. Highest-value work:

### P6.1 — CI
Obtain a successful run on `fc20522555d580b710a1836137a8b4650ccf4558`.

### P6.2 — Management plane
Create F-011 and adversarially test authorization.

### P6.3 — Identity isolation
Prove User A ≠ User B for:
- sessions
- cancellation
- usage
- memory
- files
- kernel ownership

### P6.4 — Dependency reproducibility
Introduce a deterministic dependency resolution mechanism (lock/constraints strategy and prove clean installation).

### P6.5 — Branch governance
Verify required status checks and branch protection.

### P6.6 — Traceability reconciliation
Change the documentation state machine from:

```
CI VERIFIED → MERGED
```

to:

```
CI VERIFIED → MERGED → POST-MERGE VERIFIED → CERTIFIED
```

### P6.7 — Static invariant completeness
Verify the static detector itself cannot be trivially bypassed through aliases, imports, indirect references, dynamically constructed calls, or alternate executor names.

### Release Gate
Only after A–F:

> **CERTIFIED FOR RELEASE CANDIDATE**

---

## Bottom Line

Kerno is substantially stronger than the pre-remediation state. The most important remediation claims are now backed by actual repository code, adversarial tests, and a real successful GitHub Actions execution. PR #5 was genuinely merged into `main`.

The repository is not yet fully certified. Remaining high-value gaps:

1. Post-merge CI evidence for the final main SHA
2. Dependency reproducibility
3. Management/observability endpoint authorization
4. Transport-parity verification
5. Traceability/documentation state reconciliation
6. Branch-protection verification

> **Kerno main: SECURITY-HARDENED / POST-REMEDIATION — NOT YET FINAL-CERTIFIED.**

The next logical operation is a post-merge adversarial certification pass against `fc205225...`, rather than another broad remediation round.

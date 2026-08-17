# Kerno — Proposed Detailed To-Do

**Repository:** `Abdus2023/Kerno`
**Based on:** the repository-level verification recorded in [`19-verification-passes-deep-audit.md`](19-verification-passes-deep-audit.md)
**Date:** 2026-08-17
**Status:** Proposed remediation program — findings turned into a **security-hardening + evidence-reconciliation** program, rather than another broad refactor.

---

## 0. Priority 0 — Freeze the evidence baseline

### 0.1 Create an audit baseline

Record:

- repository: `Abdus2023/Kerno`
- target: `main`
- exact HEAD SHA
- Python version/environment
- dependency lock state
- current test inventory
- current GitHub workflow inventory
- current security findings

**Deliverable:** `docs/audit/BASELINE.md`

### 0.2 Establish finding IDs

Use stable IDs:

```text
F-001  Raw-kernel FileMaterializer bypass
F-002  Unrestricted URL retrieval / SSRF surface
F-003  Unbounded file materialization
F-004  Upload filename collision/isolation
F-005  OpenAI security-profile downgrade wiring
F-006  secure_app security-profile downgrade wiring
F-007  Missing endpoint-level security tests
F-008  Runtime-origin authority boundary
F-009  CI/evidence gap
F-010  CORS production policy
```

Do **not** delete the findings when fixed; change their status.

---

## 1. P0 — Correct the execution boundary

### 1.1 Remove raw-kernel ownership from `FileMaterializer`

#### Current

```text
FileMaterializer(kernel)
        ↓
kernel.execute(load_code)
```

#### Target

Prefer:

```text
FileMaterializer
        ↓
validated materialization operation
        ↓
ExecutionEngine
        ↓
capability / policy / budget / audit
        ↓
Kernel
```

#### Recommended design

Do **not** simply replace:

```python
self.kernel
```

with:

```python
self.engine
```

and blindly execute generated code.

Instead introduce a narrow interface, e.g.:

```text
MaterializationExecutor
```

with only the operation needed for loading validated artifacts.

This prevents `FileMaterializer` from becoming another general-purpose execution authority.

#### Acceptance criteria

- `FileMaterializer` cannot import/use `KernelRuntime`.
- No `kernel.execute()` remains in `files.py`.
- Materialization execution produces normal execution/audit records.
- capability checks apply.
- allowlist applies.
- budget applies.
- cancellation/finalization applies.
- tests prove the raw kernel receives no operation outside `ExecutionEngine`.

**Priority: P0**

---

## 2. P0 — Harden file ingestion

### 2.1 Implement strict URL policy

Create a dedicated URL validator.

Reject by default:

```text
file://  ftp://  gopher://  data://  javascript://
```

Prefer an explicit allowlist:

```text
http://  https://
```

Then resolve the hostname and reject:

```text
127.0.0.0/8
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
169.254.0.0/16
::1
fc00::/7
fe80::/10
```

and other environment-specific internal ranges.

### 2.2 Redirect protection

Validate **every redirect**, not only the original URL.

Otherwise:

```text
https://attacker.example
        ↓ redirect
http://127.0.0.1:8000
```

can defeat the first check.

### 2.3 Timeouts

Set:

```text
connect timeout
read timeout
overall timeout
```

### 2.4 Size limit

Enforce a maximum response size **while downloading** rather than after the entire response has already been stored.

### 2.5 Acceptance

Tests must demonstrate rejection of:

- localhost
- private IPv4
- loopback IPv6
- link-local
- redirect → private IP
- unsupported schemes
- oversized response
- timeout

**Priority: P0**

---

## 3. P0 — Bound file materialization

### 3.1 Establish explicit upload/download budgets

Define configuration:

```text
MAX_FILE_BYTES
MAX_TOTAL_FILE_BYTES
MAX_FILES_PER_REQUEST
MAX_URL_DOWNLOAD_BYTES
MAX_MATERIALIZATION_TIME
```

Do **not** rely on the request's declared `size`. The server must measure actual bytes.

### 3.2 Base64

Avoid:

```python
base64.b64decode(entire_string)
```

for arbitrarily large input. Use bounded decoding or reject before allocation based on encoded size.

### 3.3 Acceptance

Test:

```text
0 bytes
1 byte
maximum
maximum + 1
many files
combined-size overflow
```

**Priority: P0**

---

## 4. P1 — Fix server security-profile enforcement

### 4.1 Consolidate profile resolution

There should be exactly **one authoritative mechanism**:

```text
requested_profile
        ↓
resolve_effective_profile(
    requested,
    server_default,
    allow_downgrade=False
)
        ↓
effective_profile
```

Every public server transport must use it.

### 4.2 Affected surfaces

Explicitly audit:

```text
kerno/server/app.py
kerno/server/secure_app.py
kerno/server/openai_compat.py
```

and every:

```python
make_server_engine(...)
```

call.

### 4.3 Acceptance invariant

If `server_default = data_analysis`, then:

```text
client = permissive → effective = data_analysis
client = none       → effective = data_analysis
```

while:

```text
client = read_only
```

may remain `read_only` if that is intentionally stronger than the server default.

---

## 5. P1 — Eliminate duplicate security gateways

### 5.1 Make `server/app.py` the canonical security gateway

The current `app.py` path appears to have the strongest implementation.

Prefer:

```text
                 Public APIs
                      │
           ┌──────────┼──────────┐
           ▼          ▼          ▼
          /run     /stream      /ws
           │          │          │
           └──────────┼──────────┘
                      ▼
              canonical gateway
                      ▼
               ExecutionEngine
```

Avoid maintaining independent security logic in:

```text
secure_app.py
openai_compat.py
```

### 5.2 Options

Either:

1. make them thin adapters over the canonical gateway, or
2. remove them if obsolete.

Do not maintain three independently evolving security implementations.

**Priority: P1**

---

## 6. P1 — Runtime-origin authority

### 6.1 Harden `ORIGIN_RUNTIME`

Current conceptual model:

```python
engine.execute(..., origin=ORIGIN_RUNTIME)
```

is based on a caller-provided authority label.

### 6.2 Target

Public/agent-facing APIs should not be able to manufacture runtime authority.

Possible design:

```text
public execute()       → ORIGIN_AGENT
internal runtime_execute() → ORIGIN_RUNTIME
```

or use an internal authority token/capability.

### 6.3 Tests

Explicitly attempt:

```text
agent → ORIGIN_RUNTIME
agent → runtime_execute
agent → forged runtime token
agent → manipulated execution request
```

Expected: **DENIED**

**Priority: P1**

---

## 7. P1 — Capability self-escalation

### 7.1 Complete K-008 adversarial suite

Test:

#### Self-grant

```text
agent → grant(kernel.execute)
```

must fail.

#### Cross-agent grant

```text
agent-A grant → agent-B use
```

must fail.

#### Scope widening

```text
parent = workspace/*
child  = /
```

must fail.

#### Subject mutation

```text
parent.subject = A
child.subject  = B
```

must fail.

#### Expired parent

Must fail.

#### Revoked parent

Must fail.

#### Capability mutation

Changing skill declarations after granting must not widen existing authority.

#### Runtime-origin combination

Try:

```text
self-grant + ORIGIN_RUNTIME
```

and verify neither route produces privilege escalation.

**Priority: P1**

---

## 8. P1 — File isolation

### 8.1 Replace predictable upload paths

Current conceptual model:

```text
/tmp/kerno_uploads/<filename>
```

Target:

```text
/tmp/kerno_uploads/<session>/<random-id>/<safe-name>
```

or preferably:

```text
<random server-generated object ID>
```

The original filename should be **metadata, not the storage identity**.

### 8.2 Acceptance

Concurrent users uploading `sales.csv` must never overwrite or observe one another's files.

Test:

- same user
- different users
- concurrent requests
- concurrent materialization
- failed requests
- cleanup

**Priority: P1**

---

## 9. P1 — File lifecycle cleanup

### 9.1 Guarantee cleanup

Define:

```text
success     → cleanup
failure     → cleanup
timeout     → cleanup
cancellation → cleanup
disconnect  → cleanup
```

Use `try/finally`.

Also establish **periodic orphan cleanup**. Otherwise `/tmp/kerno_uploads` becomes a persistent resource-exhaustion vector.

---

## 10. P1 — Endpoint security tests

### 10.1 Add actual transport-level tests

Do not test only `make_server_engine()`. Test the real endpoints.

#### `/run`

```text
profile downgrade
capability denial
allowlist denial
raw-kernel non-invocation
```

#### `/stream`

Same tests.

#### `/ws`

Same tests.

#### OpenAI-compatible API

Add:

```text
/v1/chat/completions
```

sync + streaming.

#### Secure app

Test its actual request path independently.

This is critical because the existing tests can otherwise create a false impression that all server implementations share the same guarantees.

---

## 11. P1 — FileMaterializer test suite

### 11.1 Create dedicated tests

Recommended:

```text
tests/unit/test_file_materializer_security.py
```

Test:

#### Input

- base64
- URL
- image URL
- file URL
- malformed file object
- missing fields

#### URL security

- localhost
- private network
- link-local
- IPv6 loopback
- redirects
- unsupported scheme

#### Resource limits

- oversized base64
- oversized download
- too many files
- total-size overflow

#### Execution

Assert:

```python
ExecutionEngine.calls == expected
RawKernel.direct_calls == 0
```

#### Isolation

Concurrent identical filenames.

#### Cleanup

Success/failure/cancellation.

---

## 12. P2 — CORS

### 12.1 Replace wildcard production CORS

Current broad policy: `*`

Define:

```text
ALLOWED_ORIGINS
ALLOWED_METHODS
ALLOWED_HEADERS
```

with secure deployment defaults.

Avoid breaking local development by providing an explicit development configuration.

### 12.2 Test

Unauthorized browser origin:

```text
Origin: https://evil.example
```

must not receive permissive CORS authorization in production.

---

## 13. P2 — Observability and audit

### 13.1 Make bypass attempts observable

Every security rejection should identify:

```text
execution_id
subject
origin
capability
requested profile
effective profile
policy decision
reason
transport
```

For file materialization:

```text
file ID
source type
size
URL
hostname
decision
```

Do **not** log:

- secrets
- API keys
- raw file contents
- authorization headers
- sensitive URLs containing credentials

---

## 14. P2 — Traceability reconciliation

### 14.1 Update the formal traceability report

Do not simply mark the previous claims as passed. Create a table:

| Claim | Source | Test | Status |
|---|---|---|---|
| Central engine | `execution/engine.py` | engine tests | PASS |
| Streaming lifecycle | engine | stream tests | PASS |
| Cross-loop choke point | loops | loop tests | PASS |
| Server `/run` gateway | `server/app.py` | server tests | PASS |
| File materializer gateway | `server/files.py` | — | **FAIL** |
| OpenAI profile enforcement | `openai_compat.py` | — | **FAIL** |
| Runtime origin isolation | engine/server | incomplete | **OPEN** |
| URL SSRF protection | files.py | incomplete | **OPEN** |
| CI execution | GitHub Actions | none | **NOT VERIFIED** |

This prevents the report from becoming more optimistic than the repository.

---

## 15. P2 — CI bootstrap

### 15.1 Install an actual GitHub Actions workflow

This remains essential. Create:

```text
.github/workflows/ci.yml
```

At minimum:

```text
checkout
   ↓
Python setup
   ↓
dependency installation
   ↓
lint
   ↓
unit tests
   ↓
integration tests
```

Then require:

```text
pytest
coverage
security tests
```

### 15.2 Important evidence rule

Do **not** write `CI PASS` until GitHub Actions actually executes it. Use `CI CONFIGURED` until then.

After execution: `CI VERIFIED` with:

- workflow run ID
- commit SHA
- timestamp
- result

---

## 16. P3 — Regression gate

### 16.1 Add a security invariant test suite

Create something like:

```text
tests/security/
```

with a compact invariant suite:

```text
test_no_raw_kernel_agent_path
test_no_raw_kernel_server_path
test_capability_denial_pre_execution
test_allowlist_denial_pre_execution
test_runtime_origin_not_agent_selectable
test_profile_cannot_downgrade
test_url_cannot_reach_private_network
test_file_size_is_bounded
test_uploads_are_isolated
test_streaming_preserves_security_boundary
test_cancellation_finalizes_transaction
```

These should become release gates.

---

## 17. P3 — Static architecture gate

### 17.1 Add a raw-kernel execution detector

A lightweight CI check can flag new:

```text
kernel.execute(
kernel.execute_silent(
```

outside approved locations.

For example:

```text
allowed: kerno/execution/engine.py
```

Everything else requires explicit review. This isn't a substitute for tests, but it prevents regression.

---

## 18. P3 — Dependency and supply-chain verification

### 18.1 Add dependency security checks

At minimum:

```text
lock dependencies
dependency vulnerability scan
SBOM
license inventory
```

Pin production dependencies where appropriate. Record results as CI artifacts.

---

## 19. P3 — Final security documentation

### 19.1 Rewrite the architecture security claim

Avoid:

> "All execution always goes through the security choke point."

until F1 is fixed.

Use the accurate interim statement:

> "Agent execution paths are routed through `ExecutionEngine`; legacy server-side materialization currently retains a separate raw-kernel execution path and is scheduled for consolidation."

After remediation, restore the stronger invariant only after endpoint tests pass.

---

## 20. Recommended implementation order

```text
PHASE 1 — STOP THE BLEED
────────────────────────
1. Freeze SHA
2. F-001 raw kernel materializer
3. F-002 SSRF
4. F-003 file-size limits
5. F-005/F-006 profile downgrade
        ↓
PHASE 2 — UNIFY
────────────────
6. Canonical server gateway
7. Remove duplicate security paths
8. Runtime-origin authority
9. Capability self-escalation tests
        ↓
PHASE 3 — HARDEN
────────────────
10. File isolation
11. Cleanup
12. CORS
13. Observability
        ↓
PHASE 4 — PROVE
───────────────
14. Endpoint integration tests
15. Security invariant suite
16. Static raw-kernel gate
17. GitHub Actions
        ↓
PHASE 5 — CERTIFY
─────────────────
18. Run CI on exact commit
19. Reconcile traceability
20. Security regression audit
21. Release gate
```

---

## 21. Definition of Done

Kerno should **not** be called security-complete until all of these are simultaneously true:

```text
[ ] No unapproved raw-kernel execution path
[ ] FileMaterializer uses restricted execution authority
[ ] SSRF controls verified
[ ] File sizes bounded
[ ] Uploads isolated
[ ] All public transports use one security gateway
[ ] Client cannot downgrade server policy
[ ] Agent cannot obtain ORIGIN_RUNTIME
[ ] Capability self-grant fails
[ ] Cross-agent capability use fails
[ ] Streaming has equivalent enforcement
[ ] Security tests run against real endpoints
[ ] GitHub Actions executes successfully
[ ] Exact commit SHA is recorded
[ ] Traceability report matches source
[ ] No "PASS" claims based solely on static inspection
```

### Overall recommendation

**Do not redesign Kerno's `ExecutionEngine` now.** The core transaction/security architecture is one of the strongest parts of the repository.

The highest-value work is **boundary consolidation**: remove the parallel raw-kernel/server paths, make the existing gateway authoritative everywhere, then prove the result with endpoint-level adversarial tests and real GitHub CI.

---

## 22. Next: execute the remediation plan in a controlled sequence

The next step should be **implementation + verification**, not another broad architectural analysis.

### Step 1 — Create the remediation branch

From the verified `main` baseline:

```text
security/hardening-server-boundaries
```

Record:

- baseline SHA
- current test result
- current finding list
- expected changes

### Step 2 — Fix the highest-risk boundary first

**F-001: `FileMaterializer` raw-kernel bypass**

Refactor toward:

```text
Request
   ↓
FileMaterializer
   ↓
validated MaterializationOperation
   ↓
ExecutionEngine
   ↓
Capability + Policy + Budget
   ↓
Kernel
```

Do **not** expose a general-purpose executor to the materializer.

### Step 3 — Fix profile enforcement everywhere

Search every `make_server_engine()` call and require an explicit security policy.

The invariant should become:

```text
public request
    ↓
requested profile
    ↓
resolve_effective_profile()
    ↓
server-authoritative profile
    ↓
ExecutionEngine
```

Then add regression tests for:

```text
data_analysis → permissive    DENY downgrade
data_analysis → none          DENY downgrade
data_analysis → data_analysis ALLOW
data_analysis → read_only     ALLOW if ranking permits
```

Do this for:

- `/run`
- `/stream`
- `/ws`
- OpenAI sync
- OpenAI streaming
- `secure_app`

### Step 4 — Lock down file ingestion

Implement:

```text
URL allowlist
private-network blocking
redirect revalidation
download timeout
download-size limit
per-request file count limit
total request-size limit
```

Then isolate uploaded files with server-generated IDs.

### Step 5 — Add the missing adversarial tests

The most valuable new tests are:

```text
test_file_materializer_cannot_execute_raw_kernel
test_openai_cannot_downgrade_security_profile
test_secure_app_cannot_downgrade_security_profile
test_streaming_cannot_downgrade_security_profile
test_ws_cannot_downgrade_security_profile
test_url_cannot_access_loopback
test_url_redirect_cannot_access_private_network
test_file_materialization_is_size_bounded
test_uploads_are_cross_user_isolated
test_agent_cannot_select_runtime_origin
test_agent_cannot_self_grant_capability
```

### Step 6 — Run locally, but classify evidence correctly

Use three states:

```text
IMPLEMENTED
TESTED LOCALLY
CI VERIFIED
```

Never collapse them into a single `PASS`.

### Step 7 — Install actual GitHub CI

Only after the local suite is stable:

```text
.github/workflows/ci.yml
```

Then execute it on the remediation commit.

The final evidence should identify:

```text
commit SHA
workflow run ID
test count
failure count
coverage
```

### Step 8 — Re-audit `main` after the fixes

Perform a fresh source search for:

```text
kernel.execute(
KernelRuntime
make_server_engine(
ORIGIN_RUNTIME
security=
urlretrieve(
```

The objective is to prove that **no old path survived the refactor**.

---

## 23. The immediate next deliverable

Create a single tracking document:

```text
docs/security/REMEDIATION_TRACKER.md
```

with:

| ID | Finding | Fix | Test | CI | Status |
|---|---|---|---|---|---|
| F-001 | Raw kernel materializer | Engine boundary | `test_file_materializer...` | Pending | 🔴 |
| F-002 | SSRF | URL policy | SSRF suite | Pending | 🔴 |
| F-003 | Unbounded files | Resource limits | size tests | Pending | 🔴 |
| F-004 | Filename collision | Isolated storage | concurrency tests | Pending | 🟡 |
| F-005 | OpenAI downgrade | server default | endpoint tests | Pending | 🔴 |
| F-006 | Secure-app downgrade | server default | endpoint tests | Pending | 🔴 |
| F-007 | Missing endpoint tests | integration suite | all transports | Pending | 🔴 |
| F-008 | Runtime-origin authority | private capability | escalation tests | Pending | 🟡 |
| F-009 | CI evidence | GitHub Actions | workflow | Pending | 🔴 |
| F-010 | CORS | explicit origins | CORS tests | Pending | 🟡 |

### Decision gate

After **F-001, F-002, F-005, F-006, F-007** are fixed and tested, do another adversarial review.

If those pass, Kerno moves from:

> **strong core security architecture with server-boundary inconsistencies**

to:

> **unified security architecture with externally verified transport enforcement.**

That is the next meaningful milestone.

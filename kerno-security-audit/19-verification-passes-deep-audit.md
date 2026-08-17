# Kerno — Deep Verification Passes (arena audit log)

**Repository:** `Abdus2023/Kerno`
**Branch audited:** `main` (workspace session branch: `arena/01a00e08-kerno`)
**Baseline commit:** `36943e1c854d576f1d3bbff96481ae57e7fb94b5`
**Date:** 2026-08-17
**Status:** Live source-level verification of the merged security work (PR #3) against the actual `main` tree, GitHub metadata, and the test suite.

---

## 0. Executive summary

Kerno is **not** in the state of "security implementation missing". It is much closer to:

> **Implementation + extensive testing infrastructure + extensive audit documentation, but insufficient external execution/governance evidence to promote the strongest claims to verified status.**

The core security refactor is real and strong:

- The canonical `_prepare_transaction` / `_finalize_transaction` lifecycle is **implemented in `main`**, including guaranteed finalization via `finally`.
- Normal, silent, and streaming execution surfaces are all routed through the engine.
- Capability authorization, human approval, cancellation, and allowlist policy are enforced **before** kernel execution, and denial is tested to mean "the kernel never sees the code".
- The capability broker implements explicit, attributable, subject-bound, expiring, revocable, and attenuable grants.

However, the verification found **three concrete implementation-level findings** concentrated at the *server integration boundary*, plus governance gaps:

| ID | Finding | Status |
|---|---|---|
| F1 | `FileMaterializer` executes generated load code directly on the **raw kernel**, bypassing `ExecutionEngine` (K-001 transport bypass) | 🔴 Confirmed |
| F2 | Unrestricted `urllib.request.urlretrieve(url, …)` URL retrieval — SSRF/resource-exhaustion surface | 🟠 Confirmed attack surface |
| F3 | No materialization size limits (base64 / URL downloads are unbounded) | 🟠 Confirmed |
| F4 | Shared upload filename namespace (`/tmp/kerno_uploads/<safe_name>`) — cross-request collision/isolation risk | 🟡 Needs isolation test |
| F5 | OpenAI-compatible and `secure_app` endpoints fail to pass `server_default` into `make_server_engine()` — client can select a weaker security profile (K-012 wiring defect) | 🟠 Confirmed |

And objectively missing:

- **GitHub Actions execution evidence** — the GitHub Actions API reports `total_count: 0` workflows. There is no workflow registered with GitHub, hence no externally executed CI proof.
- **`main` branch protection** — `protection: disabled`, no required status checks, enforcement off.

The key architectural correction: Kerno has **two generations of server security architecture** visible in `main`:

```text
Kerno main
                     │
       ┌─────────────┴─────────────┐
       │                           │
 server/app.py              secure_app.py /
       │                     openai_compat.py
       │                           │
 Gateway correctly wired       older/incomplete
       │                           │
       ▼                           ▼
 ExecutionEngine              ExecutionEngine
       │                           │
       ▼                     + raw FileMaterializer
     Kernel                          │
                                    ▼
                                 Raw Kernel
```

The core `ExecutionEngine` is not the problem. The highest-priority remediation is to **collapse all public server implementations onto the already-correct gateway path, remove raw-kernel ownership from `FileMaterializer`, and add endpoint-level security tests**.

---

## 1. Pass 1 — Baseline verification

### 1.1 The main branch baseline

The main branch is currently at:

```text
36943e1c854d576f1d3bbff96481ae57e7fb94b5
```

The latest commit is a **verified GitHub merge commit for PR #3**:

> `feat(security): complete Phase D/E runtime hardening, canonical execution transactions, and traceability matrix`

The Phase D/E work from `arena/01a00c3b-kerno` is therefore **merged into main**, not merely sitting on the arena branch.

### 1.2 Branch landscape

Verified branches:

```text
main
arena/01a00bb7-kerno
arena/01a00c3b-kerno
arena/01a0050d-kerno
arena/01a0064f-kerno
arena/019fa305-kerno
```

This allows historical arena states to be compared against the actual merged baseline rather than treating each audit report independently.

### 1.3 Repository structure

The current tree contains substantial implementation, not just documentation/scaffolding:

```text
kerno/                core Python implementation
kerno/audit/
kerno/benchmark/
kerno/cli/
kerno/comms/
docs/
examples/
extraction/
kerno-security-audit/
```

The implementation includes security-sensitive components: `capability.py`, `capability_exec.py`, `approval.py`, `action.py`, `agent.py`, `_run.py`, `artifacts.py`, `bus.py`, `cancel.py`, `compose.py`.

### 1.4 Immediate governance/CI issue

- `main` is **not protected**: GitHub branch metadata reports `protection: disabled`, `required status checks: none`, `enforcement: off`.
- `.github/workflows` is **not present** at the expected path on `main`.

Even if code and tests are excellent, repository governance does not currently prevent an unverified commit from reaching the default branch.

### 1.5 Documentation vs implementation

The repository contains substantial audit/traceability documentation:

```text
docs/TRACEABILITY_REPORT.md     ~33 KB
docs/implementation-status.md   ~39 KB
docs/kerno-deep-audit.md        ~75 KB
```

The stronger test is therefore not "does the documentation say the security phases are complete?" but:

> **Does every security claim in the audit/traceability material have corresponding implementation + test evidence in the current `main` commit?**

Recommended verification order:

1. Git integrity
2. CI reality
3. Test inventory
4. Security implementation cross-check
5. Traceability claims
6. Dependency/runtime reproducibility
7. Release readiness

---

## 2. Pass 2 — Deep verification of the `main` tree

### 2.1 CI evidence — the biggest gap

The GitHub Actions API reports **`total_count: 0` workflows**. For the current `main` commit:

> **There is no GitHub Actions execution evidence.**

This is stronger than "CI is failing" or "CI wasn't checked": there is presently **no workflow registered with GitHub**. A CI specification in documentation does **not** constitute a passed CI gate.

### 2.2 Test organization

The repository contains a proper test hierarchy:

```text
tests/
├── behavioral/
├── integration/
├── property/
├── unit/
├── fixtures/
└── conftest.py
```

Unit, behavioral, integration, and property-based tests plus fixtures indicate a multi-level testing architecture. But **repository presence ≠ execution evidence**.

| Claim | Evidence |
|---|---|
| Test suite exists | ✅ YES — repository evidence |
| Multiple testing layers exist | ✅ YES |
| Property testing exists | ✅ YES |
| Integration tests exist | ✅ YES |
| Tests passed on current `main` | ❌ NOT PROVEN |
| GitHub CI passed | ❌ NO |
| Required CI gate enforced | ❌ NO |

### 2.3 Dependency architecture

`pyproject.toml` confirms Kerno is intentionally a **lean core + optional packs**.

Core dependencies are only:

```text
jupyter-client
nbformat
ipykernel
pyyaml
```

Analytical, server, LLM-provider, SQL, NLP, graph, document, and security dependencies are optional. The project declares `version = "0.2.1-dev"` and requires `Python >= 3.11`.

**Open question:** are minimum-version ranges sufficiently reproducible? E.g. `jupyter-client>=8.0` is deliberately open-ended; two installations months apart can resolve different dependency graphs unless a lock/constraints mechanism exists elsewhere.

### 2.4 Security audit decomposition

The dedicated security-audit corpus has separate documents covering:

1. executive summary
2. project identity/scope
3. architecture/threat model
4. security findings
5. critical issues
6. evidence/verification
7. dependency/supply chain
8. runtime/sandbox security
9. cryptography/secrets
10. network/API security
11. data/storage security
12. code quality/testing
13. remediation plan

The individual claims in `06-evidence-and-verification.md` and `12-code-quality-and-testing.md` must be checked against observable repository/GitHub evidence.

### 2.5 Evidence matrix after this pass

| Area | Current assessment |
|---|---|
| Source implementation | 🟢 **Present** |
| Security architecture | 🟢 **Substantial** |
| Test architecture | 🟢 **Substantial** |
| Security audit documentation | 🟢 **Substantial** |
| Traceability documentation | 🟢 **Present** |
| Latest security work merged to `main` | 🟢 **Verified** |
| Commit cryptographic verification | 🟢 **Verified for latest merge** |
| GitHub Actions workflow | 🔴 **Absent** |
| GitHub CI execution evidence | 🔴 **Absent** |
| `main` branch protection | 🔴 **Absent** |
| Required status checks | 🔴 **Absent** |
| Current test suite actually executed | 🟡 **Not established from GitHub evidence** |
| Reproducible dependency resolution | 🟡 **Needs verification** |
| Security claims independently reconciled to code/tests | 🟡 **Still in progress** |

---

## 3. Pass 3 — Execution choke point

### 3.1 The central execution boundary is real

`kerno/_run.py` explicitly constructs an `ExecutionEngine` and passes that engine to the loop:

```python
common = dict(kernel=engine, llm=llm, verbose=verbose)
```

Loops never receive the raw kernel; agent execution is intended to pass through `ExecutionEngine`. This is a real architectural improvement, not merely documentation.

### 3.2 `_prepare_transaction` really exists

`kerno/execution/engine.py` contains `_prepare_transaction(...)`, which establishes, before execution proceeds:

- execution ID
- monotonic sequence
- capability set
- declared effects
- action state machine
- provenance
- execution-requested event
- capability authorization
- human approval
- cancellation
- allowlist policy

### 3.3 Fail-closed authorization ordering

```text
agent execution
      ↓
capability authorization
      ↓
human approval (when required)
      ↓
cancellation check
      ↓
allowlist policy
      ↓
kernel execution
```

A capability violation returns a synthetic `CellOutput` and does **not** reach the kernel. The same pattern is used for approval and allowlist denial.

### 3.4 Action lifecycle

`kerno/action.py` defines an explicit `Action` abstraction with terminal states:

```text
SUCCESS  FAILURE  CANCELLED  REJECTED  EXPIRED
```

The state machine rejects transitions after a terminal state and rejects transitions not listed in its `ALLOWED` table. Retry semantics are explicit:

```text
SAFE  IDEMPOTENT  NON_IDEMPOTENT  UNKNOWN
```

with conservative behavior for unknown/non-idempotent actions.

### 3.5 Open question at this point

The repository's current `ExecutionEngine` contains `_prepare_transaction`, but a repository search did not initially find `_finalize_transaction`. The direct file fetch proved `_prepare_transaction` exists (the search index appeared stale/incomplete), so the negative search result was **not** treated as proof that `_finalize_transaction` is absent — it became the verification point:

> Did the claimed `_prepare_transaction` / `_finalize_transaction` unified lifecycle actually land completely in `main`, or did only the preparation half land?

### 3.6 Assessment

| Property | Assessment |
|---|---|
| Universal execution abstraction | 🟢 Strong evidence |
| Agent → ExecutionEngine routing | 🟢 Strong evidence |
| Capability authorization | 🟢 Implemented |
| Fail-closed human approval | 🟢 Implemented |
| Allowlist enforcement | 🟢 Implemented |
| Immutable execution records | 🟢 Implemented |
| Causal execution events | 🟢 Implemented |
| Action state machine | 🟢 Implemented |
| Retry/idempotency policy | 🟢 Implemented |
| Pre-execution transaction preparation | 🟢 Implemented |
| Unified finalization | 🟡 Not yet proven |
| Every execution path uses the choke point | 🟡 Needs exhaustive path audit |
| Runtime/test execution on GitHub | 🔴 No CI workflows |

---

## 4. Pass 4 — K-001 bypass audit

The GitHub code-search connector returned no indexed results, even for the repository itself, so empty search results were **not** interpreted as proof of absence.

### 4.1 What is proven

The architecture explicitly establishes:

```text
agent / loop → ExecutionEngine → policy + capability + approval → kernel
```

and `ExecutionEngine` is intended to be the sole executor. The `Action` abstraction reinforces this: execution is a first-class action with authorization, lifecycle, retry, and terminal-state semantics.

### 4.2 What is not yet proven

The security invariant is stronger:

> No possible agent-controlled path can invoke the underlying kernel directly.

To prove it, every occurrence of the following must be enumerated and classified:

```text
KernelRuntime(...)
Executor(...)
.execute(...)
.execute_silent(...)
kernel.execute(...)
kernel.execute_silent(...)
```

Classification:

1. inside `ExecutionEngine` → acceptable
2. trusted runtime/setup path → potentially acceptable, but must be explicitly classified
3. agent/loop/plugin path → **security bypass**
4. test/mock/example only → not a production bypass

### 4.3 The architectural distinction that matters

The repository deliberately distinguishes:

```text
ORIGIN_AGENT    — LLM-generated code
ORIGIN_RUNTIME  — trusted host/runtime code
```

So a raw kernel invocation is not automatically a vulnerability. The real question:

> Can an `ORIGIN_AGENT` request obtain or reach the raw executor without going through the engine?

That is the correct K-001 test.

### 4.4 Trust boundary flag

`ORIGIN_RUNTIME` execution deliberately bypasses the agent allowlist/capability policy. That can be legitimate — but it means every caller capable of selecting `ORIGIN_RUNTIME` becomes part of the trusted computing base:

```text
Who can set origin?
        ↓
Who can construct ExecutionEngine?
        ↓
Who can obtain the underlying kernel?
        ↓
Who can call ORIGIN_RUNTIME?
```

If an agent-controlled component can influence any of those four boundaries, the apparent choke point can be bypassed without ever calling `kernel.execute()` directly.

### 4.5 Status

> **K-001 = IMPLEMENTED ARCHITECTURE, NOT YET EXHAUSTIVELY PROVEN.**

The implementation evidence is strong enough that the choke-point architecture cannot be called missing or merely aspirational — but the stronger claim ("all execution paths are guaranteed to pass through the security boundary") is not certified until the raw-kernel references and `ORIGIN_RUNTIME` trust paths are exhaustively reconciled.

---

## 5. Pass 5 — K-001 path audit: decisive result

### 5.1 The unified transaction lifecycle is complete

The previous uncertainty about `_finalize_transaction` is resolved. `ExecutionEngine` contains **both** `_prepare_transaction()` and `_finalize_transaction()`, and `execute()` follows the canonical lifecycle:

```text
_prepare_transaction()
        │
        ├─ capability authorization
        ├─ human approval
        ├─ cancellation
        ├─ allowlist
        ├─ effect declaration
        └─ RUNNING
        │
        ▼
kernel.execute()
        │
        ▼
finally:
    _finalize_transaction()
```

The `finally` block is particularly important: finalization executes even when the underlying kernel raises.

**Verdict: 🟢 Confirmed** — validates the architectural refactoring claim.

### 5.2 `execute_silent()` cannot bypass the lifecycle

`execute_silent()` does not call the kernel directly; it delegates to `self.execute(...)`, inheriting the entire authorization/policy/finalization lifecycle.

**Verdict: 🟢 Protected.**

### 5.3 Streaming execution is also inside the boundary

`stream_execute()` independently calls `_prepare_transaction()` and always calls `_finalize_transaction()` in its `finally` block. It supports both native kernel streaming and fallback to ordinary `kernel.execute()`, maintaining the transaction lifecycle.

This closes a common security gap where a streaming API accidentally bypasses normal execution controls.

**Verdict: 🟢 Protected.**

### 5.4 Raw kernel calls exist — classified as trusted setup

`kerno/_run.py` directly calls `kernel.execute(...)` for:

- loading skills
- installing the allowlist's kernel-side import hook
- isolated-kernel initialization
- pool-worker initialization

These are host-side setup operations performed **before** the `ExecutionEngine` is created; the subsequent agent loop receives `engine`, not the raw kernel.

| Path | Classification |
|---|---|
| `ExecutionEngine.execute()` → kernel | 🟢 Protected |
| `ExecutionEngine.execute_silent()` | 🟢 Protected |
| `ExecutionEngine.stream_execute()` | 🟢 Protected |
| `run()` → skill bootstrap | 🟡 Trusted setup |
| `run()` → allowlist kernel hook | 🟡 Trusted setup |
| isolated kernel initialization | 🟡 Trusted setup |
| pool allowlist initialization | 🟡 Trusted setup |
| loop → raw kernel | 🟢 No evidence found |
| agent → raw kernel | 🟢 No evidence found |

### 5.5 Governance issue around trusted setup

The security boundary currently relies partly on **caller discipline**: `_run.py` is trusted not to hand the raw kernel to an agent. Reasonable for the current architecture, but weaker than making the boundary structurally impossible to violate.

```text
Current:
_run.py
 ├── raw KernelRuntime ── trusted setup
 │
 └── ExecutionEngine
       └── loop

Stronger boundary:
_run.py
 └── privileged runtime
       ├── setup interface
       └── ExecutionEngine
             └── loop
                  └── Executor protocol only
```

The stronger model makes accidental future bypasses much harder.

### 5.6 Subtle issue: `ORIGIN_RUNTIME`

The engine intentionally skips agent policy when `origin == ORIGIN_RUNTIME`. The default is safely `ORIGIN_AGENT`, but if untrusted code can somehow call `engine.execute(..., origin=ORIGIN_RUNTIME)`, the allowlist/capability checks would be bypassed. This deserves a dedicated test proving agent-facing APIs cannot elevate themselves to runtime origin.

### 5.7 K-001 final status after this pass

- 🟢 Architecture confirmed: the canonical execution transaction lifecycle is implemented in `main`, including centralized preparation and guaranteed finalization.
- 🟢 The three execution surfaces — normal, silent, streaming — are all routed through that lifecycle.
- 🟡 The absolute claim that no untrusted caller can exploit a trusted/raw-kernel path still requires explicit testing of the `ORIGIN_RUNTIME` boundary and trusted setup interfaces.

| Item | Status |
|---|---|
| K-001 | 🟢 Implemented / strongly evidenced |
| K-001 absolute proof | 🟡 Needs adversarial boundary tests |
| Transaction unification | 🟢 Confirmed |
| Finalization guarantee | 🟢 Confirmed via `finally` |
| Streaming parity | 🟢 Confirmed |
| Raw kernel setup calls | 🟡 Trusted and intentionally outside agent execution path |
| Runtime-origin privilege boundary | 🟡 Next critical test |
| GitHub CI evidence | 🔴 Still absent |

---

## 6. Pass 6 — K-008 privilege-boundary audit

### 6.1 Capability grants are explicit and attributable

`CapabilityGrant` records: capability, scope, subject, issuer, expiry, parent grant, creation time. The broker does not infer capabilities from Python syntax — a capability has to be explicitly granted. Sound separation:

```text
Python allowlist       ≠ Capability authorization
```

The allowlist governs code/policy; the broker governs permissions.

### 6.2 Subject binding is enforced

A grant can be tied to `agent-1`, and `_covers()` rejects a request for another explicitly named subject. Expired and revoked grants are also rejected. A capability does not automatically become transferable merely because another agent knows its name.

**Assessment: 🟢**

### 6.3 Attenuation is explicitly implemented

The broker supports parent → child grants. The child is checked against the parent for capability name, scope, constraints, and subject — and the child cannot widen those properties. This is a real **least-authority / attenuation** mechanism, not a flat permission list.

**Assessment: 🟢**

### 6.4 Tests cover actual security boundaries

Dedicated `test_capability_broker.py` and `test_capability_exec.py` exercise: filesystem scope, path traversal, oversized reads, artifact authorization, secret authorization, kernel execution delegation, missing execution engine, audit records, unknown capabilities. For example, the traversal test deliberately attempts `workspace/../secret.txt` and expects rejection — a genuine boundary-escape test, not merely "authorized capability succeeds".

### 6.5 Capability executor reinforces K-001

The `kernel.execute` capability does **not** instantiate or access a raw kernel in `CapabilityExecutor`. The test explicitly models:

```text
agent
   ↓
CapabilityExecutor
   ↓
CapabilityBroker authorization
   ↓
ExecutionEngine
```

and verifies the executor delegates the actual operation to the engine.

### 6.6 Subtle weakness in the capability model

The attenuation scope check is `fnmatch(child.scope, parent.scope)`. Pattern containment is **not generally equivalent to set containment**: wildcard patterns can have surprising relationships, and determining whether `child pattern ⊆ parent pattern` is a formal pattern-containment problem, not just string matching. Constraints are checked only for exact key/value equality — treated as discrete attributes rather than a general partial-order lattice.

**Classification: 🟡 Hardening opportunity, not a demonstrated vulnerability.** P6 attenuation is implemented per Kerno's current pattern semantics, not mathematically proven for arbitrary wildcard languages.

### 6.7 The bigger remaining question: origin escalation

```text
CapabilityBroker
       ↓
ExecutionEngine.execute(origin=?)
```

Because the engine intentionally distinguishes `ORIGIN_AGENT` from trusted `ORIGIN_RUNTIME`, we must prove an agent cannot turn `origin=ORIGIN_AGENT` into `origin=ORIGIN_RUNTIME` and skip agent capability/allowlist enforcement.

Required adversarial cases:

1. Agent calls `engine.execute(..., origin=ORIGIN_RUNTIME)`
2. Agent passes runtime-origin through `CapabilityExecutor`
3. Agent controls subject
4. Agent controls capability set
5. Agent creates/attenuates its own grant
6. Agent attempts wildcard capability
7. Agent uses an expired/revoked parent
8. Agent attempts sibling-subject escalation

Case **#1** is the most important.

### 6.8 Scorecard

| Boundary | Status |
|---|---|
| Explicit capability grants | 🟢 |
| Subject binding | 🟢 |
| Expiration | 🟢 |
| Revocation | 🟢 |
| Attenuation | 🟢 |
| Filesystem scope | 🟢 tested |
| Traversal defense | 🟢 tested |
| Secret capability separation | 🟢 tested |
| Kernel execution delegation | 🟢 tested |
| Raw-kernel agent access | 🟢 no evidence found |
| Transaction preparation | 🟢 |
| Transaction finalization | 🟢 |
| Streaming lifecycle parity | 🟢 |
| Runtime-origin escalation | 🟡 **not yet adversarially proven** |
| GitHub CI execution | 🔴 absent |

---

## 7. Pass 7 — K-008 origin-escalation audit

### 7.1 The privilege boundary is a caller-supplied label

The distinction is explicit in `ExecutionEngine._prepare_transaction()`:

```text
ORIGIN_AGENT   = "agent"   → capability + policy enforcement
ORIGIN_RUNTIME = "runtime" → trusted host path, policy skipped
```

The engine effectively trusts `origin == "runtime"` to mean "this request originated from trusted host/runtime code". The implementation does **not** cryptographically authenticate the origin — it is a software-level trust assertion.

### 7.2 What the repository proves

For agent-origin execution, the engine explicitly performs: capability authorization → human-approval enforcement → cancellation → allowlist enforcement → execution. The capability and allowlist gates are conditional on `origin == ORIGIN_AGENT`, so the intended invariant is sound:

```text
agent   → ORIGIN_AGENT   → authorization/policy → kernel
runtime → ORIGIN_RUNTIME → trusted setup        → kernel
```

### 7.3 Default capabilities are fail-closed

The engine constructor has `default_capabilities: frozenset[str] = frozenset()` — absence of an explicit capability set does not silently grant capabilities. For agent execution the broker is consulted when capabilities are declared. The security test should explicitly verify: agent → no capability declaration → attempt privileged operation → **DENIED** (not merely "missing grant denied when the capability is explicitly supplied").

### 7.4 Status

| Property | Verdict |
|---|---|
| Explicit capability model | 🟢 |
| Subject-scoped grants | 🟢 |
| Expiration/revocation | 🟢 |
| Grant attenuation | 🟢 |
| Agent capability enforcement | 🟢 |
| Fail-closed approval | 🟢 |
| Agent allowlist enforcement | 🟢 |
| Runtime/agent distinction | 🟢 implemented |
| Runtime origin authentication | 🟡 architectural trust assumption |
| Agent → runtime-origin escalation test | 🟡 required |
| Self-grant / privilege amplification test | 🟡 required |
| GitHub CI proof | 🔴 still absent |

**Bottom line:** K-008 is not a discovered vulnerability, but not fully proven either. `ORIGIN_RUNTIME` is a trusted authority label, not an independently authenticated authority.

Next decisive step — adversarial K-008 tests: (1) forge `ORIGIN_RUNTIME`; (2) self-grant `kernel.execute`; (3) attenuate a grant into a broader grant; (4) change the subject; (5) use a revoked/expired parent grant; (6) invoke a privileged capability with no declared capability; (7) reach the raw kernel through a plugin/skill/loop object.

---

## 8. Pass 8 — K-008 / K-001 adversarial evidence (test inspection)

### 8.1 Runtime-origin bypass is explicitly tested

`tests/unit/test_execution_engine.py` proves `engine.execute(VIOLATING_CODE, origin=ORIGIN_RUNTIME)` does bypass the allowlist and capability authorization. This confirms the runtime-origin mechanism is deliberate — but also exposes the exact trust assumption: *anyone who can call `ExecutionEngine.execute()` and select `ORIGIN_RUNTIME` gets trusted-runtime semantics*. The tests prove the behavior, not that untrusted callers cannot select it.

### 8.2 The critical negative property is tested

For normal agent-origin execution, the suite verifies:

```text
agent code → allowlist violation → NO kernel call
agent code → missing capability → NO kernel call
```

The assertion is not merely "an error was returned"; it additionally checks **the dangerous operation never reached the underlying executor** — exactly the property that matters.

### 8.3 K-001 has cross-loop tests

Multiple loop implementations are constructed using `ExecutionEngine(FakeKernel)`, verifying violating code cannot reach the fake kernel: **Reactive loop, Reflect/Revise loop, Plan/Execute loop, Hierarchical loop**.

**Assessment: K-001 cross-loop enforcement: 🟢 strongly tested.**

### 8.4 Capability failure is a true pre-execution gate

```text
CapabilityBroker()
        ↓
no grant
        ↓
CAP_KERNEL_EXECUTE required
        ↓
CapabilityViolation
        ↓
kernel.calls == []
```

Capability denial occurs **before** kernel execution, not logged after execution. Critical security distinction.

### 8.5 Audit integrity is verified

Engine tests verify monotonic execution IDs, sequence numbers, blocked-attempt records, successful execution records, event chains, causal parent IDs, blocked-policy events, and immutable event dataclasses. Kerno isn't merely enforcing the security decision — it records the decision and its causal execution chain.

### 8.6 The missing test

The suite contains `test_runtime_origin_skips_policy()` and `test_runtime_origin_skips_capability_check()` — proving *runtime origin works* — but not the adversarial inverse:

```text
agent-controlled caller
       ↓
attempt ORIGIN_RUNTIME
       ↓
MUST be rejected
```

That distinction is the single most important remaining K-008 question: proving **only trusted runtime code can use runtime origin**.

### 8.7 Verdict

| Claim | Evidence |
|---|---|
| Central execution engine | 🟢 |
| Unified transaction lifecycle | 🟢 |
| Normal execution protected | 🟢 |
| Silent execution protected | 🟢 |
| Streaming execution protected | 🟢 |
| Capability denial before kernel | 🟢 |
| Allowlist denial before kernel | 🟢 |
| Cross-loop K-001 enforcement | 🟢 |
| Audit/event recording | 🟢 |
| Runtime-origin behavior | 🟢 |
| Runtime-origin authority control | 🟡 |
| Self-grant escalation test | 🟡 |
| Agent→runtime-origin adversarial test | 🟡 |
| GitHub Actions execution | 🔴 |

**Conclusion:** The earlier claim of a canonical execution transaction lifecycle is now well supported by source and dedicated tests. The remaining weakness is not "the security checks might be bypassed" — it is that **the trusted-runtime escape hatch itself needs an explicit authority boundary**.

**Recommended hardening:** instead of exposing a freely selectable string `origin=ORIGIN_RUNTIME`, use an internal/trusted execution capability or a private runtime-only API:

```text
Public API      → always ORIGIN_AGENT
Private runtime → ORIGIN_RUNTIME
```

plus an adversarial test proving the public/agent-facing surface cannot obtain the runtime path.

**Current K-008 classification:** 🟢 implemented, 🟡 authority boundary not fully proven.

---

## 9. Pass 9 — Self-grant / privilege escalation and the PR #3 claims

### 9.1 Skill Capability Attenuation Bridge

PR #3 explicitly claims K-008 includes a "Skill Capability Attenuation Bridge" via `grant_skill_capabilities()`, connecting `SkillProvenance` capabilities to `CapabilityBroker` grants scoped to the author agent, plus adversarial tests around blocked backend execution and server-policy downgrade prevention.

The security model:

```text
SkillProvenance
       ↓ declared capabilities
       ↓ grant_skill_capabilities()
       ↓ CapabilityBroker
       ↓ author-agent scope
```

The important word is **attenuation** — a skill should receive only the capabilities it declares, not silently obtain additional privileges.

### 9.2 Adversarial cases

| Attack | Required result |
|---|---|
| Skill declares `kernel.execute` but tries `filesystem.write` | **DENY** |
| Skill changes its declared capabilities after grant | **DENY / immutable grant** |
| Agent A uses Agent B's skill grant | **DENY** |
| Child skill requests broader scope than parent | **DENY** |
| Child changes subject | **DENY** |
| Expired parent → new child | **DENY** |
| Revoked parent → new child | **DENY** |
| Agent invokes grant API directly | **DENY / unavailable** |
| Agent selects `ORIGIN_RUNTIME` | **DENY** |

The broker already has the right ingredients (explicit issuer, subject, parent grant, expiry, revocation, attenuation checks), so the likely problem is **not** "capabilities are freely self-grantable" — the question is whether **all capability creation paths** eventually pass through those controls.

### 9.3 Universal gateway claim

PR #3 claims a universal gateway choke point for `/run`, `/stream`, and WebSocket `/ws` through `make_server_engine()`, eliminating raw kernel execution across public transports:

```text
HTTP /run ───────┐
HTTP /stream ────┼──→ make_server_engine()
WebSocket /ws ───┘          ↓
                      ExecutionEngine
                           ↓
                         Kernel
```

If true in merged `main`, K-001 extends beyond the loop subsystem into the network/API boundary. Questions to answer directly in source:

1. Does `/run` really use `make_server_engine()`?
2. Does `/stream` really use it?
3. Does `/ws` really use it?
4. Is there any direct `kernel.execute()` in a public transport?
5. Can a client select `ORIGIN_RUNTIME`?
6. Can a remote client downgrade the security profile?
7. Does cancellation preserve finalization?

PR claims are not evidence of the merged implementation by themselves.

### 9.4 Updated posture

**Strongly evidenced:** K-001 canonical execution lifecycle; synchronous/streaming transaction parity; cross-loop execution choke point; capability-before-execution; allowlist-before-execution; adversarial "blocked code never reaches kernel" testing; capability subject/attenuation model; public transport choke-point design claimed in merged PR.

**Still requiring direct source/test reconciliation:** capability self-grant prevention; runtime-origin authority; skill capability attenuation; `/run` `/stream` `/ws` actual implementation; remote security-profile downgrade; transport-level cancellation/finalization.

**Still objectively missing:** GitHub Actions execution evidence. "Tests exist" ≠ "tests have been executed and passed on GitHub."

---

## 10. Pass 10 — Transport-boundary finding

### 10.1 The main chat endpoint does wrap the pipeline

`secure_app.py` creates `kernel → make_server_engine(...) → engine → pipeline`, and the loop receives `kernel=engine`. The agent-generated execution path is correctly routed through the security engine. This supports K-001.

### 10.2 But file materialization bypasses the engine

Immediately before constructing the pipeline:

```python
mat = FileMaterializer(kernel)
files = mat.process_from_context(body)
```

`FileMaterializer` then directly executes generated load code with:

```python
self.kernel.execute(load_code, timeout=30)
```

That means the public authenticated HTTP path currently contains:

```text
HTTP request
   ↓
authenticated server
   ↓
raw kernel
   ↓
kernel.execute(load_code)
```

outside `ExecutionEngine`.

### 10.3 Why this matters

The generated code includes operations such as `import pandas as _pd`, `_pandas.read_csv(...)`, and for images/documents `from PIL import Image; open(...)`. That code is server-generated, not directly the user's Python program — so this is **not** immediately arbitrary remote code execution. But it is undeniably a raw-kernel execution path exposed by the authenticated server **outside the canonical ExecutionEngine boundary**. The stronger PR claim ("the authenticated server never executes raw kernel code — every session goes through the choke point") is too broad as implemented.

### 10.4 SSRF surface

`FileMaterializer._save_file()` accepts a URL and calls:

```python
urllib.request.urlretrieve(url, local_path)
```

An authenticated client can potentially cause the server to make outbound requests to arbitrary URLs. No visible restriction for: allowed schemes, private IP ranges, loopback, link-local addresses, internal DNS, redirects, maximum download size, download timeout.

**Classification: 🟠 Security hardening finding** — potential SSRF/resource-exhaustion surface, not yet a confirmed exploitable SSRF (deployment/network isolation and surrounding request validation still need inspection).

### 10.5 CORS is extremely permissive

The production server configures:

```text
allow_origins = ["*"]
allow_methods = ["*"]
allow_headers = ["*"]
```

For a public authenticated API this is a broad browser-origin policy. It doesn't automatically bypass API-key authentication, but it substantially expands the browser-facing attack surface. Production should use an explicit origin allowlist.

**Classification: 🟡 Hardening finding.**

### 10.6 `default_security` is not fully authoritative

`create_secure_app()` accepts `default_security = "data_analysis"`, but the request can supply `request.security`, which is passed to `make_server_engine(kernel, profile=getattr(request, "security", default_security))`. `make_server_engine()` contains `resolve_effective_profile()` and supports server-default enforcement when `server_default` is supplied — but `secure_app.py` does **not** pass `server_default=default_security`. The server-level downgrade protection is not actually activated here, directly contradicting the PR #3 claim that remote HTTP clients cannot downgrade server security policies.

**Classification: 🟠 Confirmed implementation mismatch.**

### 10.7 Revised transport verdict

| Property | Current `main` |
|---|---|
| `/v1/chat/completions` pipeline → engine | 🟢 |
| Agent code → engine | 🟢 |
| Raw FileMaterializer kernel execution | 🔴 bypass |
| URL-based file retrieval | 🟠 SSRF/resource-risk surface |
| CORS | 🟡 overly permissive |
| Profile-ranking mechanism | 🟢 implemented |
| Profile downgrade protection | 🟡 not wired into `secure_app.py` |
| PR #3 claim of universal server choke point | 🔴 too strong |

**This changes the audit substantially** — the first meaningful source-vs-claim discrepancy in the merged security work. The core K-001 engine remains strong; the broader "all server-driven execution goes through the choke point" statement does not hold for file materialization.

**Recommended remediation:**

```text
FileMaterializer
       ↓
produce validated load operation
       ↓
ExecutionEngine
       ↓
capability + allowlist + budget
       ↓
kernel
```

and in `secure_app.py`:

```python
make_server_engine(
    kernel,
    profile=requested_profile,
    server_default=default_security,
)
```

---

## 11. Pass 11 — Transport audit: decisive result

### 11.1 Client can select a weaker profile than the server default

`ChatCompletionRequest` exposes `security: str = "permissive"` while the server's documented default is `default_security = "data_analysis"`. The request handler passes the client-supplied value to `make_server_engine()` **without** `server_default=default_security`. The same defect exists in the streaming path.

`make_server_engine()` already contains the correct downgrade-prevention mechanism — `resolve_effective_profile(requested, server_default, allow_downgrade=False)` — but the OpenAI-compatible server doesn't activate it:

```text
server default = data_analysis
client requests = permissive
        ↓
effective profile = permissive     ← authoritative server_default not supplied
```

The code only special-cases `security == "none"` by replacing it with `default_security`; it does not prevent the client from selecting another weaker named profile such as `permissive`.

**Verdict: K-012: 🟠 Confirmed integration defect** — the policy enforcement primitive exists, but the public OpenAI transport does not correctly wire it.

### 11.2 Streaming has the same defect

The stream handler independently constructs `make_server_engine(kernel, profile=prof, capability_broker=..., budget=...)` — again without `server_default=default_security`. Consistent — but consistently too permissive.

```text
Synchronous: 🟠
Streaming:    🟠
```

### 11.3 The secure authenticated server has the same wiring problem

`secure_app.py` also does `profile=getattr(request, "security", default_security)` without passing the authoritative server default. This is a **shared integration mistake across the server layer**, not an isolated typo.

### 11.4 File materialization remains a K-001 bypass

```text
┌── ExecutionEngine ── protected
HTTP request ────┤
                 └── FileMaterializer ── raw kernel
```

The broad K-001 statement "all server-driven execution passes through the choke point" is **false as currently implemented**.

**Severity:** 🟠 High-priority architectural security finding — not automatically "critical RCE", because the materializer controls the generated loading code and is not directly executing arbitrary client Python — but the raw-kernel boundary is objectively bypassed.

### 11.5 SSRF/resource abuse remains open

`urllib.request.urlretrieve(url, local_path)` with no visible URL policy. At minimum: http/https scheme restriction, private/loopback/link-local IP blocking, redirect validation, maximum response size, connection/read timeout, download count limits, filename collision protection, ideally an outbound proxy/sandbox. Tracked separately from K-001.

### 11.6 Revised security matrix

| Area | Verdict |
|---|---|
| Core ExecutionEngine lifecycle | 🟢 |
| `_prepare_transaction` | 🟢 |
| `_finalize_transaction` | 🟢 |
| `execute_silent` | 🟢 |
| `stream_execute` | 🟢 |
| Capability-before-kernel | 🟢 |
| Allowlist-before-kernel | 🟢 |
| Cross-loop enforcement | 🟢 |
| Agent raw-kernel access | 🟢 no evidence |
| Server pipeline → engine | 🟢 |
| File materializer → raw kernel | 🔴 confirmed bypass |
| HTTP profile downgrade protection | 🟠 not wired |
| Streaming profile downgrade protection | 🟠 not wired |
| Secure-app profile downgrade protection | 🟠 not wired |
| URL attachment SSRF controls | 🟠 insufficient |
| CORS | 🟡 overly broad |
| GitHub Actions evidence | 🔴 absent |

### 11.7 Three concrete findings

- **F1 — K-001 transport bypass:** `FileMaterializer` executes directly on the raw kernel.
- **F2 — K-012 policy wiring failure:** the server exposes a security profile but fails to pass `server_default`, allowing a client to select a weaker profile such as `permissive`.
- **F3 — File URL retrieval attack surface:** authenticated file handling can make unrestricted outbound URL requests.

These should be recorded in the traceability/audit report as findings against merged `main`, rather than silently accepting PR #3's stronger claims. The core security engine remains strong; the problems are concentrated at the server integration boundary.

---

## 12. Pass 12 — K-012 reconciliation

### 12.1 The policy primitive itself is correct

```text
requested profile
      ↓
resolve_effective_profile()
      ↓
compare against server_default
      ↓
weaker request → server_default
```

If `server_default` is supplied and `allow_downgrade=False`, a weaker requested profile is replaced by the server default. **K-012 is correctly implemented at the security-library level.**

### 12.2 But the OpenAI transport does not activate it

```text
server default = data_analysis
client request = permissive
             ↓
profile = permissive
             ↓
make_server_engine(..., server_default=None)
             ↓
permissive is accepted
```

Real integration defect.

### 12.3 Test-coverage nuance

The suite contains `test_permissive_cannot_downgrade_data_analysis()`, but it exercises `kerno.server.app._execute_task` (where server-default logic is applied differently). It does **not** prove the OpenAI-compatible `/v1/chat/completions` path is protected. Classic coverage gap: the security primitive is tested, and one HTTP path is tested, but the OpenAI transport's actual integration is not covered by an equivalent downgrade test.

### 12.4 Comment vs implementation trap

The code contains comments saying `# K-001 / K-012: client cannot downgrade below server policy` — but the actual call does not enforce that invariant.

```text
Comment:       🟢 intention
Primitive:     🟢 implementation
Integration:   🔴 incorrect
Test of endpoint: 🔴 missing
```

### 12.5 The `none` special case gives false protection

Both OpenAI paths do `if prof == "none": prof = default_security`, so `security="none"` is blocked — but `security="permissive"` (with server default `data_analysis`) is not. Testing only `"none"` would miss the actual downgrade vector; `test_none_security_cannot_downgrade_server_policy()` does not establish complete K-012 coverage for the OpenAI API.

### 12.6 Proposed minimal fix

```python
make_server_engine(
    kernel,
    profile=prof,
    server_default=default_security,
    allow_downgrade=False,
    capability_broker=capability_broker,
    budget=budget,
)
```

Then, assuming the intended ranking `none < permissive < data_analysis < read_only` (as `PROFILE_RANK` defines):

| Requested | Result |
|---|---|
| `data_analysis` | accepted |
| `read_only` | accepted |
| `permissive` | upgraded to `data_analysis` |
| `none` | upgraded to `data_analysis` |

### 12.7 Required regression tests

The missing test must target the actual OpenAI transport, not merely `make_server_engine()`:

- `default_security = data_analysis`, request `security=permissive` → execute code requiring blocked capability → `AllowListViolation` → raw kernel receives nothing (run with `stream=false` **and** `stream=true`)
- requested `read_only`, server default `data_analysis` → `read_only` allowed
- requested `permissive`, server default `data_analysis` → `data_analysis` enforced
- requested `none`, server default `data_analysis` → `data_analysis` enforced

### 12.8 Finding record

```text
K-012 — Client security-profile downgrade through OpenAI-compatible API
Status:    CONFIRMED
Root cause: openai_compat.py does not pass the authoritative server_default
            into make_server_engine().
Affected paths: /v1/chat/completions synchronous
                /v1/chat/completions streaming
Existing protection: present in server/security.py
Existing test: covers another server path, not these endpoints
Remediation: wire server_default=default_security and add endpoint-level
             regression tests.
```

### 12.9 K-001 remains separate

```text
Kerno server
                       │
          ┌────────────┴────────────┐
          │                         │
    Agent execution           File materialization
          │                         │
          ▼                         ▼
 ExecutionEngine               RAW KERNEL
          │                         │
       protected                 BYPASS
```

### 12.10 Priority order

```text
P0 — evidence/governance: no GitHub Actions execution.
P1 — K-001: remove raw-kernel access from FileMaterializer.
P1 — K-012: enforce server_default in OpenAI sync + streaming endpoints.
P1 — SSRF:  constrain URL materialization.
P2 — CORS:  replace wildcard policy with explicit origins.
```

---

## 13. Pass 13 — Server file-materialization boundary

### 13.1 The authenticated server explicitly gives FileMaterializer the raw kernel

```python
kernel = pool.acquire(...)
        ↓
FileMaterializer(kernel)
        ↓
mat.process_from_context(body)
```

while separately constructing `kernel → make_server_engine(...) → engine → pipeline`. Two execution authorities in the same request:

```text
request
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
   FileMaterializer       ExecutionEngine
          │                   │
          ▼                   ▼
      RAW KERNEL             KERNEL
```

The source explicitly passes the raw kernel into the materializer. The comment immediately above says "the authenticated server never executes raw kernel code" — then the same function hands the raw kernel to a component whose job includes materializing uploaded/context files. **Source/comment contradiction.**

**Verdict: K-001 server-wide choke-point claim: ❌ not satisfied.**

### 13.2 The file-materialization input is request-controlled

```python
body = request.dict()
mat.process_from_context(body)
```

This is not isolated startup behavior — it happens **inside the authenticated request handler**, before the protected pipeline executes:

```text
remote request
    ↓
authenticated endpoint
    ↓
request body
    ↓
FileMaterializer
    ↓
raw kernel
```

A remotely reachable privileged execution surface, subject to what the materializer accepts. The architectural bypass is unequivocal (whether the attacker controls executable content or only structured file metadata still requires the materializer implementation).

### 13.3 Second, independent policy defect in `secure_app.py`

`make_server_engine(kernel, profile=getattr(request, "security", default_security))` with no `server_default=default_security`. The server layer does not consistently wire the authoritative security profile — broader than "OpenAI compatibility forgot the argument."

### 13.4 Authentication does not solve this problem

The endpoint has `Depends(auth_dep)` and derives `user_id`, `max_cells`, `rate_limit` from the authenticated identity — good. But authentication establishes **who is calling**, not **what execution authority that caller may obtain**. The raw-kernel materialization path occurs after authentication but before the engine boundary. The correct model:

```text
authenticated user
        ↓
validated request
        ↓
authorized file operation
        ↓
ExecutionEngine
        ↓
kernel
```

not `authenticated user → raw kernel`.

### 13.5 Finding F1 — high confidence

```text
Title:       Authenticated server exposes raw-kernel file-materialization path
Evidence:    secure_app.py
Confidence:  High
Impact:      Potential bypass of capability, allowlist, budget, audit, and
             transaction lifecycle controls for materialization-generated
             kernel operations.
Root cause:  FileMaterializer receives KernelRuntime instead of a restricted
             execution interface.
Fix:         Give FileMaterializer an ExecutionEngine/restricted executor, or
             redesign it to return validated materialization operations that
             the engine executes.
```

### 13.6 K-012 confirmed across both server implementations

| Server path | Server default passed? | Client downgrade protected? |
|---|---|---|
| `openai_compat.py` sync | ❌ | ❌ |
| `openai_compat.py` stream | ❌ | ❌ |
| `secure_app.py` sync | ❌ | ❌ |
| `secure_app.py` stream | ❌ | ❌ |
| `make_server_engine()` primitive | ✅ when supplied | ✅ |

Systematic integration gap, not an isolated typo.

### 13.7 Revised overall assessment

| Area | Status |
|---|---|
| Core engine | 🟢 Strong |
| Local agent execution | 🟢 Strong |
| Server agent execution | 🟢 Mostly strong (primary pipeline gets the protected engine) |
| Server materialization | 🔴 Boundary violation (raw kernel exposed) |
| Server security-profile governance | 🔴 Integration defect (primitive exists, not wired into endpoints) |
| CI/governance | 🔴 No GitHub Actions evidence |

---

## 14. Pass 14 — F1 severity refinement (file materialization, routing, tests)

### 14.1 F1 is real, but severity refined

`FileMaterializer` is explicitly designed to take a kernel and execute generated loading code inside it. Supported input includes base64 file data, URL references, and embedded message attachments; `_process_one()` ultimately performs:

```text
file input
 → save/download
 → generate load_code
 → raw kernel.execute(load_code)
```

The raw-kernel bypass is definitely present. **However**, the generated `load_code` is **template-controlled by Kerno**; no evidence in this file shows arbitrary Python code supplied as a file being directly inserted into `load_code`.

**Downgrade:** confirmed execution-boundary violation, **not** proven arbitrary remote code execution.

### 14.2 The input is nevertheless remotely influenced

`secure_app.py` passes the entire request body into `FileMaterializer(kernel).process_from_context(body)`, which extracts top-level files and message content parts of type `image_url` and `file`. A remote authenticated caller can influence **whether** this raw-kernel materialization path runs; what remains is what the caller can make the generated loader do.

### 14.3 F2 — URL retrieval (confirmed attack surface)

```text
url
 ↓
urllib.request.urlretrieve(url, local_path)
```

No visible scheme/IP/redirect validation. An authenticated request can cause Kerno to fetch a caller-selected URL. Potential consequences: SSRF against reachable internal services, access to loopback/link-local resources, redirects to internal addresses, bandwidth/resource exhaustion, large-file disk exhaustion. **🟠 Confirmed attack surface**; exact SSRF exploitability is deployment-dependent.

### 14.4 F3 — No file-size enforcement

The request contains `size`, but `_save_file()` does not enforce it. For base64: `base64.b64decode(data_b64)` → write entire decoded content. For URL: `urlretrieve(...)` → write downloaded content. No visible maximum-byte check before writing. An authenticated caller may submit extremely large attachments consuming memory (base64 decoding), disk (`/tmp/kerno_uploads`), and kernel parsing time. **🟠 Confirmed from source.**

### 14.5 F4 — Shared upload filename namespace

`safe_name = "".join(c for c in name if c.isalnum() or c in "._-")` removes path separators (good) but does not prevent collisions: `/tmp/kerno_uploads/<safe_name>` is reused, and the `_counter` affects only the generated Python variable name, not the physical filename. Two users uploading `sales.csv` target the same server-side pathname — a potential cross-request data integrity/isolation issue depending on concurrency/session behavior. **🟡 Needs concurrency/isolation testing.** A per-session/per-user directory or cryptographically generated server-side filename would be substantially safer.

### 14.6 Good news: the main `/run` server is better than `secure_app.py`

`kerno/server/app.py` has a proper gateway helper:

```python
resolve_effective_profile(
    profile,
    server_default=default_security,
    allow_downgrade=False
)
```

and passes the resulting policy into `make_server_engine()`. Its `/run` route passes `default_security` and the capability broker into `_execute_task()`, which resolves the effective profile against the server default before constructing the engine. **The primary `/run` implementation does enforce K-012 correctly.** The earlier statement that the entire server layer failed to wire `server_default` was too broad.

### 14.7 `/stream` and WebSocket also use the gateway

The SSE path uses `_build_gateway_engine(...)` and passes the resulting engine into the reactive loop; the WebSocket path does the same.

| Transport | Gateway | Downgrade protection |
|---|---|---|
| `/run` | 🟢 | 🟢 |
| `/stream` | 🟢 | 🟢 |
| `/ws` | 🟢 | 🟢 |

### 14.8 The test suite reflects this distinction

`tests/unit/test_server_security.py` tests `/run` policy enforcement, `security="none"` downgrade, `security="permissive"` downgrade, and raw kernel not receiving violating code — but those tests call `kerno.server.app._execute_task()`, **not** the separate `kerno.server.secure_app` / `kerno.server.openai_compat`. The suite proves the main gateway server but not the alternative implementations. This is the key testing gap.

### 14.9 OpenAI integration tests don't test security

The OpenAI integration test only checks health, models, synchronous completion, and streaming completion (and skips if localhost:8001 isn't running). No tests for:

- `security = permissive`, server default `data_analysis` → must remain `data_analysis`
- malicious/forbidden code → must never reach kernel
- file URL → must pass SSRF policy

The OpenAI-compatible security boundary remains untested at the endpoint level.

### 14.10 Consolidated findings after this pass

| ID | Finding | Status |
|---|---|---|
| F1 | FileMaterializer bypasses ExecutionEngine | 🔴 Confirmed |
| F2 | Unrestricted URL retrieval | 🟠 Confirmed attack surface |
| F3 | No materialization size limits | 🟠 Confirmed |
| F4 | Shared filename namespace | 🟡 Needs isolation test |
| F5 | OpenAI/secure_app profile downgrade wiring | 🟠 Confirmed |
| — | Main `/run` K-012 | 🟢 Correct gateway enforcement |
| — | Main `/stream` K-012 | 🟢 Correct gateway enforcement |
| — | Main `/ws` K-012 | 🟢 Correct gateway enforcement |
| — | OpenAI security integration tests | 🔴 Missing |
| — | File-materializer security tests | 🔴 No dedicated test file visible |
| — | GitHub Actions | 🔴 No registered workflow |

### 14.11 Bottom line

The core security refactor is real and strong. But `main` still contains legacy/parallel server paths that have not been brought to the same security standard. The highest-priority remediation is therefore **not** to redesign `ExecutionEngine`; it is to:

1. collapse all public server implementations onto the already-correct gateway path,
2. remove raw-kernel ownership from `FileMaterializer`,
3. add endpoint-level security tests.

That would eliminate the largest source of divergence between Kerno's documented security invariants and its actual deployed surfaces.

---

## 15. Consolidated findings register

| ID | Title | Severity | Status | Evidence | Remediation |
|---|---|---|---|---|---|
| F1 | `FileMaterializer` executes generated load code on the raw kernel, bypassing `ExecutionEngine` | 🟠 High-priority architectural (not proven RCE — loader code is template-controlled) | 🔴 Confirmed | `secure_app.py` passes `FileMaterializer(kernel)`; `_process_one()` → `kernel.execute(load_code)` | Route materialization through `ExecutionEngine`/restricted executor, or return validated load ops the engine executes |
| F2 | Unrestricted server-side URL retrieval (`urllib.request.urlretrieve`) | 🟠 Confirmed attack surface | 🟠 Confirmed | `FileMaterializer._save_file()`; no scheme/IP/redirect/size/timeout policy | Enforce scheme allowlist, block private/loopback/link-local IPs, validate redirects, cap size, timeouts, outbound proxy/sandbox |
| F3 | No materialization size limits (base64 decode / URL download unbounded) | 🟠 Resource exhaustion | 🟠 Confirmed | `_save_file()` writes full decoded/downloaded content; request `size` not enforced | Enforce max bytes before decode/write; reject oversized parts |
| F4 | Shared upload filename namespace (`/tmp/kerno_uploads/<safe_name>`) | 🟡 Data-integrity/isolation risk | 🟡 Needs concurrency/isolation test | `safe_name` sanitization removes separators but collisions persist | Per-session/per-user dirs or random server-side filenames |
| F5 | Client security-profile downgrade through OpenAI-compatible and `secure_app` endpoints (K-012 wiring) | 🟠 Confirmed integration defect | 🟠 Confirmed | `openai_compat.py` / `secure_app.py` omit `server_default=default_security` | Pass `server_default` + `allow_downgrade=False`; add endpoint-level regression tests for sync + streaming |
| G1 | No GitHub Actions workflow registered (`total_count: 0`) | 🔴 Governance/evidence gap | 🔴 Confirmed | GitHub Actions API | Register workflow; make it the required status check |
| G2 | `main` branch protection disabled (no required checks, enforcement off) | 🔴 Governance gap | 🔴 Confirmed | GitHub branch metadata | Enable protection + required status checks |
| G3 | `ORIGIN_RUNTIME` is a caller-supplied trust label, not an authenticated authority; no adversarial escalation test | 🟡 Authority-boundary proof missing | 🟡 Needs tests | `ExecutionEngine._prepare_transaction()` branches on caller-supplied `origin` | Restrict runtime origin to a private/trusted API; add agent→runtime-origin and self-grant adversarial tests |
| G4 | CORS `allow_origins=["*"]` on authenticated production server | 🟡 Hardening | 🟡 Confirmed | Server config | Explicit origin allowlist |
| G5 | Skill capability attenuation uses `fnmatch` pattern containment + exact-key constraint equality | 🟡 Hardening opportunity (not demonstrated vuln) | 🟡 Assessed | `CapabilityBroker` attenuation checks | Document pattern semantics; consider lattice-based constraint checks |

---

## 16. Final evidence matrix

| Area | Assessment |
|---|---|
| Source implementation | 🟢 **Present** |
| Security architecture | 🟢 **Substantial** |
| Test architecture | 🟢 **Substantial** (unit/behavioral/integration/property) |
| Security audit documentation | 🟢 **Substantial** (13-part corpus + invariants) |
| Traceability documentation | 🟢 **Present** |
| Latest security work merged to `main` | 🟢 **Verified** (PR #3 merge commit, cryptographically verified) |
| Central execution engine / transaction lifecycle | 🟢 **Confirmed** (`_prepare_transaction` / `_finalize_transaction` with `finally` guarantee) |
| Normal / silent / streaming execution surfaces | 🟢 **All routed through the lifecycle** |
| Capability denial before kernel | 🟢 **Tested** |
| Allowlist denial before kernel | 🟢 **Tested** |
| Cross-loop K-001 enforcement | 🟢 **Tested** (4+ loop strategies) |
| Audit/event/causal-chain recording | 🟢 **Tested** |
| Capability subject binding / expiry / revocation / attenuation | 🟢 **Implemented + tested** |
| Main gateway server `/run` `/stream` `/ws` downgrade protection | 🟢 **Correctly wired** |
| Agent raw-kernel access | 🟢 **No evidence found** |
| Runtime-origin authority boundary (agent → ORIGIN_RUNTIME escalation) | 🟡 **Not adversarially proven** |
| Self-grant / capability escalation | 🟡 **Requires adversarial tests** |
| File materializer → raw kernel (K-001 transport bypass) | 🔴 **Confirmed** (F1) |
| OpenAI / secure_app profile downgrade wiring (K-012) | 🟠 **Confirmed** (F5) |
| URL retrieval / SSRF controls | 🟠 **Insufficient** (F2) |
| Materialization size limits | 🟠 **Absent** (F3) |
| Upload filename namespace isolation | 🟡 **Unproven** (F4) |
| CORS policy | 🟡 **Overly broad** |
| Tests actually executed on GitHub | 🔴 **No** |
| GitHub Actions workflow registered | 🔴 **No** |
| `main` branch protection / required checks | 🔴 **No** |
| Reproducible dependency resolution (lock/constraints) | 🟡 **Needs verification** |

---

## 17. Recommendations — priority order

### P0 — Evidence / governance
- Register a GitHub Actions workflow (unit + integration + property suites) and make it a **required status check** on `main`.
- Enable `main` branch protection (require status checks, enforce admins).

### P1 — K-001: remove raw-kernel access from `FileMaterializer`
- Give `FileMaterializer` an `ExecutionEngine`/restricted executor, or redesign it to return validated materialization operations executed by the engine.
- Add tests proving materialization-generated kernel ops pass capability + allowlist + budget and are audited.

### P1 — K-012: enforce `server_default` in OpenAI sync + streaming + `secure_app` endpoints
- Wire `server_default=default_security, allow_downgrade=False` into every `make_server_engine()` call.
- Add endpoint-level regression tests for both `stream=false` and `stream=true`, covering `permissive`, `none`, and `read_only` requests against a `data_analysis` default.

### P1 — SSRF / resource limits on URL materialization
- Scheme allowlist, private/loopback/link-local blocking, redirect validation, download size cap, timeouts, per-session limits.

### P2 — Harden the runtime-origin boundary
- Replace the caller-selectable `origin=ORIGIN_RUNTIME` string with a private/trusted runtime-only API; add adversarial tests (forge runtime origin, self-grant, widen attenuation, change subject, revoked/expired parent, no declared capability).

### P2 — CORS
- Replace `allow_origins=["*"]` with an explicit origin allowlist.

### P3 — Reproducibility
- Add lock/constraints mechanism for the open-ended core dependency ranges (e.g. `jupyter-client>=8.0`).

---

## 18. Key conclusion

Kerno's security architecture is substantially stronger than the initial audit uncertainty suggested. The canonical execution transaction lifecycle (K-001) and the capability/attenuation model (K-008) are **implemented in `main` and backed by dedicated, adversarial-style tests**. The remaining work is increasingly about **proof of boundaries**, not discovering an obviously missing security subsystem.

The concrete defects are concentrated at the **server integration boundary** — the raw-kernel `FileMaterializer` path and the un-wired `server_default` downgrade protection — and at the **governance layer** (no GitHub Actions workflow, no branch protection). Closing F1/F5, adding endpoint-level security tests, and registering CI would move Kerno from "implemented + documented" to "implemented + independently verified".

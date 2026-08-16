# 11 — Security And Policy Enforcement

## Next: security / policy enforcement

The next layer I would audit is now `kerno/security/allowlist.py`, middleware, plugin transformations, and the boundary immediately before `kernel.execute()`.

We need to answer one decisive question:

> **Does Kerno actually prevent generated Python from performing dangerous operations, or does the current security layer merely inspect/log them?**

That will let us determine whether the runtime should be considered an **agent framework**, a **trusted automation framework**, or an **untrusted-code execution system**—three very different security models.

---

## Security / policy enforcement audit

This branch is **much more security-aware than the earlier runtime code suggested**. The repository explicitly has a capability broker, allowlists, an execution choke point, effect tracking, approval gates, secret redaction, Docker isolation, and invariant checks. <sup>[source]</sup>

So I need to correct one thing from the previous section:

> It would be inaccurate to characterize Kerno as having "no security layer."

It clearly has one.

The real question is now:

> **Are those security mechanisms actually mandatory and resistant to bypass?**

And there are some important weaknesses.

---

## 1. The architecture has the correct security choke point

`ExecutionEngine` explicitly defines itself as:

```text
the single choke point for code execution
```

and says agents, loops, plugins, skills, and checkpoints must execute through it. <sup>[source]</sup>

The intended flow is:

```text
LLM-generated code
       ↓
ExecutionEngine
       ↓
Capability authorization
       ↓
Allowlist
       ↓
Effect declaration
       ↓
Kernel
       ↓
Effect observation
       ↓
Audit
```

That is **the right architecture**.

---

## 2.  But the critical invariant is only architectural unless every execution path actually uses it

The engine says:

> "No agent, loop, plugin, skill, checkpoint, or subsystem may execute code except through ExecutionEngine.execute()." <sup>[source]</sup>

But we've already seen direct execution in the checkpoint subsystem and kernel runtime.

For example, the checkpoint plugin directly calls the kernel executor.

That creates the exact bypass the invariant claims must not exist.

So the important audit question is not:

```text
Does ExecutionEngine exist?
```

It does.

The important question is:

```text
Can anything call KernelRuntime.execute()
without passing through ExecutionEngine?
```

From the code already inspected, **yes**.

That is a significant architectural contradiction.

---

## 3.  This is potentially the most important security finding

The repository has:

```text
K-001:
single execution choke point
```

but also:

```text
checkpoint → kernel.execute(...)
runtime → kernel.execute(...)
```

Therefore:

```text
                    ExecutionEngine
                         │
                 ┌───────┴────────┐
                 │                │
             protected          bypass
                 │                │
               agent         checkpoint/plugin
                 │                │
                 ▼                ▼
              policy           kernel
```

The bypass means an operation can potentially avoid:

- capability checks
- allowlist
- approval
- effect declaration
- execution audit
- policy-block events
- secret redaction

That should be treated as **P0 if reachable by agent-controlled functionality**.

---

## 4. The allowlist itself is only static source inspection

`AllowList.check()` does:

```text
regex scan
+
import regex scan
+
builtin regex scan
```

<sup>[source]</sup>

That's useful, but it is not a Python security sandbox.

For example, source-code pattern matching cannot reliably determine the behavior of arbitrary Python.

---

## 5. Regex security is inherently bypassable

Consider a rule blocking:

```python
os.system(...)
```

A sufficiently capable generated program can potentially construct equivalent behavior indirectly.

Examples conceptually include:

```python
getattr(os, "system")(...)
```

or indirect imports, aliases, object traversal, dynamically constructed strings, or already-loaded modules.

The allowlist does block `__import__`, `eval`, `exec`, and `compile` in the restrictive profiles, which is good. <sup>[source]</sup>

But regex matching should be regarded as:

> **policy linting**, not isolation.

---

## 6. AST analysis would be substantially stronger

Instead of:

```text
source
 ↓
regex
```

use:

```text
source
 ↓
AST parse
 ↓
AST policy
 ↓
capability analysis
 ↓
execution
```

For example:

```text
Import
ImportFrom
Call
Attribute
Name
Subscript
Lambda
```

can be inspected structurally.

This doesn't make Python safe by itself either, but it is much more robust than regex matching.

---

## 7. The runtime import hook is clever—but not a security boundary

The allowlist generates a kernel-side replacement for:

```python
builtins.__import__
```

and explicitly tries to avoid recursive import interception. <sup>[source]</sup>

The implementation permits:

```text
relative imports
already-loaded modules
stdlib modules
explicitly allowed modules
```

That's a sensible compatibility design.

But:

> Once arbitrary Python is running inside the same interpreter, modifying `__import__` is not equivalent to sandboxing the interpreter.

An attacker with enough Python capability can potentially reach already-imported objects or use other interpreter mechanisms.

So again:

```text
import hook = policy layer
```

not:

```text
import hook = security boundary
```

---

## 8. There's an important interaction with `sys.modules`

The import hook deliberately allows:

```python
if top_level in _sys.modules:
    return _original_import(...)
```

because kernel internals need it. <sup>[source]</sup>

That is operationally sensible.

But it weakens the security guarantee:

```text
module already loaded
        ↓
allowed
```

Therefore a capability may effectively be inherited from **kernel bootstrap state**, rather than explicitly granted to the current agent.

This is another reason why process-level isolation is still necessary.

---

## 9. CapabilityBroker is significantly stronger than the allowlist

This part is well designed conceptually.

A capability grant contains:

```text
capability
scope
constraints
subject
issuer
expiry
parent_grant
```

and supports attenuation. <sup>[source]</sup>

That is much closer to a real authorization system.

For example:

```text
agent-1
   ↓
filesystem.read
scope=/workspace/**
   ↓
child grant
scope=/workspace/data/**
```

The child cannot broaden the parent's authority.

That's a strong property.

---

## 10.  But `CapabilityBroker` does not itself enforce anything unless callers request capabilities

This is the critical line:

```text
agent execution
 ↓
capabilities = ...
 ↓
broker.require(...)
```

The engine only checks capabilities supplied in the execution request.

If:

```python
capabilities = frozenset()
```

then no capability is requested.

The broker has nothing to authorize.

Therefore:

> **The system is capability-secure only if capability requirements are complete and trustworthy.**

That is a major dependency.

---

## 11. `default_capabilities` can become dangerous

The engine accepts:

```python
default_capabilities
```

and uses them when an execution doesn't explicitly provide capabilities. <sup>[source]</sup>

This is convenient.

But if a caller configures:

```text
default_capabilities = TRUSTED
```

then generated agent code could inherit broad authority.

The security model therefore depends heavily on configuration.

For a secure default:

```text
default_capabilities = ∅
```

should be mandatory for `ORIGIN_AGENT`.

---

## 12.  The `ORIGIN_RUNTIME` escape hatch is extremely powerful

The engine explicitly says:

```text
ORIGIN_AGENT
→ authorization + policy

ORIGIN_RUNTIME
→ skips both
```

<sup>[source]</sup>

That's reasonable for trusted host operations.

But it creates a dangerous rule:

> Anything incorrectly labeled `runtime` becomes trusted code.

So the origin must never be inferred from:

```text
"this function was called by a plugin"
```

or:

```text
"this is internal code"
```

It should be an explicitly controlled API boundary.

---

## 13. This is especially dangerous for plugin code

Kerno has:

```text
plugins
skills
checkpoint
middleware
```

all of which may run inside the runtime.

If an agent can indirectly cause a plugin to execute arbitrary text through an `ORIGIN_RUNTIME` path, then the entire security model collapses.

Therefore plugin APIs should have separate types:

```text
TrustedRuntimeAction
AgentAction
```

rather than a freely passed:

```text
origin="runtime"
```

string.

---

## 14.  Effect tracking is currently detection, not prevention

The engine does:

```text
declare effects
 ↓
execute
 ↓
observe
 ↓
if violation:
    log warning/event
```

<sup>[source]</sup>

That's valuable.

But if an undeclared effect occurs:

```text
effect violation
```

the side effect has **already happened**.

So:

```text
EffectLedger
```

is an accountability mechanism, not a security barrier.

---

## 15. Example

Suppose the agent declares:

```text
effects = NONE
```

then executes:

```python
open("/workspace/x", "w").write("secret")
```

The engine can detect the filesystem effect afterward.

But:

```text
secret already written
```

The ledger cannot undo it.

For high-risk capabilities, the authorization must happen **before** execution.

---

## 16. The strongest design is:

```text
Capability authorization
        ↓
Effect declaration
        ↓
Effect policy
        ↓
Execution
        ↓
Effect observation
```

not:

```text
Execution
        ↓
Effect observation
        ↓
"oops"
```

Kerno already has pieces for the first model; they need to be made mandatory.

---

## 17. Human approval is correctly fail-closed

This is one of the strongest pieces.

If an agent requests:

```text
human.approval
```

and no approval gate exists:

```text
→ DENY
```

The engine explicitly documents:

> "FAIL CLOSED" <sup>[source]</sup>

That's exactly what we want.

---

## 18. Secret redaction is also correctly placed

The engine redacts agent-origin output:

```text
kernel output
 ↓
redactor
 ↓
LLM
notebook
event store
```

<sup>[source]</sup>

This is important because redaction **after persistence** would be too late.

The stated architecture:

> Execution → Observation → Redaction → Store

is correct.

---

## 19. But secret redaction must be treated as defense-in-depth

A redactor can fail.

For example:

```text
secret = "abc123"
```

could appear as:

```text
a b c 1 2 3
```

or be encoded/serialized/transformed.

So the actual security guarantee should be:

```text
secret access
 ↓
capability authorization
 ↓
secret broker
 ↓
minimal exposure
 ↓
redaction
```

not merely:

```text
output → regex → redact
```

The repository does have a dedicated `SecretBroker`, which is a strong sign that the architecture is heading in the right direction. <sup>[source]</sup>

---

## 20. Another important finding: the security architecture is fragmented

The repository now contains:

```text
AllowList
CapabilityBroker
SecretBroker
EffectLedger
ApprovalGate
ExecutionEngine
DockerExecutor
ActionStateMachine
InvariantChecker
ProvenanceGraph
```

This is good functionality.

But it creates a new risk:

> **multiple security mechanisms can disagree.**

For example:

```text
AllowList:
    ALLOW

CapabilityBroker:
    ALLOW

EffectLedger:
    detects violation

ApprovalGate:
    not consulted
```

The system needs one canonical policy decision.

---

## 21. Introduce a `SecurityDecision`

Instead of each subsystem independently deciding:

```text
allow / deny
```

have:

```python
SecurityDecision(
    allowed=True,
    capabilities=...,
    effects=...,
    approval=...,
    policy=...,
    subject=...,
    reason=...,
)
```

Then:

```text
CapabilityBroker
       │
AllowList
       │
EffectPolicy
       │
ApprovalGate
       │
       ▼
SecurityDecision
       │
       ▼
ExecutionEngine
```

One decision.

One audit record.

---

## 22. Security policy should be immutable for an execution

Once execution starts:

```text
policy snapshot
```

should not change underneath it.

Otherwise:

```text
t0:
CAP_NETWORK_CONNECT = allowed

t1:
execution begins

t2:
grant revoked

t3:
execution still running
```

needs explicit semantics.

The current broker supports revocation and expiry. <sup>[source]</sup>

The execution record should therefore capture the authorization snapshot.

---

## 23. Scope matching deserves additional scrutiny

Capabilities use:

```python
fnmatch(scope, cap.scope)
```

<sup>[source]</sup>

This is convenient, but filesystem/network scopes often need canonicalization.

For paths:

```text
/workspace/data/../secrets/file
```

and:

```text
/workspace/secrets/file
```

can refer to the same location.

So capability scope should be evaluated against a **canonical target**, not raw user-provided strings.

Similarly for URLs:

```text
example.com
example.com:443
https://example.com/
```

need normalization.

---

## 24. Capability constraints currently use exact equality

The broker does:

```text
request.constraints[key] == grant.constraints[key]
```

for constraints. <sup>[source]</sup>

That's safe in the conservative direction, but not expressive enough for things like:

```text
max_bytes <= 10MB
```

or:

```text
method ∈ {GET, HEAD}
```

Eventually constraints need typed predicates.

But that's a P2 design issue, not the main security flaw.

---

## 25. The most important bypass to eliminate

We now have enough evidence to define the invariant precisely:

```text
K-001:
Every code-bearing string reaching an executor
MUST pass through ExecutionEngine.execute()
```

Not:

```text
every agent cell
```

but:

> **every code-bearing execution.**

That includes:

```text
agent code
recovery code
checkpoint code
diagnostic code
skill code
plugin code
replay code
migration code
bootstrap code
```

Trusted host bootstrap can have an explicitly separate primitive, but it should never accept LLM-generated code.

---

## 26. This immediately fixes several earlier findings

If checkpointing is changed from:

```python
kernel.execute(checkpoint_code)
```

to:

```text
ExecutionEngine.execute(
    checkpoint_code,
    origin=RUNTIME_CHECKPOINT
)
```

then the execution is at least:

```text
audited
correlated
budgeted
observable
```

But I'd go further:

> **Checkpoint serialization should not be implemented as generated Python at all.**

Use host-side serialization.

---

## 27. Same for memory/diagnostics

Avoid:

```text
runtime health
 ↓
generate Python
 ↓
kernel.execute
```

Use:

```text
host process
 ↓
inspect PID/process
```

This eliminates another potential K-001 bypass.

---

## 28. Security hierarchy I'd recommend

```text
                    HARD SECURITY
                         │
                 OS/container boundary
                         │
                 Capability authorization
                         │
                    Approval gate
                         │
                   Effect policy
                         │
                  Static code policy
                         │
                    AST analysis
                         │
                 Import restrictions
                         │
                   Output redaction
                         │
                    Audit/provenance
                         │
                    Soft guardrails
```

The key principle:

> **The farther down the list, the less it should be trusted as the sole security control.**

---

## 29. Current Kerno security maturity

I'd classify the branch approximately as:

### Architecture: **strong**

It has the right concepts.

### Policy model: **strong direction**

Capabilities, subjects, scopes, attenuation, approval.

### Static enforcement: **moderate**

Allowlist is useful but regex-based.

### Runtime enforcement: **moderate**

Import hook + effect observation, but Python remains fundamentally unrestricted at interpreter level.

### Isolation: **potentially strong**

Docker executor exists, but must be the actual executor for untrusted workloads, not merely an optional component. <sup>[source]</sup>

### Execution integrity: **needs hardening**

Direct executor bypasses conflict with K-001.

---

## 30. Revised critical findings

| Finding | Severity |
|---|---:|
| Direct execution paths can bypass `ExecutionEngine` |  **P0** |
| `ORIGIN_RUNTIME` is a powerful trusted escape hatch |  **P1** |
| Allowlist regex is not a sandbox |  **P1** |
| Capability security depends on complete capability declarations |  **P1** |
| Effect ledger detects some violations only after the effect |  **P1** |
| Soft Python import restrictions aren't process isolation |  **P1** |
| Capability scopes need canonicalization |  P2 |
| Security decisions are fragmented across multiple mechanisms |  P2 |
| Constraint language is relatively primitive |  P3 |

---

## 31. The target security architecture

The clean version is:

```text
                 LLM
                  │
                  ▼
             Code Proposal
                  │
                  ▼
             AST Validator
                  │
                  ▼
          Capability Resolver
                  │
                  ▼
            Effect Planner
                  │
                  ▼
          ┌───────────────┐
          │ Approval Gate │
          └───────┬───────┘
                  │
                  ▼
          SecurityDecision
                  │
          ┌───────┴────────┐
          │                │
       DENY              ALLOW
          │                │
          ▼                ▼
       Journal       OS-isolated executor
                           │
                           ▼
                       Observation
                           │
                   ┌───────┴───────┐
                   │               │
                Redaction      Effect audit
                   │               │
                   └───────┬───────┘
                           ▼
                       Provenance
```

---

## 32. The biggest conceptual conclusion so far

Kerno is **not merely a Python notebook agent**.

The branch is attempting something considerably more ambitious:

```text
LLM
+
execution engine
+
capability system
+
effect ledger
+
approval
+
memory
+
provenance
+
checkpointing
+
replay
+
isolation
+
distributed execution
```

The repository itself exposes these as first-class components. <sup>[source]</sup>

That means the correct audit standard is no longer:

> "Does the notebook agent work?"

It is:

> **"Can an autonomous actor cause an externally observable effect without an authorized, attributable, and auditable execution transition?"**

That's the right security invariant for this project.

---

## Next layer: the actual isolation boundary

The next thing to inspect is **`DockerExecutor`, `SubprocessExecutor`, `CapabilityExecutor`, `EffectLedger`, and the server-facing execution paths**.

That will answer the final major security question:

```text
LLM
 ↓
ExecutionEngine
 ↓
Docker / subprocess / Jupyter
 ↓
HOST
```

Specifically, we need to determine whether filesystem, network, process, and secret capabilities are **actually enforced by the operating system**, or whether Kerno currently relies primarily on Python-level policy.

If the latter is true, the final classification will be:

> **policy-controlled arbitrary Python**, not a true security sandbox.

If Docker/process isolation is mandatory and correctly configured, Kerno can legitimately claim a much stronger execution-security model.

---

## Isolation boundary audit

I checked the actual deployment files on `arena/01a0064f-kerno`. This gives us an important correction to the previous security assessment.

Kerno **does run inside Docker in its production deployment**, but the Docker configuration shown here is primarily **containerizing the Kerno server itself**. It does **not yet prove that each untrusted Python kernel is independently sandboxed**.

That distinction is critical.

---

## 1. Current deployment topology

The production stack is essentially:

```text
Internet
   │
   ▼
Nginx
   │
   ▼
Open WebUI
   │
   ▼
Kerno API server
   │
   ▼
KernelPool
   │
   ▼
Jupyter kernels
```

The production Compose file exposes Kerno on port `8001`, mounts persistent `/data` and `/sessions`, mounts skills read-only, and applies an 8 GB / 4 CPU service-level resource limit. <sup>[source]</sup>

The Kerno image itself is based on:

```text
python:3.11-slim
```

and installs the complete Kerno package with:

```text
pip install -e ".[all]"
```

<sup>[source]</sup>

---

## 2.  Dockerizing Kerno ≠ sandboxing generated Python

This is the central finding.

There are two very different architectures.

### Current apparent model

```text
Docker container
└── Kerno server
    ├── KernelPool
    ├── Jupyter kernel 1
    ├── Jupyter kernel 2
    └── Jupyter kernel 3
```

### Strong isolation model

```text
Kerno server container
        │
        ├── execution request
        │
        ▼
   isolated worker
        │
        ├── separate filesystem
        ├── restricted network
        ├── restricted capabilities
        ├── resource limits
        └── disposable process/container
```

The first protects the **host from the Kerno container**, but doesn't automatically protect one generated workload from another.

---

## 3. Why this matters

Suppose an agent executes:

```python
open("/sessions/other-session/file", "r")
```

If all kernels share the same container filesystem, Docker hasn't prevented cross-session access.

Likewise:

```python
import subprocess
subprocess.run(...)
```

can potentially create processes **inside the same Kerno container**.

And:

```python
import socket
```

can potentially access whatever network the Kerno container can access.

So the security boundary becomes:

```text
host
  ↓
Docker
  ↓
Kerno
  ↓
ALL kernels
```

rather than:

```text
host
  ↓
Kerno control plane
  ↓
isolated workload
```

---

## 4. The current Compose configuration does not show a per-kernel container

The Compose file defines one `kerno` service:

```text
kerno:
    build:
      dockerfile: Dockerfile.kerno
```

and its pool size controls the number of kernels:

```text
KERNO_POOL_SIZE
```

<sup>[source]</sup>

There is no corresponding:

```text
kernel-worker:
    ...
```

service or dynamically created execution container visible in this deployment configuration.

Therefore I would **not claim per-kernel Docker isolation yet**.

---

## 5. Resource limits are applied at the Kerno service level

Compose specifies:

```text
memory: 8G
cpus: "4"
```

<sup>[source]</sup>

That's useful.

But it means approximately:

```text
Kerno server
+
kernel 1
+
kernel 2
+
kernel 3
+
all plugins
+
all background tasks
=
8 GB / 4 CPUs
```

It does **not** necessarily mean:

```text
kernel 1 = 8 GB
kernel 2 = 8 GB
kernel 3 = 8 GB
```

nor does it give each agent an independent quota.

---

## 6. This creates a multi-tenant resource problem

Suppose:

```text
POOL_SIZE = 5
```

and five agents run simultaneously.

One agent executes:

```python
huge_dataframe = ...
```

and consumes 5 GB.

The other four agents share the remaining container resources.

Therefore:

```text
agent A
   ↓
memory exhaustion
   ↓
container pressure
   ↓
agent B/C/D/E affected
```

The capability system doesn't solve this.

You need **per-execution resource accounting**.

---

## 7. Recommended resource hierarchy

I'd define:

```text
Host/container
      │
      ├── global CPU limit
      ├── global memory limit
      │
      └── execution
            ├── CPU quota
            ├── memory limit
            ├── process limit
            ├── file size limit
            ├── wall-clock timeout
            └── output limit
```

Then:

```text
execution_id
   ↓
resource budget
```

becomes part of the execution record.

---

## 8.  Network isolation is currently the bigger concern

The production container is a network-facing service.

Kerno needs to communicate with:

```text
OpenRouter
Open WebUI
possibly external APIs
```

Therefore the container necessarily has network access.

But generated Python runs in that same environment unless a separate executor is used.

So an agent may potentially have the same network reachability as the Kerno server.

That is a major capability boundary.

---

## 9. Capability `network.connect` must correspond to OS enforcement

A capability system might say:

```text
network.connect
scope = api.example.com
```

But Python running in the same container may simply use:

```python
socket.create_connection(...)
```

unless the network namespace/firewall actually enforces the restriction.

Therefore:

```text
CapabilityBroker
```

alone isn't sufficient.

You need:

```text
CapabilityBroker
       ↓
OS/network policy
```

---

## 10. The ideal architecture for network access

Instead of allowing arbitrary kernel networking:

```text
Kernel
  │
  └── socket → Internet
```

use:

```text
Kernel
  │
  ▼
Network broker
  │
  ├── destination allowlist
  ├── method restrictions
  ├── rate limits
  ├── credential injection
  └── audit
       │
       ▼
    Internet
```

Then the kernel never receives unrestricted network authority.

---

## 11. Secrets are especially important here

The server receives:

```text
OPENROUTER_API_KEY
```

through its environment. <sup>[source]</sup>

That means the Kerno process necessarily has access to the API key.

If the Jupyter kernel executes inside the same process/container security domain, you must ensure generated Python cannot obtain server secrets.

For example, a workload should never be able to simply inspect:

```python
os.environ
```

and discover:

```text
OPENROUTER_API_KEY
```

This is exactly where **process/container separation** becomes much stronger than Python-level filtering.

---

## 12.  Environment variables are part of the attack surface

The server startup reads:

```text
OPENROUTER_API_KEY
KERNO_MODEL
KERNO_POOL_SIZE
KERNO_MAX_CELLS
```

<sup>[source]</sup>

If generated code has unrestricted access to the process environment:

```python
import os
print(os.environ)
```

then server configuration becomes potentially observable.

Therefore secrets should not live in an environment visible to untrusted execution workers.

Prefer:

```text
Kerno control plane
    │
    └── secret
          │
          ▼
      secure broker
          │
          ▼
   narrowly authorized request
```

---

## 13.  The mounted `/skills` directory deserves attention

Production mounts:

```text
./skills:/skills:ro
```

<sup>[source]</sup>

Read-only is good.

But "read-only" doesn't mean "untrusted code cannot inspect it."

If skills contain:

- API configuration
- internal prompts
- credentials accidentally committed
- proprietary logic
- tool schemas

then generated code may be able to read them.

A security-sensitive skills directory should be treated as application code, not merely static data.

---

## 14. Persistent `/sessions` is another boundary

The production stack mounts:

```text
kerno_sessions:/sessions
```

<sup>[source]</sup>

Earlier we identified that kernels can potentially interact with filesystem state.

Therefore:

```text
session A
session B
session C
```

need explicit filesystem isolation.

Otherwise:

```text
agent A
   ↓
/sessions/B/...
```

could become a cross-session information leak.

---

## 15. The correct model is per-session filesystem namespaces

At minimum:

```text
/sessions/
    session-A/
    session-B/
    session-C/
```

with authorization enforcing:

```text
session-A → /sessions/session-A/**
session-B → /sessions/session-B/**
```

But again, a Python-level allowlist isn't enough for hostile code.

The stronger model is:

```text
worker A → mount only session-A
worker B → mount only session-B
```

Then the OS itself enforces the boundary.

---

## 16. This connects directly to the earlier soft-reset finding

We previously established:

```text
soft reset
≠
clean process
```

Now we have:

```text
shared Kerno container
+
persistent filesystem
+
shared process environment
```

Therefore a soft reset is insufficient for multi-tenant security.

This is no longer merely a correctness concern.

It becomes a **security boundary issue**.

---

## 17. Kernel generation is not a security identity

Earlier we introduced:

```text
kernel_id
generation
```

But:

```text
kernel-1 generation-4
```

doesn't necessarily mean:

```text
isolated security domain
```

It is only an execution lifecycle identity.

A stronger model needs:

```text
tenant_id
session_id
worker_id
process_id
container_id
kernel_id
generation
```

Then provenance can distinguish:

```text
WHO
WHERE
WHICH PROCESS
WHICH KERNEL
WHICH GENERATION
```

---

## 18. Docker should be the *outer* boundary, not necessarily the only boundary

A robust deployment would look like:

```text
                         Host
                           │
                    ┌──────┴──────┐
                    │ Docker/K8s  │
                    └──────┬──────┘
                           │
                    Kerno Control Plane
                           │
                    ┌──────┴──────┐
                    │             │
                Worker A       Worker B
                sandbox       sandbox
                    │             │
                 kernel         kernel
```

The control plane should never share the same privilege domain with arbitrary generated code.

---

## 19. `--cap-drop=ALL` should be considered

For worker containers, a strong baseline would be:

```text
cap_drop:
  - ALL
```

Then explicitly add only what is required.

Also consider:

```text
no-new-privileges
read-only root filesystem
tmpfs for writable temporary state
non-root user
PID limits
memory limits
CPU quota
network policy
```

These are OS-level controls.

They don't replace Kerno's capability model.

They enforce it.

---

## 20. Don't give the worker Docker socket access

This should be an explicit invariant:

```text
worker MUST NOT have:
    /var/run/docker.sock
```

Because if generated code gets Docker socket access, it can potentially escape the intended container boundary and control other containers.

This is one of the highest-value deployment checks.

---

## 21. Another important concern: server exposure

The server starts with:

```text
host = 0.0.0.0
```

<sup>[source]</sup>

and Compose publishes:

```text
8001:8001
```

<sup>[source]</sup>

So Kerno's API is directly exposed on the host interface unless firewall/network configuration says otherwise.

The configuration also has:

```text
KERNO_ENABLE_AUTH=false
```

by default. <sup>[source]</sup>

That is a **serious production configuration concern**.

---

## 22.  Production authentication should fail closed

This default:

```text
KERNO_ENABLE_AUTH=false
```

is dangerous if an operator deploys the Compose file without overriding it.

For an internet-facing autonomous-code execution service, the safer default is:

```text
KERNO_ENABLE_AUTH=true
```

and startup should fail if no valid authentication configuration exists.

---

## 23. Open WebUI also has signup enabled by default

The Compose file contains:

```text
ENABLE_SIGNUP=${ENABLE_SIGNUP:-true}
```

<sup>[source]</sup>

That deserves special attention because the application behind WebUI is not just a chatbot.

It can execute code.

Therefore:

```text
public signup
+
agent execution
=
potential arbitrary-code service
```

unless authorization and isolation are very strong.

For production:

```text
ENABLE_SIGNUP=false
```

should probably be the secure default.

---

## 24. `KERNO_API_KEYS` defaults to empty

The Compose file has:

```text
KERNO_API_KEYS=${KERNO_API_KEYS:-}
```

<sup>[source]</sup>

Combined with:

```text
KERNO_ENABLE_AUTH=false
```

this makes an accidental unauthenticated deployment very easy.

That's acceptable for a local development stack.

It is not an ideal secure production default.

---

## 25. This changes our overall security classification

Based on the code and deployment evidence we've examined:

### Local trusted notebook

**Reasonable**

### Single-user local agent

**Potentially reasonable with guardrails**

### Multi-user Kerno service

**Needs stronger isolation**

### Internet-facing autonomous Python execution service

**Not yet safe to classify as strongly sandboxed**

The distinction is important.

---

## 26. Current architecture should be divided into two planes

## Control plane

```text
Kerno API
LLM
memory
policy
capabilities
audit
provenance
scheduler
kernel pool manager
```

## Data/execution plane

```text
Python
subprocesses
filesystem
network
ML workloads
user data
external APIs
```

The control plane should **not share the same trust domain** as arbitrary execution.

---

## 27. Recommended Kerno vNext topology

```text
                 ┌─────────────────────┐
                 │    API / Web UI      │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │   Kerno Control     │
                 │       Plane         │
                 │                     │
                 │ policy              │
                 │ capabilities        │
                 │ journal             │
                 │ provenance          │
                 │ scheduler           │
                 └──────────┬──────────┘
                            │
                      signed job
                            │
             ┌──────────────┴──────────────┐
             ▼                             ▼
       ┌────────────┐                ┌────────────┐
       │ Worker A   │                │ Worker B   │
       │ sandbox    │                │ sandbox    │
       ├────────────┤                ├────────────┤
       │ Python     │                │ Python     │
       │ Jupyter    │                │ Jupyter    │
       │ FS A       │                │ FS B       │
       │ Net policy │                │ Net policy │
       └────────────┘                └────────────┘
```

---

## 28. What should happen when a kernel dies?

With this architecture:

```text
worker A
   ↓
kernel generation 7
   ↓
crash
   ↓
worker destroyed
   ↓
new worker
   ↓
generation 8
```

Now the reset boundary is actually strong.

Instead of:

```text
restart Jupyter kernel inside same Python process
```

we get:

```text
replace entire security domain
```

That solves several earlier problems simultaneously:

- namespace contamination
- environment leakage
- background threads
- subprocesses
- imported modules
- leaked secrets
- filesystem state
- network connections

---

## 29. Then checkpoint recovery becomes much cleaner

After worker destruction:

```text
checkpoint
    ↓
new isolated worker
    ↓
restore approved data
    ↓
re-observe
```

No need to replay arbitrary historical side effects.

This directly addresses our earlier P0 replay problem.

---

## 30. The resulting recovery model

```text
              Failure
                 │
                 ▼
          Destroy worker
                 │
                 ▼
        Create clean worker
                 │
                 ▼
        Restore checkpoint
                 │
                 ▼
       Reconcile side effects
                 │
                 ▼
          Re-observe state
                 │
                 ▼
          Resume execution
```

This is far stronger than:

```text
restart kernel
↓
re-execute successful cells
```

---

## 31. Updated priority list

After inspecting the runtime, checkpoint, security, and deployment layers, I'd rank the work approximately:

###  P0

1. **Eliminate direct executor bypasses around `ExecutionEngine`.**
2. **Prevent blind replay of side-effecting cells.**
3. **Establish a genuine execution isolation boundary for untrusted Python.**
4. **Make production authentication fail closed.**
5. **Prevent secrets from being visible to execution workers.**

###  P1

6. Per-execution filesystem isolation.
7. Network capability enforcement at OS/network layer.
8. Per-execution resource quotas.
9. Immutable execution/security decision records.
10. Generation-aware checkpoint/recovery.
11. Eliminate generated Python for internal checkpoint/diagnostic operations.

###  P2

12. AST-based policy analysis.
13. Canonical capability scope matching.
14. Typed effect constraints.
15. More granular worker lifecycle telemetry.

---

## 32. One thing I would **not** do

I would **not** try to solve this by making the regex allowlist increasingly complicated.

That leads to:

```text
regex v1
 ↓
bypass
 ↓
regex v2
 ↓
bypass
 ↓
regex v3
...
```

Python is too dynamic for that to become a reliable sandbox.

Instead:

```text
policy
+
capability authorization
+
OS isolation
+
resource limits
+
audit
```

should be the security architecture.

---

## 33. Current Kerno maturity map

After this round, I would describe the project like this:

```text
                    KERNO
                      │
       ┌──────────────┼──────────────┐
       │              │              │
   Agent loop      Runtime        Security
       │              │              │
    strong-ish      strong-ish      ambitious
       │              │              │
       └──────────────┼──────────────┘
                      │
                 Main weakness
                      │
                      ▼
             integration boundaries
                      │
          ┌───────────┼───────────┐
          │           │           │
       replay      executor     isolation
          │        bypass         │
          │           │           │
          └───────────┴───────────┘
                      │
                      ▼
              needs hardening
```

The interesting thing is that **the individual components are often thoughtfully designed; the dangerous bugs are appearing at the boundaries between them.**

---

## Next audit: API / multi-user boundary

The next layer should be `kerno/server/openai_compat.py`, authentication, session creation, request-to-agent mapping, and user/session ownership.

That's where we can determine whether:

```text
User A
   ↓
API request
   ↓
Session A
   ↓
Kernel A
   ↓
Memory A
   ↓
Files A
```

is actually enforced—or whether two users can accidentally share:

```text
kernel
namespace
memory
checkpoints
filesystem
capabilities
or session state
```

That will complete the **multi-tenant isolation audit** and connect the server layer to the runtime/security findings above.

---

## HTTP / multi-user boundary audit

This round gives us a much clearer picture. I inspected the OpenAI-compatible server and its server-side security wrapper.

There are **good protections**, but there are also several concrete issues that become important if this is exposed to multiple users.

The most important conclusion:

> **Kerno creates a fresh `session_id` for every HTTP request, but it does not currently establish a durable authenticated user/tenant identity or explicitly bind persistent resources to that identity.**

That is a major difference between **request isolation** and **multi-tenant isolation**.

---

## 1. The HTTP request → kernel path is correctly wrapped

The synchronous endpoint does:

```text
HTTP request
    ↓
_extract_task()
    ↓
task_id
session_id
    ↓
pool.acquire()
    ↓
make_server_engine()
    ↓
ExecutionEngine
    ↓
loop
```

The code explicitly comments that raw kernel execution should not happen directly from the HTTP surface. <sup>[source]</sup>

That's good.

The streaming endpoint follows the same pattern.

So the earlier **HTTP → raw kernel bypass** concern is substantially mitigated.

---

## 2. But session identity is ephemeral

Every request creates:

```python
session_id = str(uuid.uuid4())
```

<sup>[source]</sup>

So:

```text
request 1 → session A
request 2 → session B
request 3 → session C
```

Even if all three requests originate from the same user.

That means Kerno currently has:

> **request sessions**

rather than:

> **user-owned persistent sessions**.

---

## 3. This is a major semantic limitation

Suppose a user asks:

```text
"Load my dataset."
```

Request 1 gets:

```text
session-A
kernel-A
```

Then the user asks:

```text
"Now analyze it."
```

Request 2 gets:

```text
session-B
kernel-B
```

The second request cannot automatically assume that Python state from session A exists.

That's actually safer from a cross-user perspective, but it means the API isn't really exposing a persistent notebook session.

---

## 4. More importantly: there is no user identity in `AgentState`

The code creates:

```python
AgentState(
    task=task,
    session_id=session_id
)
```

<sup>[source]</sup>

There is no:

```text
user_id
tenant_id
principal_id
organization_id
```

attached to the agent state.

Therefore downstream systems cannot reliably answer:

> "Who owns this execution?"

---

## 5. This affects capabilities

Capability systems are based around subjects.

The security architecture already has concepts like:

```text
subject
issuer
grant
scope
```

But the HTTP surface doesn't appear to translate:

```text
authenticated user
       ↓
capability subject
```

because the request model doesn't contain an authenticated principal.

That makes multi-user authorization incomplete.

---

## 6.  The API documentation explicitly says the key isn't validated

The OpenAI compatibility code contains:

> `Key: (any string — we don't validate it)`

<sup>[source]</sup>

That's acceptable for a local Open WebUI adapter.

It is **not acceptable as a production authentication model** for an endpoint capable of executing Python.

The production Compose file also defaults:

```text
KERNO_ENABLE_AUTH=false
```

which compounds the issue. <sup>[source]</sup>

---

## 7.  This should be classified as a production P0/P1

For an API that can invoke autonomous Python execution:

```text
unauthenticated HTTP
      ↓
LLM
      ↓
Python execution
```

is effectively an unauthenticated code-execution service.

For local development, that's fine.

For internet exposure, it's unacceptable.

---

## 8. The server needs a real Principal

The request should resolve into:

```text
Principal
├── principal_id
├── tenant_id
├── roles
├── capabilities
├── session_ids
└── quotas
```

Then:

```text
HTTP credentials
      ↓
Authentication
      ↓
Principal
      ↓
Authorization
      ↓
Execution
```

---

## 9. API keys should not merely be "accepted"

If Kerno wants simple API-key authentication, the request pipeline should be:

```text
Authorization: Bearer <key>
             │
             ▼
        key verifier
             │
             ▼
         principal
             │
       ┌─────┴─────┐
       │           │
   tenant_id    capabilities
```

The key should map to an identity.

Never pass the raw API key downstream.

---

## 10. Session ownership then becomes explicit

Instead of:

```text
session_id = UUID()
```

use:

```text
Session
├── session_id
├── principal_id
├── tenant_id
├── created_at
├── kernel_id
├── generation
├── capability_snapshot
└── resource_budget
```

Now every session has an owner.

---

## 11. The current `task_id` is also request-local

The code generates:

```python
task_id = f"oai-{str(uuid.uuid4())[:8]}"
```

<sup>[source]</sup>

The short eight-character suffix is fine for human readability, but it shouldn't be treated as a globally authoritative identity.

Use a full UUID internally:

```text
execution_id = UUID
display_id = short prefix
```

---

## 12.  Important: session ID is not authorization

A UUID is only an identifier.

It doesn't prove:

```text
who owns it
```

So an API like:

```text
/session/<id>
```

would require an explicit ownership check.

Otherwise:

```text
User A
  ↓
guesses/obtains
  ↓
User B session ID
```

could become a cross-tenant access problem.

The current code doesn't expose such a session endpoint here, but the architecture should enforce ownership before adding one.

---

## 13. CORS is currently completely permissive

The server installs:

```text
allow_origins = ["*"]
allow_methods = ["*"]
allow_headers = ["*"]
```

<sup>[source]</sup>

This is another production concern.

CORS does not provide authentication, so `*` isn't by itself a remote code-execution vulnerability.

But for a browser-facing authenticated application it broadens the set of origins that can interact with the API.

Production should specify known origins.

---

## 14.  More important than CORS: CSRF/auth interaction

If Kerno eventually supports cookie-based authentication, permissive CORS becomes much more dangerous.

The correct model should be:

```text
Bearer API token
+
explicit allowed origins
+
no ambient credentials
```

or a carefully designed browser session with CSRF protection.

Don't rely on CORS as a security boundary.

---

## 15. Request-level `security` is client-controlled

This is an interesting weakness.

The request model contains:

```python
security: str = "permissive"
```

<sup>[source]</sup>

Then:

```python
profile = getattr(request, "security", default_security)
```

and that is passed into `make_server_engine()`.

<sup>[source]</sup>

So the client can request:

```text
security = "permissive"
```

or:

```text
security = "read_only"
```

or even:

```text
security = "none"
```

---

## 16.  `security="none"` is an explicit policy bypass

`make_server_engine()` says:

```python
if profile != "none":
    allowlist = ...
```

So:

```text
security = "none"
```

means:

```text
allowlist = None
```

<sup>[source]</sup>

This is documented as an explicit opt-out.

That is fine **only for a trusted administrative API**.

It should never be available to an untrusted external HTTP caller.

---

## 17. This is a concrete security bug

The request itself controls the security profile.

The safe pattern is:

```text
authenticated principal
       ↓
server policy
       ↓
security profile
```

not:

```text
HTTP client
       ↓
"please use no security"
```

The client should be allowed to request a **stricter** policy, never a weaker one.

---

## 18. Correct policy resolution

Use:

```text
effective_policy =
    intersection(
        server_policy,
        tenant_policy,
        principal_policy,
        request_policy
    )
```

Conceptually:

```text
server = data_analysis
client = permissive

effective = data_analysis
```

Never:

```text
server = data_analysis
client = none

effective = none
```

---

## 19. Capability defaults have an interesting property

`make_server_engine()` uses:

```text
default_capabilities = {"kernel.execute"}
```

when a broker exists. <sup>[source]</sup>

That's actually sensible as a baseline because the pipeline needs permission to execute kernel code.

But it also means:

```text
every server session
   ↓
kernel.execute
```

is implicitly authorized.

That's fine if `kernel.execute` means:

> "may execute within the already constrained server policy."

It becomes dangerous if `kernel.execute` is interpreted as:

> "may do anything Python can do."

Capability semantics must remain narrow.

---

## 20. A single `kernel.execute` capability is too coarse

Eventually distinguish:

```text
kernel.execute
kernel.read_output
filesystem.read
filesystem.write
network.read
network.write
process.spawn
secret.read
checkpoint.write
```

Then a data-analysis agent might have:

```text
kernel.execute
filesystem.read(/workspace/data/**)
filesystem.write(/workspace/output/**)
```

but not:

```text
network.write
process.spawn
secret.read
```

---

## 21. Streaming has a separate ownership problem

The streaming path:

```text
pool.acquire(task_id)
    ↓
StreamingExecutor
    ↓
finally:
pool.release(task_id)
```

<sup>[source]</sup>

is structurally good.

But HTTP disconnect behavior needs careful verification.

If the browser closes the connection:

```text
client disconnect
      ↓
SSE generator cancellation
```

we need to ensure:

```text
LLM stops
kernel execution stops
background task stops
kernel released
budget released
```

Otherwise a user can disconnect while computation continues consuming a kernel.

---

## 22. This is a resource-exhaustion attack vector

Imagine:

```text
100 requests
 ↓
100 expensive LLM tasks
 ↓
clients disconnect
```

If cleanup is imperfect:

```text
kernels/tasks remain active
```

Eventually:

```text
pool exhaustion
CPU exhaustion
memory exhaustion
```

So cancellation propagation must be treated as part of the HTTP security boundary.

---

## 23. `max_cells` is client-controlled too

The request contains:

```python
max_cells: int = 50
```

<sup>[source]</sup>

and the pipeline receives:

```text
max_cells=request.max_cells
```

There is no visible server-side clamp in this code.

So a caller could potentially request:

```text
max_cells = 1000000
```

If downstream validation doesn't clamp it, the server's advertised resource policy can be bypassed.

---

## 24. Server-side budgets should dominate request limits

Correct:

```text
server_max = 50
client_requested = 1000

effective = min(50, 1000)
```

Not:

```text
effective = 1000
```

Similarly:

```text
effective_timeout
effective_memory
effective_output
effective_tokens
effective_concurrency
```

should all be server-controlled upper bounds.

---

## 25. `_extract_task()` introduces an instruction-boundary issue

The API takes arbitrary user messages and combines:

```text
last user message
+
system context
+
prior conversation
```

into one task string. <sup>[source]</sup>

That means the LLM receives a flattened representation rather than a strongly typed message structure.

This isn't necessarily wrong, but it increases prompt-injection ambiguity.

For example:

```text
System context:
"Only analyze CSV files"

Prior conversation:
USER: ignore previous instructions...
```

becomes text inside one task.

The agent layer needs to distinguish:

```text
trusted system policy
user instruction
historical context
tool output
```

rather than relying solely on textual ordering.

---

## 26. This matters even more because the LLM can execute Python

In an ordinary chatbot:

```text
prompt injection
→ bad text response
```

In Kerno:

```text
prompt injection
→ generated Python
→ filesystem/network/process effects
```

Therefore prompt injection becomes an **authorization problem**, not merely an LLM quality problem.

---

## 27. Prior conversation should not automatically gain authority

The current `_extract_task()` adds previous conversation as:

```text
Prior conversation:
...
```

That context is useful.

But tool outputs, user messages, and system instructions must have distinct trust labels.

A robust internal representation would be:

```text
Message
├── source = SYSTEM
├── source = USER
├── source = TOOL
├── source = MEMORY
└── source = MODEL
```

Then policy can say:

```text
only SYSTEM may modify execution policy
```

---

## 28. `_compile_output()` returns the executed code to the client

The synchronous response includes:

```text

```
{cell.code}
```

```

for every cell. <sup>[source]</sup>

That's useful for transparency.

But it creates another information boundary.

If the generated code contains:

```text
embedded credentials
private file contents
internal paths
secret-bearing literals
```

the API response could disclose them.

Output redaction therefore needs to cover:

```text
stdout
stderr
code
tracebacks
generated markdown
images metadata
```

not just stdout.

---

## 29. Code itself is potentially sensitive

Consider generated code:

```python
API_KEY = "..."
```

Even if stdout is redacted:

```text
_compile_output()
```

will return the source.

So source redaction is an important missing layer.

---

## 30. The OpenAI-compatible API also reports zero token usage

It returns:

```text
prompt_tokens = 0
completion_tokens = 0
total_tokens = 0
```

<sup>[source]</sup>

That's not a security issue, but it is important for resource accounting.

A server that supports budgets should eventually track:

```text
LLM input tokens
LLM output tokens
kernel cells
CPU time
memory peak
wall time
network bytes
filesystem bytes
```

Then billing/quota enforcement becomes possible.

---

## 31. The correct multi-tenant model

I'd make this the canonical hierarchy:

```text
Tenant
  │
  ├── Principal
  │     │
  │     ├── Session
  │     │     │
  │     │     ├── Execution
  │     │     │     │
  │     │     │     └── Kernel generation
  │     │     │
  │     │     └── Checkpoints
  │     │
  │     └── Capabilities
  │
  └── Resource quota
```

Everything persistent should be reachable through that ownership chain.

---

## 32. Execution record should become the universal security correlation ID

For every operation:

```text
tenant_id
principal_id
session_id
execution_id
kernel_id
generation
```

Then logs can answer:

> Who caused this?

> Which request caused it?

> Which kernel executed it?

> Which capability authorized it?

> Which files were touched?

> Which external effects occurred?

> Which model generated the code?

That's the provenance layer Kerno is already conceptually aiming toward.

---

## 33. Revised HTTP findings

###  P0

**Unauthenticated production defaults for an arbitrary-code execution API.**

`KERNO_ENABLE_AUTH=false` is the most concerning deployment default. <sup>[source]</sup>

###  P1

**Client-controlled security profile allows `security="none"`.** <sup>[source]</sup>

###  P1

**No authenticated principal/tenant identity is propagated into `AgentState`.**

###  P1

**Persistent resources need explicit session/user ownership.**

###  P1

**Client-controlled `max_cells` needs server-side upper bounds.**

###  P2

**Wildcard CORS is too broad for production.**

###  P2

**Generated source code is returned without the same redaction guarantees as execution output.**

###  P2

**Disconnect/cancellation needs explicit end-to-end verification.**

###  P2

**Flattening system/user/history into one task string weakens trust boundaries.**

---

## 34. What is already good

It is important not to lose sight of the positive findings.

The server **does**:

- create unique execution/session IDs;
- acquire kernels through the pool;
- wrap server execution in `ExecutionEngine`;
- apply an allowlist profile;
- optionally use `CapabilityBroker`;
- optionally use `ExecutionBudget`;
- use the same security wrapper in streaming and synchronous paths;
- release the kernel in `finally`;
- shut down the pool with the application;
- expose health information;
- provide OpenAI-compatible streaming.

Those are meaningful engineering choices. <sup>[source]</sup>

The problem is mainly that **the security context stops at the request/session boundary instead of extending all the way to authenticated ownership and OS-level isolation.**

---

## 35. The complete request path should become

```text
HTTP
 │
 ▼
TLS / reverse proxy
 │
 ▼
Authentication
 │
 ▼
Principal
 │
 ▼
Tenant policy
 │
 ▼
Session authorization
 │
 ▼
Request budget clamp
 │
 ▼
Prompt / message trust classification
 │
 ▼
LLM
 │
 ▼
Execution plan
 │
 ▼
Capability authorization
 │
 ▼
Effect policy
 │
 ▼
Approval if necessary
 │
 ▼
Isolated worker
 │
 ▼
Python/Jupyter
 │
 ▼
Effect observation
 │
 ▼
Redaction
 │
 ▼
Immutable journal
 │
 ▼
Tenant-scoped response
```

That is the architecture I would target.

---

## 36. The most important architectural rule from this audit

Kerno should enforce:

> **No externally supplied request may choose a weaker security policy than the server has authorized.**

Formally:

```text
effective_policy
    =
server_policy ∩ tenant_policy ∩ principal_policy ∩ request_policy
```

The request can narrow permissions.

It cannot widen them.

This one rule fixes the `security="none"` problem elegantly.

---

## 37. Current overall assessment

After auditing:

```text
runtime
checkpoint
recovery
security
isolation
HTTP
deployment
```

I would now describe this Kerno branch as:

> **A serious agent-execution platform prototype with a surprisingly broad security architecture, but whose strongest security guarantees are not yet consistently enforced across all boundaries.**

The most important work is no longer adding features.

It is **making the existing guarantees true**.

---

## Next audit target

The remaining major layer is **memory + persistence + provenance**.

We should inspect:

```text
kerno/memory/
kerno/provenance/
session persistence
memory store
checkpoint metadata
event journal
```

The key question will be:

> **Can information, secrets, tool outputs, or state from one user/session survive into another session through memory, checkpoints, provenance, or the persistent stores mounted at `/data` and `/sessions`?**

That will close the loop on the multi-tenant audit:

```text
User
 ↓
API
 ↓
Session
 ↓
Kernel
 ↓
Memory
 ↓
Checkpoint
 ↓
Future session
```

and determine whether Kerno has **true tenant isolation**, or only **kernel/request isolation**.

---

## Memory / persistence / provenance audit

This layer reveals one of the more important architectural gaps in this Kerno branch.

The memory abstraction is thoughtfully designed, but **tenant/session isolation is not encoded into the memory interface strongly enough**. The current implementation relies heavily on callers remembering to filter by `session_id`.

That is dangerous for a system intended to support autonomous agents and potentially multiple users.

---

## 1. Kerno correctly distinguishes three kinds of state

The memory module explicitly distinguishes:

```text
Kernel namespace
    = active session state

Checkpoint
    = full object serialization

Memory
    = semantic cross-session knowledge
```

<sup>[source]</sup>

This is a **good architectural distinction**.

It prevents the common mistake of treating "memory" as simply dumping the entire Python namespace into a database.

---

## 2. The `MemoryEntry` model is simple and useful

Each entry contains:

```text
content
kind
session_id
task
entry_id
created_at
score
metadata
```

<sup>[source]</sup>

The supported kinds include:

```text
result
error
insight
skill
plan
```

This gives Kerno a reasonable semantic-memory vocabulary.

---

## 3.  But there is no `tenant_id` / `principal_id`

This is the most important finding.

The memory entry contains:

```python
session_id
```

but not:

```text
tenant_id
principal_id
owner_id
```

<sup>[source]</sup>

Therefore the system knows:

> "This memory came from session X."

but not necessarily:

> "This memory belongs to tenant Y."

That becomes problematic because sessions themselves are currently request-generated UUIDs.

---

## 4. Session IDs are not durable ownership boundaries

We already found that the HTTP layer creates:

```python
session_id = uuid.uuid4()
```

for each request.

Therefore the chain is currently approximately:

```text
HTTP request
    ↓
random session_id
    ↓
MemoryEntry.session_id
```

There is no cryptographically/authenticated ownership relationship.

The architecture should instead be:

```text
Principal
   ↓
Tenant
   ↓
Session
   ↓
Execution
   ↓
MemoryEntry
```

---

## 5. The biggest danger is the default retrieval API

The abstract interface has:

```python
retrieve(
    query,
    k=5,
    kind=None,
    min_score=0.0
)
```

There is **no session or tenant argument**. <sup>[source]</sup>

That means the natural operation is:

```text
retrieve("database migration")
```

rather than:

```text
retrieve(
    tenant_id=...,
    principal_id=...,
    session_id=...,
    query="database migration"
)
```

That is a serious design smell for multi-tenant memory.

---

## 6. `list()` is safer—but only if callers use it correctly

`list()` supports:

```python
session_id=None
```

<sup>[source]</sup>

So callers **can** request:

```text
list(session_id=current_session)
```

But because the default is:

```text
session_id=None
```

the API permits unrestricted global listing.

That should not be the default behavior for an agent-facing API.

---

## 7. This is the same security problem in another form

We previously found:

```text
client → security="none"
```

can weaken execution policy.

Here we have:

```text
caller → session_id=None
```

potentially weakening memory isolation.

The underlying pattern is:

> **security-sensitive narrowing is optional instead of mandatory.**

---

## 8. The correct memory API should make ownership mandatory

I'd change the conceptual interface to:

```python
retrieve(
    principal_id,
    tenant_id,
    query,
    ...
)
```

or preferably use a security context:

```python
retrieve(
    context: MemoryContext,
    query: str,
    ...
)
```

where:

```text
MemoryContext
├── tenant_id
├── principal_id
├── session_id
└── authorized_scopes
```

Then the store itself enforces ownership.

---

## 9. Do not trust the caller to filter memory

This is important.

Avoid:

```python
results = memory.retrieve(query)

results = [
    x for x in results
    if x.session_id == session_id
]
```

because someone will eventually forget the filter.

Instead:

```python
memory.retrieve(
    context=current_security_context,
    query=query,
)
```

and let the **store enforce it**.

Security should live below the caller.

---

## 10. SimpleMemoryStore persists to JSON

The default persistence path is:

```text
.kerno/memory.json
```

<sup>[source]</sup>

The implementation writes all entries into a single JSON array.

That's perfectly reasonable for:

> local development / small deployments.

But it creates a problem for:

> multi-user production memory.

---

## 11. A single JSON memory file is effectively a shared database

Conceptually:

```text
.kerno/memory.json
├── User A
├── User B
├── User C
├── Agent X
└── Agent Y
```

The file itself has no OS-level tenant boundary.

Therefore access control has to happen entirely in Python.

That is not ideal for sensitive memory.

---

## 12. It also creates an atomicity problem

`_save()` does:

```text
open(path, "w")
json.dump(...)
```

<sup>[source]</sup>

There is no visible:

```text
temporary file
fsync
atomic rename
```

So a crash during serialization could leave:

```text
.kerno/memory.json
```

partially written.

For a memory system that is supposed to survive crashes, I'd use:

```text
write temp
    ↓
flush/fsync
    ↓
atomic rename
```

or SQLite.

---

## 13. Thread locking does not solve multi-process safety

The store uses:

```python
threading.Lock()
```

<sup>[source]</sup>

That protects threads in the same Python process.

It does not protect:

```text
process A
    ↓
memory.json

process B
    ↓
memory.json
```

from racing.

And Docker workers/processes make this distinction important.

---

## 14. SQLite is a much better baseline

For persistent local Kerno memory:

```text
SQLite
```

would give:

- transactions
- concurrent readers
- locking
- atomic updates
- indexes
- structured metadata
- tenant/session columns
- deletion
- retention policies

Schema could be:

```text
memory_entries
────────────────────────
entry_id
tenant_id
principal_id
session_id
kind
content
task
metadata
created_at
```

with indexes on:

```text
tenant_id
principal_id
session_id
kind
created_at
```

---

## 15. Chroma has the same ownership problem

The Chroma implementation creates one collection:

```text
kerno_memory
```

by default. <sup>[source]</sup>

Entries include:

```text
session_id
kind
task
created_at
```

but again:

```text
tenant_id
principal_id
```

are absent.

So semantic search has the same fundamental isolation issue.

---

## 16.  Semantic retrieval is especially dangerous for tenant isolation

Imagine:

```text
Tenant A:
"Database password is XYZ"

Tenant B:
"How did we configure the database?"
```

A semantic vector search could consider A's memory highly relevant to B.

If retrieval doesn't apply a mandatory tenant filter:

```text
Tenant B
   ↓
query
   ↓
vector search
   ↓
Tenant A memory
```

This is a classic cross-tenant information leak.

And semantic similarity makes accidental leakage **more likely** because exact identifiers don't have to match.

---

## 17. Chroma needs mandatory metadata filtering

Instead of:

```python
where = {"kind": kind}
```

the query should always include something equivalent to:

```text
tenant_id = current_tenant
principal_id = current_principal
```

Then optionally:

```text
session_id = current_session
```

depending on the memory scope.

The crucial point is:

> **The tenant predicate must be generated by the trusted security context, not supplied by the model.**

---

## 18. Memory should have explicit scopes

I'd define at least:

```text
SESSION
PRINCIPAL
TENANT
GLOBAL
```

For example:

### SESSION

```text
only current execution/session
```

### PRINCIPAL

```text
all sessions belonging to this user
```

### TENANT

```text
shared knowledge inside organization
```

### GLOBAL

```text
application-wide curated knowledge
```

Then retrieval can explicitly say:

```text
scope = PRINCIPAL
```

rather than implicitly searching everything.

---

## 19. `store_session_result()` currently stores the namespace

This is particularly interesting:

```python
content = (
    f"Task: {task}\n\n"
    f"Summary: {summary}\n\n"
    f"Final state: {namespace[:500]}"
)
```

<sup>[source]</sup>

So up to the first **500 characters of the final namespace** become persistent memory.

That can be useful.

But it can also capture:

```text
API keys
tokens
private paths
user data
internal variables
PII
database connection strings
```

if those happen to be present in the namespace representation.

---

## 20.  Memory ingestion needs secret filtering

Before:

```text
namespace
    ↓
MemoryEntry
```

we need:

```text
namespace
    ↓
sanitizer
    ↓
secret detector
    ↓
privacy classifier
    ↓
memory policy
    ↓
MemoryEntry
```

Do not rely solely on later retrieval-time redaction.

Once sensitive data enters semantic memory, it may be embedded and replicated across vector-store structures.

---

## 21. This is an important distinction

Output redaction protects:

```text
LLM output
API response
logs
```

Memory sanitization protects:

```text
future retrieval
embeddings
persistent storage
cross-session recall
```

They are different security controls.

---

## 22. Memory poisoning is another risk

Because memory is cross-session, an agent can potentially store:

```text
"Always use this secret API endpoint."
```

or:

```text
"The administrator approved unrestricted execution."
```

If future agents trust memory as authoritative, you've created a persistent prompt-injection mechanism.

Therefore memory should be treated as:

```text
UNTRUSTED CONTEXT
```

unless explicitly promoted.

---

## 23. A memory entry should carry provenance

Instead of:

```text
MemoryEntry(
    content="Use endpoint X",
    kind="insight"
)
```

store:

```text
MemoryEntry
├── content
├── kind
├── tenant_id
├── principal_id
├── session_id
├── execution_id
├── source
├── confidence
├── created_at
├── expires_at
├── sensitivity
└── provenance
```

Then the LLM can know:

```text
This came from:
execution 123
user X
session Y
at time Z
```

rather than treating it as timeless truth.

---

## 24. Memory should not automatically become policy

This is a very important Kerno rule:

```text
memory ≠ authority
```

A stored memory saying:

```text
"network access was approved"
```

must never grant:

```text
network.connect
```

Capabilities must come from the security system.

So:

```text
Memory → context
CapabilityBroker → authority
```

must remain separate.

---

## 25. Memory deletion needs tenant-aware authorization

The interface has:

```python
delete(entry_id)
```

<sup>[source]</sup>

But there is no:

```text
tenant_id
principal_id
```

argument.

Therefore whoever has an `entry_id` and access to the store can potentially delete it.

Deletion should be:

```text
delete(
    context,
    entry_id
)
```

and enforce ownership.

---

## 26. This also matters for GDPR-style deletion

If Kerno eventually supports real users, a user might request:

> Delete all my data.

The system needs to find:

```text
memory
checkpoints
event journal
provenance
session files
vector embeddings
cached outputs
```

associated with:

```text
principal_id
tenant_id
```

That is impossible to do reliably if the persistent model only knows random session IDs.

---

## 27. Retention is missing from the memory model

Entries have:

```text
created_at
```

but no:

```text
expires_at
retention_policy
```

<sup>[source]</sup>

That means memories can become effectively permanent.

For autonomous systems, memory should have lifecycle semantics:

```text
temporary
session
30-day
permanent
curated
```

---

## 28. Memory should have sensitivity labels

I'd introduce:

```text
PUBLIC
INTERNAL
CONFIDENTIAL
SECRET
```

and retrieval policy:

```text
agent capability
      +
memory sensitivity
      ↓
authorization
```

In particular:

```text
SECRET
```

should generally never be placed in semantic memory.

---

## 29. Checkpoints and memory should remain separate

The existing documentation correctly says:

```text
memory ≠ checkpoint
```

<sup>[source]</sup>

Keep that boundary.

### Checkpoint

```text
"restore the exact computational state"
```

### Memory

```text
"recall useful knowledge"
```

Trying to use semantic memory to reconstruct execution state would be unsafe and nondeterministic.

---

## 30. The correct checkpoint trust model

A checkpoint should be:

```text
tenant-bound
session-bound
execution-bound
generation-bound
integrity-protected
```

For example:

```text
checkpoint
├── checkpoint_id
├── tenant_id
├── principal_id
├── session_id
├── execution_id
├── kernel_generation
├── state_hash
├── created_at
└── schema_version
```

And restoration should verify ownership before deserialization.

---

## 31. Never deserialize an untrusted checkpoint blindly

If checkpoint state uses Python serialization such as pickle-like mechanisms, this becomes a very serious issue.

The safe architecture is:

```text
untrusted checkpoint bytes
       ↓
authenticate
       ↓
integrity check
       ↓
schema/version check
       ↓
safe decoder
       ↓
isolated worker
```

not:

```text
bytes
 ↓
pickle.loads()
 ↓
hope
```

This should be a dedicated P0/P1 checkpoint rule if applicable to the implementation.

---

## 32. Memory + execution now form a feedback loop

Kerno's architecture effectively creates:

```text
Execution
   ↓
Result
   ↓
Memory
   ↓
Future prompt
   ↓
LLM
   ↓
Future execution
```

That means memory isn't passive storage.

It becomes part of the **future control loop**.

Therefore memory poisoning is equivalent to a delayed prompt injection.

---

## 33. The safe feedback loop

```text
Execution
   ↓
Observed result
   ↓
Sanitize
   ↓
Classify
   ↓
Store with provenance
   ↓
Retrieve under tenant policy
   ↓
Mark as UNTRUSTED CONTEXT
   ↓
LLM reasoning
   ↓
Capability authorization
   ↓
Execution
```

The key is that memory can influence reasoning but cannot directly grant authority.

---

## 34. Updated architecture

At this point the Kerno design should be thought of as four security domains:

```text
┌─────────────────────────────────────┐
│ CONTROL                             │
│ Policy / Capability / Approval      │
└────────────────┬────────────────────┘
                 │
┌────────────────▼────────────────────┐
│ EXECUTION                           │
│ Isolated Python / Jupyter           │
└────────────────┬────────────────────┘
                 │
┌────────────────▼────────────────────┐
│ STATE                               │
│ Sessions / checkpoints / files      │
└────────────────┬────────────────────┘
                 │
┌────────────────▼────────────────────┐
│ KNOWLEDGE                           │
│ Memory / vectors / insights         │
└─────────────────────────────────────┘
```

And every boundary must carry:

```text
tenant
principal
session
execution
provenance
```

---

## 35. Current memory findings

| Area | Assessment |
|---|---|
| Memory abstraction |  Good |
| Separation from kernel state |  Good |
| Semantic memory concept |  Good |
| Simple local store |  Good for development |
| Vector store abstraction |  Good |
| Tenant identity |  Missing |
| Principal ownership |  Missing |
| Mandatory retrieval isolation |  Missing |
| Memory sanitization |  Needs hardening |
| Memory poisoning defenses |  Needs design |
| Retention |  Missing |
| Provenance depth |  Insufficient |
| Atomic persistence |  Needs improvement |
| Multi-process persistence |  Needs stronger backend |

---

## 36. Most important fixes

If I were hardening this branch, I'd prioritize:

### P0

**1. Make memory retrieval tenant-scoped by construction.**

```text
retrieve(context, query)
```

not:

```text
retrieve(query)
```

### P0

**2. Add authenticated ownership metadata.**

```text
tenant_id
principal_id
```

### P0

**3. Sanitize memory before persistence.**

### P1

**4. Treat memory as untrusted context, never authority.**

### P1

**5. Add provenance to every memory entry.**

### P1

**6. Replace JSON persistence with SQLite for serious deployments.**

### P1

**7. Add retention and deletion semantics.**

### P1

**8. Apply mandatory tenant metadata filters to Chroma/vector retrieval.**

---

## 37. The deeper finding

We're now seeing a consistent pattern across Kerno:

```text
ExecutionEngine       → strong concept
CapabilityBroker     → strong concept
MemoryStore          → strong concept
Checkpointing        → strong concept
Provenance           → strong concept
```

But:

```text
                 integration
                     ↓
       ┌─────────────┼─────────────┐
       │             │             │
    identity      ownership      isolation
       │             │             │
       └─────────────┼─────────────┘
                     ↓
               still incomplete
```

This is actually encouraging.

It means the repository doesn't need a completely different architecture.

It needs **security context propagation across every subsystem**.

---

## 38. The single object I'd introduce

A lot of these problems disappear if Kerno introduces one immutable object:

```python
SecurityContext
```

containing:

```text
tenant_id
principal_id
session_id
execution_id
capability_snapshot
policy_snapshot
resource_budget
```

Then every security-sensitive subsystem receives it:

```text
ExecutionEngine(context)
MemoryStore(context)
CheckpointStore(context)
ProvenanceStore(context)
SecretBroker(context)
EffectLedger(context)
```

No subsystem should have to guess:

> "Which user does this belong to?"

---

## 39. Final target

The entire Kerno lifecycle becomes:

```text
                   PRINCIPAL
                       │
                       ▼
                    SESSION
                       │
                       ▼
                   EXECUTION
                       │
              SecurityContext
                       │
       ┌───────────────┼────────────────┐
       │               │                │
       ▼               ▼                ▼
   Capability       Memory          Checkpoint
       │               │                │
       ▼               ▼                ▼
    Policy         Provenance       Integrity
       │               │                │
       └───────────────┼────────────────┘
                       ▼
                 Isolated Worker
                       │
                       ▼
                    Effects
                       │
                       ▼
                    Journal
```

That would give Kerno a coherent security model instead of a collection of individually good security components.

---

## Next: provenance + event journal

The remaining piece I would audit is the **event/provenance layer itself**:

```text
execution events
audit records
effect events
memory provenance
checkpoint provenance
request IDs
kernel IDs
generation IDs
```

The key question is:

> **Can Kerno produce a cryptographically/structurally trustworthy chain showing exactly which authenticated principal caused which LLM decision, which generated code, which capability grant, which kernel execution, which side effect, and which persisted memory?**

That is the final step from **"audited agent runtime"** to a genuinely **traceable agent runtime**.

---

## Provenance, audit trail, and artifact integrity

I inspected the actual `arena/01a0064f-kerno` implementation rather than treating the documentation as proof.

This round changes the picture somewhat: **Kerno already has a substantial audit/provenance design.** In particular, the notebook audit trail and content-addressed artifact store are stronger than the earlier high-level architecture suggested.

The remaining issue is that these mechanisms are currently better described as **traceability artifacts** than as a complete **tamper-evident security ledger**.

---

## 1. Kerno has a real audit subsystem

The branch contains:

```text
kerno/audit/
├── __init__.py
└── notebook.py
```

<sup>[source]</sup>

So auditability is not merely documentation.

There is executable audit code.

---

## 2. The notebook is intended to be the primary artifact

`NotebookAuditTrail` explicitly describes the notebook as:

```text
the primary artifact
```

and records:

- executed cells
- reasoning
- errors
- recoveries
- session metadata
- execution correlation
- reproducibility information

<sup>[source]</sup>

That's a strong design choice.

The resulting `.ipynb` becomes a human-readable reconstruction of an agent session.

---

## 3.  Code is explicitly redacted before entering the notebook

This is an important positive finding.

The implementation doesn't only redact reasoning.

It does:

```text
reasoning → redactor
error → redactor
code → redactor
```

The source code comment explicitly states that generated code is redacted so secret literals don't land in the notebook. <sup>[source]</sup>

That directly addresses one of the concerns from the previous memory audit.

---

## 4. But the redaction boundary is incomplete

There is a subtle problem.

The code source is passed through:

```python
self._redactor(cell.code)
```

but the outputs are converted separately.

For example:

```python
cell.output.stdout
cell.output.stderr
cell.output.result
cell.output.displays
cell.output.images
cell.output.error.traceback
```

are placed into notebook outputs. <sup>[source]</sup>

The `_convert_outputs()` implementation does **not visibly call `_redact()`** on all those fields.

So we have:

```text
code       → redacted
reasoning  → redacted
error text → partly redacted
stdout     → not visibly redacted
stderr     → not visibly redacted
result     → not visibly redacted
HTML       → not visibly redacted
JSON       → not visibly redacted
images     → not visibly redacted
traceback  → not visibly redacted
```

###  This is a concrete finding.

The comment says:

> secrets are never stored in the notebook

but the implementation shown does not establish that invariant for all output channels.

That claim should therefore be weakened until verified.

---

## 5. Tracebacks are particularly dangerous

A traceback can contain:

```text
/home/user/secrets/project.py
```

or:

```text
ConnectionError("https://user:password@example.com")
```

or variable values embedded in exception messages.

The notebook currently converts traceback lines directly:

```python
tb.split("\n")
```

<sup>[source]</sup>

Therefore traceback redaction needs to happen before persistence.

---

## 6. HTML output is another hidden exfiltration channel

Generated code may produce:

```python
display(HTML(...))
```

The notebook stores:

```text
text/html
```

directly. <sup>[source]</sup>

That HTML can contain:

- secrets
- URLs
- tokens
- embedded data
- external resources
- potentially active HTML content

Therefore HTML needs both:

```text
secret redaction
+
content sanitization
```

---

## 7. Images can contain sensitive information too

The audit trail stores base64 PNG data:

```text
image/png
```

<sup>[source]</sup>

A secret displayed in a plot or screenshot won't be detected by a simple text redactor.

So:

```text
text redaction
```

cannot guarantee:

```text
visual secrecy
```

If notebooks are shared outside the original tenant, image output becomes part of the data-loss boundary.

---

## 8. The artifact store is significantly stronger

`kerno/artifacts.py` implements a content-addressed store.

The key property is:

```text
digest = SHA-256(content)
```

and artifacts are stored under that digest. <sup>[source]</sup>

That gives us:

```text
artifact
   ↓
SHA-256
   ↓
content address
```

This is a strong integrity primitive.

---

## 9. The artifact invariant is explicit

When reading an artifact, Kerno calculates:

```text
sha256(stored_bytes)
```

and compares it with the requested digest.

If they differ:

```text
ArtifactIntegrityError
```

is raised. <sup>[source]</sup>

That's good.

It means corrupted/tampered bytes are detectable.

---

## 10. But this is integrity, not authenticity

This distinction is crucial.

A SHA-256 content address proves:

> These bytes correspond to this digest.

It does **not** prove:

> A trusted Kerno authority created these bytes.

An attacker who can write to the artifact directory can create:

```text
malicious artifact
      ↓
SHA-256
      ↓
valid-looking artifact
```

The hash remains internally consistent.

Therefore:

```text
hash ≠ signature
```

---

## 11. For security-sensitive provenance, add signatures or a trusted journal

A stronger model would be:

```text
artifact bytes
     ↓
SHA-256
     ↓
artifact digest
     ↓
signed provenance record
     ↓
trusted signer
```

Then we have:

```text
integrity
+
authenticity
+
provenance
```

rather than integrity alone.

---

## 12. There is also a subtle metadata problem

`ArtifactRef` contains:

```text
digest
media_type
size
creator_execution
created_at
metadata
```

<sup>[source]</sup>

But the digest covers only:

```text
artifact bytes
```

not necessarily:

```text
metadata
creator_execution
tenant
session
```

So someone could potentially alter the metadata associated with an artifact without changing the artifact's content hash.

The metadata therefore needs its own integrity/provenance protection.

---

## 13. `creator_execution` is a good start

This field is valuable:

```text
creator_execution
```

<sup>[source]</sup>

It lets Kerno say:

```text
artifact
   ↓
created by execution X
```

But we need to connect:

```text
execution X
 ↓
principal
 ↓
tenant
 ↓
session
 ↓
kernel generation
```

Otherwise `creator_execution` is only a local identifier.

---

## 14. Notebook correlation is also good

Each code cell stores:

```text
kerno_execution
├── execution_id
├── code_hash
└── output_hash
```

<sup>[source]</sup>

This is one of the strongest pieces of the current audit design.

It creates a direct relationship:

```text
Notebook cell
    │
    ├── execution_id
    ├── code hash
    └── output hash
```

That is excellent for forensic reconstruction.

---

## 15. But the hash is truncated

The code stores:

```python
hexdigest()[:16]
```

for both code and output hashes. <sup>[source]</sup>

That means the notebook metadata contains only:

```text
64-bit-ish prefix
```

rather than the complete SHA-256 digest.

For a human-readable audit trail this may be acceptable.

For cryptographic identity, I would use the full:

```text
sha256:<64 hex characters>
```

and optionally display a short prefix separately.

---

## 16. Reproducibility metadata is a strong feature

The notebook can embed:

```text
task_hash
model
kernel_generation
Python version
platform
kernel spec
package count
```

<sup>[source]</sup>

That's valuable because:

```text
same code
≠
same environment
```

An agent result can change because:

- Python version changed
- package version changed
- model changed
- kernel generation changed

Recording these values is exactly the right direction.

---

## 17. But the environment manifest itself must be authenticated

The manifest is written as:

```text
<session_id>.manifest.json
```

<sup>[source]</sup>

Again:

```text
manifest
```

is data.

If someone can modify it after execution, the audit record could claim:

```text
model = X
Python = 3.11
```

when the actual execution happened under something else.

So provenance needs:

```text
manifest hash
+
execution record
```

or a signed record.

---

## 18. Artifact immutability is slightly weaker than the documentation suggests

The implementation says:

> mutation is impossible

but `store_bytes()` actually does this if an existing artifact's bytes don't match the digest:

```text
restore canonical content
```

<sup>[source]</sup>

That's a useful self-healing behavior.

But it isn't true immutability in the OS sense.

The file is still writable.

A process with filesystem write access can modify it.

Kerno detects and restores the content when accessed/stored again.

That's:

```text
content-address integrity + repair
```

not:

```text
immutable storage
```

---

## 19. This distinction matters for forensics

Suppose an attacker modifies an artifact:

```text
original
 ↓
tampered
```

Kerno later reads it:

```text
hash mismatch
 ↓
error
```

or restores it during a subsequent store operation.

But we don't necessarily get an immutable record saying:

```text
AT TIME T
artifact X
was modified by process Y
```

That's an **audit event** problem.

---

## 20. The audit ledger therefore needs events

The minimum useful event structure is:

```text
AuditEvent
├── event_id
├── timestamp
├── tenant_id
├── principal_id
├── session_id
├── execution_id
├── kernel_id
├── generation
├── event_type
├── subject
├── action
├── decision
├── capability
├── artifact_refs
├── previous_event_hash
└── event_hash
```

---

## 21. Then the events form a hash chain

For example:

```text
Event 1
hash = H(event1)

Event 2
previous = H(event1)
hash = H(previous || event2)

Event 3
previous = H(event2)
hash = H(previous || event3)
```

Result:

```text
E1 → E2 → E3 → E4 → E5
```

If E3 changes:

```text
E1 → E2 → ❌ E3
             ↓
          E4 invalid
          E5 invalid
```

That makes tampering evident.

---

## 22. Better still: periodic signed checkpoints

For a production audit system:

```text
events
 ↓
hash chain
 ↓
checkpoint every N events
 ↓
digital signature
```

Then you don't need a blockchain.

You need:

```text
append-only journal
+
hash chaining
+
trusted signing key
```

That's much simpler.

---

## 23. The notebook should be a projection, not the authoritative ledger

This is an important architectural refinement.

Currently the notebook documentation says:

> The notebook is the primary artifact.

I would change that conceptually to:

```text
Authoritative record
        ↓
Execution/Audit ledger
        │
        ├── Notebook projection
        ├── Artifact projection
        ├── UI projection
        └── API response
```

Why?

Because notebooks are:

- editable
- executable
- human-readable
- relatively large
- not inherently append-only

They are excellent **evidence views**.

They are not ideal authoritative audit logs.

---

## 24. Re-running the notebook is also dangerous

The audit documentation says the notebook can be:

> re-run by a human. <sup>[source]</sup>

That's useful for reproducibility.

But an audit notebook containing:

```python
requests.post(...)
```

can repeat side effects.

Therefore the notebook needs explicit execution semantics:

```text
REPLAY-SAFE
```

versus:

```text
SIDE-EFFECTING
```

A human opening the notebook should receive a warning before executing cells with known effects.

---

## 25. This reconnects with our earlier replay finding

We previously identified:

```text
successful historical cell
        ↓
blind replay
```

as unsafe.

The audit notebook creates another possible replay path:

```text
audit notebook
       ↓
human clicks "Run All"
       ↓
side effects happen again
```

Therefore audit artifacts need effect annotations.

---

## 26. Every cell should ideally have an effect classification

For example:

```text
PURE
READ_LOCAL
WRITE_LOCAL
NETWORK_READ
NETWORK_WRITE
PROCESS
DATABASE_WRITE
EXTERNAL_SIDE_EFFECT
UNKNOWN
```

Then the notebook could visually mark:

```text
Cell 7  🟢 PURE
Cell 8  🔵 READ_LOCAL
Cell 9  🔴 NETWORK_WRITE
```

This would make the artifact much safer to replay.

---

## 27. Artifact provenance should include effect provenance

For:

```text
report.pdf
```

Kerno should be able to answer:

```text
created by execution X
from input artifacts A/B/C
using code hash H
under model M
in kernel generation G
authorized by capability C
```

That creates a provenance DAG:

```text
A ──┐
    ├──> Execution X ──> Report.pdf
B ──┘
```

rather than merely:

```text
Report.pdf → execution X
```

---

## 28. This is where Kerno could become genuinely differentiated

The project already has the ingredients:

```text
Agent
Kernel
Execution
Capability
Memory
Artifact
Notebook
Manifest
```

If connected through a rigorous provenance graph:

```text
Principal
   ↓
Task
   ↓
Model decision
   ↓
Generated code
   ↓
Capability decision
   ↓
Execution
   ↓
Effects
   ↓
Artifacts
   ↓
Memory
```

Kerno becomes not merely:

> an agent that executes Python

but:

> **an agent execution system where computational actions are traceable, attributable, and reconstructible.**

That's a much stronger architectural identity.

---

## 29. Updated provenance maturity

| Component | Assessment |
|---|---|
| Notebook audit |  Strong |
| Code/output correlation |  Strong concept |
| Code redaction |  Present |
| Content-addressed artifacts |  Strong |
| Artifact integrity checking |  Strong |
| Reproducibility metadata |  Strong |
| Full output redaction |  Incomplete |
| Tenant attribution |  Missing/incomplete |
| Cryptographic authenticity |  Missing |
| Append-only event chain |  Not established |
| Effect provenance |  Needs expansion |
| Artifact dependency graph |  Needs expansion |
| Safe replay semantics |  Needs enforcement |
| Audit artifact immutability |  Not OS-level |

---

## 30. The most important correction to the previous audit

I would **not** say:

> "Kerno has no provenance."

That would be wrong.

The repository clearly contains meaningful provenance mechanisms.

The accurate statement is:

> **Kerno has substantial artifact- and notebook-level traceability, but it has not yet demonstrated a single authoritative, tenant-aware, tamper-evident event ledger connecting identity → decision → capability → execution → effect → artifact → memory.**

That's much more precise.

---

## 31. Recommended target architecture

```text
                    PRINCIPAL
                        │
                        ▼
                      TASK
                        │
                        ▼
                 MODEL DECISION
                        │
                        ▼
                 GENERATED CODE
                        │
                        ▼
               POLICY EVALUATION
                        │
                        ▼
              CAPABILITY DECISION
                        │
                        ▼
                  EXECUTION
                        │
             ┌──────────┼──────────┐
             ▼          ▼          ▼
          FILES      NETWORK     PROCESS
             │          │          │
             └──────────┼──────────┘
                        ▼
                     EFFECT
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
       ARTIFACT       MEMORY       NOTEBOOK
          │             │             │
          └─────────────┼─────────────┘
                        ▼
                AUDIT EVENT CHAIN
                        │
                        ▼
                 SIGNED CHECKPOINT
```

That is the architecture I'd use as the **Kerno security/provenance north star**.

---

## 32. Final P0/P1 list after this audit

We now have a much tighter list.

###  P0 — Security boundary

1. **Authenticated principal + tenant propagation**
2. **Per-worker OS/container isolation**
3. **Server-controlled security profile**
4. **No unauthenticated production execution**
5. **Mandatory tenant-scoped memory retrieval**
6. **Secrets excluded from execution workers**

###  P1 — State and provenance

7. **Full output redaction before notebook persistence**
8. **Tenant/principal provenance on artifacts**
9. **Authoritative execution/event ledger**
10. **Hash-linked audit events**
11. **Checkpoint integrity + ownership**
12. **Memory sanitization and provenance**
13. **Server-side resource-budget clamps**
14. **Safe replay/effect classification**

###  P2 — Hardening

15. SQLite-backed memory
16. retention policies
17. signed provenance checkpoints
18. artifact dependency DAG
19. richer effect taxonomy
20. replay-safe notebook UX

---

## 33. The next layer is now the actual execution/capability enforcement

We have now audited:

```text
1. deployment
2. HTTP/API
3. session identity
4. memory
5. persistence
6. artifacts
7. notebook audit
8. provenance model
```

The next—and probably most technically important—part is:

```text
kerno/capability.py
kerno/capability_exec.py
kerno/action.py
kerno/approval.py
kerno/_run.py
kerno/agent.py
```

We need to trace one real operation all the way through:

```text
LLM says:
    "Run this Python"

        ↓

Action / plan

        ↓

Capability request

        ↓

CapabilityBroker

        ↓

Approval

        ↓

ExecutionEngine

        ↓

Kernel

        ↓

Actual OS effect
```

The critical question is no longer whether Kerno **has** a capability system—it clearly does.

The question is:

> **Can generated Python actually bypass the capability system through imports, subprocesses, filesystem APIs, sockets, Jupyter internals, or direct executor access?**

That is the next decisive audit.

---

## capability enforcement vs. actual Python escape paths

This is the most important security round so far.

I inspected the actual `AllowList` implementation in the `arena/01a0064f-kerno` branch. The project has **two-layer enforcement** by design:

```text
generated code
      │
      ├── static inspection
      │
      ▼
AllowList.check()
      │
      ▼
kernel execution
      │
      ▼
runtime import hook
```

That is a good architecture in principle. <sup>[source]</sup>

But the implementation is still fundamentally **Python-code pattern enforcement**, not a security boundary.

That distinction is critical.

---

## 1. What Kerno is doing right

The threat model in `allowlist.py` explicitly recognizes:

- prompt injection through data;
- capability creep;
- data exfiltration.

It also explicitly says enforcement occurs at:

1. static analysis before execution;
2. runtime import hooks inside the kernel. <sup>[source]</sup>

That is considerably better than simply telling the LLM:

> "Don't use dangerous Python."

---

## 2. The data-analysis profile is reasonably restrictive

The `data_analysis()` profile permits things such as:

```text
pandas
numpy
matplotlib
sklearn
scipy
statsmodels
seaborn
plotly
IPython
pathlib
json
re
math
datetime
collections
itertools
functools
typing
dataclasses
warnings
io
```

and Kerno-specific wrappers. <sup>[source]</sup>

It explicitly blocks:

```text
subprocess
urllib
requests
socket
shutil
importlib
```

and several filesystem-writing operations.

That's a sensible **policy profile**.

---

## 3. The read-only profile is stronger

`read_only()` blocks:

```text
open()
subprocess
urllib
requests
socket
os.*
shutil
pickle
importlib
```

and various write operations. <sup>[source]</sup>

It also blocks:

```text
eval()
exec()
compile()
__import__()
open()
```

So the author clearly understands several common Python escape mechanisms.

---

## 4. But static regex analysis cannot be the security boundary

This is the fundamental problem.

The static layer essentially asks:

```text
"Does the source text contain something dangerous?"
```

A security boundary must instead answer:

```text
"Can the resulting process perform the dangerous operation?"
```

Those are very different questions.

---

## 5. Example: aliasing

Suppose a policy blocks:

```python
os.system(...)
```

but allows:

```python
import os
```

or another path that gives access to the same functionality.

Textual matching can be defeated by:

```python
alias = os.system
alias("...")
```

The exact pattern doesn't necessarily match.

The underlying capability still exists.

---

## 6. Dynamic attribute access is another problem

Pattern rules can block:

```python
subprocess.Popen(...)
```

but Python supports dynamic attribute resolution.

For example, dangerous objects can sometimes be reached through:

```text
getattr(...)
globals()
locals()
sys.modules
object.__subclasses__()
```

This is precisely why Python sandboxing is notoriously difficult.

A regex is not a Python security model.

---

## 7. `blocked_builtins` is only textual

The implementation checks:

```python
pattern = r'\b' + builtin + r'\s*\('
```

<sup>[source]</sup>

So it catches:

```python
eval(...)
```

but the security property is not:

> "The `eval` capability doesn't exist."

It is:

> "This particular textual form of calling `eval` wasn't detected."

That's substantially weaker.

---

## 8. AST analysis would be better—but still isn't enough

The first improvement should be:

```text
source
 ↓
Python AST
 ↓
semantic validation
```

instead of regex alone.

That catches:

```python
getattr(...)
__import__(...)
```

more reliably.

But even AST validation isn't sufficient for a hostile Python process.

Why?

Because Python is dynamically introspective.

---

## 9. The real security boundary must be outside Python

This is the central conclusion.

If Kerno wants to execute potentially adversarial LLM-generated Python, the architecture should be:

```text
                untrusted Python
                       │
                       ▼
                isolated worker
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       filesystem    network      process
       sandbox       policy       boundary
```

The OS/container should enforce the final boundary.

Not the regex.

---

## 10. Think of AllowList as Layer 1, not Layer 4

I'd classify the current mechanism as:

```text
Layer 1 — prompt/code policy
        ↓
Layer 2 — import restriction
        ↓
Layer 3 — capability authorization
        ↓
Layer 4 — OS/container isolation
```

Kerno currently has substantial work in Layers 1–3.

Layer 4 is the decisive one.

---

## 11. The dangerous assumption

The dangerous assumption would be:

```text
AllowList passed
      ↓
Python is safe
```

The correct assumption is:

```text
AllowList passed
      ↓
Python is policy-compatible
      ↓
still untrusted
      ↓
execute inside sandbox
```

That distinction should be documented explicitly.

---

## 12. `stdlib_module_names` is particularly interesting

The runtime import hook allows:

```python
if top_level in getattr(_sys, 'stdlib_module_names', ()):
    return _original_import(...)
```

<sup>[source]</sup>

This means **the entire Python standard library is implicitly available** once the runtime hook is installed.

That is a much larger attack surface than the allowlist initially suggests.

---

## 13. Why this matters

The static profile might say:

```text
"Only pandas/numpy/etc."
```

but the runtime hook effectively says:

```text
standard library = allowed
```

That includes powerful modules depending on Python version/platform.

For example, standard-library access can expose facilities involving:

```text
filesystem
process environment
networking
subprocess execution
dynamic loading
introspection
IPC
```

Even if some obvious names are blocked statically.

---

## 14. This creates a policy inconsistency

The static layer says:

```text
blocked:
    subprocess
    socket
    os.environ
```

while the runtime layer says:

```text
stdlib modules:
    allowed
```

These policies are not necessarily equivalent.

The system therefore has:

```text
static policy
     ≠
runtime policy
```

That is a red flag.

The two enforcement layers should derive from **one canonical capability policy**.

---

## 15. Already-loaded modules are also automatically allowed

The runtime hook contains:

```python
if top_level in _sys.modules:
    return _original_import(...)
```

<sup>[source]</sup>

The rationale is understandable:

> Jupyter/ipykernel itself lazily imports internal modules.

But security-wise this means:

```text
already loaded
      =
automatically accessible
```

That creates a capability inheritance problem.

---

## 16. The kernel itself becomes part of the trusted computing base

Once Kerno executes:

```text
ipykernel
IPython
Jupyter internals
```

inside the same Python process, those objects exist in the interpreter.

If untrusted code can obtain references to them, the import hook is no longer enough.

So:

```text
import restriction
```

cannot guarantee:

```text
object/reference restriction
```

---

## 17. This is where Python introspection becomes important

Python has mechanisms such as:

```text
globals()
locals()
vars()
getattr()
object.__subclasses__()
type(...)
```

and access to existing objects.

A secure Python sandbox must assume that **object graph traversal is hostile**.

Blocking imports doesn't eliminate this.

---

## 18. The `os.path` exception deserves attention

The data-analysis allowlist includes:

```text
"os.path"
```

<sup>[source]</sup>

That's reasonable for path inspection.

But because Python import semantics operate around the top-level module:

```text
os
```

vs:

```text
os.path
```

the implementation needs careful testing around:

```python
import os
from os import path
import os.path
```

The static checker and runtime hook must agree on all three forms.

---

## 19. `from ... import ...` parsing is also imperfect

The static regex:

```python
r'^\s*(?:import|from)\s+([\w.]+)'
```

extracts only the initial module path. <sup>[source]</sup>

For:

```python
from package import dangerous
```

it knows:

```text
package
```

but not necessarily whether:

```text
dangerous
```

itself represents a prohibited capability.

Again:

```text
module allowlist
```

is not equivalent to:

```text
capability allowlist
```

---

## 20. The real unit should be an effect

Instead of only:

```text
allowed module = X
```

Kerno should reason about:

```text
effect = filesystem.read
effect = filesystem.write
effect = network.connect
effect = process.spawn
effect = secret.read
effect = native_code.load
```

Then:

```text
pandas.read_csv()
```

is evaluated according to the **effect it causes**, not merely the fact that pandas is allowed.

---

## 21. This is especially important for `pandas`

The project correctly blocks:

```text
read_csv("https://...")
read_json("https://...")
read_excel("https://...")
```

<sup>[source]</sup>

That's good.

But pandas can reach external resources through more mechanisms than one regex can enumerate.

The stronger design is:

```text
network disabled at OS level
```

Then even if pandas discovers another network path:

```text
network call
   ↓
OS denies
```

---

## 22. Same for filesystem writes

The allowlist blocks:

```text
Path.write_text()
Path.write_bytes()
Path.unlink()
DataFrame.to_csv()
DataFrame.to_parquet()
DataFrame.to_excel()
savefig()
```

<sup>[source]</sup>

That's useful.

But there are many ways to write bytes in Python.

The sandbox should instead establish:

```text
/read-only input
/workspace writable
/data policy-controlled
/system inaccessible
```

Then filesystem policy is enforced independently of Python syntax.

---

## 23. This leads to a much cleaner architecture

Instead of trying to blacklist every Python write method:

```text
Python
 ↓
OS sandbox
 ↓
filesystem policy
```

Then Kerno's Python allowlist becomes:

```text
defense in depth
```

rather than:

```text
sole protection
```

---

## 24. Network isolation should be equally explicit

For a data-analysis worker:

```text
network namespace
    ↓
NO INTERNET
```

If the agent legitimately needs network access:

```text
network
   ↓
policy proxy
   ↓
allowlisted destination
```

rather than:

```text
Python socket
   ↓
Internet
```

---

## 25. Secrets should never be inherited

This is another OS-level control.

The worker should receive a deliberately constructed environment:

```text
PATH=/usr/bin:/bin
HOME=/workspace/home
PYTHONPATH=...
```

and **not** the parent server's environment containing:

```text
API keys
database credentials
cloud tokens
service credentials
```

This protects against:

```python
os.environ
```

even if a future policy accidentally permits it.

---

## 26. The capability broker should control effects, not just intentions

The ideal flow is:

```text
LLM:
"download this URL"

       ↓

planner:
network.read

       ↓

CapabilityBroker:
DENY

       ↓

no network socket exists
```

The strongest result is:

```text
policy denial
+
technical impossibility
```

---

## 27. Skill persistence introduces another serious issue

The `CapabilityRegistry` is **not the same thing as the execution capability broker**.

It stores learned Python skills.

A `RegisteredSkill` contains:

```text
name
code
description
version
source
origin_sessions
dependencies
tags
```

<sup>[source]</sup>

The registry then converts active skills into a `SkillSet` that can be loaded into a kernel.

<sup>[source]</sup>

This creates a new trust boundary.

---

## 28.  Learned code becomes persistent executable code

The pipeline is effectively:

```text
agent generates code
       ↓
skill registered
       ↓
skills.json
       ↓
future startup
       ↓
SkillSet
       ↓
kernel
```

That means Kerno has **persistent executable memory**.

A malicious or compromised skill can outlive the session that created it.

---

## 29. This is potentially more dangerous than ordinary memory

Ordinary memory says:

```text
"Use pandas for this task."
```

A skill stores:

```python
def do_something():
    ...
```

and can later be loaded into execution.

So:

```text
Memory poisoning
```

becomes:

```text
Skill poisoning
```

which is substantially more powerful.

---

## 30.  Skill provenance is currently insufficient

`origin_sessions` records which sessions contributed to a skill. <sup>[source]</sup>

But again there is no visible:

```text
tenant_id
principal_id
approval
code_hash
security_profile
review_status
```

Therefore a skill's provenance does not yet answer:

> Who created this executable capability, under what authority, and after what review?

---

## 31. Skill registration needs a promotion lifecycle

I'd change:

```text
generated skill
   ↓
ACTIVE
```

to:

```text
generated
   ↓
QUARANTINED
   ↓
static analysis
   ↓
sandbox tests
   ↓
provenance recorded
   ↓
approval
   ↓
ACTIVE
```

For autonomous agents:

```text
LLM-generated code
```

should **never automatically become a trusted reusable skill**.

---

## 32. The skill registry should be tenant-scoped

Currently:

```text
~/.kerno/capabilities/
```

is essentially a shared persistent library.

For multi-user deployment:

```text
/data/tenants/<tenant>/capabilities/
```

or, preferably:

```text
database
    tenant_id
    skill_id
```

should establish ownership.

---

## 33. Skill code should be content-addressed

Use:

```text
skill_id
code_hash
version
```

rather than relying only on:

```text
skill_id = UUID
```

For example:

```text
skill:v1
sha256:abc123...
```

Then every execution can say:

```text
execution X
used skill SHA-256 Y
```

This creates reproducibility.

---

## 34. Skill updates should be immutable

Currently `update()` mutates an existing skill:

```python
for key, value in kwargs.items():
    setattr(skill, key, value)
```

<sup>[source]</sup>

For executable code, I'd prefer:

```text
skill v1
   ↓
skill v2
```

rather than:

```text
skill object
   ↓
mutated in place
```

That preserves historical provenance.

---

## 35. The supersession implementation has a subtle semantic oddity

When a skill with the same name exists:

```python
existing.superseded_by = name
```

then immediately afterward:

```python
existing.superseded_by = skill.skill_id
```

<sup>[source]</sup>

The final value is correct, but the intermediate assignment:

```text
superseded_by = name
```

is unnecessary and potentially confusing.

Not a security vulnerability, but worth cleaning.

---

## 36. The changelog is not an audit ledger

The capability registry keeps:

```text
changelog.json
```

with entries like:

```text
action
skill_id
name
session_id
timestamp
```

<sup>[source]</sup>

That's useful operational history.

But it is:

```text
JSON file
```

not:

```text
append-only
tamper-evident
tenant-aware
cryptographically linked
```

So it shouldn't be treated as authoritative security evidence.

---

## 37. We now have three different "capability" concepts

This is important to keep terminology precise.

### A. Security capability

```text
kernel.execute
filesystem.read
network.read
```

### B. Learned skill

```text
load_sales
plot_correlation
```

### C. Python module permission

```text
pandas
numpy
scipy
```

They are currently somewhat adjacent.

They should be explicitly separated:

```text
Skill
   ↓
requests Effects
   ↓
CapabilityBroker
   ↓
AllowList / sandbox
   ↓
Execution
```

---

## 38. This would solve a major conceptual problem

A learned skill could declare:

```text
Skill: load_sales
Effects:
    filesystem.read
    dataframe.create
```

Then the broker evaluates:

```text
Can this principal perform filesystem.read?
```

The skill itself does **not** grant permission.

That's the correct authority direction.

---

## 39. Proposed skill manifest

I'd use something like:

```json
{
  "skill_id": "skill-...",
  "name": "load_sales",
  "version": "1.2.0",
  "code_sha256": "...",
  "tenant_id": "...",
  "creator_principal": "...",
  "origin_execution": "...",
  "requested_effects": [
    "filesystem.read"
  ],
  "security_profile": "data_analysis",
  "status": "quarantined",
  "approved_by": null
}
```

After review:

```json
{
  "status": "active",
  "approved_by": "principal-..."
}
```

---

## 40. The key security invariant

Kerno should enforce:

> **No Python code, learned skill, memory item, notebook, or artifact can grant itself a capability.**

Authority must flow only from:

```text
trusted policy
```

into:

```text
capability decision
```

Never in the reverse direction.

---

## 41. Updated threat model

We can now map the major escape routes:

| Attack path | Current defense | Verdict |
|---|---|---|
| `os.system()` | regex |  defense-in-depth |
| `subprocess` | regex/import |  |
| `socket` | regex/import |  |
| `requests` | regex/import |  |
| shell escape `!` | regex |  |
| IPython magic | regex |  |
| `eval/exec` | regex/builtin check |  |
| dynamic Python introspection | no strong boundary |  |
| standard-library access | runtime allows stdlib |  |
| already-loaded modules | runtime allows |  |
| filesystem escape | regex |  without OS sandbox |
| network escape | regex |  without network isolation |
| process escape | regex |  without OS isolation |
| inherited secrets | not an AllowList problem |  |
| malicious persistent skill | registry |  |
| cross-tenant skill loading | no tenant field |  |

---

## 42. Overall conclusion from this round

This is **not** a case where the author forgot security.

Quite the opposite.

The repository shows a deliberate attempt at defense in depth:

```text
static analysis
+
runtime import restrictions
+
capability concepts
+
execution engine
+
audit
+
artifact integrity
```

The problem is that **Python remains the ultimate execution environment**.

Therefore the allowlist cannot be the ultimate trust boundary.

---

## 43. The architecture I recommend

```text
                    UNTRUSTED LLM
                         │
                         ▼
                  Generated Python
                         │
                         ▼
              AST / policy inspection
                         │
                         ▼
                 Capability request
                         │
                         ▼
                 Capability Broker
                         │
              ┌──────────┴──────────┐
              │                     │
            DENY                   ALLOW
                                    │
                                    ▼
                           Isolated worker
                                    │
                ┌───────────────────┼──────────────────┐
                ▼                   ▼                  ▼
             seccomp             filesystem         network
             policy                policy             policy
                │                   │                  │
                └───────────────────┼──────────────────┘
                                    ▼
                              Python kernel
                                    │
                                    ▼
                               Observed effects
                                    │
                                    ▼
                            Provenance ledger
```

This preserves everything Kerno already has while giving it a real final security boundary.

---

## 44. Priority fixes from this round

###  P0

**OS-level isolation for generated Python.**

###  P0

**Do not treat `AllowList` as a sandbox.**

###  P0

**Prevent inheritance of server secrets/environment.**

###  P1

**Remove "all stdlib is allowed" from restrictive profiles, or make it an explicit policy decision.**

###  P1

**Do not automatically trust already-loaded modules.**

###  P1

**Quarantine learned skills before activation.**

###  P1

**Tenant-scope the skill registry.**

###  P1

**Hash and version skill code immutably.**

###  P2

Replace regex-only static inspection with AST-based analysis **as an additional layer**, not as the final sandbox.

---

## 45. The next audit should be the kernel boundary itself

We've reached the point where the decisive question is no longer in `allowlist.py`.

We need to inspect exactly how Kerno launches and communicates with the Jupyter kernel:

```text
KernelManager
KernelPool
kernel.start
kernel.execute
stdin/stdout
ZMQ channels
connection files
process environment
working directory
mounts
Docker/Podman configuration
resource limits
```

Specifically:

```text
LLM-generated Python
       ↓
Jupyter kernel process
       ↓
OS process
```

We need to determine whether the **kernel process itself is isolated**, or whether all the clever capability/allowlist code is ultimately protecting an ordinary Python process running with the same privileges as Kerno.

That will tell us whether this project is currently:

> **a policy-controlled Python agent**

or genuinely:

> **a sandboxed agent execution platform.**

---

## Kernel boundary audit

I traced the repository structure further into the kernel layer. The branch has a dedicated kernel runtime and pool:

- `kerno/kernel/runtime.py`
- `kerno/kernel/pool.py`
- `kerno/kernel/__init__.py`
- `kerno/_run.py`
- runtime behavioral tests

<sup>[source]</sup>

There is also an important finding from the repository search: **I cannot yet establish from the indexed source that Kerno launches the kernel inside an OS/container sandbox.** The repository clearly has a kernel abstraction, but the evidence currently available does not justify calling that abstraction a security sandbox.

So the security conclusion should remain conservative.

---

## 1. The architecture appears to be

```text
Kerno application
      │
      ▼
KernelPool
      │
      ▼
KernelRuntime
      │
      ▼
Jupyter/IPython kernel
      │
      ▼
Python process
```

The existence of both `runtime.py` and `pool.py` confirms that Kerno treats kernels as managed execution resources rather than simply calling `exec()` inside the main application. <sup>[source]</sup>

That's good architecture.

But **process separation ≠ security isolation**.

---

## 2. The critical distinction

There are three progressively stronger models:

### Model A — same process

```text
Kerno
 └── exec(untrusted_code)
```

Very dangerous.

### Model B — separate Python/Jupyter process

```text
Kerno
 └── Jupyter kernel process
```

Better for reliability.

### Model C — isolated worker

```text
Kerno
 └── container / sandbox
       └── Jupyter kernel
```

This is what we want for adversarial code.

The repository evidence currently establishes the kernel abstraction, but **not enough evidence for Model C**.

---

## 3. Why Jupyter itself isn't a sandbox

This is fundamental.

Jupyter gives Kerno:

```text
execution
state
streams
interrupt
restart
kernel lifecycle
```

It does **not automatically provide**:

```text
filesystem isolation
network isolation
UID isolation
seccomp
capability dropping
secret isolation
mount isolation
resource isolation
```

Therefore:

```text
Jupyter kernel
```

should be treated as:

> a separate execution process

rather than:

> a security sandbox.

---

## 4. KernelPool is useful—but potentially creates a trust problem

The presence of a kernel pool means Kerno can reuse execution environments. <sup>[source]</sup>

That creates a major security invariant:

```text
kernel K
   ↓
execution A
   ↓
state remains
   ↓
execution B
```

If A is untrusted and B belongs to another task/user, B may inherit:

- Python variables
- imported modules
- filesystem handles
- object references
- environment state
- monkey patches
- modified builtins
- loaded credentials

---

## 5. Therefore kernel reuse must be scoped

The safe default should be:

```text
tenant
  +
security profile
  +
session
  +
trust domain
      ↓
kernel
```

not:

```text
pool
  ↓
any available kernel
```

A kernel must never cross a trust boundary merely because it is idle.

---

## 6. Strong invariant

I recommend formally defining:

> **A kernel may only be reused by executions belonging to the same security principal, tenant, capability profile, and trust domain.**

If any of those changes:

```text
destroy kernel
create fresh kernel
```

---

## 7. Restart is not equivalent to destruction

This is another subtle issue.

A Jupyter:

```text
restart
```

may reset Python state.

But a security boundary requires certainty that:

```text
old process
```

is actually gone.

For high-risk execution:

```text
terminate process
wait
verify PID gone
close channels
remove connection material
create new process
```

is preferable to relying on a logical kernel restart.

---

## 8. Imported modules can survive ordinary reuse

Suppose execution A does:

```python
import some_module
```

and modifies:

```python
some_module.some_global = malicious_value
```

Execution B then imports that module.

Depending on lifecycle semantics:

```text
sys.modules
```

can preserve state.

This is another reason kernel reuse must be trust-scoped.

---

## 9. Monkey-patching is especially relevant

A malicious cell could theoretically modify objects used by later code:

```text
builtins
sys
IPython
os
module globals
```

Even if the next cell is benign.

So a persistent kernel has **ambient mutable state**.

That makes the kernel itself part of the security boundary.

---

## 10. `skills` make this even more important

We already found that Kerno has persistent executable skills in:

```text
kerno/skills/registry.py
```

and bootstrap/skill infrastructure. <sup>[source]</sup>

Therefore there are two persistence mechanisms:

```text
persistent skill code
+
persistent kernel state
```

These should never be confused.

---

## 11. Recommended kernel lifecycle

For untrusted agent execution:

```text
REQUEST
  │
  ▼
select security profile
  │
  ▼
create isolated worker
  │
  ▼
create fresh kernel
  │
  ▼
install minimal approved environment
  │
  ▼
execute
  │
  ▼
capture effects
  │
  ▼
destroy worker
```

Not:

```text
REQUEST
 ↓
borrow arbitrary pooled kernel
 ↓
execute
 ↓
return kernel
```

unless the trust domain is explicitly identical.

---

## 12. Kernel connection files need protection

Jupyter kernels use connection information containing details necessary for clients to communicate with the kernel.

Those files/materials must be:

```text
owner-only
short-lived
unpredictable
deleted after shutdown
```

A leaked connection credential can potentially provide another local process access to the kernel.

This should be treated as a security credential, not ordinary temporary metadata.

---

## 13. The kernel should have a dedicated OS identity

For production:

```text
kerno-server
      │
      ├── UID 1000
      │
      └── worker UID 20000+
```

The worker should not run as:

```text
root
```

and ideally should not share the server's identity.

---

## 14. Filesystem model

A secure worker should see something like:

```text
/
├── usr/              read-only
├── lib/              read-only
├── app/              read-only
├── input/            controlled read-only
├── output/           controlled writable
└── tmp/              isolated
```

Not the user's entire:

```text
/home
```

and definitely not:

```text
/
```

with unrestricted write access.

---

## 15. Network model

For ordinary analytical tasks:

```text
network = OFF
```

For explicitly authorized network tasks:

```text
worker
  ↓
network proxy
  ↓
destination allowlist
```

That provides a much stronger guarantee than blocking:

```python
requests
socket
urllib
```

with source inspection.

---

## 16. Secret model

The kernel should not inherit:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
AWS_ACCESS_KEY_ID
DATABASE_URL
GITHUB_TOKEN
```

from the Kerno server environment.

Instead:

```text
Kerno control plane
        │
        ▼
Capability Broker
        │
        ▼
short-lived scoped credential
        │
        ▼
isolated worker
```

If a task does not need a secret:

```text
secret = absent
```

---

## 17. Resource isolation

This is another place where process separation isn't sufficient.

An untrusted Python process can consume:

```text
CPU
RAM
disk
file descriptors
processes
threads
```

Potentially causing denial of service.

The worker needs explicit limits:

```text
CPU quota
memory limit
PID limit
filesystem quota
execution timeout
output size
open-file limit
```

---

## 18. Notebook output also needs a hard limit

We previously found that Kerno records:

```text
stdout
stderr
result
HTML
JSON
images
tracebacks
```

into the notebook.

<sup>[source]</sup>

That means a malicious program can generate enormous output.

So:

```text
stdout limit
stderr limit
result limit
image limit
notebook total limit
```

should be enforced at the worker boundary.

---

## 19. Otherwise this attack is possible

Conceptually:

```python
while True:
    print("AAAAAAAAAAAAAAAA...")
```

Even if the code cannot escape the sandbox, it can potentially attack the control plane through:

```text
memory consumption
IPC saturation
disk consumption
notebook growth
```

Therefore **output limits are part of the security boundary**, not merely UX.

---

## 20. The behavioral test suite is valuable

The repository contains:

```text
tests/behavioral/test_runtime.py
```

<sup>[source]</sup>

That's good because the runtime needs behavioral verification, not just unit tests.

But the security tests need to evolve from:

```text
"blocked source code"
```

toward:

```text
"actual effect impossible"
```

---

## 21. The tests I would add immediately

### Filesystem

```python
open("/etc/passwd").read()
```

Expected:

```text
DENIED
```

### Network

```python
socket.create_connection(...)
```

Expected:

```text
DENIED
```

### Process

```python
os.fork()
```

Expected:

```text
DENIED
```

### Shell

```python
subprocess.run(...)
```

Expected:

```text
DENIED
```

### Dynamic import

```python
__import__("...")
```

Expected:

```text
DENIED
```

### Introspection

Test object-graph traversal.

### Environment

```python
os.environ
```

Expected:

```text
no secrets
```

---

## 22. More importantly: test bypasses

Don't only test obvious attacks.

Test semantic variants:

```text
getattr
globals
locals
vars
sys.modules
importlib
builtins
object subclasses
existing references
aliases
dynamic strings
```

The objective is:

> **Can the process cause the prohibited effect?**

not:

> **Did the regex match the example?**

---

## 23. The security test should have two layers

### Layer 1 — policy tests

```text
source
 ↓
AllowList
 ↓
ALLOW/DENY
```

### Layer 2 — sandbox tests

```text
source
 ↓
real worker
 ↓
real OS
 ↓
attempt effect
 ↓
verify effect impossible
```

The second layer is the one that establishes actual security evidence.

---

## 24. We should also test cross-session contamination

Example:

```text
Session A
   ↓
x = SECRET
   ↓
kernel returned

Session B
   ↓
"print(x)"
```

Expected:

```text
NameError
```

Then:

```text
Session A
   ↓
monkey patch module
   ↓
kernel returned

Session B
   ↓
import module
```

Expected:

```text
clean module
```

---

## 25. Cross-tenant kernel reuse must be tested explicitly

Create:

```text
Tenant A → kernel K
Tenant B → kernel K?
```

The expected result should be:

```text
REJECT
```

unless K has been completely destroyed and recreated under B's security domain.

---

## 26. This changes the architecture score

Based on the evidence we've now inspected:

| Area | Assessment |
|---|---|
| Kernel abstraction |  Good |
| Kernel pooling |  Useful |
| Jupyter integration |  Strong architecture |
| Runtime policy |  Defense-in-depth |
| Static security |  Regex-heavy |
| Process isolation |  Not yet established |
| OS sandbox |  Not established by current evidence |
| Network isolation |  Not established |
| Secret isolation |  Not established |
| Resource isolation |  Not established |
| Cross-tenant kernel isolation |  Must be proven |
| Persistent skill isolation |  Needs work |
| Provenance | / Strong foundation |

---

## 27. Most important conclusion

At this stage I would **not classify Kerno as a secure Python sandbox yet**.

I would classify it as:

> **a capability-aware, auditable Jupyter execution architecture with defense-in-depth policy controls, pending a demonstrated OS-level isolation boundary.**

That is a much more accurate description.

---

## 28. The target should be "sandbox by construction"

The ideal Kerno contract becomes:

```text
Kerno control plane
        │
        │ untrusted request
        ▼
   Policy Engine
        │
        ▼
 Capability Broker
        │
        ▼
 Worker Specification
        │
        ├── UID
        ├── filesystem
        ├── network
        ├── memory
        ├── CPU
        ├── PIDs
        ├── secrets
        └── timeout
        │
        ▼
  isolated process
        │
        ▼
  Jupyter kernel
        │
        ▼
 generated Python
```

Then the Python allowlist becomes only one additional layer.

---

## 29. And the provenance record becomes extremely powerful

Every worker could emit:

```json
{
  "execution_id": "...",
  "tenant_id": "...",
  "principal_id": "...",
  "kernel_id": "...",
  "security_profile": "data_analysis",
  "code_sha256": "...",
  "skill_sha256": "...",
  "capabilities": [],
  "worker_limits": {},
  "input_artifacts": [],
  "output_artifacts": [],
  "effects": [],
  "exit_status": "success"
}
```

Now the audit system can prove:

```text
WHO
WHAT
WHEN
WHERE
WITH WHICH CODE
WITH WHICH SKILL
UNDER WHICH POLICY
WITH WHICH LIMITS
PRODUCED WHICH ARTIFACT
```

That is the foundation of a serious agent execution platform.

---

## Next

The next layer I would audit is **the complete execution call chain**, starting at `kerno/_run.py` and following it into `KernelRuntime`/`KernelPool`, then into the capability/skill machinery.

The goal is to produce one concrete trace:

```text
API request
 → agent
 → plan
 → skill
 → capability decision
 → kernel allocation
 → code execution
 → output
 → artifact
 → audit record
```

At that point we'll be able to identify exactly **where the authoritative security decision is made, where it can be bypassed, and which component must become the real trust boundary**.

---

## the actual execution choke point

This round gives us a much stronger result because `kerno/_run.py` and `kerno/execution/engine.py` expose the intended control flow directly.

The key finding is:

> **Kerno has deliberately created an execution choke point.** Every agent-generated cell is supposed to pass through `ExecutionEngine.execute()` before reaching the kernel.

That is a significant architectural strength. <sup>[source]</sup>

But there is one major caveat: **the choke point is enforced by object wiring inside Python, not yet by an independently enforced OS boundary.**

---

## 1. The intended execution path is very clear

The main `run()` function constructs:

```text
KernelRuntime
      ↓
ExecutionEngine
      ↓
Agent loop
```

and explicitly comments:

```text
ALL agent code — regardless of loop strategy —
must pass through the ExecutionEngine
```

<sup>[source]</sup>

That's exactly the architecture we wanted to find.

---

## 2. The loops don't receive the raw kernel

This is particularly important.

`_run.py` creates:

```text
kernel
   ↓
ExecutionEngine(kernel)
   ↓
agent
```

and passes the engine into the loops. <sup>[source]</sup>

So the intended dependency graph is:

```text
                 KernelRuntime
                      │
                      ▼
               ExecutionEngine
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
       Reactive    Reflect      Plan
          │           │           │
          └───────────┼───────────┘
                      ▼
                  execute()
```

That's considerably better than letting each loop call `kernel.execute()` independently.

---

## 3. The engine has a genuine five-stage pipeline

`ExecutionEngine.execute()` explicitly performs:

```text
1. Authorization
2. Policy
3. Execution
4. Audit
5. Event logging
```

<sup>[source]</sup>

This is exactly the kind of centralized execution semantics we want.

---

## 4. Capability authorization happens before execution

The engine calls the capability broker before touching the kernel:

```text
agent code
   ↓
capability check
   ↓
DENY → synthetic error
```

The implementation explicitly says policy/capability violations:

> never touch the kernel. <sup>[source]</sup>

That's a strong invariant.

---

## 5. The default capability is also sensible

When a broker exists and the caller doesn't specify capabilities:

```text
kernel.execute
```

is automatically required. <sup>[source]</sup>

So this:

```python
run(..., capability_broker=broker)
```

doesn't silently mean:

```text
agent may execute anything
```

Instead it defaults to:

```text
kernel.execute
```

That's a good fail-closed direction.

---

## 6. But there is an important configuration caveat

The capability system only activates if:

```text
capability_broker is not None
```

The code explicitly constructs:

```text
broker = capability_broker
```

and otherwise `ExecutionEngine.require_capabilities()` simply returns. <sup>[source]</sup>

So:

```text
run(llm=...)
```

without a broker is **not equivalent** to:

```text
run(llm=..., capability_broker=...)
```

That should be made very explicit in production APIs.

---

## 7. Recommended production rule

For an untrusted/remote agent:

```text
capability_broker = REQUIRED
```

not:

```text
capability_broker = OPTIONAL
```

I would separate APIs:

```python
run_local_trusted(...)
run_agent_sandboxed(...)
```

or require:

```python
security_profile=...
```

for agent execution.

---

## 8. The `origin` model is important

The engine distinguishes:

```text
ORIGIN_AGENT
ORIGIN_RUNTIME
```

and says:

```text
agent → policy enforced
runtime → trusted host code
```

<sup>[source]</sup>

This is a good idea.

It allows Kerno's internal setup to execute trusted initialization code without forcing that code through the LLM policy.

---

## 9. But `origin` is itself a trust decision

Here's the key security question:

> Who is allowed to set `origin=ORIGIN_RUNTIME`?

If an untrusted plugin, skill, agent loop, or user-controlled extension can invoke:

```python
engine.execute(..., origin=ORIGIN_RUNTIME)
```

the entire policy boundary can be bypassed.

So the invariant must be:

```text
ORIGIN_RUNTIME
    ↓
host-internal code only
```

not:

```text
any caller
    ↓
choose origin
```

---

## 10.  This deserves a hard API boundary

I would not expose:

```python
execute(code, origin="runtime")
```

as a generally callable public capability.

Instead:

```text
ExecutionEngine.execute_agent(...)
ExecutionEngine.execute_runtime(...)
```

where the runtime path is private or capability-protected.

For example:

```text
_execute_runtime()
```

could only be used by Kerno's trusted host components.

---

## 11. The redaction architecture has improved

This is a significant correction to our earlier audit.

Earlier, the notebook conversion appeared not to redact all outputs.

Now we can see the upstream execution engine does:

```text
kernel output
    ↓
_redact_output()
    ↓
loop
    ↓
notebook
```

for agent-origin execution. <sup>[source]</sup>

That is much stronger.

---

## 12. It redacts multiple output channels

The engine explicitly scrubs:

```text
stdout
stderr
result
HTML
JSON
```

before returning the output to the loop. <sup>[source]</sup>

Therefore the earlier finding should be revised:

### Previous concern

> output redaction appears incomplete.

### Updated finding

> **The execution engine provides centralized output redaction before outputs reach the agent loop and downstream persistence.**

That's a genuine improvement.

---

## 13. But images still need explicit examination

The visible `_redact_output()` code handles:

```text
stdout
stderr
result
display html
display json
```

but the displayed implementation does not show equivalent processing of image payloads.

Therefore the remaining question is:

```text
image/png
image/jpeg
base64 display
```

Can a secret rendered into an image reach:

```text
LLM
notebook
artifact
```

without redaction?

That remains a specific test target.

---

## 14. Code previews are also redacted

The execution record stores only:

```text
code[:80]
```

and passes that through the redactor. <sup>[source]</sup>

That's good.

The full source is not placed into the execution event payload in the shown path.

---

## 15. Code hashes are generated

The engine computes:

```text
SHA-256(code)
```

and stores a shortened 16-character prefix. <sup>[source]</sup>

This gives us:

```text
execution_id
+
code_hash
```

which is exactly what we need for correlation.

But again, I recommend the **full hash** in authoritative provenance.

---

## 16. Execution IDs are genuinely useful

Each attempt gets a universal:

```text
execution_id
```

and this ID is correlated across:

```text
ExecutionRecord
ExecutionEvent
CellOutput
provenance
notebook
```

The code explicitly calls it the:

> universal correlation key. <sup>[source]</sup>

That's excellent architecture.

---

## 17. The event stream has causal relationships

Each event has:

```text
event_id
execution_id
sequence
parent_event_id
timestamp
payload
```

<sup>[source]</sup>

So Kerno already has the structural foundation for:

```text
REQUESTED
    ↓
CAPABILITY CHECK
    ↓
STARTED
    ↓
COMPLETED
```

rather than merely logging text.

---

## 18. But it isn't yet a cryptographic audit chain

This is an important distinction.

The events have:

```text
sequence
parent_event_id
```

but the code shown does not establish:

```text
hash(previous_event)
+
hash(current_event)
```

Therefore:

```text
causal ordering
```

exists, but:

```text
tamper evidence
```

doesn't necessarily follow.

Our earlier recommendation still stands.

---

## 19. Effect tracking is an interesting addition

`ExecutionEngine` accepts:

```text
EffectLedger
```

and declares effects **before** execution, then observes effects **after** execution. <sup>[source]</sup>

That's conceptually powerful.

The model becomes:

```text
declared effects
      ↓
execute
      ↓
observed effects
      ↓
compare
```

---

## 20. This is much better than source-code checking alone

For example:

```text
Agent declares:
filesystem.write
```

then the ledger observes:

```text
/tmp/result.csv
```

If actual effects exceed declared effects:

```text
EFFECT_VIOLATION
```

can be emitted.

That's a move from:

```text
"What did the source look like?"
```

toward:

```text
"What actually happened?"
```

---

## 21. But effect observation must itself be trustworthy

This is another critical boundary.

If `EffectLedger.observe()` merely scans expected paths after execution, it can miss:

```text
process execution
network calls
device access
deleted files
temporary files
side effects outside the watched directory
```

So an effect ledger should ultimately consume **OS-level observations** where possible.

---

## 22. The approval system is fail-closed

The code has another strong property.

If:

```text
human.approval
```

is required but no `ApprovalGate` exists:

```text
DENY
```

<sup>[source]</sup>

That's exactly what we want.

Not:

```text
no approval service
 → proceed
```

but:

```text
no approval service
 → refuse
```

---

## 23. Cancellation is also placed at the choke point

The engine checks cancellation before starting execution and can pass cancellation into the executor when supported. <sup>[source]</sup>

This matters because:

```text
cancel request
```

should not merely stop the agent loop while a dangerous kernel cell continues running.

The architecture is at least attempting to solve that correctly.

---

## 24. Budget enforcement wraps the choke point

`_run.py` wraps the engine with:

```text
BudgetedExecutor
```

when a budget is provided. <sup>[source]</sup>

So:

```text
agent
 ↓
budget
 ↓
execution engine
 ↓
kernel
```

is intended to prevent unlimited:

- cells
- wall time
- output

before execution reaches the kernel.

Good design.

---

## 25. Now the big issue: trusted setup happens directly on the kernel

`_run.py` explicitly executes allowlist runtime code directly:

```text
kernel.execute(kcode)
```

before the `ExecutionEngine` becomes the agent execution path. <sup>[source]</sup>

Likewise skills are bootstrapped directly into the kernel.

This is acceptable **only if that setup code is genuinely trusted**.

But it means:

```text
raw KernelRuntime
```

still exists inside the architecture.

---

## 26. This creates a "raw kernel reference" problem

The design says:

> loops never receive the raw kernel.

Good.

But `_run.py` itself does.

So the invariant isn't:

> **No code can access the kernel except ExecutionEngine.**

It is actually:

> **Agent loops are intended to access the kernel only through ExecutionEngine.**

Those are different guarantees.

---

## 27. The strongest invariant would be

```text
KernelRuntime
    ↓
ONLY ExecutionEngine
```

and trusted setup would be performed through a separate initialization interface:

```text
KernelRuntime.initialize_trusted(...)
```

or before the kernel is exposed to application code.

That reduces accidental bypasses.

---

## 28. The isolated multi-agent path is interesting

`_run.py` contains:

```text
isolation="isolated"
```

and constructs:

```text
kernel_factory
```

where each agent gets a fresh `KernelRuntime`. <sup>[source]</sup>

This is valuable.

It demonstrates that the architecture already recognizes:

```text
agent A state
≠
agent B state
```

and has an explicit mechanism for isolation at the kernel level.

---

## 29. But "isolated kernel" still doesn't mean OS sandbox

The factory does:

```text
new KernelRuntime
start()
install allowlist
ExecutionEngine(...)
```

<sup>[source]</sup>

So:

```text
isolated = fresh kernel
```

not necessarily:

```text
isolated = isolated OS/container
```

This distinction must be preserved in the API documentation.

---

## 30. The pool path needs special scrutiny

The existence of:

```text
run_with_pool()
```

means multiple tasks can share a `KernelPool`. <sup>[source]</sup>

This is exactly where we need a dedicated security invariant.

If:

```text
task A → kernel K
```

and then:

```text
task B → kernel K
```

we must prove:

```text
A's state cannot affect B
```

or require:

```text
same trust domain
```

---

## 31. My recommended policy for `run_with_pool`

For a public/multi-tenant deployment:

```text
run_with_pool()
```

should require one of:

### Option A

Fresh kernel per task.

### Option B

Pool partition:

```text
pool[tenant][security_profile]
```

### Option C

Complete kernel reset plus isolation verification.

Option C is the hardest to prove.

---

## 32. Another important discovery: dry-run mode

`_run.py` supports:

```text
mode="dry_run"
```

where the kernel isn't started. <sup>[source]</sup>

This is excellent for policy validation:

```text
LLM-generated code
 ↓
allowlist
 ↓
capability logic
 ↓
audit
```

without executing code.

This should become a first-class security testing tool.

---

## 33. We can build a security regression suite around dry-run

For every dangerous construct:

```text
source
 ↓
dry_run
 ↓
expected DENY
```

Then separately:

```text
source
 ↓
live sandbox
 ↓
actual effect test
```

This gives us:

```text
policy correctness
+
runtime correctness
```

rather than relying on either alone.

---

## 34. The execution architecture now looks like this

```text
                    LLM
                     │
                     ▼
                  Agent
                     │
                     ▼
             ExecutionEngine
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   Capability      Policy       Approval
     Broker       AllowList       Gate
        │            │            │
        └────────────┼────────────┘
                     ▼
               Effect Ledger
                     │
                     ▼
                KernelRuntime
                     │
                     ▼
              Jupyter/Python
                     │
                     ▼
                 OS effects
```

This is a **good control-plane architecture**.

---

## 35. But the data-plane boundary is still the missing piece

The architecture currently strongly controls:

```text
WHO may execute
WHAT code is intended to execute
WHICH capabilities are declared
WHETHER approval exists
WHAT gets recorded
```

It still needs hard proof of:

```text
WHAT the OS physically allows the process to do
```

That's the difference between policy enforcement and containment.

---

## 36. Revised maturity assessment

| Layer | Status |
|---|---|
| Central execution choke point |  **Strong** |
| Capability authorization |  **Strong design** |
| Allowlist enforcement | / |
| Approval fail-closed |  |
| Cancellation |  |
| Budget wrapper |  |
| Output redaction |  **better than previously assessed** |
| Execution correlation |  |
| Causal events |  |
| Effect ledger | / |
| Cryptographic audit chain |  |
| Runtime-vs-agent origin separation |  |
| Raw kernel exposure |  |
| Kernel pooling isolation | / pending proof |
| OS sandbox |  not established |
| Network containment |  not established |
| Secret isolation |  not established |

---

## 37. The most important P0 now

I would **not rewrite the ExecutionEngine**.

The architecture is good enough to preserve.

Instead:

### P0-A — Protect the choke point

Make `ExecutionEngine` the only application-level execution interface.

### P0-B — Make `ORIGIN_RUNTIME` privileged

Prevent arbitrary callers from selecting the trusted origin.

### P0-C — Add an actual worker sandbox

Container/namespace/OS policy around `KernelRuntime`.

### P0-D — Make pool trust-domain aware

Never reuse a kernel across incompatible tenants/profiles.

### P0-E — Prove the effect boundary

Test actual filesystem/network/process behavior.

---

## 38. One architectural change would make Kerno much stronger

Introduce an explicit:

```text
WorkerSpec
```

For example:

```text
WorkerSpec
├── tenant_id
├── principal_id
├── security_profile
├── filesystem_policy
├── network_policy
├── environment_policy
├── resource_limits
├── capabilities
├── secrets
└── kernel_spec
```

Then:

```text
CapabilityBroker
       ↓
WorkerSpec
       ↓
Worker launcher
       ↓
KernelRuntime
```

Now the kernel cannot accidentally start with the wrong environment.

---

## 39. This separates control plane and execution plane

### Control plane

```text
Agent
CapabilityBroker
ApprovalGate
ExecutionEngine
Provenance
Audit
```

### Data plane

```text
Worker
Kernel
Python
Filesystem
Network
Processes
```

The control plane decides.

The data plane enforces.

That is the architecture I would push Kerno toward.

---

## 40. Final finding for this round

The earlier question was:

> Is Kerno merely a policy-controlled Python agent, or a sandboxed agent execution platform?

**Current evidence supports the first, not yet the second.**

But importantly, Kerno is **much closer to the second than a conventional Jupyter agent** because it already has:

```text
central execution choke point
+
capability authorization
+
policy enforcement
+
approval
+
budget
+
cancellation
+
effect observation
+
execution provenance
+
audit events
```

<sup>[source]</sup>

The missing leap is **independent containment of the kernel process**.

---

## Next audit target

The next decisive inspection is now narrower:

```text
KernelRuntime
    ↓
KernelPool
    ↓
actual kernel process launch
    ↓
connection lifecycle
    ↓
shutdown/restart
    ↓
environment / cwd / PID / resources
```

That will let us answer, from actual code rather than assumptions:

**1. Is `KernelRuntime` a real subprocess?**
**2. How is it launched?**
**3. What UID/environment/filesystem does it inherit?**
**4. Does `KernelPool` reuse processes?**
**5. What exactly does `auto_restart` restore?**
**6. Can a killed/restarted kernel retain sensitive state?**
**7. Is `isolation="isolated"` genuine process isolation or merely a fresh Jupyter kernel?**

Those seven answers will determine the final security rating of this Kerno branch.

---

## decisive KernelRuntime / KernelPool findings

We now have the actual kernel-launch code. This changes the audit from speculation to concrete evidence.

## 1. Confirmed: Kerno launches a real separate Python/Jupyter process

`KernelRuntime.start()` constructs a `jupyter_client.KernelManager` and calls:

```python
self._km.start_kernel()
```

then creates a client and waits for the kernel to become ready. <sup>[source]</sup>

So the architecture is definitely:

```text
Kerno process
     │
     └── KernelManager
             │
             ▼
       Python/Jupyter
       kernel process
```

### This is good.

It means generated code is **not simply executed with `exec()` inside the Kerno control process**.

---

## 2. But we can now state the limitation precisely

The code does **not** configure:

- a container;
- a separate UID;
- Linux namespaces;
- seccomp;
- cgroups;
- restricted mounts;
- network namespace;
- capability dropping;
- sanitized environment.

The call is essentially:

```python
KernelManager(kernel_name="python3")
start_kernel()
```

<sup>[source]</sup>

Therefore the kernel is a **separate process**, but the repository evidence still does not establish an **OS security sandbox**.

That's the key distinction.

---

## 3. The kernel inherits the normal execution environment

Because Kerno doesn't show a restricted `env`, `cwd`, user, namespace, or container configuration in `KernelRuntime.start()`, the Jupyter process should be assumed to inherit the normal environment provided by `jupyter_client`/the host process unless configured elsewhere.

That means we should currently assume:

```text
Kerno privileges
      ↓
Jupyter kernel privileges
```

rather than:

```text
Kerno privileges
      ↓
restricted worker privileges
```

This is the most important remaining security gap.

---

## 4. `kernel_name="python3"` is not a security profile

The default is:

```python
kernel_name = "python3"
```

<sup>[source]</sup>

A kernelspec identifies an execution environment.

It does **not** inherently mean:

```text
sandboxed Python
```

So a production Kerno deployment should distinguish:

```text
python3
```

from something like:

```text
kerno-sandbox-python
```

where the latter is explicitly launched inside the required isolation boundary.

---

## 5. Kernel shutdown is real process shutdown

This part is good.

`shutdown()` calls:

```python
self._km.shutdown_kernel(now=now)
```

and stops the client channels first. <sup>[source]</sup>

The pool also uses:

```python
runtime.shutdown(now=True)
```

when retiring kernels. <sup>[source]</sup>

So retirement is considerably stronger than merely clearing Python variables.

---

## 6. Restart actually restarts the kernel process

`KernelRuntime.restart()` invokes:

```python
self._km.restart_kernel()
```

and waits for readiness again. <sup>[source]</sup>

This is important.

A restart isn't simply:

```python
%reset
```

It creates a new kernel process generation.

The code also increments:

```text
generation += 1
```

which gives us an excellent provenance primitive.

---

## 7. But soft reset is fundamentally weaker

The pool's normal successful-task path uses:

```python
pk.runtime.reset_namespace()
```

which executes:

```python
%reset -f
```

<sup>[source]</sup>

That means:

```text
Task A
   ↓
%reset -f
   ↓
Task B
```

uses the **same OS process**.

This is a major security distinction.

---

## 8. `%reset -f` is not a security boundary

A namespace reset removes ordinary variables.

It does not prove that all process state has been restored.

Potential persistent state includes:

```text
sys.modules
import hooks
monkey patches
thread state
background threads
open resources
environment modifications
native-library state
process-level caches
signal handlers
```

Therefore:

> **Soft reset is appropriate for performance isolation, not adversarial security isolation.**

---

## 9. The pool itself confirms this design

The code explicitly says:

```text
soft reset:
    clear namespace
    reload skills
```

while hard reset means:

```text
restart kernel process
```

<sup>[source]</sup>

So Kerno knowingly has two isolation strengths.

That is fine—but the API should make the distinction impossible to misunderstand.

---

## 10. Current lifecycle

The normal pool path is:

```text
                    ┌───────────────┐
                    │ warm kernel   │
                    └───────┬───────┘
                            │
                         acquire
                            │
                            ▼
                         Task A
                            │
                         release
                            │
                            ▼
                       soft reset
                            │
                            ▼
                    ┌───────────────┐
                    │ warm kernel   │
                    └───────┬───────┘
                            │
                         acquire
                            │
                            ▼
                         Task B
```

Therefore Task A and Task B can share one Python process.

---

## 11. This creates a clear security classification

I'd recommend Kerno explicitly define three modes:

### `trusted`

Same kernel can be reused.

### `isolated`

Fresh kernel process per task, but potentially same OS sandbox.

### `sandboxed`

Fresh worker **plus OS-level containment**.

For example:

```text
trusted
  ↓
soft reset

isolated
  ↓
restart / fresh kernel

sandboxed
  ↓
new isolated worker
  ↓
new kernel
```

---

## 12. The current name `isolation="isolated"` is potentially misleading

We saw `_run.py` create a fresh `KernelRuntime` for isolated agents.

That gives:

```text
fresh kernel process
```

but not necessarily:

```text
OS sandbox
```

So I would rename the conceptual terminology:

```text
kernel_isolation
```

rather than simply:

```text
isolation
```

or document precisely:

> `isolated` means process-level kernel isolation, not OS/container isolation.

---

## 13. There is another serious issue: pool acquisition isn't tenant-aware

`KernelPool.acquire()` accepts:

```python
acquire(task_id)
```

<sup>[source]</sup>

There is no:

```text
tenant_id
principal_id
security_profile
trust_domain
```

in the acquisition API.

Therefore the pool itself cannot enforce:

```text
Tenant A kernel
≠
Tenant B kernel
```

It only knows:

```text
task_id
```

---

## 14. This is a major architectural gap

Imagine:

```text
Task A / Tenant A
       ↓
kernel K
       ↓
release
       ↓
soft reset
       ↓
Task B / Tenant B
       ↓
kernel K
```

The current pool API has no obvious security concept preventing this.

That is acceptable for a single-user trusted deployment.

It is **not sufficient for multi-tenant hostile workloads**.

---

## 15. The fix is straightforward conceptually

Change the pool identity from:

```python
acquire(task_id)
```

to something like:

```python
acquire(
    task_id=...,
    tenant_id=...,
    principal_id=...,
    security_profile=...,
)
```

Then either:

```text
pool[tenant][profile]
```

or attach a trust-domain label to every kernel.

---

## 16. Even better: don't put security policy inside the generic pool

I would introduce:

```text
WorkerPool
```

above `KernelPool`.

For example:

```text
SecurityPolicy
      │
      ▼
WorkerPool
      │
      ▼
KernelPool
```

The WorkerPool decides whether reuse is permitted.

KernelPool should mainly manage:

```text
start
stop
health
capacity
lifecycle
```

This keeps security decisions above infrastructure mechanics.

---

## 17. Memory limits are currently monitoring, not enforcement

This is another important finding.

`PooledKernel` defines:

```python
MAX_MEMORY = 4096.0
```

and checks:

```python
memory > MAX_MEMORY
```

<sup>[source]</sup>

But this doesn't stop the process from reaching 4 GB.

It detects that it already happened.

So:

```text
MAX_MEMORY
```

is currently a **retirement threshold**, not an OS memory limit.

---

## 18. Same problem with CPU

There is no visible CPU quota in `KernelRuntime`.

Therefore a worker can potentially consume all available CPU until Kerno notices something is wrong.

A real sandbox needs:

```text
cgroup CPU quota
```

or equivalent enforcement.

---

## 19. Same problem with lifetime

The pool checks:

```python
MAX_LIFETIME = 3600
```

and retires expired kernels. <sup>[source]</sup>

Good lifecycle management.

But it doesn't physically prevent a task from running for an hour.

The monitor merely warns for acquired tasks after an hour:

```text
"Consider interrupting."
```

<sup>[source]</sup>

That's not enforcement.

---

## 20. This is an important pattern throughout Kerno

We can now classify the existing controls:

```text
Detection:
    🟢 strong

Recovery:
    🟢 strong

Policy:
    🟢 strong

Containment:
    🔴 weak / not established
```

Kerno is very good at saying:

> "Something went wrong; recycle the kernel."

It needs stronger mechanisms that say:

> "The process was never allowed to do that in the first place."

---

## 21. Timeout escalation is actually quite good

The runtime has:

```text
soft interrupt
      ↓
2 second grace
      ↓
SIGKILL
      ↓
restart
```

The code obtains the kernel process and calls:

```python
proc.kill()
proc.wait(...)
```

<sup>[source]</sup>

That's a real process-level recovery mechanism.

This is stronger than simply sending another Python interrupt.

---

## 22. But the timeout kill isn't necessarily a security kill

Important distinction:

```text
SIGKILL
```

terminates the kernel process.

It does not necessarily terminate:

```text
child processes
```

that the kernel may have spawned.

If untrusted code can create child processes, you need a **process group / cgroup / namespace** strategy so that destroying the worker destroys its descendants too.

---

## 23. This gives us another P0 requirement

Worker termination must mean:

```text
kernel
+
children
+
grandchildren
+
background processes
```

are terminated.

Otherwise:

```text
kernel
   └── malicious child
          ↓
       survives
```

is possible.

A container/cgroup solves this much more cleanly.

---

## 24. `memory_mb` itself imports `psutil` inside the kernel

The pool checks memory using:

```python
import psutil, os
```

inside the worker. <sup>[source]</sup>

That's fine for telemetry.

But it illustrates an important principle:

> **Telemetry inside the worker is not trustworthy enforcement.**

A hostile process can:

```text
modify its own telemetry
hide behavior
break psutil
hang before reporting
```

The authoritative resource monitor should be outside the worker.

---

## 25. KernelPool bootstrap executes arbitrary skills directly

This deserves another red flag.

`_bootstrap()` reads:

```python
code = path.read_text()
```

and then executes:

```python
runtime.execute(code, silent=True)
```

<sup>[source]</sup>

So:

```text
skills_path
   ↓
raw source code
   ↓
kernel.execute()
```

This bypasses the normal `ExecutionEngine` authorization path.

---

## 26.  This is one of the most concrete bypasses we've found

The normal agent path is:

```text
Agent
 ↓
ExecutionEngine
 ↓
CapabilityBroker
 ↓
Kernel
```

But skill bootstrap is:

```text
skills file
 ↓
KernelRuntime.execute()
 ↓
Kernel
```

There is no `ExecutionEngine` in that path.

This is acceptable **only if `skills_path` is completely trusted**.

If learned or user-controlled skill files can reach `skills_path`, the capability architecture can be bypassed.

---

## 27. This connects directly to our previous skill-registry finding

We already established that Kerno has persistent executable skills.

Now we have:

```text
persistent skill
      ↓
skills_path
      ↓
KernelPool._bootstrap()
      ↓
runtime.execute()
```

Therefore the skill system has a direct route into the kernel.

That route needs its own trust boundary.

---

## 28. Recommended skill bootstrap architecture

Instead of:

```python
runtime.execute(skill_code)
```

use:

```text
Skill
 ↓
validate
 ↓
hash
 ↓
security profile
 ↓
Capability declaration
 ↓
ExecutionEngine / trusted bootstrap executor
 ↓
isolated kernel
```

And ideally:

```text
skills
```

should be **data/manifests**, while executable skill code is loaded only after explicit authorization.

---

## 29. Another issue: soft reset reloads the skills

The pool does:

```text
%reset -f
      ↓
_bootstrap()
```

<sup>[source]</sup>

This means the skill source gets re-executed for every task reuse.

So a compromised skill file isn't merely executed once.

It becomes:

```text
persistent startup payload
```

for every kernel lifecycle.

That increases the importance of skill integrity.

---

## 30. Skill integrity should therefore be verified before bootstrap

At minimum:

```text
skills file
 ↓
SHA-256
 ↓
trusted manifest
 ↓
match?
```

If mismatch:

```text
DO NOT LOAD
```

For production:

```text
signed skill bundle
```

would be even stronger.

---

## 31. The pool's reset strategy is currently asymmetric

```text
complete
   ↓
soft reset

error
   ↓
hard reset

timeout
   ↓
hard reset

OOM
   ↓
retire
```

<sup>[source]</sup>

This is reasonable operationally.

But for **untrusted agent code**, I would consider:

```text
untrusted task complete
   ↓
destroy worker
```

rather than soft reset.

Performance can be recovered with a pool of already-created **isolated workers**, rather than reusing the same Python process across trust boundaries.

---

## 32. This suggests two pools

### Fast trusted pool

```text
soft reset
```

### Secure agent pool

```text
worker destroyed after task
```

For example:

```text
TrustedPool
SandboxPool
```

This prevents developers from accidentally using the high-performance semantics for hostile code.

---

## 33. Recommended policy matrix

| Execution | Reuse process? | Soft reset? | Fresh kernel? | OS sandbox? |
|---|---:|---:|---:|---:|
| Internal trusted code |  |  | optional | optional |
| Same-user notebook |  |  | optional | recommended |
| LLM-generated code |  |  |  | **required** |
| User-uploaded code |  |  |  | **required** |
| Multi-tenant code |  |  |  | **required** |
| Untrusted plugin |  |  |  | **required** |

---

## 34. We can now define Kerno's actual security tiers

### Tier 0 — trusted

```text
normal Python
```

### Tier 1 — policy-controlled

```text
AllowList
+
ExecutionEngine
```

### Tier 2 — isolated

```text
fresh Jupyter process
+
policy
```

### Tier 3 — sandboxed

```text
fresh worker
+
fresh Jupyter process
+
filesystem isolation
+
network isolation
+
resource limits
+
secret isolation
```

### Tier 4 — hardened

```text
Tier 3
+
seccomp
+
read-only root
+
UID isolation
+
cgroup
+
audit integrity
+
signed skills
```

That terminology would make Kerno much easier to reason about.

---

## 35. Current branch assessment after inspecting actual launch code

I would now rate the project approximately:

### Architecture

**8/10**

The separation between:

```text
Agent
ExecutionEngine
KernelRuntime
KernelPool
CapabilityBroker
EffectLedger
Audit
```

is genuinely strong.

### Operational resilience

**8/10**

The project has:

```text
interrupt
timeout escalation
restart
generation
health checking
kernel retirement
overflow
pool monitoring
```

### Security policy

**7/10**

The capability/allowlist architecture is thoughtful.

### Actual containment

**3–4/10**

Because the kernel is a separate process, but the repository does not yet demonstrate:

```text
namespace
container
seccomp
cgroup
network isolation
UID isolation
secret isolation
```

### Overall security maturity

**promising, but not yet a hostile-code sandbox.**

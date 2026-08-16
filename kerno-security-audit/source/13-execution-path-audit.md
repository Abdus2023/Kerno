# 13 — Execution Path Audit

## Execution-path audit

The next step is to stop looking at individual security components in isolation and construct the **complete execution graph**.

The question is:

> **Can every path that causes Python code to execute be proven to pass through the intended authorization, policy, provenance, and sandbox layers?**

This is more important than adding another allowlist rule.

---

## 1. The execution invariant

For an untrusted execution, we want exactly:

```text
Request
  ↓
Identity
  ↓
Capability resolution
  ↓
Approval / policy
  ↓
Security profile
  ↓
Sandbox creation
  ↓
Fresh kernel
  ↓
Code execution
  ↓
Effect recording
  ↓
Result
```

The dangerous architecture would be:

```text
Request
  ↓
some helper
  ↓
KernelRuntime.execute()
```

without the policy chain.

---

## 2. Search target: every execution sink

The audit should identify every function capable of eventually executing Python.

Conceptually, the sinks are:

```text
KernelRuntime.execute()
KernelRuntime.run()
KernelRuntime.execute_code()
jupyter_client execute()
ipykernel execution
exec()
eval()
compile()
subprocess(...)
```

We then construct:

```text
caller → intermediate function → sink
```

for **every occurrence**.

The important result isn't the number of sinks.

It's whether each sink has a complete upstream chain.

---

## 3. `KernelRuntime` should be the lowest trusted boundary

The ideal architecture is:

```text
                 untrusted caller
                       │
                       X
                       │
               ExecutionEngine
                       │
                       ▼
                  KernelRuntime
```

But there is a subtle problem.

If application code can instantiate:

```python
KernelRuntime(...)
```

directly, then:

```text
ExecutionEngine
```

is no longer the sole gate.

Therefore the runtime needs an explicit distinction between:

```text
public API
```

and:

```text
internal privileged API
```

---

## 4. Don't rely on Python naming conventions

Something like:

```python
_InternalKernelRuntime
```

doesn't establish security.

Likewise:

```python
_do_execute()
```

doesn't prevent direct invocation.

Python code inside the same trust domain can call it.

The real solution is architectural:

```text
untrusted code
       ↓
cannot access runtime control channel
```

which again points toward process/container separation.

---

## 5. Skill bootstrap is especially important

The README describes a bootstrap mechanism that loads skills into the kernel.

That creates a path like:

```text
Agent
 ↓
skill name
 ↓
skill loader
 ↓
skill source
 ↓
kernel
```

This path must be treated exactly like:

```text
Agent
 ↓
execute(code)
 ↓
kernel
```

because **skill source is executable code**.

---

## 6. Skill loading should therefore produce an execution authorization

Instead of:

```python
load_skill("timeseries")
```

implicitly executing arbitrary bootstrap code, conceptually:

```text
load_skill
   ↓
resolve manifest
   ↓
verify integrity
   ↓
resolve dependencies
   ↓
resolve capabilities
   ↓
resolve security profile
   ↓
authorize
   ↓
bootstrap
```

---

## 7. A skill manifest should become authoritative

For example:

```yaml
name: documents
version: 0.2.0

dependencies:
  python:
    - pdfplumber
    - python-docx

capabilities:
  - filesystem.read

security_profile: document-reader
```

Then Kerno knows **before execution** what the skill intends to use.

---

## 8. Don't let skill code declare its own authority

This would be dangerous:

```python
skill.capabilities = [
    "filesystem.write",
    "network.connect",
]
```

and then trusting that declaration.

Instead:

```text
skill manifest
      ↓
administrator-approved capability ceiling
      ↓
requested capability
      ↓
intersection
```

The skill can request less authority, never more.

---

## 9. Capability monotonicity

A very useful invariant is:

> Loading a skill must never increase authority beyond the caller's existing security ceiling.

Formally:

```text
effective_after =
    effective_before
    ∩
    skill_allowed
```

not:

```text
effective_after =
    effective_before
    ∪
    skill_requested
```

This is a major security property.

---

## 10. Example

Suppose the agent has:

```text
filesystem.read = /workspace/data
```

Then it loads:

```text
documents
```

The skill requests:

```text
filesystem.read
```

Effective:

```text
/workspace/data
```

Good.

If the skill requests:

```text
filesystem.write = /
```

the result must still be:

```text
DENIED
```

The skill cannot escalate the agent.

---

## 11. The same applies to network

Agent:

```text
network = disabled
```

Skill:

```text
web
network = enabled
```

Result:

```text
network = disabled
```

unless an administrator explicitly authorizes a profile transition.

---

## 12. Security-profile transitions need explicit authorization

There should be no implicit:

```text
load web skill
  ↓
network suddenly enabled
```

Instead:

```text
requested profile
       ↓
policy
       ↓
approval if required
       ↓
new sandbox
```

This may require **restarting the worker**.

That's actually desirable.

---

## 13. Never mutate a hardened worker from unrestricted → restricted

Suppose:

```text
Worker A
network enabled
```

then the agent asks:

```text
network disabled
```

You could modify policy in place.

But the safer design is:

```text
Worker A
  ↓
destroy
  ↓
Worker B
  ↓
network disabled
```

Why?

Because Worker A may already contain:

```text
connections
file descriptors
loaded modules
threads
state
credentials
```

Changing a flag doesn't necessarily erase those capabilities.

---

## 14. Therefore security profiles should be immutable per worker

Conceptually:

```text
WorkerIdentity
├── worker_id
├── generation
├── security_profile
└── capability_ceiling
```

These should be fixed when the worker starts.

---

## 15. Kernel generation becomes security-relevant

For example:

```text
worker-42
generation-7
profile=readonly
network=off
```

If the profile changes:

```text
generation-8
profile=networked
network=on
```

Now the audit trail is unambiguous.

---

## 16. This also solves pooled-kernel problems

A kernel pool should never simply be:

```text
available_workers = [...]
```

It should be:

```text
pool[
    (profile, tenant, trust_domain)
]
```

For example:

```text
readonly/untrusted
networked/trusted
documents/untrusted
sql/read-only
```

Workers from one pool must never silently cross into another trust domain.

---

## 17. The pool key should include identity boundaries

At minimum:

```text
tenant
trust_domain
security_profile
```

Potentially:

```text
principal
```

as well.

Then:

```text
tenant-A / untrusted
```

cannot reuse:

```text
tenant-B / trusted
```

---

## 18. Soft reset is not sufficient for cross-tenant reuse

Even if:

```python
%reset -f
```

succeeds, Python process state can include:

```text
sys.modules
threads
file descriptors
environment
native-library state
temporary files
background tasks
```

Therefore:

```text
untrusted A
   ↓
soft reset
   ↓
untrusted B
```

is not a strong isolation boundary.

Prefer:

```text
untrusted A
   ↓
destroy worker
   ↓
fresh sandbox
   ↓
untrusted B
```

---

## 19. EffectLedger should record security context

The effect ledger shouldn't merely record:

```json
{
  "effect": "kernel.execute"
}
```

It should eventually contain something like:

```json
{
  "effect": "kernel.execute",
  "execution_id": "...",
  "worker_id": "...",
  "kernel_generation": 8,
  "security_profile": "untrusted-readonly",
  "capability": "kernel.execute",
  "network": "disabled",
  "filesystem": "workspace-readonly"
}
```

Then an auditor can reconstruct the actual execution environment.

---

## 20. This is especially important for failure events

Suppose:

```text
Execution #1938
```

fails because:

```text
memory limit exceeded
```

The audit should tell us:

```text
worker = 17
generation = 4
profile = untrusted
memory = 512 MB
PID limit = 32
network = off
```

That turns an opaque failure into a reproducible event.

---

## 21. The audit trail should distinguish policy denial from sandbox denial

These are different events.

### Policy denial

```text
Agent requested:
network.connect

Policy:
DENY
```

### Sandbox denial

```text
Agent execution allowed
Python attempted network operation
OS:
EPERM / network unavailable
```

The second event is particularly valuable because it proves the defense-in-depth boundary is working.

---

## 22. Security event taxonomy

I'd introduce:

```text
POLICY_DENIED
CAPABILITY_DENIED
APPROVAL_DENIED
SKILL_DENIED
DEPENDENCY_MISSING
SANDBOX_CREATE_FAILED
SANDBOX_POLICY_VIOLATION
RESOURCE_LIMIT
WORKER_KILLED
WORKER_RESTARTED
CROSS_DOMAIN_REUSE_ATTEMPT
```

This would make security telemetry much more useful.

---

## 23. `kerno doctor` can verify the whole chain

Eventually:

```bash
kerno doctor --security
```

could perform:

```text
[✓] ExecutionEngine exists
[✓] Capability broker active
[✓] Approval gate active
[✓] Effect ledger active
[✓] Skill manifests validated

[✓] Sandbox backend detected
[✓] Filesystem isolation
[✓] Network isolation
[✓] PID limit
[✓] Memory limit
[✓] Process-tree cleanup

[✓] Worker profile immutable
[✓] Cross-profile reuse blocked

Security posture:
HARDENED
```

or:

```text
Security posture:
POLICY-ONLY — NOT SUITABLE FOR HOSTILE CODE
```

That distinction would be extremely valuable.

---

## 24. CI should enforce the distinction

We should have two test suites:

```text
tests/
├── unit/
│   ├── policy/
│   ├── capabilities/
│   └── skills/
│
├── integration/
│   ├── kernel/
│   ├── execution/
│   └── provenance/
│
└── security/
    ├── sandbox/
    ├── escape/
    ├── resources/
    └── isolation/
```

And importantly:

```text
policy tests passing
```

must **not** imply:

```text
sandbox tests passing
```

---

## 25. Security status should therefore have separate gates

I'd define:

```text
G0 — package integrity
G1 — policy correctness
G2 — execution-path completeness
G3 — process isolation
G4 — OS sandbox
G5 — adversarial escape testing
G6 — production hardening
```

This prevents the common mistake:

> "All tests passed, therefore the sandbox is secure."

---

## 26. The current project should not claim G4/G5 yet

Based on what we've established so far:

```text
G0  ✓
G1  substantially implemented
G2  needs complete call-graph audit
G3  partially present
G4  not demonstrated
G5  not demonstrated
G6  not demonstrated
```

That's a much more rigorous status than simply saying "Kerno has security."

---

## 27. The next concrete source audit

The next pass should enumerate:

```text
1. every KernelRuntime constructor
2. every execute method
3. every Jupyter execute call
4. every skill bootstrap path
5. every subprocess call
6. every code-generation path
7. every reset/restart path
8. every pool checkout path
9. every direct import-hook installation
10. every public API that can reach execution
```

Then produce a table:

| Sink | Caller | Policy gate | Capability gate | Approval | Sandbox | Audit |
|---|---|---|---|---|---|---|
| Kernel execute | ? | ? | ? | ? | ? | ? |
| Skill bootstrap | ? | ? | ? | ? | ? | ? |
| Jupyter execute | ? | ? | ? | ? | ? | ? |
| Restart | ? | ? | ? | ? | ? | ? |

The goal is **100% closure**.

---

## 28. The key question for the next stage

For every path, we need to be able to prove:

```text
Can an untrusted caller reach this execution sink
without first obtaining the corresponding capability?
```

If the answer is:

```text
NO
```

good.

If:

```text
YES
```

that's a **P0 execution-policy bypass**.

And if the policy can be bypassed but the OS sandbox still contains it:

```text
policy vulnerability
+
successful containment
```

then we have defense in depth rather than a host compromise.

---

## 29. Where the project is heading

The architecture is becoming:

```text
                    KERNO
                      │
        ┌─────────────┴─────────────┐
        │                           │
    CONTROL PLANE               DATA PLANE
        │                           │
        ▼                           ▼
   Identity                    Sandbox Worker
   Policy                           │
   Capability                       ▼
   Approval                      Jupyter
   Skill Registry                    │
   Provenance                        ▼
   Audit                            OS
        │
        └────────── governs ─────────┘
```

This separation is the architectural goal.

**Control plane decides what may happen.
Data plane physically constrains what can happen.**

That's the distinction that will turn Kerno from a well-designed execution framework into a genuinely defensible agent runtime.

---

## Turn the audit into an implementation specification

The next logical step is to define the **security contract** that the `arena/01a0064f-kerno` branch should satisfy before we touch implementation.

The central principle is:

> **Kerno must fail closed at every boundary.**

Not merely "usually checks permissions."

---

## 1. Define the execution contract

Every execution should have an immutable context:

```text
ExecutionContext
├── execution_id
├── request_id
├── principal_id
├── tenant_id
├── trust_domain
├── skill_id
├── capability_set
├── security_profile
├── worker_id
├── kernel_generation
└── policy_version
```

This becomes the security identity of an execution.

---

## 2. Why `execution_id` alone isn't enough

Imagine:

```text
execution_id = 1938
```

That tells us *which request* happened.

It doesn't tell us:

```text
who requested it
which worker executed it
which security policy applied
whether the worker was reused
what capabilities existed
```

So provenance should bind all of them.

---

## 3. Security context should be immutable

Once a worker begins:

```text
profile = untrusted-readonly
network = disabled
filesystem = /workspace/read-only
```

the worker must not silently become:

```text
profile = unrestricted
network = enabled
filesystem = host
```

The safe transition is:

```text
old worker
    ↓
terminate
    ↓
new security context
    ↓
new worker
```

---

## 4. `SecurityProfile` becomes the central object

I'd define profiles approximately like:

```python
SecurityProfile(
    name="untrusted-readonly",

    filesystem=...,
    network=...,
    process=...,
    resources=...,
    identity=...,

    capabilities=frozenset(...)
)
```

Important:

```text
immutable
```

after construction.

---

## 5. Profile examples

### `trusted`

```text
filesystem: host
network: enabled
process: enabled
resources: high
```

### `analysis`

```text
filesystem: workspace
network: disabled
process: restricted
memory: 1 GiB
```

### `untrusted`

```text
filesystem: isolated
network: disabled
process: disabled
memory: 512 MiB
PID: 32
```

### `networked-untrusted`

```text
filesystem: isolated
network: explicit egress
process: disabled
memory: 512 MiB
PID: 32
```

---

## 6. Capabilities should describe *intent*

Security profiles describe the physical boundary.

Capabilities describe what the application is asking to do.

For example:

```text
kernel.execute
filesystem.read
filesystem.write
network.connect
database.read
database.write
process.spawn
secret.read
```

Then:

```text
capability
    ↓
profile
```

determines whether the physical sandbox can support the request.

---

## 7. Capability ≠ permission

This distinction is subtle but important.

A capability is:

> "The caller is authorized to request this effect."

A sandbox permission is:

> "The operating system allows the worker to physically perform it."

Therefore:

```text
authorized ≠ physically unrestricted
```

The second layer should always remain.

---

## 8. Example: filesystem read

Agent requests:

```text
filesystem.read
```

Capability broker:

```text
ALLOW
```

But the sandbox says:

```text
readable:
/workspace/input
```

So:

```text
/workspace/input/a.csv
```

works.

While:

```text
/etc/passwd
```

fails at the OS boundary.

That's exactly what we want.

---

## 9. Example: network

Agent requests:

```text
network.connect
```

Capability broker:

```text
ALLOW
```

But the profile is:

```text
network = disabled
```

The effective authority becomes:

```text
DENY
```

before execution.

If a policy bug nevertheless lets the code execute:

```text
OS/network layer
        ↓
still blocked
```

Defense in depth.

---

## 10. Capability intersection

The implementation should effectively calculate:

```text
effective_capabilities =
    requested
    ∩ caller_ceiling
    ∩ skill_ceiling
    ∩ profile_ceiling
    ∩ administrator_policy
```

Never:

```text
requested ∪ ...
```

This is the mathematical heart of the model.

---

## 11. Skill manifests

Every executable skill should eventually have:

```yaml
id: documents
version: 0.2.0

dependencies:
  - pdfplumber
  - python-docx

capabilities:
  - filesystem.read

security_profile:
  minimum: document-reader
```

This makes skill loading deterministic.

---

## 12. Why `minimum` is useful

A skill shouldn't necessarily dictate the exact worker profile.

It can say:

```text
requires:
    filesystem.read
```

Then the administrator decides:

```text
document-reader
```

or:

```text
restricted-document-reader
```

depending on deployment.

---

## 13. Skill integrity

Before bootstrap:

```text
skill source
    ↓
canonical serialization
    ↓
SHA-256
    ↓
manifest hash
```

For stronger deployments:

```text
signature verification
```

The worker should not execute an unverified skill merely because its name exists in the registry.

---

## 14. Skill loading lifecycle

Recommended:

```text
resolve skill
     ↓
verify identity
     ↓
verify version
     ↓
verify dependencies
     ↓
verify integrity
     ↓
resolve capabilities
     ↓
resolve security profile
     ↓
create worker
     ↓
bootstrap skill
     ↓
record provenance
```

Every step should be auditable.

---

## 15. Dependency failures should happen before execution

For example:

```text
timeseries
requires:
    statsmodels
```

If missing:

```text
SKILL_UNAVAILABLE
```

not:

```text
start kernel
 ↓
execute bootstrap
 ↓
ImportError
```

The former is cleaner and safer.

---

## 16. This connects directly to the package extras

The package defines:

```text
timeseries → statsmodels
nlp        → nltk
graphs     → networkx
documents  → pdfplumber + python-docx
```

and a broad `all` profile.

The skill registry should therefore be able to map:

```text
skill
 ↓
required Python packages
 ↓
installed?
```

without executing the skill first.

---

## 17. `kerno doctor`

This is now worth treating as a first-class feature.

Example:

```bash
kerno doctor
```

Output:

```text
Kerno 0.2.0

Core
  Python                  PASS
  Jupyter                 PASS
  Kernel runtime          PASS

Optional skills
  timeseries              PASS
  nlp                     MISSING
  graphs                  PASS
  documents               PASS

Security
  capability broker       PASS
  approval gate           PASS
  execution policy        PASS
  sandbox backend         FAIL
  network isolation       FAIL
  filesystem isolation    FAIL
  resource enforcement    FAIL

Overall:
  POLICY-ONLY
```

This prevents operators from accidentally assuming that installing Kerno automatically provides hostile-code containment.

---

## 18. `kerno doctor --strict`

For production:

```bash
kerno doctor --strict
```

should exit nonzero unless:

```text
execution policy
+
sandbox
+
resource controls
+
worker isolation
```

are all available.

This can become a CI/deployment gate.

---

## 19. Sandbox backend abstraction

Don't hard-code one Linux technology into the core.

Define:

```text
SandboxBackend
├── create()
├── start()
├── terminate()
├── inspect()
└── cleanup()
```

Then implementations can include:

```text
ContainerBackend
NamespaceBackend
BubblewrapBackend
PlatformBackend
```

depending on the environment.

---

## 20. The important rule

The Python layer should not know *how* the sandbox is implemented.

It asks:

```text
Create worker:
profile=untrusted
```

The backend translates that into the platform's mechanisms.

This keeps Kerno portable.

---

## 21. Linux implementation direction

For a Linux production backend, the eventual containment stack could combine mechanisms such as:

```text
namespaces
+
resource controller
+
filesystem isolation
+
capability reduction
+
no-new-privileges
+
seccomp
+
network restrictions
```

The exact combination should be determined by the supported deployment environments and tested experimentally rather than assumed.

---

## 22. Don't build a fake sandbox in Python

Avoid:

```python
def sandbox():
    builtins.open = restricted_open
    os.system = forbidden
```

This can be useful for convenience, but it is not a security boundary.

A compromised Python process remains inside the host process.

---

## 23. Resource control

The profile should define:

```text
CPU
memory
PIDs
wall time
disk
file descriptors
output size
```

For example:

```yaml
resources:
  memory: 512MiB
  cpu: 1
  pids: 32
  timeout: 120s
  disk: 100MiB
  output: 10MiB
```

---

## 24. The enforcement hierarchy

Do not depend exclusively on cooperative monitoring.

Bad:

```text
worker
 ↓
monitor
 ↓
notice memory > 512MB
 ↓
kill
```

Better:

```text
worker
 ↓
OS resource controller
 ↓
hard limit
```

Monitoring then becomes:

```text
telemetry
```

rather than the primary enforcement mechanism.

---

## 25. Process-tree containment

When a worker dies:

```text
worker
 ├── child A
 ├── child B
 └── child C
```

all descendants must die with it.

Otherwise:

```text
worker terminated
      ↓
malicious child survives
```

and the security boundary has failed.

This deserves a dedicated integration test.

---

## 26. Filesystem model

For an untrusted worker:

```text
/
├── runtime            read-only
├── libraries          read-only
├── workspace
│   ├── input          read-only
│   └── output         controlled write
└── tmp                isolated
```

The host root filesystem should not simply be mounted read/write.

---

## 27. Secrets

One of the most important rules:

```text
untrusted worker
        ≠
host environment
```

Don't automatically inherit:

```text
os.environ
```

especially:

```text
API keys
cloud credentials
database credentials
CI tokens
GitHub tokens
```

Credentials should be explicitly injected only when a capability requires them.

---

## 28. Secret injection should be capability-scoped

Instead of:

```text
worker gets:
OPENAI_API_KEY
DATABASE_URL
AWS credentials
```

use:

```text
skill = llm
capability = llm.openai
```

and provide only the required credential to that worker.

---

## 29. Credentials should disappear with the worker

If:

```text
worker generation 7
```

contains a credential, then:

```text
generation 7 destroyed
```

should eliminate that worker's credential context.

A reused process should not retain it.

---

## 30. This makes kernel pooling much safer

The pool should really be:

```text
FreshWorkerFactory
        │
        ▼
SandboxedWorker
        │
        ▼
Kernel
```

rather than:

```text
global kernel pool
```

for hostile workloads.

For trusted workloads, pooling can remain an optimization.

---

## 31. Trust domains should determine pooling strategy

```text
trusted
    → reuse allowed

controlled
    → restricted reuse

untrusted
    → destroy after execution
```

This gives Kerno a practical performance/security trade-off.

---

## 32. Performance doesn't need to be sacrificed completely

Possible optimization:

```text
immutable base image
       ↓
fast worker creation
       ↓
execute
       ↓
destroy
```

Then the security boundary remains strong while startup latency is minimized.

---

## 33. Security regression suite

The project should eventually have tests for:

```text
filesystem escape
network escape
process escape
PID exhaustion
memory exhaustion
CPU exhaustion
environment leakage
credential leakage
cross-worker state leakage
cross-tenant reuse
skill escalation
profile escalation
policy bypass
worker cleanup
```

---

## 34. The most important regression test

A test should explicitly establish:

```text
Given:
    AllowList is bypassed

Then:
    OS sandbox still prevents host compromise
```

That test captures the entire defense-in-depth philosophy.

---

## 35. Security status terminology

I'd introduce three states:

### `POLICY_ONLY`

```text
Python policy exists
OS containment unavailable
```

### `CONTAINED`

```text
OS isolation exists
adversarial suite passes
```

### `HARDENED`

```text
contained
+
resource enforcement
+
identity separation
+
credential isolation
+
audit integrity
+
production verification
```

This is much clearer than a single boolean:

```text
secure = true
```

---

## 36. Where `arena/01a0064f-kerno` should ultimately land

```text
             KERNO
               │
       ┌───────┴────────┐
       │                │
 CONTROL PLANE       DATA PLANE
       │                │
       ▼                ▼
 Identity           Sandbox
 Policy             Worker
 Capability         Kernel
 Approval              │
 Skills                ▼
 Provenance            OS
 Audit
       │
       └──── governs ────┘
```

And the governing invariant:

```text
                 AUTHORITY
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
     Application             OS
       policy              containment
          │                     │
          └──────────┬──────────┘
                     ▼
              effective authority
```

---

## Next stage

The next audit should become much more concrete: **construct the actual call graph from the repository**.

For every executable sink, we should produce:

```text
SOURCE
  ↓
CALLER
  ↓
POLICY
  ↓
CAPABILITY
  ↓
APPROVAL
  ↓
WORKER
  ↓
KERNEL
  ↓
AUDIT
```

and mark each edge:

**PASS / BYPASS / UNKNOWN**.

That will let us identify the exact P0 execution paths in `arena/01a0064f-kerno`, rather than continuing at the architectural level.

---

## Execution-path closure and the next audit gate

We now have enough architectural understanding to define the **actual closure test** for Kerno.

The goal is no longer "find security features." It is:

> **Prove that there is no executable path from an untrusted actor to Python execution that bypasses the intended control plane.**

---

## 1. The execution graph

The repository should be modeled as a directed graph:

```text
Actor
  │
  ▼
Public API
  │
  ▼
Request normalization
  │
  ▼
Capability resolution
  │
  ▼
Approval / policy
  │
  ▼
Execution planner
  │
  ▼
Worker selection
  │
  ▼
Kernel execution
  │
  ▼
Effect recording
  │
  ▼
Result
```

But we must also search for **side entrances**:

```text
                 ┌──────────────► Kernel
                 │
Actor ──► API ───┤
                 │
                 ├──────────────► Skill bootstrap
                 │
                 ├──────────────► Tool execution
                 │
                 ├──────────────► Notebook execution
                 │
                 └──────────────► Subprocess
```

Every arrow to executable behavior needs classification.

---

## 2. Four types of execution sink

I recommend categorizing every sink as:

### E1 — Python execution

```text
exec
eval
compile
Jupyter execute
IPython execution
```

### E2 — native/process execution

```text
subprocess
os.system
spawn
fork
shell
```

### E3 — dynamic loading

```text
import
importlib
plugin loading
skill loading
```

### E4 — external effects

```text
network
filesystem
database
cloud APIs
```

These aren't all equivalent, but they all need authority boundaries.

---

## 3. The `KernelRuntime` sink is special

The most important sink is effectively:

```text
KernelRuntime.execute(...)
```

Everything that can reach it should be traceable.

The audit table should eventually look like:

| Sink | Reachable from | Policy | Capability | Approval | Worker | Audit |
|---|---|---|---|---|---|---|
| Kernel execute | Agent API | ? | ? | ? | ? | ? |
| Skill bootstrap | Skill loader | ? | ? | ? | ? | ? |
| Notebook execute | Notebook API | ? | ? | ? | ? | ? |
| Tool execution | Tool API | ? | ? | ? | ? | ? |

A `?` isn't a failure.

It is an **audit gap**.

---

## 4. Why "private" functions aren't enough

Suppose we find:

```python
def _execute_raw(code):
    ...
```

and assume:

> "Only ExecutionEngine calls it."

That isn't a security property in Python.

If another trusted component can import the module and call:

```python
_execute_raw(...)
```

the policy is bypassed.

The solution is not naming.

The solution is:

```text
trust boundary
+
process boundary
+
minimal privileged interface
```

---

## 5. Recommended interface separation

Instead of exposing:

```python
runtime.execute(code)
```

throughout the application, define:

```text
ExecutionService
```

as the only public execution interface.

Conceptually:

```text
Application
    │
    ▼
ExecutionService
    │
    ├── authorize
    ├── construct context
    ├── select worker
    ├── execute
    └── record
```

The raw kernel handle stays behind that boundary.

---

## 6. Kernel handles should be opaque

The rest of Kerno shouldn't receive:

```text
KernelClient
```

if it doesn't need one.

Instead:

```text
ExecutionHandle
```

could expose:

```text
execution_id
status
result
cancel()
```

but not:

```text
arbitrary_execute()
```

This dramatically reduces accidental bypasses.

---

## 7. Cancellation is part of the security model

Cancellation must follow the same path:

```text
cancel(execution_id)
       ↓
authorize
       ↓
locate worker
       ↓
terminate execution
       ↓
cleanup descendants
       ↓
record event
```

Don't expose a generic:

```python
worker.kill()
```

to arbitrary application code.

---

## 8. Restart is also security-sensitive

A restart isn't merely operational.

It destroys:

```text
Python state
threads
imports
connections
temporary credentials
```

Therefore:

```text
restart
```

should produce a new:

```text
kernel_generation
```

and new provenance context.

---

## 9. The state machine should be explicit

A worker should have states:

```text
CREATED
   ↓
STARTING
   ↓
READY
   ↓
EXECUTING
   ↓
IDLE
   ↓
TERMINATING
   ↓
TERMINATED
```

Failures:

```text
STARTING ──► FAILED
EXECUTING ─► CRASHED
EXECUTING ─► TIMEOUT
```

No execution should be accepted from:

```text
CREATED
STARTING
TERMINATING
TERMINATED
FAILED
```

---

## 10. Security profile belongs to the state machine

A worker should be born with:

```text
profile = X
```

and remain:

```text
profile = X
```

until termination.

Changing profile means:

```text
terminate
+
new worker
```

This prevents stale privileges.

---

## 11. Cross-tenant reuse test

This should become a mandatory regression test.

```text
Tenant A
  ↓
Worker W
  ↓
execute secret A
  ↓
destroy W

Tenant B
  ↓
Worker W2
  ↓
attempt to access A
```

Expected:

```text
no state
no files
no credentials
no modules
no connections
```

---

## 12. Cross-profile reuse test

Likewise:

```text
Profile: networked
   ↓
Worker A
   ↓
destroy

Profile: network-disabled
   ↓
Worker B
```

Worker B must not inherit:

```text
network sockets
DNS state
environment variables
credentials
```

from A.

---

## 13. Skill bootstrap must have its own provenance

When a skill loads:

```text
skill_id
skill_version
skill_hash
dependency_set
capability_set
security_profile
```

should be attached to the execution context.

This means we can later answer:

> Which exact skill code executed inside this worker?

---

## 14. Dependency provenance

For:

```text
documents
```

record:

```text
pdfplumber version
python-docx version
Python version
Kerno version
```

This is important for reproducibility and security investigations.

---

## 15. `kerno[all]` makes this more important

Because the full installation introduces many additional libraries, a worker may have a substantial dependency surface.

So an audit record such as:

```text
skill=documents
```

isn't enough.

We eventually want:

```text
skill=documents
dependencies:
  pdfplumber=...
  python-docx=...
```

That becomes useful when a dependency vulnerability is discovered.

---

## 16. Dependency inventory

Kerno should be able to produce:

```bash
kerno inventory
```

with:

```text
Core
  numpy
  pandas
  scipy
  ...

Optional
  statsmodels
  nltk
  networkx
  ...
```

and ideally:

```text
skill → dependency → version
```

mapping.

---

## 17. Why this belongs in the security architecture

Imagine:

```text
skill A
 ↓
dependency B
 ↓
vulnerability
```

If Kerno doesn't know that relationship, it cannot selectively disable the affected skill.

With manifests:

```text
dependency vulnerability
        ↓
affected skills
        ↓
disable
        ↓
policy update
```

Much better.

---

## 18. Dynamic skill registration needs special treatment

The README advertises:

```text
register_skill(...)
```

This is powerful.

But it means Kerno effectively supports:

```text
runtime code loading
```

Therefore registration itself is a privileged action.

I recommend:

```text
skill.register
```

as a capability.

Not:

```text
any code can register a skill
```

---

## 19. Skill registration should not immediately execute code

Safer:

```text
register
  ↓
validate manifest
  ↓
validate source
  ↓
verify integrity
  ↓
store
```

Then:

```text
execute
  ↓
authorize
  ↓
sandbox
  ↓
bootstrap
```

Registration and execution should be separate lifecycle phases.

---

## 20. This also protects the registry

Otherwise a malicious agent might:

```text
register malicious skill
       ↓
skill becomes discoverable
       ↓
future agent uses it
```

That creates persistent poisoning.

The registry should therefore distinguish:

```text
REGISTERED
VERIFIED
APPROVED
AVAILABLE
REVOKED
```

---

## 21. Revocation is important

A skill should be revocable:

```text
skill X
 ↓
vulnerability discovered
 ↓
REVOKED
```

Then:

```text
new execution
 ↓
DENY
```

Already-running workers should preferably be:

```text
drained
+
terminated
```

depending on severity.

---

## 22. The same concept applies to dependencies

If:

```text
network library
```

becomes compromised:

```text
dependency revoked
 ↓
affected skills identified
 ↓
skill disabled
```

This becomes a software supply-chain defense.

---

## 23. Security policy versioning

Every execution should record:

```text
policy_version
```

Example:

```text
policy = 17
```

If policy changes:

```text
policy = 18
```

then old executions remain explainable.

This is essential for audit reproducibility.

---

## 24. Configuration should be immutable during execution

Avoid:

```text
global_allowlist.modify(...)
```

while workers are executing.

Instead:

```text
Policy v17
   ↓
execution context
```

The execution gets a snapshot.

Future executions use v18.

---

## 25. This prevents TOCTOU-style problems

Without snapshots:

```text
check permission
       ↓
policy changes
       ↓
execute under different policy
```

With immutable context:

```text
policy v17
       ↓
authorize
       ↓
execute using v17 context
```

Much cleaner.

---

## 26. The final provenance chain

For each execution, we want:

```text
Request
  │
  ├── principal
  ├── tenant
  └── request_id
        │
        ▼
Authorization
  │
  ├── policy_version
  ├── capabilities
  └── approval
        │
        ▼
Skill
  │
  ├── skill_id
  ├── version
  ├── hash
  └── dependencies
        │
        ▼
Worker
  │
  ├── worker_id
  ├── generation
  └── security_profile
        │
        ▼
Kernel
        │
        ▼
Effects
```

That is the complete provenance graph.

---

## 27. This creates an auditable execution record

Conceptually:

```json
{
  "execution_id": "exec-1938",
  "request_id": "req-882",
  "principal": "agent-7",
  "tenant": "tenant-a",

  "policy_version": 17,

  "skill": {
    "id": "documents",
    "version": "0.2.0",
    "hash": "..."
  },

  "capabilities": [
    "kernel.execute",
    "filesystem.read"
  ],

  "worker": {
    "id": "worker-42",
    "generation": 8
  },

  "security_profile": "untrusted-document-reader",

  "sandbox": {
    "network": false,
    "filesystem": "isolated"
  }
}
```

The actual implementation can use the project's existing provenance structures rather than necessarily adopting this exact JSON.

---

## 28. Security evidence becomes measurable

Then we can define:

```text
E1 = execution path closed
E2 = policy enforced
E3 = worker isolated
E4 = resources enforced
E5 = credentials isolated
E6 = cross-tenant isolation
E7 = adversarial tests pass
```

And report:

```text
E1 PASS
E2 PASS
E3 PASS
E4 PASS
E5 PASS
E6 PASS
E7 PASS
```

rather than saying simply:

```text
Security: PASS
```

---

## 29. This fits the project's existing traceability philosophy

Kerno already emphasizes:

```text
provenance
audit
effect ledger
execution records
```

So we're not introducing an alien concept.

We're extending the same philosophy down into:

```text
worker
sandbox
dependency
skill
policy
```

---

## 30. The resulting architecture is unusually strong

At maturity:

```text
                AGENT
                  │
                  ▼
             INTENT / PLAN
                  │
                  ▼
           AUTHORIZATION
                  │
                  ▼
          CAPABILITY BROKER
                  │
                  ▼
            SKILL RESOLVER
                  │
                  ▼
          SECURITY PROFILE
                  │
                  ▼
           SANDBOX FACTORY
                  │
                  ▼
           ISOLATED WORKER
                  │
                  ▼
              JUPYTER
                  │
                  ▼
              PYTHON
                  │
                  ▼
                 OS
```

With an independent audit stream observing the entire chain.

---

## 31. The most important implementation rule

**Do not make the sandbox a decorator around `execute()`.**

Bad:

```python
@sandbox
def execute(code):
    ...
```

if the underlying worker can still be reached elsewhere.

Instead:

```text
ExecutionService
       │
       ▼
SandboxFactory
       │
       ▼
WorkerHandle
       │
       ▼
Kernel
```

The sandbox should be part of the **worker lifecycle**, not merely an execution wrapper.

---

## 32. This also simplifies failure handling

If:

```text
worker crashes
```

then:

```text
WorkerHandle
   ↓
mark FAILED
   ↓
terminate descendants
   ↓
destroy sandbox
   ↓
record provenance
   ↓
create fresh worker
```

No need to reason about whether Python state was successfully reset.

The worker is gone.

---

## 33. The strongest trust rule

For hostile execution:

```text
ONE EXECUTION
=
ONE SECURITY CONTEXT
=
ONE ISOLATED WORKER
```

That is the simplest model to reason about.

Pooling can then be an optimization only where the trust model permits it.

---

## 34. Recommended next repository work

The next concrete pass should produce a **Kerno Execution Sink Matrix**:

```text
Sink
Caller
Entry point
Trust level
Policy check
Capability check
Approval
Skill provenance
Worker isolation
Sandbox profile
Audit event
Result
```

Then classify each row:

```text
GREEN   complete
YELLOW  policy-only
RED     bypass
GRAY    unknown
```

The first **RED** row is the next P0 to fix.

---

## Current architectural conclusion

We're now beyond the question:

> "Does Kerno have security?"

The useful question is:

> **"Can Kerno prove authority, containment, and provenance for every executable effect?"**

The target is:

```text
AUTHORIZATION
      +
CAPABILITY
      +
IMMUTABLE CONTEXT
      +
ISOLATED WORKER
      +
OS ENFORCEMENT
      +
PROVENANCE
      =
DEFENSIBLE EXECUTION
```

That should become the central security specification for `arena/01a0064f-kerno`.

---

## The next layer: build the **Execution Sink Matrix**

At this point, the right move is to turn the architecture into an auditable repository-level artifact.

For the `arena/01a0064f-kerno` branch, we want to answer one question with evidence:

> **Where can executable code or externally visible effects originate, and what security gates does each path cross?**

---

## 1. Start with the sink taxonomy

The audit should classify sinks into six groups:

```text
E1  Python execution
E2  Process execution
E3  Dynamic import/loading
E4  Filesystem effects
E5  Network effects
E6  Persistent/external effects
```

### E1 — Python

```text
exec()
eval()
compile()
IPython/Jupyter execute
kernel execution
dynamic notebook execution
```

### E2 — Process

```text
subprocess
Popen
os.system
spawn
fork
shell commands
```

### E3 — Dynamic loading

```text
importlib
__import__
plugin loading
skill loading
module discovery
```

### E4 — Filesystem

```text
open()
write()
unlink()
rename()
mkdir()
temporary files
```

### E5 — Network

```text
socket
HTTP clients
DNS
web requests
external APIs
```

### E6 — Persistent effects

```text
database writes
queue publication
cloud operations
credential operations
external service mutations
```

---

## 2. Why this classification matters

A function doesn't need to execute Python to be dangerous.

For example:

```text
Agent
  ↓
filesystem.write
```

can cause significant damage even if:

```text
KernelRuntime.execute()
```

is never called.

Therefore the security graph must cover **effects**, not just code execution.

---

## 3. The actual matrix

The final audit artifact should look like:

| ID | Sink | Entry point | Trust | Policy | Capability | Approval | Sandbox | Audit | Status |
|---|---|---|---|---|---|---|---|---|---|
| E1-01 | Python execution | … | … | … | … | … | … | … | ? |
| E1-02 | Jupyter execute | … | … | … | … | … | … | … | ? |
| E2-01 | subprocess | … | … | … | … | … | … | … | ? |
| E3-01 | skill bootstrap | … | … | … | … | … | … | … | ? |
| E4-01 | filesystem write | … | … | … | … | … | … | … | ? |
| E5-01 | network | … | … | … | … | … | … | … | ? |

The important part is that **unknown is not PASS**.

---

## 4. Establish the root of trust

We need to identify Kerno's highest-trust components.

Conceptually:

```text
ROOT
 │
 ├── Policy
 ├── Capability Broker
 ├── Approval
 ├── Sandbox Factory
 ├── Worker Manager
 └── Audit
```

Everything else should have less authority.

---

## 5. Authority should flow downward

Ideal:

```text
Root Policy
    ↓
ExecutionService
    ↓
Worker
    ↓
Skill
    ↓
User code
```

Never:

```text
User code
    ↓
Root Policy
```

That would permit the code being controlled to modify its controller.

---

## 6. Separate "decision" from "execution"

This is a very important architectural boundary.

### Decision plane

```text
Should this happen?
```

### Execution plane

```text
Make it happen.
```

They should not be the same component.

---

## 7. Example

Bad conceptual architecture:

```text
Kernel
  ├── checks policy
  └── executes code
```

Better:

```text
ExecutionController
      │
      ├── policy decision
      │
      ▼
SandboxWorker
      │
      └── execution
```

The worker doesn't decide its own authority.

---

## 8. Why this matters for Jupyter

Jupyter is fundamentally an execution environment.

It should therefore be treated as:

```text
DATA PLANE
```

not:

```text
SECURITY CONTROL PLANE
```

The controller decides what the Jupyter worker is allowed to do.

---

## 9. Kernel policy should be defense-in-depth

The existing `AllowList` remains valuable.

Its role becomes:

```text
first defense
```

not:

```text
ultimate security boundary
```

So:

```text
Policy
  ↓
AllowList
  ↓
Sandbox
```

is stronger than:

```text
AllowList
  ↓
hope
```

---

## 10. Import restrictions should become capability-aware

Instead of thinking:

```text
allowed_modules = [...]
```

think:

```text
module
  ↓
capabilities required
```

For example conceptually:

```text
filesystem module
    → filesystem.*

network module
    → network.*

process module
    → process.*

native module
    → native.*
```

Then module loading becomes an authorization event.

---

## 11. This avoids the "safe standard library" assumption

Earlier we identified the problem with:

```text
stdlib = trusted
```

The better model is:

```text
stdlib
   ↓
capability classification
   ↓
policy
```

Some modules can be harmless computational utilities.

Others expose powerful OS interfaces.

---

## 12. Capability classes

I'd define at least:

```text
compute
memory
filesystem.read
filesystem.write
network.connect
network.listen
process.spawn
native.load
secret.read
database.read
database.write
```

Then every privileged library maps to one or more classes.

---

## 13. Native loading should be a distinct capability

Don't combine:

```text
native.load
```

with ordinary:

```text
filesystem.read
```

A native extension can radically change the threat model.

Therefore:

```text
native.load = DENY
```

should be the default for untrusted workers.

---

## 14. Process creation should also be independent

Likewise:

```text
process.spawn
```

should not follow automatically from:

```text
filesystem.write
```

Every authority should be explicit.

---

## 15. Network should distinguish directions

Eventually:

```text
network.connect
network.listen
network.bind
```

should be separate.

A worker allowed to make HTTPS requests doesn't necessarily need:

```text
listen(0.0.0.0, ...)
```

---

## 16. Filesystem should distinguish locations

Instead of:

```text
filesystem.write
```

use something like:

```text
filesystem.write:/workspace/output
```

Conceptually.

Then:

```text
/workspace/output/report.pdf
```

may be allowed while:

```text
/etc/
```

is not.

---

## 17. Capabilities should be parameterized

This is where Kerno can become substantially more powerful.

Instead of:

```text
filesystem.read = true
```

use:

```text
filesystem.read:
    /workspace/input
```

Similarly:

```text
network.connect:
    api.example.com:443
```

This turns capabilities into **constrained authority**, not simple booleans.

---

## 18. Skill capability declaration

A skill could declare:

```yaml
capabilities:
  filesystem:
    read:
      - /workspace/input

  network:
    connect:
      - api.example.com:443
```

The policy engine intersects that with the deployment policy.

---

## 19. The effective capability calculation

Conceptually:

```text
effective =
    caller
    ∩ tenant
    ∩ skill
    ∩ security_profile
    ∩ administrator
```

For a path-based capability:

```text
effective_paths =
    intersection(all_allowed_path_sets)
```

For network endpoints:

```text
effective_endpoints =
    intersection(all_allowed_endpoint_sets)
```

---

## 20. This gives us capability narrowing

A child context should only be able to:

```text
maintain or reduce authority
```

never expand it.

Formally:

```text
Authority(child) ⊆ Authority(parent)
```

This should become a tested invariant.

---

## 21. Important test

Create a test:

```text
parent:
    filesystem.read=/workspace

skill:
    filesystem.read=/

expected:
    filesystem.read=/workspace
```

The skill cannot widen the parent's authority.

---

## 22. Another test

```text
parent:
    network=disabled

skill:
    network=*

expected:
    network=disabled
```

Again:

```text
child ⊆ parent
```

---

## 23. Another important test: capability removal

Suppose:

```text
parent:
    filesystem.read=/workspace
    filesystem.write=/workspace/output
```

A skill only needs:

```text
filesystem.read=/workspace
```

The resulting worker should preferably have:

```text
filesystem.read=/workspace
filesystem.write=DENIED
```

Why give it authority it doesn't need?

That's the **least-authority** principle.

---

## 24. Skills should request minimal capabilities

The skill manifest should therefore distinguish:

```text
required
```

from:

```text
optional
```

Example:

```yaml
capabilities:
  required:
    - filesystem.read

  optional:
    - network.connect
```

The optional capability shouldn't automatically activate.

---

## 25. This is particularly useful for `documents`

A PDF parser normally needs:

```text
filesystem.read
```

It shouldn't automatically receive:

```text
network.connect
filesystem.write
process.spawn
```

just because another dependency happens to expose them.

---

## 26. Dependency capabilities should not leak automatically

This is a major principle:

> **Installing a package must not grant its capabilities to the agent.**

For example:

```text
requests installed
```

doesn't mean:

```text
network enabled
```

Likewise:

```text
sqlalchemy installed
```

doesn't mean:

```text
database.write enabled
```

Availability and authority are different concepts.

---

## 27. This resolves the `kerno[all]` issue elegantly

You can safely have:

```bash
pip install "kerno[all]"
```

for a development environment.

Because:

```text
installed packages
        ≠
granted capabilities
```

The runtime still controls what a particular worker may actually do.

---

## 28. But package exposure still matters

Even if a package isn't granted a capability explicitly, having it available expands the code surface.

Therefore we still want:

```text
minimal production extras
```

and:

```text
skill-specific environments
```

where practical.

---

## 29. Skill environments

Eventually:

```text
core environment
      │
      ├── analysis environment
      ├── NLP environment
      ├── documents environment
      └── graph environment
```

This reduces dependency cross-contamination.

The worker can start with only the environment associated with the selected skill.

---

## 30. Stronger isolation: environment per skill

For hostile multi-tenant execution:

```text
skill
 ↓
immutable environment/image
 ↓
sandbox
 ↓
worker
```

This is significantly easier to reason about than one giant Python environment containing every optional dependency.

---

## 31. But don't over-engineer too early

A sensible progression is:

### Phase 1

```text
one environment
+
explicit skill manifests
+
capability policy
```

### Phase 2

```text
skill-specific environments
```

### Phase 3

```text
immutable sandbox images
```

This preserves development velocity.

---

## 32. Security and reproducibility converge here

If the worker is:

```text
image hash
+
skill hash
+
dependency lock
+
policy version
```

then an execution becomes reproducible.

We can say:

```text
Execution 1938
```

ran with a precise software/security state.

---

## 33. Reproducibility record

Conceptually:

```json
{
  "kerno": "...",
  "python": "...",
  "environment": "...",
  "skill": "...",
  "skill_hash": "...",
  "dependencies": "...",
  "policy": "...",
  "sandbox": "..."
}
```

This is excellent for debugging as well as security.

---

## 34. Incident investigation becomes possible

Suppose someone reports:

> "The documents skill behaved strangely yesterday."

You can retrieve:

```text
execution_id
skill hash
dependency lock
policy version
worker generation
sandbox profile
effects
```

and reproduce the environment.

---

## 35. This should integrate with the EffectLedger

The ledger then becomes more than:

```text
what happened
```

It becomes:

```text
what happened
+
under what authority
+
under which environment
+
under which security boundary
```

That's a much stronger provenance model.

---

## 36. Integrity of the ledger

Eventually, consider hash chaining:

```text
event 1
   ↓ hash
event 2
   ↓ hash
event 3
   ↓ hash
event 4
```

So tampering becomes detectable.

This is a later hardening phase, not the first thing to implement.

---

## 37. The priority order is now clear

I would **not** start with cryptographic audit chains.

First:

```text
P0
execution-path closure
```

Then:

```text
P0
worker isolation
```

Then:

```text
P0
resource enforcement
```

Then:

```text
P1
skill manifests
```

Then:

```text
P1
capability parameterization
```

Then:

```text
P1
dependency/environment provenance
```

Finally:

```text
P2
tamper-evident audit
```

---

## 38. The critical invariant set

Kerno's security specification should eventually contain explicit invariants:

### I1 — No unapproved execution

```text
execute → authorized
```

### I2 — No capability escalation

```text
child_authority ⊆ parent_authority
```

### I3 — Immutable worker security

```text
worker.profile(t1) = worker.profile(t2)
```

until termination.

### I4 — No unsafe cross-domain reuse

```text
tenant/profile/trust mismatch → worker reuse denied
```

### I5 — OS containment

```text
policy bypass ≠ host compromise
```

### I6 — Complete provenance

```text
execution → actor + policy + skill + worker + effects
```

### I7 — Fail closed

```text
unknown security state → deny
```

These are more valuable than hundreds of individual assertions because they define the system's behavior.

---

## 39. The strongest one is I7

This should be explicit everywhere:

```text
UNKNOWN
   ↓
DENY
```

Not:

```text
UNKNOWN
   ↓
best effort
   ↓
ALLOW
```

Examples:

```text
sandbox backend unknown → deny untrusted execution

skill integrity unknown → deny skill execution

capability mapping unknown → deny capability

worker trust domain unknown → deny reuse
```

---

## 40. Final architecture

The mature Kerno model now looks like:

```text
                         KERNO
                           │
             ┌─────────────┴─────────────┐
             │                           │
       CONTROL PLANE                DATA PLANE
             │                           │
       ┌─────┼─────┐                     │
       │     │     │                     │
    Policy  Skill  Audit                  │
       │   Registry │                     │
       │     │     │                     │
       └─────┼─────┘                     │
             ▼                           │
       Capability Broker                 │
             │                           │
       Execution Context                 │
             │                           │
       Sandbox Factory ──────────────────┘
             │
             ▼
       Isolated Worker
             │
             ▼
          Jupyter
             │
             ▼
           Python
             │
             ▼
             OS
```

---

## The next step is now repository evidence, not more architecture

We should take the actual `Abdus2023/Kerno` branch and produce the **Execution Sink Matrix + Security Invariant Matrix** from the source tree.

The result should explicitly identify:

```text
1. every execution sink
2. every caller
3. every public entry point
4. every skill bootstrap path
5. every capability check
6. every approval check
7. every worker creation/reuse path
8. every sandbox boundary
9. every audit/provenance write
10. every path where the chain is incomplete
```

Then we can stop saying **"Kerno should..."** and start saying **"Kerno currently does X at file/function Y, while path Z bypasses gate W."**

That is the point where this becomes a genuine **deep repository security audit** rather than an architectural review.

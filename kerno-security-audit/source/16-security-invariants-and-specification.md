# 16 — Security Invariants And Specification

## Definitive audit direction: build the **execution call graph**

The next stage is to stop treating individual security classes as independent features and reconstruct the path from an agent request all the way to Python execution.

### The graph we need

```text
Agent request
     │
     ▼
Agent loop / planner
     │
     ▼
Pipeline
     │
     ▼
ExecuteStep
     │
     ▼
Executor
     │
     ├── AllowList
     ├── CapabilityBroker
     ├── SecretBroker
     └── Audit
     │
     ▼
KernelRuntime
     │
     ▼
Jupyter kernel
     │
     ▼
Python process
```

Every arrow needs evidence.

---

## 1. The decisive boundary is `KernelRuntime.execute()`

Everything ultimately converges here.

The question isn't:

> "Does Kerno have an allowlist?"

It is:

> **"Can anything reach `KernelRuntime.execute()` without passing the intended authorization boundary?"**

That is the security invariant.

---

## 2. We need to classify every caller

The call sites should fall into exactly four categories:

### A — Trusted infrastructure

```text
kernel initialization
bootstrap
internal lifecycle
cleanup
```

Allowed to use raw kernel APIs.

### B — Authorized agent execution

```text
ExecuteStep
tool execution
pipeline execution
```

Must pass through authorization.

### C — Extension code

```text
skills
plugins
custom steps
```

Must have explicit trust classification.

### D — Tests/debugging

```text
unit tests
fixtures
development utilities
```

Not production execution paths.

---

## 3. The most dangerous category is B/C

If we find:

```text
ExecuteStep
    ↓
KernelRuntime.execute()
```

then the security question becomes:

```text
Where is CAP_KERNEL_EXECUTE checked?
```

If nowhere:

```text
🔴 confirmed enforcement gap
```

If immediately before it:

```text
🟢 logical authorization exists
```

Then we still ask:

```text
Can the agent bypass ExecuteStep?
```

---

## 4. Capability enforcement should be centralized

The ideal implementation is:

```text
execute(request)
       │
       ▼
authorize(request.capability)
       │
       ├── DENY → stop
       │
       └── ALLOW
             │
             ▼
        audit(record)
             │
             ▼
        kernel.execute()
```

Not:

```text
some callers check capability
some callers use allowlist
some callers call kernel directly
```

The latter creates security drift.

---

## 5. `CAP_KERNEL_EXECUTE` should be unavoidable

The agent should not be able to say:

```text
"I don't need CAP_KERNEL_EXECUTE;
I'll just use another step."
```

Every mechanism that causes Python execution should converge on the same capability.

For example:

```text
ExecuteStep
StreamingExecuteStep
ToolStep
SkillStep
NotebookStep
RetryStep
ParallelStep
```

must all eventually require:

```text
CAP_KERNEL_EXECUTE
```

---

## 6. Streaming must not create a second security path

The safe structure is:

```text
StreamingExecuteStep
        ↓
same authorization
        ↓
same executor
        ↓
KernelRuntime.stream_execute()
```

The unsafe structure is:

```text
ExecuteStep
 → security

StreamingExecuteStep
 → raw kernel
```

Streaming is a classic place where security gets accidentally duplicated incorrectly.

---

## 7. Retries must preserve authorization

Suppose:

```text
attempt #1 → authorized
attempt #2 → retry
```

The retry must not become:

```text
retry
 ↓
direct kernel.execute()
```

It must inherit the same:

```text
security context
capabilities
principal
audit identity
resource limits
```

---

## 8. Parallel execution has the same requirement

For:

```text
Agent
 ├── task A
 ├── task B
 └── task C
```

each branch must retain:

```text
principal
policy
capabilities
budget
audit context
```

It must not create a fresh unrestricted kernel executor.

---

## 9. Skill execution must not silently become runtime execution

This is a subtle but important distinction.

If:

```text
Skill
 ↓
kernel.execute()
```

then the skill effectively becomes a privileged runtime component.

That's acceptable **only if skills are explicitly trusted**.

For dynamically supplied skills:

```text
Skill
 ↓
AgentExecutor
 ↓
policy
 ↓
kernel
```

---

## 10. Plugin loading should happen outside the agent privilege boundary

Plugins should preferably be:

```text
installed/configured by host
       ↓
loaded before agent execution
```

rather than:

```text
agent
 ↓
install plugin
 ↓
import plugin
 ↓
gain arbitrary runtime privileges
```

If Kerno allows dynamic plugin registration, that needs its own authorization gate.

---

## 11. Secret access needs a different capability

Don't overload:

```text
CAP_KERNEL_EXECUTE
```

to mean:

```text
"Python may access secrets."
```

Keep:

```text
CAP_KERNEL_EXECUTE
CAP_SECRET_READ
```

separate.

Then an analytical workload can potentially have:

```text
CAP_KERNEL_EXECUTE
```

without:

```text
CAP_SECRET_READ
```

That's good least-privilege design.

---

## 12. Network and subprocess should remain separate too

Likewise:

```text
CAP_NETWORK_CONNECT
CAP_PROCESS_SPAWN
```

should never automatically follow from:

```text
CAP_KERNEL_EXECUTE
```

Python execution is broad, but Kerno's policy model should treat these as independent effects.

---

## 13. This leads to a capability lattice

Conceptually:

```text
              KERNEL_EXECUTE
              /     |      \
             /      |       \
       filesystem  network  process
          /   \               \
       read  write            spawn
          \
        secrets
```

A profile should explicitly select the subset.

For example:

```text
READ_ONLY
    filesystem.read

DATA_ANALYSIS
    kernel.execute
    filesystem.read
    package.import

RESEARCH
    kernel.execute
    network.connect
    filesystem.read

TRUSTED
    broad capabilities
```

The exact mapping needs verification from the branch rather than assumption.

---

## 14. The strongest test isn't "denied"

The strongest regression test is:

```text
for every public execution API:
    execute known code
    assert capability authorization occurred
    assert audit record exists
```

And for denied capabilities:

```text
attempt effect
    ↓
authorization denied
    ↓
kernel code never executes
```

That last assertion is essential.

A system that logs:

```text

```

but executes anyway is obviously broken.

---

## 15. Security tests should inspect side effects

For example:

```text
deny network
 ↓
attempt network connection
 ↓
assert no connection
```

```text
deny filesystem write
 ↓
attempt write
 ↓
assert file does not exist
```

```text
deny subprocess
 ↓
attempt process spawn
 ↓
assert process wasn't created
```

This is especially important because logical policy and actual OS enforcement are different things.

---

## 16. The OS sandbox remains the final barrier

Even a perfect capability broker cannot guarantee:

```text
Python cannot bypass policy
```

unless the environment itself enforces the restrictions.

For hostile code:

```text
Capability policy
       +
OS isolation
```

is the correct defense-in-depth model.

---

## 17. Recommended security tiers

I would formalize three deployment modes:

### `trusted`

```text
same-process kernel
broad capabilities
trusted code only
```

### `restricted`

```text
policy enforcement
limited capabilities
worker isolation
resource limits
```

### `hostile`

```text
separate process/container
network isolation
filesystem isolation
resource limits
ephemeral worker
strict capability policy
```

This avoids pretending one mechanism solves every threat model.

---

## 18. The architectural gate

I would now define:

## K-SEC-001 — Mandatory execution boundary

> Every agent-controlled operation capable of executing Python must converge on one authorized executor before reaching `KernelRuntime`.

## K-SEC-002 — No privilege self-escalation

> Agent-controlled code cannot manufacture trusted profiles, runtime-origin execution, or unrestricted capability grants.

## K-SEC-003 — Capability inheritance

> Retry, streaming, parallel, skill, and plugin-derived execution inherit the originating security context.

## K-SEC-004 — OS defense in depth

> Capability policy is not considered equivalent to process-level sandboxing.

## K-SEC-005 — Evidence

> Each authorized execution produces an auditable execution record containing principal, capabilities, origin, and execution identity.

---

## 19. Current audit confidence

At this stage, the correct status is:

| Area | Status |
|---|---|
| Security primitives exist |  |
| Capability vocabulary exists |  |
| Profiles exist |  |
| Mandatory execution choke point |  |
| `CAP_KERNEL_EXECUTE` enforcement |  |
| Trusted-profile acquisition |  |
| Raw-kernel exposure |  |
| Skill trust boundary |  |
| Plugin trust boundary |  |
| Secret isolation |  |
| OS sandbox |  |
| Security regression suite |  |

No security **PASS** should be declared yet.

---

## The next step is now very concrete

We should reconstruct one complete chain:

```text
`CAP_KERNEL_EXECUTE`
       ↓
`CapabilityBroker`
       ↓
authorization call
       ↓
executor / step
       ↓
`KernelRuntime.execute()`
```

Then repeat the same process for:

```text
CAP_FILESYSTEM_READ
CAP_FILESYSTEM_WRITE
CAP_NETWORK_CONNECT
CAP_PROCESS_SPAWN
CAP_SECRET_READ
```

That will tell us whether Kerno's capability system is **actually enforced**, where the enforcement occurs, and which public APIs can bypass it.

Only after that should we write the patch.

---

## Consolidate the audit into a **Security Boundary Map**

At this point, the next useful step is to convert the investigation into a formal map that can be implemented and tested.

One correction remains important: **we should not treat the earlier `ExecutionEngine` discussion as confirmed for `arena/01a0064f-kerno` until the exact branch's call graph proves it.** The branch definitely contains capability/security primitives; the mandatory execution boundary is still the question to prove.

---

## 1. Kerno's security architecture should be viewed as 5 layers

```text
┌─────────────────────────────────────────────┐
│  L5 — OS / Process Isolation                │
│  namespaces · cgroups · filesystem · net    │
├─────────────────────────────────────────────┤
│  L4 — Kernel Runtime                        │
│  Jupyter/Python execution                   │
├─────────────────────────────────────────────┤
│  L3 — Execution Boundary                    │
│  Executor / authorization / audit           │
├─────────────────────────────────────────────┤
│  L2 — Capability Policy                     │
│  AllowList · CapabilityBroker · profiles    │
├─────────────────────────────────────────────┤
│  L1 — Agent / Pipeline                      │
│  planner · skills · tools · custom steps    │
└─────────────────────────────────────────────┘
```

The key rule is:

> **L1 must never be able to jump directly to L4.**

It must pass through L2/L3.

---

## 2. The dangerous architecture

```text
Agent
  │
  ├───────────────► KernelRuntime.execute()
  │
  │
  └───────────────► CapabilityBroker
```

This is fundamentally broken because the capability broker becomes advisory.

---

## 3. The required architecture

```text
Agent
  │
  ▼
Pipeline
  │
  ▼
Authorized Executor
  │
  ├── CapabilityBroker
  ├── AllowList
  ├── Audit
  └── Resource policy
  │
  ▼
KernelRuntime
```

Now the broker is on the actual execution path.

---

## 4. We should distinguish **code execution** from **effects**

This is one of the most important architectural refinements.

Python execution itself is:

```text
CAP_KERNEL_EXECUTE
```

But inside Python, the agent may attempt:

```text
filesystem
network
subprocess
secrets
package installation
```

Those are effects.

So:

```text
Python execution
      │
      ├── read file
      ├── write file
      ├── connect network
      ├── spawn process
      ├── read secret
      └── install package
```

must remain separately controlled.

---

## 5. Capability inheritance

Every execution should carry something equivalent to:

```python
ExecutionContext(
    principal=...,
    capabilities=...,
    origin=...,
    execution_id=...,
)
```

Then:

```text
Agent
 ↓
Pipeline
 ↓
Step
 ↓
Retry
 ↓
Kernel
```

all retain the same context.

This prevents a retry or nested task from accidentally receiving a broader privilege set.

---

## 6. Parallel execution must inherit the same principal

Suppose:

```text
Agent A
 ├── Worker 1
 ├── Worker 2
 └── Worker 3
```

Worker 2 must not become:

```text
PROFILE_TRUSTED
```

just because it was created by a different internal function.

The context should flow:

```text
A
 │
 ├── B(context=A)
 ├── C(context=A)
 └── D(context=A)
```

with explicit capability narrowing allowed:

```text
child.capabilities ⊆ parent.capabilities
```

but never:

```text
child.capabilities ⊃ parent.capabilities
```

without an explicit trusted authorization event.

---

## 7. This gives us a very useful invariant

### **Privilege monotonicity**

For normal agent-derived execution:

```text
child privileges ≤ parent privileges
```

That should apply to:

- retries
- parallel tasks
- sub-agents
- skills
- tools
- pipelines
- callbacks

This is a powerful security property to test.

---

## 8. `PROFILE_TRUSTED` should be treated specially

A trusted profile is not just another configuration.

It represents:

```text
host authorization
```

Therefore:

```text
agent → PROFILE_TRUSTED
```

should be impossible.

Instead:

```text
host
 ↓
trusted policy
 ↓
trusted execution context
```

The profile itself can be public as a constant; **the authority to activate it must not be public to untrusted code.**

---

## 9. `grant_profile()` therefore deserves a guard

Conceptually:

```python
grant_profile(profile)
```

should require a trusted caller.

Something like:

```text
if caller_origin != RUNTIME:
    deny
```

or, better, expose profile selection only during construction of a trusted execution context.

Do not let ordinary agent code construct arbitrary grants.

---

## 10. SecretBroker needs the same privilege rule

The agent should request:

```text
CAP_SECRET_READ
```

and the broker decides.

It should never be able to request:

```text
"give me every secret"
```

through a generic trusted profile.

Secrets should additionally be:

```text
scoped
audited
short-lived
redacted
```

where practical.

---

## 11. Package installation is particularly dangerous

Because Python execution can potentially invoke:

```text
pip
subprocess
importlib
```

a capability such as:

```text
CAP_PACKAGE_IMPORT
```

must not be confused with arbitrary package installation.

Importing an already-approved package is substantially different from:

```text
pip install attacker-package
```

The latter implies:

```text
network
filesystem write
process execution
code loading
```

and therefore deserves explicit policy.

---

## 12. Network capability is also transitive

If:

```text
CAP_NETWORK_CONNECT
```

is granted, an agent may potentially retrieve:

- remote code
- credentials
- malicious packages
- arbitrary data

Therefore `network.connect` should ideally include:

```text
destination policy
protocol policy
DNS policy
rate/resource limits
```

for stronger deployments.

---

## 13. Filesystem capability should be path-scoped

Rather than:

```text
CAP_FILESYSTEM_WRITE
```

meaning "write anywhere", the execution context should eventually contain:

```text
/workspace
/tmp/kerno/<execution-id>
```

and deny:

```text
/etc
/home/other-user
credentials
system sockets
```

This is where OS-level isolation becomes much stronger than application-level checks.

---

## 14. Audit records should describe effects, not just code

A useful execution record should answer:

```text
WHO?
WHAT?
WHICH CAPABILITIES?
WHICH RESOURCES?
WHEN?
WHICH WORKER?
WHICH POLICY?
WHAT EFFECT?
SUCCESS/FAILURE?
```

Example:

```text
execution_id: e-123
principal: agent-42
origin: agent
capabilities:
  - kernel.execute
  - filesystem.read
resource:
  /workspace/data.csv
result:
  success
```

That is substantially more useful than simply recording:

```text
"Python executed"
```

---

## 15. Security events should be immutable

Once an execution record says:

```text
CAP_NETWORK_CONNECT denied
```

the agent shouldn't be able to modify the event afterward.

So audit storage should be treated as:

```text
append-only
```

at least from the agent's perspective.

---

## 16. Kernel pooling introduces one additional invariant

For a reusable kernel:

```text
Agent A
 ↓
Kernel K
 ↓
reset
 ↓
Agent B
```

we must guarantee:

```text
state(A) ∩ state(B) = ∅
```

at the security boundary.

That means clearing more than Python variables.

Potential leakage includes:

- environment variables
- imported modules
- working directory
- filesystem artifacts
- network connections
- subprocesses
- secrets
- notebook state
- temporary files

For hostile tenants, **destroy/recreate** is much safer than reset/reuse.

---

## 17. This gives us two lifecycle classes

### Reusable worker

```text
trusted workloads
 ↓
reset
 ↓
reuse
```

### Ephemeral worker

```text
untrusted workload
 ↓
destroy
 ↓
new worker
```

The pool should know which class it is managing.

---

## 18. Proposed security profiles

A useful eventual model:

| Profile | Kernel | FS | Network | Process | Secrets | Worker |
|---|---|---|---|---|---|---|
| `read_only` | limited | read | no | no | no | reusable |
| `data_analysis` | yes | workspace | no/limited | no | no | reusable |
| `research` | yes | workspace | limited | limited | no | restricted |
| `trusted` | broad | broad | broad | broad | explicit | reusable |
| `hostile` | yes | isolated | isolated | isolated | no | ephemeral |

The exact capabilities must be derived from the branch's actual profile definitions—not assumed.

---

## 19. This is now a candidate implementation roadmap

### Milestone S1 — Execution boundary

```text
[ ] identify actual Executor
[ ] identify every KernelRuntime.execute caller
[ ] force agent paths through Executor
```

### Milestone S2 — Capability enforcement

```text
[ ] CAP_KERNEL_EXECUTE enforced
[ ] filesystem capabilities enforced
[ ] network capability enforced
[ ] process capability enforced
[ ] secret capability enforced
```

### Milestone S3 — Privilege integrity

```text
[ ] no self-granting
[ ] no PROFILE_TRUSTED escalation
[ ] runtime operations host-only
[ ] child context cannot gain privilege
```

### Milestone S4 — Lifecycle

```text
[ ] retry preserves context
[ ] parallel preserves context
[ ] pool isolation verified
[ ] hostile workers destroyed
```

### Milestone S5 — OS sandbox

```text
[ ] filesystem isolation
[ ] network isolation
[ ] process isolation
[ ] resource limits
```

### Milestone S6 — Evidence

```text
[ ] security regression suite
[ ] integration tests
[ ] negative tests
[ ] audit records
[ ] CI evidence
```

---

## 20. The key thing we should **not** do yet

Don't start modifying `Session` based only on the earlier `ExecutionEngine` assumption.

First establish:

```text
What is the actual executor abstraction in THIS branch?
```

Otherwise we risk introducing a second architecture into a repository that already has a different execution design.

---

## Next

The highest-value next operation is now:

```text
KernelRuntime.execute()
        ↓
ALL CALLERS
        ↓
identify caller type
        ↓
trace backwards
        ↓
find authorization boundary
```

Then do the same for:

```text
KernelRuntime.stream_execute()
```

because streaming is the most likely place for a parallel execution path.

Once those two call graphs are established, we can produce the **exact patch surface**—files, classes, methods, tests, and invariants—without guessing.

---

## Move from the conceptual map to the **exact repository verification plan**

The previous stages established what must be true. Now the audit should become mechanical: **trace concrete symbols and refuse to infer missing evidence.**

### Verification order

```text
1. KernelRuntime.execute()
2. KernelRuntime.stream_execute()
3. ExecuteStep
4. Session
5. CapabilityBroker
6. grant_profile()
7. PROFILE_TRUSTED
8. skills
9. plugins
10. pool/worker lifecycle
```

---

## 1. Start at the sink, not the policy

The most reliable audit technique is to start from the dangerous operation:

```text
KernelRuntime.execute()
```

and walk **backwards**.

For every caller, record:

```text
caller
file
public/private
trusted/untrusted
authorization check
security context
```

The resulting table should look like:

| Caller | Public? | Agent reachable? | Capability check? | Result |
|---|---:|---:|---:|---|
| bootstrap | No | No | N/A | trusted |
| ExecuteStep | Yes | Yes | ? |  |
| Session | Yes | Yes | ? |  |
| tests | No | No | N/A | test |
| plugin | ? | ? | ? |  |

This avoids accidentally missing a bypass.

---

## 2. Then inspect the streaming sink

Do the same with:

```text
KernelRuntime.stream_execute()
```

We want:

```text
stream_execute()
     ▲
     │
Authorized executor
     ▲
     │
Streaming step
     ▲
     │
Agent
```

Not:

```text
stream_execute()
     ▲
     │
HTTP streaming handler
     ▲
     │
agent
```

with an independent security implementation.

---

## 3. HTTP must not become a security exception

The server route:

```text
POST /run
```

should eventually become:

```text
HTTP request
 ↓
identity/principal
 ↓
policy
 ↓
execution context
 ↓
authorized executor
 ↓
kernel
```

The route itself should **not** be trusted merely because it is server-side code.

Otherwise:

```text
remote user
 ↓
HTTP endpoint
 ↓
raw kernel
```

becomes possible.

---

## 4. The request must never select arbitrary privilege

This is a classic anti-pattern:

```json
{
  "code": "...",
  "profile": "trusted"
}
```

If the server simply trusts that field:

```text
client → PROFILE_TRUSTED
```

the entire capability architecture collapses.

The server must derive the maximum privilege from:

```text
authenticated principal
server policy
deployment configuration
approval state
```

not from the request body.

---

## 5. Same rule for origin

Never accept:

```json
{
  "origin": "runtime"
}
```

from the agent/client.

Origin is an **internal security fact**.

It should be assigned by trusted infrastructure.

---

## 6. Capability requests should be declarative

A useful request could say:

```json
{
  "requested_capabilities": [
    "kernel.execute",
    "filesystem.read"
  ]
}
```

But the server should treat this as:

```text
REQUEST
```

not:

```text
GRANT
```

Then:

```text
requested
   ↓
policy evaluation
   ↓
allowed subset
   ↓
ExecutionContext
```

For example:

```text
requested:
  kernel.execute
  filesystem.read
  network.connect

allowed:
  kernel.execute
  filesystem.read

denied:
  network.connect
```

---

## 7. Capability narrowing should be explicit

This is a strong design:

```text
Parent:
  kernel.execute
  filesystem.read
  network.connect

Child:
  kernel.execute
  filesystem.read
```

Allowed.

But:

```text
Parent:
  kernel.execute

Child:
  kernel.execute
  network.connect
```

must be rejected.

Formally:

```text
Capabilities(child)
    ⊆
Capabilities(parent)
```

unless the child is created by a trusted authority.

---

## 8. The same invariant applies to sub-agents

If Kerno supports agent delegation:

```text
Agent A
 ↓
Agent B
```

B should inherit a restricted context.

Never:

```text
Agent A
 ↓
Agent B
 ↓
PROFILE_TRUSTED
```

unless an explicit host authorization occurs.

---

## 9. Skills should expose declared requirements

A strong design would let a skill declare:

```text
required:
    kernel.execute
    filesystem.read
```

Then the host computes:

```text
skill requirements
        ∩
agent permissions
        ↓
effective permissions
```

If the intersection is insufficient:

```text
SKILL_DENIED
```

rather than silently upgrading the agent.

---

## 10. Plugins need a stronger trust class

I'd define:

```text
PLUGIN_TRUSTED
PLUGIN_RESTRICTED
PLUGIN_AGENT
```

But **agent plugins should never become runtime plugins**.

A runtime plugin has access to infrastructure.

An agent extension should only receive the explicit capability context.

---

## 11. Audit the import boundary

Because this is Python/Jupyter, arbitrary imports are potentially equivalent to privilege escalation.

For example:

```python
import subprocess
import socket
import pathlib
import os
```

The allowlist/security policy must either:

1. actually prevent dangerous operations, or
2. run inside an environment where those operations are harmless/restricted.

Simply blocking a few import names is insufficient.

---

## 12. AST filtering must be considered defense-in-depth

If Kerno has an AST sanitizer, it should be described as:

```text
Layer 1: static filtering
Layer 2: capability authorization
Layer 3: OS isolation
```

Never:

```text
AST filter = sandbox
```

Python has too many dynamic mechanisms for an application-level blacklist to constitute a complete security boundary.

---

## 13. Resource exhaustion is a separate threat

Even code with no filesystem/network access can do:

```python
while True:
    pass
```

or:

```python
"*" * enormous_number
```

So execution policy also needs:

```text
wall-clock timeout
CPU limit
memory limit
output limit
queue limit
concurrency limit
```

This belongs in the execution context/resource policy.

---

## 14. Output is also an attack surface

A kernel can generate enormous output:

```text
print("x" * 10_000_000_000)
```

Therefore:

```text
stdout limit
stderr limit
result-size limit
stream-rate limit
```

should be enforced independently of Python-level code.

Otherwise a "safe" workload can still exhaust the service.

---

## 15. Package loading deserves a trust policy

The distinction should be:

```text
approved package
        ≠
arbitrary package
```

For production agent execution, ideally:

```text
immutable environment
+
preinstalled dependencies
```

rather than allowing:

```text
agent → pip install
```

during execution.

If dynamic packages are required, use an isolated disposable worker.

---

## 16. Kernel state must have a security identity

Every worker should conceptually carry:

```text
worker_id
execution_id
principal_id
security_profile
capabilities
created_at
```

Then logs can answer:

> Which principal ran this code inside this worker?

This becomes essential when pooling is enabled.

---

## 17. Pool reuse should have a hard security rule

For different principals:

```text
Principal A
   ↓
Worker 17
   ↓
destroy/reset
   ↓
Principal B
```

We should not rely on a vague:

```text
"reset()"
```

claim.

There should be a documented and tested reset invariant.

For hostile execution:

```text
destroy Worker 17
```

is safer.

---

## 18. The audit should produce a machine-checkable security matrix

Eventually:

```yaml
execution:
  kernel_execute:
    required: CAP_KERNEL_EXECUTE

effects:
  filesystem_read:
    required: CAP_FILESYSTEM_READ

  filesystem_write:
    required: CAP_FILESYSTEM_WRITE

  network:
    required: CAP_NETWORK_CONNECT

  process:
    required: CAP_PROCESS_SPAWN

  secrets:
    required: CAP_SECRET_READ
```

Then tests can verify that every sensitive operation has an associated capability.

This prevents new functionality from accidentally bypassing the model.

---

## 19. Add a "security boundary test"

A particularly valuable test is:

```text
Enumerate public execution entry points
        ↓
for each:
        execute benign code
        ↓
verify security context
        ↓
verify audit record
```

Then enumerate dangerous effects:

```text
filesystem
network
process
secret
package
```

and verify denial under restrictive profiles.

---

## 20. Final architecture target

```text
                 ┌─────────────┐
                 │    Agent    │
                 └──────┬──────┘
                        │
                        ▼
                ┌───────────────┐
                │ Policy / Auth │
                └───────┬───────┘
                        │
                        ▼
              ┌──────────────────┐
              │ ExecutionContext  │
              │ principal         │
              │ capabilities      │
              │ origin            │
              │ resource limits   │
              └────────┬─────────┘
                       │
                       ▼
                ┌────────────┐
                │  Executor  │
                └─────┬──────┘
                      │
               authorization
                      │
                      ▼
                ┌────────────┐
                │   Audit    │
                └─────┬──────┘
                      │
                      ▼
              ┌───────────────┐
              │ Sandbox/Worker│
              └───────┬───────┘
                      │
                      ▼
                KernelRuntime
                      │
                      ▼
                 Python/Jupyter
```

---

## The important conclusion

We're now at the point where **more conceptual architecture isn't the bottleneck**.

The next useful evidence must come from the repository itself:

```text
KernelRuntime.execute()
KernelRuntime.stream_execute()
CAP_KERNEL_EXECUTE
CapabilityBroker
grant_profile()
PROFILE_TRUSTED
Session
ExecuteStep
skills
plugins
```

The objective is to produce a concrete matrix:

```text
CALLER → KERNEL SINK → AUTHORIZATION → CAPABILITY → TRUST LEVEL
```

and then identify every row where:

```text
AUTHORIZATION = NONE
```

Those rows are the actual vulnerabilities/bypass candidates.

**After that, the work becomes implementation rather than speculation: patch only the bypasses that the call graph proves exist, add regression tests, and leave anything not externally verified explicitly marked `UNVERIFIED`.**

---

## Next phase: convert the audit into a **proof-oriented security specification**

The important shift now is from *"does Kerno have security features?"* to:

> **Can we state precise invariants that the implementation and tests must prove?**

For `arena/01a0064f-kerno`, I would define the following.

---

## K-SEC-001 — No direct agent → kernel path

### Required invariant

```text
Agent-controlled code
        │
        ├── must NOT ───────────────► KernelRuntime
        │
        ▼
authorized execution boundary
        │
        ▼
KernelRuntime
```

Any public API that can execute Python is therefore a candidate for this test.

### Test concept

```python
def test_agent_cannot_bypass_execution_boundary():
    ...
```

The test should not merely inspect class names. It should demonstrate that an agent execution request cannot invoke the raw runtime without authorization.

---

## K-SEC-002 — Kernel execution requires a capability

The invariant is:

```text
KernelRuntime execution
        requires
CAP_KERNEL_EXECUTE
```

Therefore:

```text
PROFILE_READ_ONLY
        ↓
kernel.execute()
        ↓
DENY
```

while:

```text
PROFILE_DATA_ANALYSIS
        ↓
CAP_KERNEL_EXECUTE
        ↓
kernel.execute()
        ↓
ALLOW
```

assuming that is the actual profile definition in this branch.

We should derive the exact mapping from `capabilities.py`, not invent it.

---

## K-SEC-003 — Capability grants cannot self-escalate

This is potentially more important than the capability check itself.

We want:

```text
Agent
 ↓
request capability
 ↓
broker
 ↓
policy
 ↓
grant/deny
```

Not:

```text
Agent
 ↓
grant_profile(PROFILE_TRUSTED)
 ↓
everything
```

So the test should explicitly attempt privilege escalation.

### Negative test

```python
def test_agent_cannot_grant_itself_trusted_profile():
    ...
```

Expected:

```text
CapabilityError / AuthorizationError
```

---

## K-SEC-004 — Privilege must not increase through delegation

Suppose:

```text
Parent:
    kernel.execute
```

Then:

```text
Child:
    kernel.execute
    network.connect
```

must fail.

The invariant is:

```text
effective(child)
    ⊆
effective(parent)
```

unless a trusted authority explicitly creates the child context.

This protects:

- sub-agents
- parallel tasks
- skills
- retries
- callbacks
- nested pipelines

---

## K-SEC-005 — Origin is not user-controlled

If the repository uses execution origins, the security rule should be:

```text
origin = internal execution fact
```

not:

```text
origin = request parameter
```

A request must never be able to say:

```json
{"origin":"runtime"}
```

and thereby receive trusted privileges.

---

## K-SEC-006 — Retry preserves security context

The following must be equivalent from a security perspective:

```text
attempt 1
attempt 2
attempt 3
```

The retry must preserve:

```text
principal
capabilities
origin
policy
resource budget
audit identity
```

A retry must not create a fresh unrestricted executor.

---

## K-SEC-007 — Streaming preserves security context

Streaming should use the same authorization boundary:

```text
execute()
   └── authorization

stream_execute()
   └── SAME authorization
```

Not two independent security implementations.

This is why `stream_execute()` is a high-priority sink in the repository audit.

---

## K-SEC-008 — Pool reuse cannot cross security boundaries

For a reusable worker:

```text
Worker
 ├── Principal A
 ├── reset
 └── Principal B
```

we need evidence that A's state cannot affect B.

At minimum test:

```text
Python variables
environment
cwd
filesystem
imports
temporary files
open handles
subprocesses
credentials
```

For hostile workloads, the preferred model is:

```text
Worker A → destroy
Worker B → new
```

rather than trusting a reset routine.

---

## K-SEC-009 — Secrets are independently authorized

A profile containing:

```text
CAP_KERNEL_EXECUTE
```

should not automatically imply:

```text
CAP_SECRET_READ
```

The distinction should remain:

```text
execute Python ≠ read secrets
```

The same principle applies to:

```text
network
filesystem
process
package installation
```

---

## K-SEC-010 — Capability enforcement must correspond to real effects

This is a crucial test distinction.

Suppose the broker says:

```text
NETWORK = DENIED
```

but Python can still execute:

```python
import socket
socket.create_connection(...)
```

Then the policy is only advisory.

A meaningful test therefore checks:

```text
policy → deny
       ↓
attempt effect
       ↓
effect actually fails
```

not merely:

```text
broker.authorize() == False
```

---

## K-SEC-011 — AST filtering is not the security boundary

If Kerno's sanitizer blocks:

```python
import subprocess
```

that's useful.

But the security specification should explicitly say:

```text
AST sanitizer
    =
defense in depth
```

not:

```text
AST sanitizer
    =
sandbox
```

Python's dynamic nature makes the latter unsafe as a security assumption.

---

## K-SEC-012 — Resource limits are security controls

Agent code can attack availability without accessing anything sensitive.

Examples:

```python
while True:
    pass
```

or huge memory allocation/output.

Therefore the execution policy should eventually cover:

```text
CPU
memory
wall time
stdout
stderr
result size
concurrency
disk
```

These are availability boundaries rather than authorization boundaries, but they belong in the same execution security model.

---

## 13. The security state should become explicit

A useful eventual structure is:

```python
@dataclass(frozen=True)
class ExecutionContext:
    execution_id: str
    principal_id: str
    origin: ExecutionOrigin
    capabilities: frozenset[Capability]
    resource_policy: ResourcePolicy
```

Then every execution API receives that context.

This is preferable to scattered arguments such as:

```text
allowlist=...
profile=...
trusted=...
secret_access=...
sandbox=...
```

because the security state becomes inspectable and auditable.

---

## 14. Capability narrowing

When creating a child execution:

```python
child = context.derive(
    capabilities={
        CAP_KERNEL_EXECUTE,
        CAP_FILESYSTEM_READ,
    }
)
```

the implementation should validate:

```text
child.capabilities ⊆ parent.capabilities
```

This gives us a simple invariant that can be tested automatically.

---

## 15. Audit records should be tied to the context

Every execution should produce something equivalent to:

```text
ExecutionRecord
 ├── execution_id
 ├── principal
 ├── origin
 ├── capabilities
 ├── policy
 ├── worker_id
 ├── start_time
 ├── end_time
 ├── result
 └── security_events
```

The agent should be able to see appropriate results, but it should not be able to rewrite the security record.

---

## 16. This produces a clean trust hierarchy

```text
                    HOST
                     │
             ┌───────┴───────┐
             │               │
         TRUSTED          AGENT
             │               │
             ▼               ▼
      privileged context  restricted
             │               │
             └───────┬───────┘
                     ▼
              authorized executor
                     │
                     ▼
               isolated worker
                     │
                     ▼
                  kernel
```

The crucial rule is:

> **Trust can flow downward only; agent execution cannot manufacture a higher-trust context.**

---

## 17. Repository evidence should be recorded in four states

Given your earlier emphasis on evidence discipline, I would use:

```text
CONFIRMED
```

when source/tests prove it.

```text

```

when some implementation exists but the invariant is incomplete.

```text

```

when the repository does not yet establish the claim.

```text

```

when a reproducible bypass exists.

Do **not** turn:

```text
"security class exists"
```

into:

```text
"security boundary PASS"
```

---

## 18. Proposed audit record

For every security invariant:

```yaml
id: K-SEC-001
title: No direct agent-to-kernel path
status: UNVERIFIED
evidence:
  - file: ...
    symbol: ...
    lines: ...
test:
  - ...
risk: critical
```

This makes the audit reproducible.

---

## 19. Priority order

I'd now rank the investigation:

### P0

```text
direct KernelRuntime bypass
CAP_KERNEL_EXECUTE bypass
trusted-profile self-grant
```

### P1

```text
secret exposure
worker cross-principal leakage
plugin privilege escalation
streaming bypass
```

### P2

```text
resource exhaustion
audit completeness
package policy
network destination restrictions
```

### P3

```text
documentation
developer ergonomics
policy configuration UX
```

---

## 20. What we should do next

The next stage is no longer another conceptual design pass.

We need the **symbol-level evidence table**:

```text
┌──────────────────────────┬───────────────┬──────────────┬──────────────┐
│ Sink / API               │ Caller        │ Auth check   │ Status       │
├──────────────────────────┼───────────────┼──────────────┼──────────────┤
│ KernelRuntime.execute    │ ???           │ ???          │ UNVERIFIED   │
│ KernelRuntime.stream...  │ ???           │ ???          │ UNVERIFIED   │
│ ExecuteStep              │ ???           │ ???          │ UNVERIFIED   │
│ Session                  │ ???           │ ???          │ UNVERIFIED   │
│ grant_profile             │ ???           │ ???          │ UNVERIFIED   │
│ PROFILE_TRUSTED           │ ???           │ ???          │ UNVERIFIED   │
└──────────────────────────┴───────────────┴──────────────┴──────────────┘
```

Once those rows are filled from the actual `arena/01a0064f-kerno` source, we can stop saying *"should"* and say precisely:

> **This file/method is the bypass, this is why it is reachable, this is the smallest safe fix, and this regression test proves the fix.**

That is the point where I would begin the actual patch rather than continuing architectural speculation.

---

## Switch from the security model to the **repository implementation audit**

The next phase should be much more concrete.

We have established the *required* invariants. Now we need to inspect Kerno in this order:

```text
Kernel sink
   ↓
execution abstraction
   ↓
security enforcement
   ↓
public entry points
   ↓
extensions
   ↓
worker lifecycle
```

### 1. Kernel sink

Start with every implementation of:

```text
KernelRuntime.execute()
KernelRuntime.stream_execute()
```

For each caller, classify it:

```text
TRUSTED_INTERNAL
AGENT_REACHABLE
HTTP_REACHABLE
PLUGIN_REACHABLE
SKILL_REACHABLE
TEST_ONLY
```

The first **AGENT_REACHABLE → KernelRuntime** path without a capability check is the highest-priority finding.

---

## 2. Find the real executor abstraction

We should not assume the class is named `ExecutionEngine`.

It may actually be something like:

```text
Executor
KernelExecutor
ExecutionManager
PipelineExecutor
RuntimeExecutor
KernelAdapter
```

The repository should tell us.

The important property is behavioral:

```text
Does every agent-triggered execution pass through the same object?
```

If yes, that object is the real security choke point, regardless of its name.

If no, then Kerno has multiple execution paths and each must be secured.

---

## 3. Build the actual graph

The desired graph is:

```text
                  Agent
                    │
                    ▼
             Public API
                    │
                    ▼
             Executor/Step
                    │
             ┌──────┴──────┐
             ▼             ▼
       Capability       AllowList
         Broker
             │
             └──────┬──────┘
                    ▼
               Audit/Event
                    │
                    ▼
             KernelRuntime
```

But we must be prepared to discover:

```text
Agent ───────────────► KernelRuntime
Agent ─► Pipeline ───► KernelRuntime
HTTP ────────────────► KernelRuntime
Skill ───────────────► KernelRuntime
```

If several independent routes exist, **centralization becomes the first architectural fix**.

---

## 4. `CapabilityBroker` needs two separate audits

Don't just ask whether it has `authorize()`.

Check:

### A. Can it deny?

```text
request
 ↓
authorize
 ↓
DENY
```

### B. Can callers bypass it?

```text
request
 ↓
some other API
 ↓
kernel
```

A perfectly implemented broker is irrelevant if the kernel can be reached without it.

---

## 5. Audit the profile API

For:

```text
grant_profile()
```

we need to determine:

```text
Who can call it?
```

There are three possible designs.

### Safe

```text
host configuration
 ↓
grant_profile()
```

### Conditionally safe

```text
trusted runtime
 ↓
grant_profile()
```

### Dangerous

```text
agent
 ↓
grant_profile()
```

The third case is a direct privilege-escalation vulnerability.

---

## 6. `PROFILE_TRUSTED` should have an explicit trust boundary

A good implementation might enforce:

```text
PROFILE_READ_ONLY
PROFILE_DATA_ANALYSIS
PROFILE_RESEARCH
```

as ordinary policy profiles.

But:

```text
PROFILE_TRUSTED
```

should be special.

For example:

```text
TrustedProfileFactory
       ↑
       │
host only
```

rather than:

```text
grant_profile(PROFILE_TRUSTED)
```

being universally callable.

---

## 7. The same applies to `CAP_HUMAN_APPROVAL`

If Kerno exposes:

```text
CAP_HUMAN_APPROVAL
```

the important question is:

> Who can satisfy the approval?

It must not be possible for agent code to simply produce:

```text
approved = True
```

The approval event must originate outside the untrusted execution context.

---

## 8. SecretBroker should be audited independently

The desired architecture is:

```text
Agent
  │
  ▼
Secret request
  │
  ▼
SecretBroker
  │
  ├── principal check
  ├── capability check
  ├── scope check
  └── audit
  │
  ▼
secret
```

Not:

```text
Agent
  ↓
os.environ
```

or:

```text
Agent
  ↓
filesystem
  ↓
.env
```

This is particularly important for a Python kernel.

---

## 9. A logical capability cannot protect the OS by itself

Suppose Kerno denies:

```text
CAP_FILESYSTEM_WRITE
```

The question is:

> What prevents Python from calling `open()`?

If the answer is only:

```text
AllowList
```

then the restriction may be bypassable.

For strong isolation:

```text
logical policy
       +
worker isolation
       +
OS restrictions
```

should work together.

---

## 10. Worker isolation is therefore a separate security gate

For a pooled worker:

```text
Worker #12
    │
    ├── Agent A
    │
    ├── reset
    │
    └── Agent B
```

we need evidence that A cannot leave:

```text
Python state
files
environment
imports
processes
sockets
credentials
```

behind.

For hostile workloads:

```text
Agent A
 ↓
Worker #12
 ↓
DESTROY
```

is safer than:

```text
Agent A
 ↓
reset
 ↓
Agent B
```

---

## 11. Resource limits need their own policy

Security isn't only confidentiality/integrity.

An agent can attack availability:

```python
while True:
    pass
```

or:

```python
x = bytearray(...)
```

or:

```python
print("x" * huge_size)
```

So eventually the execution context should carry:

```text
timeout
CPU
memory
output
disk
concurrency
```

limits.

---

## 12. Security context should propagate through every execution mechanism

We should test:

```text
run()
run_stream()
retry()
parallel()
skill()
plugin()
sub-agent()
pool()
HTTP
```

For every one:

```text
principal
capabilities
origin
resource policy
execution ID
```

must survive the transition.

---

## 13. The strongest invariant

I would make this the central Kerno security rule:

> **No agent-derived execution may acquire capabilities that were not present in its originating authorized execution context.**

Formally:

```text
C_child ⊆ C_parent
```

unless:

```text
TrustedAuthority.authorize(...)
```

explicitly creates the additional privilege.

This one invariant catches many subtle escalation bugs.

---

## 14. Another important invariant: execution origin

If Kerno distinguishes runtime and agent execution, then:

```text
ORIGIN_AGENT
```

should propagate automatically.

It should not be possible for:

```text
Agent → origin=RUNTIME
```

to work.

The runtime origin should be created only by trusted infrastructure.

---

## 15. Don't forget nested execution

This is an easy bypass to miss.

Imagine:

```text
Agent
 ↓
Python
 ↓
tool()
 ↓
new kernel/session
 ↓
execute()
```

The nested session must not silently reset security.

It should inherit or narrow:

```text
parent context
```

not create:

```text
new unrestricted context
```

This is exactly why the execution context should be explicit.

---

## 16. The same applies to callbacks

For:

```text
kernel
 ↓
callback
 ↓
agent tool
```

the callback must not gain runtime privileges merely because it was invoked from trusted infrastructure.

Trust should follow the **principal**, not the call stack.

---

## 17. Proposed security object model

A mature implementation could eventually have:

```python
ExecutionContext
    principal
    origin
    capabilities
    resources
    audit_id

ExecutionPolicy
    allowed_capabilities
    filesystem
    network
    process
    secrets

Executor
    execute(context, request)

Sandbox
    create(context)

ExecutionRecord
    identity
    policy
    effects
    result
```

This cleanly separates:

```text
WHO
WHAT MAY THEY DO
HOW IS IT EXECUTED
WHERE IS IT EXECUTED
WHAT HAPPENED
```

---

## 18. What the repository audit should produce

For every public API:

```text
API
 ↓
execution path
 ↓
security context
 ↓
capability check
 ↓
kernel sink
 ↓
sandbox
 ↓
audit
```

Example:

```text
Session.run()
 ↓
???
 ↓
???
 ↓
CAP_KERNEL_EXECUTE?
 ↓
KernelRuntime.execute()
 ↓
???
 ↓
ExecutionRecord?
```

The `???` entries are exactly what we need to fill from source evidence.

---

## 19. Status should remain conservative

At this stage I'd use:

```text
Security primitives          CONFIRMED
Capability vocabulary        CONFIRMED
Profiles                     CONFIRMED

Mandatory execution gate     UNVERIFIED
Kernel capability enforcement UNVERIFIED
Trusted-profile protection   UNVERIFIED
Raw-kernel exposure          UNVERIFIED
Secret isolation             UNVERIFIED
Worker isolation             UNVERIFIED
OS sandbox                   UNVERIFIED
```

This is much more defensible than declaring the system secure because the relevant classes exist.

---

## 20. Next concrete target

The next step is the **symbol-level call-site matrix**.

Start with:

```text
KernelRuntime.execute
KernelRuntime.stream_execute
```

Then walk backwards to every caller.

After that:

```text
CAP_KERNEL_EXECUTE
```

and walk forwards to the actual enforcement.

Then:

```text
grant_profile
PROFILE_TRUSTED
```

and determine whether privilege creation is host-only.

That will finally give us the answer we've been circling around:

```text
                         ┌─ authorized ──► Kernel
Agent ──► execution ─────┤
                         └─ bypass ─────► Kernel
```

**If the second branch exists, that's the patch. If it doesn't, we move to the next boundary rather than inventing one.**

---

## The audit now needs an evidence-driven **source-of-truth pass**

We should stop extending the conceptual model until the exact branch is mechanically reconciled. The repeated continuation has reached the point where another hypothetical architecture would add noise.

### The source of truth

Your repository is:

Reference: the `Abdus2023/Kerno` repository, branch `arena/01a0064f-kerno`.

For this branch, we should treat only **observed source, tests, and CI results** as evidence.

---

## Phase A — repository identity

First establish:

```text
repository = Abdus2023/Kerno
branch     = arena/01a0064f-kerno
```

and keep it separate from any other Kerno project or branch.

This matters because you explicitly said this is a **different project with the same name**.

So from this point:

```text
Kerno-A ≠ other Kerno
```

No findings from another repository should be silently transferred into this audit.

---

## Phase B — package surface

The observed security surface includes:

```text
kerno.security
├── allowlist
├── capabilities
├── sanitizer
└── secrets
```

with capability concepts including:

```text
CAP_KERNEL_EXECUTE
CAP_FILESYSTEM_READ
CAP_FILESYSTEM_WRITE
CAP_NETWORK_CONNECT
CAP_PROCESS_SPAWN
CAP_PACKAGE_IMPORT
CAP_SECRET_READ
CAP_HUMAN_APPROVAL
```

and profiles including:

```text
PROFILE_READ_ONLY
PROFILE_DATA_ANALYSIS
PROFILE_RESEARCH
PROFILE_TRUSTED
```

That is **confirmed architectural vocabulary**.

It is not yet proof that every capability reaches an enforcement point.

---

## Phase C — trace the sink

The audit should now establish every route to:

```text
KernelRuntime.execute()
```

Think of this as a reverse dependency graph:

```text
                    KernelRuntime.execute()
                              ▲
               ┌──────────────┼──────────────┐
               │              │              │
             caller A       caller B       caller C
               ▲              ▲              ▲
             step           session         server
               ▲              ▲              ▲
             agent           API            HTTP
```

Every branch gets a security classification.

---

## Phase D — trace the capability forward

Then reverse direction:

```text
CAP_KERNEL_EXECUTE
        │
        ▼
CapabilityBroker
        │
        ▼
authorization
        │
        ▼
execution API
        │
        ▼
KernelRuntime.execute()
```

The two graphs must meet.

### Strong evidence

```text
caller → authorization → kernel
```

### Weak evidence

```text
capability exists
```

### Failure

```text
caller → kernel
```

with no authorization.

---

## Phase E — establish the **single choke-point invariant**

There are two acceptable architectures.

### Architecture 1 — centralized

```text
all execution
      │
      ▼
   Executor
      │
      ▼
authorization
      │
      ▼
    kernel
```

### Architecture 2 — multiple explicitly secured boundaries

```text
Session ─────► secured executor ──► kernel

HTTP ────────► secured executor ──► kernel

Skill ───────► secured executor ──► kernel
```

What we do **not** want is:

```text
Session ─────────► kernel
HTTP ────────────► secured executor
Skill ───────────► kernel
```

because security then depends on which API happened to be used.

---

## Phase F — test the public API surface

The audit shouldn't only inspect internal classes.

For every public method capable of executing code:

```text
run()
execute()
stream()
submit()
eval()
notebook()
skill()
tool()
```

ask:

```text
Can an untrusted caller reach Python?
        │
        ├── NO → irrelevant
        │
        └── YES
             │
             ▼
       authorization?
             │
          ┌──┴──┐
          YES    NO
           │      │
         continue P0
```

This catches "forgotten" convenience APIs.

---

## Phase G — HTTP boundary

If the branch exposes an HTTP service, the security identity must be derived before execution.

Correct:

```text
HTTP request
     │
     ▼
authentication
     │
     ▼
authorization
     │
     ▼
ExecutionContext
     │
     ▼
kernel
```

Dangerous:

```text
HTTP request
     │
     ▼
code
     │
     ▼
kernel
```

And especially dangerous:

```json
{
  "code": "...",
  "profile": "trusted"
}
```

if `profile` is accepted as an authoritative grant.

---

## Phase H — custom pipelines

This is one of the highest-value tests.

Suppose the framework permits:

```python
pipeline = CustomPipeline(...)
```

The audit must determine whether custom code can inject:

```text
KernelRuntime
```

directly.

If yes:

```text
default path secure
custom path insecure
```

is still a real vulnerability.

Framework extensibility must not become a privilege boundary bypass.

---

## Phase I — skills

Classify skills into:

```text
HOST_TRUSTED
USER_TRUSTED
AGENT_GENERATED
```

The last category should inherit the agent context.

A generated skill must not be able to say:

```text
"I am now trusted."
```

---

## Phase J — plugins

Plugins are more privileged.

The repository should make the distinction explicit:

```text
plugin loading
     ≠
agent execution
```

A plugin with runtime access should require host-level trust.

An agent should not be able to dynamically load arbitrary Python as a trusted plugin.

---

## Phase K — `PROFILE_TRUSTED`

This deserves its own gate:

```text
K-SEC-TRUST-001
```

### Requirement

```text
Untrusted caller
      ↓
PROFILE_TRUSTED
      ↓
DENY
```

unless a trusted authority explicitly delegates it.

This prevents the classic:

```text
"I need more permissions"
        ↓
grant_profile(TRUSTED)
```

escalation.

---

## Phase L — origin

If origin is part of Kerno's model, define:

```text
AGENT
RUNTIME
SYSTEM
```

or whatever the branch actually implements.

Then enforce:

```text
agent code
    ≠
runtime authority
```

The origin must be generated by trusted infrastructure.

---

## Phase M — resource isolation

After authorization is proven, inspect the worker itself.

For untrusted code:

```text
filesystem
network
process
memory
CPU
time
output
```

must have enforceable limits.

A logical capability system does not automatically provide those.

---

## Phase N — pooling

The pool needs a security invariant:

```text
worker security context
       =
current execution context
```

and after reuse:

```text
previous principal
       ≠
new principal's state
```

For hostile workloads, destruction is preferable:

```text
execute
  ↓
destroy
```

rather than:

```text
execute
  ↓
reset
  ↓
reuse
```

unless reset isolation is actually demonstrated.

---

## Phase O — tests

The final test suite should contain both **positive and negative** tests.

### Positive

```text
authorized kernel execution → succeeds
authorized filesystem read → succeeds
```

### Negative

```text
unauthorized kernel execution → denied
filesystem write → denied
network → denied
process spawn → denied
secret read → denied
trusted profile → denied
```

And importantly:

```text
DENIED
  ↓
no side effect
```

not merely:

```text
DENIED log emitted
```

---

## Phase P — evidence levels

Given the evidence discipline you've used throughout the other projects, I recommend this exact vocabulary:

| State | Meaning |
|---|---|
| **CONFIRMED** | Source/test directly establishes it |
| **PARTIAL** | Implementation exists but invariant incomplete |
| **UNVERIFIED** | We haven't established it |
| **FAILED** | Reproducible violation |
| **FIXED — UNVERIFIED** | Patch exists but execution evidence is missing |
| **PASS — CI EVIDENCE** | Actual CI/test execution proves it |

This prevents the recurring mistake of confusing:

```text
code written
```

with:

```text
behavior verified
```

---

## The resulting audit ledger

We can now maintain:

```text
K-SEC-001  Agent→Kernel boundary       UNVERIFIED
K-SEC-002  CAP_KERNEL_EXECUTE          UNVERIFIED
K-SEC-003  No self-grant               UNVERIFIED
K-SEC-004  Privilege monotonicity      UNVERIFIED
K-SEC-005  Origin integrity             UNVERIFIED
K-SEC-006  Retry inheritance             UNVERIFIED
K-SEC-007  Streaming inheritance         UNVERIFIED
K-SEC-008  Pool isolation                UNVERIFIED
K-SEC-009  Secret separation             UNVERIFIED
K-SEC-010  Effect enforcement             UNVERIFIED
K-SEC-011  AST defense-in-depth            CONFIRMED/PARTIAL
K-SEC-012  Resource controls               UNVERIFIED
```

The exact statuses should be changed only when the corresponding source/test evidence is observed.

---

## The key change from the earlier analysis

We should **not keep designing a hypothetical `ExecutionEngine`**.

The next operation is to discover what `arena/01a0064f-kerno` **actually calls**.

The decisive evidence chain is:

```text
KernelRuntime.execute()
       ▲
       │
   ALL callers
       │
       ▲
public execution APIs
       │
       ▲
agent / HTTP / skill / plugin
```

and independently:

```text
CAP_KERNEL_EXECUTE
       │
       ▼
CapabilityBroker
       │
       ▼
actual authorization call
       │
       ▼
execution sink
```

### If those graphs converge:

Kerno has a genuine capability enforcement architecture.

### If they don't:

the gap between them is the actual security vulnerability.

That is the next point at which we should make a code change.

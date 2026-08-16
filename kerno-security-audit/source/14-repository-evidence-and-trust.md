# 14 — Repository Evidence And Trust

## We now have concrete repository evidence

This pass changes the assessment materially because we can now inspect the **actual execution sink and kernel-pool implementation** in the branch you specified.

Reference: the `Abdus2023/Kerno` repository, branch `arena/01a0064f-kerno`.

The repository's recent history also shows this branch/project has already received substantial work: the latest commit is **"Enrich skill library and improve kernel reliability (#2)"**, following the large Parts I–XI scaffold.  <sup>[source]</sup>

And now we can identify several **concrete security findings**, rather than hypothetical ones.

---

## 1. P0 finding: `KernelRuntime` itself has no authorization boundary

The most important fact in `kerno/kernel/runtime.py` is that `KernelRuntime` directly creates a Jupyter kernel:

```text
KernelRuntime.start()
    ↓
jupyter_client.KernelManager
    ↓
start_kernel()
```

and `execute()` directly calls:

```text
self._kc.execute(code)
```

There is no capability check, approval check, or security-context parameter in the constructor or `execute()` API.So conceptually:

```text
caller
  ↓
KernelRuntime(...)
  ↓
start()
  ↓
execute(code)
  ↓
Python
```

is already an execution path.

### Security consequence

The allowlist is **not structurally mandatory** at the lowest execution sink.

That means our earlier invariant:

```text
every execution → policy → capability → worker
```

is **not established by the runtime API itself**.

### Severity

**P0 architectural security gap** if `KernelRuntime` is reachable by an untrusted caller.

---

## 2. The allowlist exists, but it is caller-enforced

The `AllowList` documentation says it is safe to call before every `kernel.execute()` call.That wording is significant.

It means:

```text
AllowList
   ↓
caller responsibility
   ↓
KernelRuntime.execute()
```

rather than:

```text
KernelRuntime
   ↓
mandatory policy
   ↓
execute
```

The latter is considerably stronger.

---

## 3. This gives us the first concrete sink matrix entry

| Sink | Direct execution | Policy intrinsically enforced? | Finding |
|---|---|---|---|
| `KernelRuntime.execute()` | Yes | **No** | **P0** |
| `KernelRuntime.execute_silent()` | Yes, via `execute()` | inherited | **P0 dependency** |
| `KernelRuntime.stream_execute()` | **Yes** | **No visible AllowList check** | **P0** |
| `KernelRuntime.reset_namespace()` | via `execute()` | inherited | **P0 dependency** |
| `KernelRuntime.memory_mb()` | via `execute_silent()` | inherited | **P0 dependency** |
| `KernelPool._bootstrap()` | via `runtime.execute()` | **No visible policy gate** | **P0/P1** |

The especially interesting row is `stream_execute()`.

---

## 4. `stream_execute()` is a second execution route

`KernelRuntime.execute()` and `KernelRuntime.stream_execute()` are separate paths.

`stream_execute()` does:

```text
assert running
   ↓
self._kc.execute(code)
   ↓
stream(...)
```

with no visible allowlist invocation.Therefore, even if the normal caller does:

```text
AllowList.check(code)
KernelRuntime.execute(code)
```

that does **not automatically secure**:

```text
AllowList.check(code)
KernelRuntime.stream_execute(code)
```

unless every caller separately enforces the same policy.

This is exactly why security checks should be placed at the authoritative sink.

---

## 5. P0: two execution APIs mean two enforcement paths

We now have:

```text
                 KernelRuntime
                      │
             ┌────────┴────────┐
             ▼                 ▼
         execute()       stream_execute()
             │                 │
             ▼                 ▼
        Jupyter execute   Jupyter execute
```

The desired architecture is:

```text
             ExecutionService
                    │
             mandatory policy
                    │
             mandatory capability
                    │
             mandatory sandbox
                    │
              KernelRuntime
                    │
                    ▼
                Jupyter
```

---

## 6. The kernel runtime also exposes `execute_silent()`

This is less severe because it delegates to:

```text
execute(...)
```

but it reinforces the architectural issue.

We have multiple public execution surfaces:

```text
execute
execute_silent
stream_execute
```

A future contributor can easily add another.

The security contract should therefore be:

> **There is exactly one authoritative execution gate.**

All variants must pass through it.

---

## 7. More serious: `KernelRuntime` can be instantiated directly

The constructor accepts:

```text
kernel_name
startup_timeout
kernel_id
timeout_policy
```

but no:

```text
security_profile
capability_set
policy
sandbox
```So the runtime doesn't know what security domain it belongs to.

That makes it impossible for `KernelRuntime` itself to enforce:

```text
network = off
filesystem = restricted
process = disabled
```

---

## 8. This is the architectural split we need to fix

Currently:

```text
KernelRuntime
    =
Jupyter process manager + executor
```

It should become:

```text
KernelRuntime
    =
low-level worker interface
```

while:

```text
ExecutionService
    =
authorization + capability + worker lifecycle
```

Then only the trusted control plane should be able to obtain the low-level runtime handle.

---

## 9. P0 finding: the pool reuses workers after a soft reset

This is now directly confirmed in `kerno/kernel/pool.py`.

After a normal task:

```text
release(task_id, reason="complete")
```

the pool starts:

```text
_soft_reset(pk)
```

which does:

```text
runtime.reset_namespace()
_bootstrap(runtime)
```

and returns the **same process** to the available queue.So:

```text
Task A
 ↓
Worker W
 ↓
soft reset
 ↓
Task B
 ↓
Worker W
```

---

## 10. Why this matters

`%reset -f` clears the user namespace.

It does **not mean the Python process has been recreated**.

The same process retains things such as:

```text
sys.modules
process identity
environment
open descriptors
threads
native-library state
Jupyter internals
runtime state
```

Therefore:

```text
namespace reset ≠ security reset
```

This directly confirms the concern we raised earlier.

---

## 11. The pool's own comments recognize contamination

Interestingly, `KernelPool` explicitly lists:

> "Kernel contamination between tasks (state leaks)"

as a problem it intends to solve.But the implementation's normal solution is:

```text
soft reset
```

rather than:

```text
destroy process
+
create new isolated worker
```

For trusted workloads, that can be perfectly reasonable.

For hostile multi-tenant workloads, it is not enough.

---

## 12. P0/P1: no trust-domain key exists in the pool

`KernelPool.acquire()` takes:

```text
task_id
```

not:

```text
tenant
trust_domain
security_profile
capability_ceiling
```

The available queue therefore contains generic kernels.

Conceptually:

```text
available:
    W1
    W2
    W3
```

rather than:

```text
available:
    W1 = tenant A / readonly
    W2 = tenant A / networked
    W3 = tenant B / readonly
```---

## 13. This creates a missing security dimension

Current pool identity:

```text
kernel_id
task_id
```

Required security identity:

```text
kernel_id
generation
tenant
principal
trust_domain
security_profile
capability_ceiling
```

The latter is what allows safe reuse decisions.

---

## 14. The pool's `restart()` is especially interesting

The pool explicitly supports:

```text
restart(task_id)
```

and says:

> "The same KernelRuntime object survives (generation increments)."That is useful operationally.

But security-wise:

```text
same process
same object
new generation
```

must not automatically be interpreted as:

```text
new trust boundary
```

A generation number provides **provenance**, not containment.

---

## 15. Generation ≠ isolation

This is a key distinction.

Current:

```text
generation 1
    ↓ restart
generation 2
```

Good for:

```text
"this is a new kernel lifecycle"
```

But it does not prove:

```text
"no state from generation 1 survived"
```

For security isolation, the process itself must be replaced.

---

## 16. `KernelRuntime.restart()` uses Jupyter's restart

The implementation calls:

```text
self._km.restart_kernel()
```

then waits for readiness and increments `_generation`.This likely gives a new kernel process, which is substantially better than `%reset`.

But it still isn't an **OS sandbox**.

A restarted process can still have exactly the same host privileges.

---

## 17. Therefore we have three different concepts

Kerno should explicitly distinguish:

```text
RESET
RESTART
RECREATE
```

### RESET

```text
same process
clear namespace
```

### RESTART

```text
new Python/Jupyter process
same host security context
```

### RECREATE

```text
new sandbox
new process
new security context
```

For untrusted execution:

**RECREATE is the important operation.**

---

## 18. Another concrete issue: `_bootstrap()` executes arbitrary file contents

`KernelPool._bootstrap()` does:

```text
path.read_text()
    ↓
runtime.execute(code)
```

The source file is therefore executable code, not merely configuration.And importantly:

```text
_bootstrap()
```

does not visibly call:

```text
AllowList.check()
```

before execution.

---

## 19. This creates a second P0/P1 sink

The path is:

```text
KernelPool
   ↓
_bootstrap()
   ↓
read_text()
   ↓
runtime.execute(code)
   ↓
Jupyter
```

The code being executed is treated as trusted bootstrap material.

That may be acceptable **if and only if** `skills_path` is an administrator-controlled trusted artifact.

But that trust assumption needs to be explicit and enforced.

---

## 20. `skills_path` is therefore a trust boundary

The constructor accepts:

```text
skills_path
```

as an arbitrary string.The code checks:

```text
path.exists()
```

then executes its entire contents.

There is no visible:

```text
signature verification
hash verification
manifest verification
ownership check
capability declaration
```

---

## 21. Skill bootstrap needs two modes

### Trusted bootstrap

```text
administrator-owned
signed/verified
immutable
```

can run as privileged initialization.

### Untrusted/dynamic skill

must go through:

```text
manifest
integrity
capabilities
policy
sandbox
```

before execution.

These should not share the same code path without a trust distinction.

---

## 22. Another concrete concern: the memory monitor executes Python

`PooledKernel._safe_memory()` calls:

```text
runtime.memory_mb
```

and `memory_mb` executes:

```python
import psutil, os
...
```

inside the kernel.So even a seemingly administrative operation:

```text
health check
```

causes code execution inside the worker.

This is a subtle but important finding.

---

## 23. Monitoring is therefore another execution path

We previously classified:

```text
agent → execute
```

but the repository also contains:

```text
pool monitor
   ↓
memory_mb()
   ↓
execute_silent()
   ↓
execute()
   ↓
Jupyter
```

This isn't necessarily exploitable by itself, but it demonstrates why the execution sink must be centralized.

**Every execution path must use the same policy machinery, including internal monitoring.**

---

## 24. `memory_mb()` also assumes `psutil` is available

The kernel executes:

```text
import psutil, os
```

regardless of the configured AllowList.

That becomes problematic if we later enforce:

```text
untrusted worker
stdlib/import restrictions
```

because internal monitoring and agent code would then share the same import environment.

This reinforces the need for:

```text
control-plane telemetry
```

outside the untrusted kernel.

---

## 25. Better memory measurement

Instead of asking the worker:

```text
"tell me your RSS"
```

the trusted host controller should measure:

```text
worker PID
    ↓
OS/process metrics
```

Then:

```text
untrusted Python
```

doesn't need:

```text
psutil
os
```

at all.

That's cleaner and more secure.

---

## 26. Resource enforcement is currently monitoring-oriented

The pool has:

```text
MAX_CELLS
MAX_LIFETIME
MAX_MEMORY
```

but `MAX_MEMORY` is checked through Python-level measurement.This means the implementation currently has:

```text
resource observation
```

rather than necessarily:

```text
hard OS resource enforcement
```

Those are different.

---

## 27. `MAX_MEMORY` is not a hard 4 GB limit

The code says:

```text
MAX_MEMORY = 4096 MB
```

but the mechanism is:

```text
check RSS
 ↓
if > 4096
 ↓
retire
```

Therefore the worker can potentially exceed 4 GB before the monitor observes it.

The real invariant isn't:

```text
RSS ≤ 4 GB
```

It's:

```text
RSS is periodically observed and eventually triggers retirement
```

That's weaker.

---

## 28. Same issue with lifetime

`MAX_LIFETIME` is:

```text
3600 seconds
```

but expiration is checked periodically.

So it isn't:

```text
hard one-hour maximum
```

It's:

```text
retirement eligibility after approximately one hour
```

That's perfectly acceptable operationally, but should be documented accurately.

---

## 29. Same issue with cells

`MAX_CELLS = 200` is a lifecycle retirement threshold.

It isn't an execution-level guarantee that:

```text
cell #201
```

cannot run.

The pool checks health before acquisition / monitoring, rather than enforcing a strict capability at the execution sink.

Again:

```text
policy threshold
≠
hard security boundary
```

---

## 30. The timeout ladder is better

The runtime's timeout escalation is more robust.

It attempts:

```text
soft interrupt
   ↓
grace period
   ↓
process kill
   ↓
restart
```

and the implementation explicitly uses the kernel process handle when escalating.That's a good operational design.

But it still needs to be connected to the security worker lifecycle.

---

## 31. Security consequence of `proc.kill()`

If a worker has spawned children, killing only the kernel process may not necessarily guarantee that every descendant is gone.

Therefore the security requirement should be:

```text
worker process group / sandbox
       ↓
terminate
       ↓
all descendants gone
```

not merely:

```text
kernel PID killed
```

This is another reason an OS-level worker supervisor is preferable.

---

## 32. Updated finding table

We now have concrete evidence for:

| Finding | Severity | Evidence |
|---|---:|---|
| `KernelRuntime.execute()` has no intrinsic authorization | **P0** | `runtime.py` |
| `stream_execute()` is a separate execution sink | **P0** | `runtime.py` |
| Pool performs soft-reset reuse | **P0/P1** for hostile isolation | `pool.py` |
| Pool has no tenant/trust/profile key | **P0/P1** for multi-tenant isolation | `pool.py` |
| Skill bootstrap directly executes file contents | **P1/P0 depending trust source** | `pool.py` |
| Bootstrap has no visible integrity verification | **P1** | `pool.py` |
| Memory telemetry executes code in worker | **P1** | `runtime.py` |
| Resource limits are monitoring/retirement thresholds | **P1** | `pool.py` |
| Generation is provenance, not isolation | **P1** | `runtime.py` |
| Python AllowList is not the OS boundary | **P0 design requirement** | `allowlist.py` |

---

## 33. The biggest architectural correction

The target shouldn't be:

```text
AllowList
    ↓
KernelRuntime
```

It should be:

```text
                ExecutionService
                       │
              ┌────────┴────────┐
              │                 │
           Policy          Capability
              │                 │
              └────────┬────────┘
                       ▼
                WorkerFactory
                       │
                SecurityProfile
                       │
                       ▼
                Sandbox Worker
                       │
                       ▼
                 KernelRuntime
                       │
                       ▼
                    Jupyter
```

---

## 34. `KernelRuntime` should become deliberately dumb

Its responsibilities should be:

```text
start
execute
stream
interrupt
restart
shutdown
state
```

It should **not** decide:

```text
who is authorized
which tenant
which capabilities
which filesystem
which network
which skill
```

Those belong above it.

But the runtime should also be inaccessible to untrusted code.

---

## 35. Introduce an execution gate

Conceptually:

```python
ExecutionService.execute(
    context=ExecutionContext,
    code=code,
)
```

Then:

```text
ExecutionService
 ├── validate context
 ├── resolve policy
 ├── authorize capabilities
 ├── select/create worker
 ├── enforce sandbox
 ├── execute
 ├── collect result
 └── record effect
```

All execution routes—including streaming—must converge here.

---

## 36. The low-level API can remain internal

For compatibility, Kerno can keep:

```python
KernelRuntime.execute(...)
```

but document it as:

> **trusted internal API; not a security boundary.**

Then production-facing APIs use:

```python
ExecutionService
```

This is less disruptive than immediately deleting the existing runtime interface.

---

## 37. Pool should be changed from generic to profile-aware

Current:

```text
KernelPool
  ↓
KernelRuntime[]
```

Target:

```text
KernelPool
  ↓
WorkerPoolKey
    ├── trust_domain
    ├── security_profile
    ├── tenant_scope
    └── capability_ceiling
```

Then acquisition becomes conceptually:

```text
acquire(task, security_context)
```

rather than:

```text
acquire(task_id)
```

---

## 38. For untrusted workloads, default to no reuse

The safest initial implementation is:

```text
trusted:
    reuse

untrusted:
    create → execute → destroy
```

Only after adversarial testing should we consider isolated worker reuse.

This gives Kerno a simple security baseline.

---

## 39. Soft reset remains useful

Don't delete it.

Use it for:

```text
trusted internal workloads
```

where performance matters.

But don't call it:

```text
security isolation
```

Call it:

```text
state reset
```

That terminology prevents future architectural confusion.

---

## 40. The next audit target is now very specific

We've confirmed the first execution sink.

Next we need to trace:

```text
SkillRegistry
       ↓
skill bootstrap
       ↓
Skill execution
       ↓
ExecutionEngine / loops
       ↓
KernelRuntime
```

The key files already visible in the repository include:

- `kerno/skills/registry.py`
- `kerno/kernel/runtime.py`
- `kerno/kernel/pool.py`
- loop implementations
- `kerno/compose.py`
- notebook continuation
- the package entry points.1turn68file8turn68file7turn68file4turn68file

The next pass should determine **whether the higher-level agent/skill APIs actually enforce policy before reaching these low-level sinks**.

That will let us classify the current architecture precisely as:

```text
GREEN  = gated end-to-end
YELLOW = caller-enforced
RED    = reachable without required authorization
GRAY   = not yet proven
```

### Current evidence-based status

**The project has a substantial security architecture, but the low-level execution primitive is currently more privileged than the policy layer.** The most important remediation is therefore **not another regex in `AllowList`**.

It is to establish a **single mandatory execution gate** and make the Jupyter worker lifecycle/security profile authoritative above `KernelRuntime`.

That is the first real architectural P0.

---

## SkillRegistry reveals another important trust-boundary problem

The next layer is `kerno/skills/registry.py`. This is particularly important because it sits directly between **skill loading** and the kernel execution primitive.

The branch is the one you specified: Reference: the `Abdus2023/Kerno` repository, branch `arena/01a0064f-kerno`.

---

## 1. `SkillRegistry.load_file()` is itself an execution gateway

The implementation is explicit:

```text
load_file(kernel, path)
    ↓
Path(path)
    ↓
read_text()
    ↓
kernel.execute(code)
```

The file contents are executed directly in the supplied kernel.So the actual path is:

```text
SkillRegistry
      │
      ▼
read arbitrary Python file
      │
      ▼
KernelRuntime.execute()
      │
      ▼
Jupyter
      │
      ▼
Python
```

There is **no authorization parameter** and no capability context.

---

## 2. `load_code()` is even more direct

`load_code()` accepts:

```python
code: str
```

and immediately executes it:

```text
load_code(code)
      ↓
kernel.execute(code)
```

Again, there is no visible:

```text
policy
capability
approval
sandbox profile
```

between the caller and execution.Therefore we now have at least:

```text
E1-01 KernelRuntime.execute()
E1-02 KernelRuntime.stream_execute()
E1-03 SkillRegistry.load_file()
E1-04 SkillRegistry.load_code()
E1-05 KernelPool._bootstrap()
```

all converging on the same low-level execution primitive.

---

## 3. Important distinction: `load_code()` is not necessarily a vulnerability

This needs careful wording.

A function like:

```python
registry.load_code(kernel, code)
```

may legitimately be a **trusted control-plane API**.

The problem is that the code currently doesn't make that trust boundary explicit.

There is no type such as:

```text
TrustedSkillSource
```

or:

```text
SkillExecutionContext
```

or:

```text
CapabilityContext
```

that tells us:

> "Only the trusted controller may invoke this."

So this is currently best classified as:

**P0/P1 architectural boundary gap**, not automatically "remote code execution vulnerability."

---

## 4. The registry records hashes — but the hash is not an authorization mechanism

This is good:

```text
code
 ↓
SHA-256
 ↓
code_hash
 ↓
SkillRecord
```

The registry records:

```text
name
source_file
signature
docstring
code_hash
```That gives useful provenance.

But:

```text
hashing code
```

doesn't mean:

```text
authorizing code
```

These are different properties.

---

## 5. Current sequence is backwards for security

Current:

```text
read code
   ↓
EXECUTE code
   ↓
record hash
```

A stronger design is:

```text
read code
   ↓
hash
   ↓
verify source/integrity
   ↓
resolve declared capabilities
   ↓
authorize
   ↓
create appropriate worker
   ↓
execute
   ↓
record execution
```

The hash becomes part of the decision.

---

## 6. Dynamic skills are therefore especially important

`load_code()` labels dynamic code as:

```text
source_file = "<dynamic>"
```

and records the caller-provided `name`.This is useful for provenance.

But there is currently no visible distinction between:

```text
administrator-approved dynamic skill
```

and:

```text
LLM-generated arbitrary code
```

Both become:

```text
SkillRegistry.load_code(...)
```

---

## 7. That is a critical semantic distinction

Kerno needs at least two concepts:

```text
Skill
```

and:

```text
Arbitrary Code
```

They should not automatically be equivalent.

A skill should have:

```text
identity
version
source
integrity
capabilities
approval
lifecycle
```

while arbitrary code should default to:

```text
untrusted
ephemeral
minimal capability
isolated worker
```

---

## 8. Current registry is mostly a namespace manager

The file's own description says the registry:

- tracks what was loaded
- prevents accidental shadowing
- makes skills introspectable
- provides a manifest.That's useful.

But it means its primary security feature is currently **namespace integrity**, not **execution authorization**.

Those should remain separate concepts.

---

## 9. The protection mechanism is not a sandbox

The registry injects:

```python
class _ProtectedNamespace(dict):
    ...
```

and replaces the IPython namespace class.

Its purpose is:

```text
prevent:
foo = malicious_replacement
```

for protected skill names.

That's valuable against accidental or deliberate **shadowing**.

But it doesn't prevent:

```python
import os
os.system(...)
```

or:

```python
open(...)
```

or:

```python
import socket
```

or arbitrary Python execution.

So:

```text
namespace protection
≠
execution isolation
```

---

## 10. Another important problem: protection is installed by executing code

`_install_protection()` itself calls:

```text
kernel.execute(_PROTECTION_CODE)
```

then:

```text
kernel.execute("_KERNO_PROTECTED.update(...)")
```So even the security mechanism itself travels through the same unrestricted execution sink.

This reinforces the need for a trusted execution controller.

---

## 11. The registry therefore creates a recursive trust dependency

Current structure:

```text
KernelRuntime.execute()
       │
       ▼
SkillRegistry security mechanism
       │
       ▼
KernelRuntime.execute()
```

The security feature depends on the same primitive it is supposed to protect.

That's not inherently wrong, but it means the real boundary must be **outside the Python kernel**.

---

## 12. `check_integrity()` deserves a separate finding

The implementation attempts to verify a skill with:

```text
str(name)
   ↓
sha256(...)
```

and compares that against the original:

```text
record.code_hash
```But these aren't necessarily hashes of the same thing.

At registration:

```text
code_hash = SHA256(source code)
```

At integrity check:

```text
SHA256(str(current runtime object))
```

Those are fundamentally different representations.

---

## 13. Therefore the current integrity check is semantically suspect

Example:

```text
source:
def foo(x):
    return x + 1
```

Registration hash:

```text
SHA256(source_text)
```

Later:

```text
str(foo)
```

might look like:

```text
<function foo at 0x...>
```

The two hashes cannot meaningfully match.

So this isn't a reliable source-integrity comparison.

### Finding

**P1 — `SkillRegistry.check_integrity()` does not appear to compare equivalent representations.**

It needs a repository-level test to confirm the exact runtime behavior, but statically this is a strong defect.

---

## 14. Better integrity model

Don't hash:

```text
str(function)
```

Instead preserve the original source hash:

```text
SkillRecord
    source_hash
```

and verify against the **source artifact**.

For example:

```text
registered:
    source_file
    source_hash

verification:
    read source_file
    hash source_file
    compare
```

For dynamic code:

```text
dynamic skill
    source_blob
    source_hash
```

The immutable source should remain available for verification.

---

## 15. Better still: identity hash + content hash

Use:

```text
skill_id
skill_version
content_hash
```

For example:

```text
documents
1.2.0
sha256:...
```

Then a record becomes:

```text
SkillIdentity {
    id
    version
    source_hash
}
```

This gives deterministic provenance.

---

## 16. The registry currently allows arbitrary file paths

`load_file()` accepts:

```text
path: str
```

then:

```text
Path(path).read_text()
```If an untrusted caller can reach this API, they effectively receive:

```text
read arbitrary host file
+
execute arbitrary host file
```

That is extremely powerful.

Again, the vulnerability depends on **who can call the API**.

Therefore this is a critical question for the next pass:

> **Is `SkillRegistry` reachable from the agent-facing API?**

If yes, severity rises dramatically.

---

## 17. This is now our next trace target

We need to trace:

```text
Agent / Composer
       ↓
SkillRegistry
       ↓
load_file / load_code
       ↓
KernelRuntime
```

Specifically:

```text
Who constructs SkillRegistry?
Who gets a reference to it?
Who can call load_file()?
Who can call load_code()?
Can an LLM-generated action reach either?
```

That is more important than adding new security features right now.

---

## 18. The composer is likely a key boundary

The repository contains:

```text
kerno/skills/composer.py
```

and the registry search shows it alongside the registry itself.The composer should be examined for a possible path like:

```text
compose(...)
    ↓
load_code(...)
    ↓
execute(...)
```

If that path is reachable from agent-controlled input, we have a much more concrete attack surface.

---

## 19. Skill loading should ultimately look like this

```text
                Skill Request
                     │
                     ▼
              Skill Resolver
                     │
             ┌───────┴───────┐
             ▼               ▼
          Trusted         Dynamic
           Skill            Code
             │               │
             ▼               ▼
        verify hash       isolate
             │               │
             └───────┬───────┘
                     ▼
              Capability Set
                     │
                     ▼
                 Policy
                     │
                     ▼
              Worker Factory
                     │
                     ▼
                KernelRuntime
```

---

## 20. Don't let `SkillRegistry` become the policy engine

The registry should answer:

```text
"What skills exist?"
```

and:

```text
"What is their identity?"
```

The policy engine should answer:

```text
"May this principal execute this skill?"
```

The worker factory should answer:

```text
"Where can this skill execute?"
```

The kernel runtime should answer:

```text
"How do I communicate with the Python worker?"
```

This separation is much easier to audit.

---

## 21. Updated trust architecture

We can now describe Kerno more precisely:

```text
                 CONTROL PLANE

 Principal
    │
    ▼
 Policy ─────── Capability
    │                │
    └───────┬────────┘
            ▼
       Skill Resolver
            │
            ▼
       Worker Factory
            │
            ▼

                 DATA PLANE

       ┌───────────────────┐
       │   isolated worker │
       │                   │
       │    Jupyter        │
       │       │           │
       │    Python         │
       │       │           │
       │    Skill code     │
       └───────────────────┘
```

The **registry belongs in the control plane**, not inside the security boundary of the Python worker.

---

## 22. One particularly important rule

Never allow:

```text
Python worker
   ↓
SkillRegistry
   ↓
new skill
   ↓
execute
```

because then code inside the sandbox can potentially manipulate the mechanism that decides what gets loaded next.

Instead:

```text
Controller
   ↓
SkillRegistry
   ↓
authorize
   ↓
new worker
   ↓
load skill
```

The worker should be the **consumer** of an already-authorized skill, not the authority that grants itself another skill.

---

## 23. Dynamic code should be disposable

For:

```text
load_code(...)
```

the safest model is:

```text
dynamic code
   ↓
new untrusted worker
   ↓
execute
   ↓
collect result
   ↓
destroy worker
```

rather than:

```text
dynamic code
   ↓
shared long-lived worker
   ↓
future trusted skill
```

This prevents dynamic code from contaminating future execution contexts.

---

## 24. The current protection mechanism actually highlights this problem

The registry tries to prevent skill names being overwritten.

But a malicious dynamic program could simply use a new name:

```python
evil_skill = ...
```

Namespace protection doesn't prevent that.

Therefore:

```text
protected namespace
```

is useful for integrity of **known skills**, but doesn't solve **code admission control**.

---

## 25. Recommended SkillRecord evolution

Current:

```text
SkillRecord
    name
    source_file
    signature
    docstring
    code_hash
```

Target:

```text
SkillRecord
    id
    version
    source
    source_hash
    dependencies
    capabilities
    trust_level
    approval
    created_at
    revoked_at
```

Not all fields need implementation immediately.

The crucial additions are:

```text
source_hash
capabilities
trust_level
approval
```

---

## 26. Trust levels

A simple initial enum:

```text
TRUSTED
APPROVED
UNTRUSTED
REVOKED
```

Then:

```text
TRUSTED
    → normal worker reuse allowed

APPROVED
    → constrained sandbox

UNTRUSTED
    → ephemeral isolated worker

REVOKED
    → execution denied
```

This makes worker-pool policy much clearer.

---

## 27. Revocation becomes straightforward

If:

```text
skill_hash = X
```

is compromised:

```text
registry.revoke(X)
```

then:

```text
new execution → DENY
existing worker → drain
future worker → don't preload
```

This is much stronger than merely changing a namespace name.

---

## 28. The next major audit question

We have now reached the point where the **agent-facing composition layer** matters most.

The next source paths to inspect are:

```text
kerno/skills/composer.py
kerno/compose.py
kerno/_run.py
kerno/__init__.py
```

The repository search confirms these are present on the branch.8turn71file9turn71file10turn71file

The goal is to trace:

```text
USER / AGENT INPUT
       ↓
planner/composer
       ↓
skill selection
       ↓
skill loading
       ↓
kernel execution
```

---

## 29. What we want to prove next

There are only three possible outcomes.

### A — Strong

```text
Agent
 ↓
authorized composer
 ↓
authorized skill
 ↓
isolated worker
 ↓
kernel
```

**GREEN**

### B — Caller-dependent

```text
Agent
 ↓
composer
 ↓
skill
 ↓
kernel
```

with some checks performed only by certain callers.

**YELLOW**

### C — Bypass

```text
Agent-controlled input
 ↓
load_code/load_file
 ↓
KernelRuntime
 ↓
Python
```

with no mandatory authorization.

**RED / P0**

---

## Current audit position

The repository evidence has now moved us from a generic architectural discussion to a concrete chain:

```text
KernelRuntime
      ▲
      │
KernelPool
      ▲
      │
SkillRegistry
      ▲
      │
?????
```

We have established that:

1. **`KernelRuntime` is an unrestricted execution primitive.**
2. **`KernelPool` can reuse a worker through namespace reset.**
3. **`KernelPool` bootstrap executes Python directly.**
4. **`SkillRegistry.load_file()` executes arbitrary file contents.**
5. **`SkillRegistry.load_code()` executes arbitrary supplied code.**
6. **Skill hashing provides provenance, but current integrity verification appears logically mismatched.**
7. **Namespace protection is useful anti-shadowing logic, but is not a security sandbox.**
8. **The decisive unanswered question is whether the agent/composer layer can reach these APIs without a mandatory authorization boundary.**

That is the next branch of the audit: **follow the call graph upward until we reach the actual public/agent entry point.**

---

## The public `Session` path confirms the bypass

We now have the missing upper layer, and this changes the confidence level substantially.

The concrete path is:

```text
Session.run()
   │
   ├── KernelRuntime()
   │
   ├── AllowList → injected into kernel
   │
   ├── _load_skills()
   │
   └── Pipeline
         │
         ▼
      loop
         │
         ▼
      kernel.execute()
```

This is directly visible in `kerno/compose.py`.---

## 1. The biggest finding: `Session` does not make security mandatory

`Session.with_security()` merely stores:

```python
self._allowlist = allowlist
```

It is optional.Then `run()` does:

```text
if self._allowlist:
    ...
```

So this is legal:

```python
Session() \
    .with_llm(llm) \
    .with_kernel() \
    .run("...")
```

with **no security object configured**.

That means the public high-level API can construct and start a kernel without an explicit security policy.

### Status: **P0**

Not because every caller is malicious, but because the security model is **opt-in instead of fail-closed**.

---

## 2. Worse: the allowlist is installed by executing generated Python

`Session.run()` does:

```text
_allowlist.to_kernel_code()
        ↓
kernel.execute(...)
```So the security configuration itself is injected through the unrestricted execution primitive.

That gives us:

```text
Session
 ↓
KernelRuntime.execute()
 ↓
security code
```

Again, this is not necessarily exploitable, but it means the enforcement architecture is entirely dependent on **cooperative Python execution**.

---

## 3. `Session._load_skills()` contains a direct arbitrary-file execution path

This is much more concrete.

When:

```text
self._skills
```

is a string, the code does:

```text
Path(self._skills).read_text()
        ↓
kernel.execute(...)
```So:

```text
Session
  ↓
with_skills("/some/path.py")
  ↓
read file
  ↓
execute entire file
```

There is no visible:

```text
hash verification
path restriction
skill manifest
capability declaration
approval
```

before execution.

---

## 4. This confirms the earlier SkillRegistry concern

We now have **two independent arbitrary-code loading routes**:

```text
Route A

SkillRegistry.load_file()
       ↓
kernel.execute()
```

and:

```text
Route B

Session._load_skills()
       ↓
Path(...).read_text()
       ↓
kernel.execute()
```

So even if we hardened `SkillRegistry`, `Session` would still provide another route.

This is precisely why security must be enforced at the execution boundary.

---

## 5. `SkillSet.load_into()` has another route

The composer implementation does:

```text
SkillSet.load_into(kernel)
       ↓
for each skill
       ↓
reg.load_code(kernel, skill.code, ...)
```Therefore:

```text
Session
  ↓
SkillSet
  ↓
SkillRegistry.load_code
  ↓
KernelRuntime.execute
```

is yet another path.

---

## 6. Full-stack skills are especially significant

`full_stack_skills()` assembles a very large collection:

```text
data
viz
introspect
meta
ml
stats
text
nlp
timeseries
synthetic
features
quality
anomaly
report
artifacts
export
docs
filesystem
synth
network
graph
simulation
optimization
finance
experiment
llm_tools
api
web
sql
```This is important for the earlier `kerno[all]` discussion.

Installing optional dependencies is one thing.

But loading the **full skill stack into the same Python worker** is a substantially larger authority/code surface.

---

## 7. `network` and `filesystem` are first-class skills

The composer explicitly includes:

```text
filesystem
network
web
api
sql
```

in `full_stack_skills()`.Therefore the security architecture cannot simply assume:

```text
Kerno = data analysis
```

The full runtime potentially encompasses:

```text
filesystem
network
database
web
LLM tools
```

These should have explicit capability boundaries.

---

## 8. Dependencies currently express ordering, not authority

For example:

```text
nlp
  depends on
text
```

and:

```text
ml
  depends on
data + viz
```But a dependency currently means:

```text
load before me
```

not:

```text
I inherit exactly these capabilities
```

That distinction is important.

---

## 9. Dependency confusion risk

Consider:

```text
Skill A
 dependencies = ["data"]
```

The current loader interprets this as:

```text
load data first
```

It doesn't verify:

```text
which data version?
which hash?
which trust level?
which capability set?
```

The dependency graph is therefore currently a **composition graph**, not a security dependency graph.

---

## 10. `replace()` is another integrity consideration

`SkillSet.__or__()` allows:

```text
same skill name
      ↓
other skill replaces it
```That's useful composability.

But from a security perspective:

```text
trusted "data"
      ↓
replacement "data"
```

must not automatically inherit the original trust level.

A replacement should invalidate:

```text
approval
hash
capability decision
```

and require reauthorization.

---

## 11. This gives us a concrete security invariant

We need:

> **Skill identity is `(name, version, content_hash)`, not merely `name`.**

Currently the composition layer heavily uses:

```text
name
```

as the identity key.

That is sufficient for namespace management.

It isn't sufficient for security provenance.

---

## 12. The `FileSkill.code` property is another direct filesystem boundary

`FileSkill` defines:

```text
code = Path(self.path).read_text()
```So merely accessing:

```python
skill.code
```

performs a filesystem read.

That means the object model itself has side effects.

A safer design would separate:

```text
SkillDescriptor
```

from:

```text
LoadedSkillSource
```

so reading metadata doesn't unexpectedly access the filesystem.

---

## 13. More importantly, `FileSkill` has no path policy

The path can be arbitrary:

```text
FileSkill(
    name="x",
    path="/..."
)
```

There is no visible:

```text
allowed_root
```

or:

```text
trusted_source
```

So again:

```text
FileSkill
```

must only be constructible by a trusted loader or validated before execution.

---

## 14. `Session` makes the trust boundary even clearer

The API is designed around:

```text
Session()
   .with_llm(...)
   .with_kernel(...)
   .with_skills(...)
   .with_security(...)
   .run(...)
```

But the builder treats all these objects as peers.

Security shouldn't be just another optional component.

Compare:

```text
with_plugins(...)
with_memory(...)
with_security(...)
```

The API semantics imply security is a configurable feature.

For hostile execution, it must instead be a **required invariant**.

---

## 15. Better API

Instead of:

```python
Session().with_kernel()
```

allow:

```python
Session().with_execution_policy(policy)
```

but require a policy before `run()`:

```text
run()
 ↓
if no policy
 ↓
DENY
```

Even better:

```text
Session(policy=ExecutionPolicy.required(...))
```

so insecure construction is harder.

---

## 16. `with_kernel()` should not expose raw authority

Currently the caller can provide:

```python
with_kernel(kernel=...)
```This is convenient, but it allows a caller to inject an arbitrary executor.

That can be legitimate for testing.

But production APIs should distinguish:

```text
TrustedExecutor
```

from:

```text
Untrusted/ExternalExecutor
```

Otherwise the policy layer doesn't know whether the supplied executor obeys its rules.

---

## 17. The custom pipeline is another major escape hatch

`Session.with_pipeline()` says:

> "Provide a fully custom pipeline. Overrides with_loop()."This is powerful.

But the security question becomes:

```text
Can a custom Pipeline call kernel.execute()
without passing through the standard transformer chain?
```

The answer appears to be **yes in principle**, because the custom pipeline is accepted as an arbitrary object.

Therefore:

```text
with_pipeline(custom_pipeline)
```

must not be considered security-neutral.

---

## 18. This is a crucial distinction

The default pipeline does:

```text
NormalizationTransformer
+
AllowListTransformer
+
...
```

But a custom pipeline can potentially bypass:

```text
AllowListTransformer
```

because the caller supplies the entire pipeline.

So:

```text
Transformer security
```

cannot be the authoritative security boundary.

---

## 19. This is the same architectural pattern again

We now see the same problem at three layers:

### Skills

```text
SkillRegistry → kernel.execute
```

### Session

```text
_load_skills → kernel.execute
```

### Pipeline

```text
custom pipeline → potentially kernel.execute
```

Therefore security is currently distributed across **callers**.

That is the core architectural weakness.

---

## 20. The authoritative sink must be below all three

The only reliable design is:

```text
                    Session
                       │
                    Skills
                       │
                    Pipeline
                       │
                       ▼
              ExecutionController
                       │
                mandatory policy
                       │
                mandatory caps
                       │
                mandatory worker
                       │
                       ▼
                 KernelRuntime
```

No caller should be able to skip the controller.

---

## 21. The controller should wrap the executor

Conceptually:

```python
executor.execute(
    code,
    context=ExecutionContext(...)
)
```

The executor can be low-level.

But only:

```text
ExecutionController
```

can obtain it.

---

## 22. Even better: capability-scoped execution handles

Instead of giving the pipeline:

```text
KernelRuntime
```

give it:

```text
ExecutionHandle
```

whose capabilities are already restricted:

```text
handle.execute(code)
```

and internally:

```text
handle
  ↓
fixed context
  ↓
fixed worker
  ↓
policy
```

The pipeline can't replace the security context.

---

## 23. Custom pipelines then remain possible

We don't have to remove the composability feature.

Instead:

```text
Custom Pipeline
      │
      ▼
ExecutionHandle
```

rather than:

```text
Custom Pipeline
      │
      ▼
Raw KernelRuntime
```

This preserves Kerno's design philosophy.

---

## 24. The same applies to skills

A skill shouldn't receive:

```text
KernelRuntime
```

directly.

It should receive:

```text
SkillExecutionContext
```

containing only what it is authorized to use.

---

## 25. This is especially important for `full_stack_skills()`

If all 28-ish built-ins share one unrestricted Python namespace:

```text
data
viz
network
filesystem
web
sql
llm_tools
...
```

then a compromise in one skill effectively compromises the entire worker.

This is **trust-domain flattening**.

---

## 26. Trust domains should instead be explicit

For example:

```text
DATA
  data
  viz
  stats
  timeseries

DOCUMENTS
  docs
  filesystem

NETWORK
  api
  web
  network

DATABASE
  sql

AI
  llm_tools
```

The exact grouping can evolve.

The important principle is:

```text
different authority → different security profile
```

---

## 27. Full stack shouldn't mean full authority

This is the key distinction for your earlier installation question:

```bash
pip install "kerno[all]"
```

can mean:

> all optional Python packages are installed.

It should **not** mean:

> every execution capability is automatically granted.

Likewise:

```text
full_stack_skills()
```

should mean:

> all skills are available for selection.

It shouldn't mean:

> every skill is automatically authorized with every capability.

---

## 28. Proposed skill metadata

For example:

```python
@dataclass
class SkillPolicy:
    name: str
    version: str
    content_hash: str

    capabilities: frozenset[str]

    trust_level: str
    approved: bool
```

Then:

```text
SkillSet
```

becomes a catalog.

And:

```text
SkillPolicy
```

becomes the security declaration.

---

## 29. Proposed execution context

```python
@dataclass(frozen=True)
class ExecutionContext:
    session_id: str
    principal: str
    tenant: str | None

    skill_id: str
    skill_hash: str

    capabilities: frozenset[str]

    policy_version: str
    security_profile: str
```

This context should be immutable.

---

## 30. The controller performs intersection

For example:

```text
principal capabilities
        ∩
tenant capabilities
        ∩
skill requested capabilities
        ∩
security profile
        ∩
administrator policy
```

Then:

```text
effective capabilities
```

are attached to the worker.

---

## 31. A concrete example

Suppose `docs` requests:

```text
filesystem.read
```

and `network.connect`.

The administrator profile says:

```text
filesystem.read = /workspace/input
network = DENY
```

Result:

```text
filesystem.read=/workspace/input
network=DENY
```

The skill cannot expand itself.

---

## 32. `network` skill gets a different profile

For the network skill:

```text
network.connect=allowed endpoints
filesystem.read=/workspace/input
filesystem.write=DENY
process.spawn=DENY
```

That is much safer than loading everything into the same unrestricted worker.

---

## 33. The public `Session.run()` should enforce a preflight

Before starting execution:

```text
PRECHECK
  │
  ├── LLM configured?
  ├── policy configured?
  ├── skill verified?
  ├── capabilities resolved?
  ├── sandbox available?
  ├── worker profile valid?
  └── audit context created?
```

Any unknown:

```text
DENY
```

---

## 34. Importantly, sandbox failure should not degrade to unsandboxed execution

Bad:

```text
sandbox unavailable
      ↓
use ordinary KernelRuntime
```

Correct:

```text
sandbox unavailable
      ↓
FAIL CLOSED
```

This should be an explicit invariant.

---

## 35. Updated call graph

We can now draw the actual current architecture:

```text
                    Session.run()
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
       AllowList      SkillSet       Pipeline
          │              │              │
          ▼              ▼              │
    kernel.execute   SkillRegistry      │
          │              │              │
          └───────┬──────┘              │
                  ▼                     │
             KernelRuntime ◄────────────┘
                  │
                  ▼
               Jupyter
                  │
                  ▼
                Python
```

The problem is visually obvious:

**everything converges on a raw executor without a mandatory centralized authorization gate.**

---

## 36. Target architecture

```text
                    Session.run()
                         │
                         ▼
                  ExecutionController
                         │
              ┌──────────┼──────────┐
              │          │          │
           Policy      Skills     Pipeline
              │          │          │
              └──────────┼──────────┘
                         ▼
                  ExecutionContext
                         │
                         ▼
                   WorkerFactory
                         │
                         ▼
                   SecurityProfile
                         │
                         ▼
                   IsolatedWorker
                         │
                         ▼
                   KernelRuntime
                         │
                         ▼
                      Jupyter
```

---

## 37. Current findings are now stronger

| Finding | Status |
|---|---|
| Security is optional in `Session` |  **P0** |
| String skill path directly executes file |  **P0/P1** |
| `SkillRegistry.load_code()` directly executes code |  **P0/P1** |
| `SkillSet.load_into()` reaches raw execution |  **P0/P1** |
| Custom pipeline can potentially bypass transformer policy |  **P1** |
| Skill replacement keyed primarily by name |  **P1** |
| Full stack flattens many capabilities into one worker |  **P1** |
| `FileSkill` performs arbitrary path reads |  **P1** |
| Integrity hash semantics need correction |  **P1** |
| Namespace protection is not sandboxing |  **Design limitation** |

---

## 38. The most important conclusion so far

This Kerno branch is **not merely missing a few security checks**.

The deeper issue is:

> **Security currently behaves like a configurable pipeline feature, while Python execution behaves like a primitive available to multiple components.**

Those two properties are inverted for a secure execution platform.

The desired relationship is:

```text
Execution is privileged.
Security is mandatory.
Everything else is composable around that invariant.
```

---

## 39. What I would fix first

### P0-1 — Create `ExecutionController`

One authoritative execution gate.

### P0-2 — Make security mandatory

`Session.run()` must refuse to execute without an effective policy.

### P0-3 — Remove raw kernel access from untrusted components

Pass capability-scoped execution handles instead.

### P0-4 — Make skill loading pass through the controller

No direct:

```text
load_code → kernel.execute
```

### P0-5 — Separate trusted bootstrap from dynamic code

Trusted built-ins and dynamic user/LLM code must have different trust domains.

### P0-6 — Disable worker reuse for untrusted contexts

Until process/sandbox isolation is proven.

---

## Next audit target

There is now one remaining critical branch before we can close the call graph:

```text
Session
   ↓
_build_pipeline()
   ↓
make_reactive()
make_reflect()
make_plan_execute()
   ↓
LoopStep
   ↓
ExecuteStep
   ↓
kernel.execute()
```

We need to inspect those loop implementations and `ExecuteStep`.

That will answer the final question:

> **Does the actual LLM-generated code execution path pass through the same controls, or can the loop directly invoke `KernelRuntime.execute()`?**

If it directly invokes the kernel, we have a confirmed end-to-end **P0 authorization bypass**, rather than merely an architectural concern.

---

## The actual agent execution path is now confirmed

We have now reached the decisive file: `kerno/steps/execute.py`.

The result is stronger than the previous architectural concern.

## 1. `ExecuteStep` directly executes agent-generated code

The implementation is explicit:

```text
AgentState.metadata["last_code"]
          ↓
ExecuteStep.run()
          ↓
self.kernel.execute(code)
```

There is no policy check inside `ExecuteStep`.This is the actual execution step used by the pipeline.

So the real path is:

```text
LLM
 ↓
GenerateCodeStep
 ↓
TransformCodeStep(s)
 ↓
ExecuteStep
 ↓
Executor.execute()
 ↓
Jupyter/Python
```

That confirms that **the execution boundary is not owned by the security layer**.

---

## 2. The comments themselves reveal the intended architecture

`execute.py` describes `ExecuteStep` as:

> "The only step that touches the kernel."

That's actually useful.

It means the project already has the beginnings of a natural security choke point.

The problem is that this choke point currently does:

```text
code → kernel.execute()
```

instead of:

```text
code
 ↓
authorize
 ↓
capabilities
 ↓
sandbox
 ↓
kernel.execute()
```

So we don't need to redesign the entire pipeline.

**`ExecuteStep` is the ideal place to integrate the mandatory execution controller.**

---

## 3. The pipeline confirms `ExecuteStep` is composable

`Pipeline` accepts arbitrary `Step` objects:

```text
Pipeline([
    ...
    ExecuteStep(kernel),
    ...
])
```

and executes each step sequentially.This means a caller can construct:

```python
Pipeline([
    GenerateCodeStep(...),
    ExecuteStep(kernel),
])
```

without necessarily including:

```text
AllowListTransformer
```

or any other security transformer.

That's a **real bypass of pipeline-level policy**.

---

## 4. This confirms our previous suspicion about custom pipelines

The `Session` API allows a custom pipeline.

The `Pipeline` class itself doesn't enforce security.

And `ExecuteStep` directly calls:

```text
self.kernel.execute(...)
```

Therefore:

```text
custom pipeline
      ↓
ExecuteStep(kernel)
      ↓
raw execution
```

can bypass security components that exist elsewhere in the default pipeline.

### Finding

**P0 — security transformers are not an authoritative execution boundary.**

---

## 5. The correct security architecture is now obvious

Instead of:

```text
Pipeline
   ↓
ExecuteStep
   ↓
Executor
```

we need:

```text
Pipeline
   ↓
ExecuteStep
   ↓
ExecutionController
   ↓
Policy
   ↓
Capability check
   ↓
Worker/Sandbox
   ↓
Executor
```

Then even:

```text
custom Pipeline
```

cannot bypass policy.

---

## 6. `ExecuteStep` should not accept a raw `Executor`

Current:

```python
ExecuteStep(kernel)
```

The type is:

```text
Executor
```

and the only requirement appears to be an `.execute()` method.That is ideal for testing.

But production security needs something stronger:

```text
ExecutionHandle
```

or:

```text
ExecutionController
```

rather than a raw executor.

---

## 7. Why the interface matters

A raw executor means:

```text
anything implementing execute()
```

is trusted.

So this would satisfy the interface:

```python
class UnsafeExecutor:
    def execute(self, code, timeout=None):
        ...
```

The pipeline has no way to know whether the executor:

- enforces policy
- has a sandbox
- has network access
- has filesystem access
- belongs to another tenant
- is trusted

The type system doesn't encode the security contract.

---

## 8. Introduce two interfaces

I'd separate:

```text
Executor
```

from:

```text
AuthorizedExecutor
```

For example:

```text
Executor
    ↓
low-level execution capability

AuthorizedExecutor
    ↓
policy-bound execution capability
```

Only the latter should be accepted by `ExecuteStep` in production.

---

## 9. Even better: `ExecutionContext`

`ExecuteStep` should receive:

```text
ExecutionController
```

and the controller should own:

```text
ExecutionContext
```

containing:

```text
session_id
principal
skill
skill_hash
tenant
capabilities
security_profile
policy_version
worker_id
```

Then every execution is attributable.

---

## 10. This also fixes auditability

Currently telemetry records:

```text
step.execute
code.preview
```That's useful, but incomplete.

The security event should additionally record:

```text
execution_id
principal
session_id
skill_id
skill_hash
capabilities
worker_id
security_profile
policy_decision
```

Then you can answer:

> Who executed this code, under which policy, with which capabilities, in which worker?

---

## 11. Don't log full code by default

The current tracer includes:

```text
code.preview = code[:60]
```

This is safer than logging the entire program, but even previews can contain:

```text
API keys
tokens
personal data
SQL fragments
URLs
file paths
```

So production telemetry should prefer:

```text
code_hash
language
size
execution_id
```

and perhaps an opt-in redacted preview.

---

## 12. Another significant issue: `state.namespace = self.kernel.namespace`

After execution:

```text
state.namespace = self.kernel.namespace
```This exposes the worker namespace to the agent state.

That means the state potentially carries a reference to the live execution environment.

This deserves attention.

---

## 13. Why namespace references are dangerous

A namespace can contain:

```text
variables
objects
modules
file handles
clients
connections
credentials
models
large datasets
```

If the namespace becomes accessible outside the intended control plane, you've effectively exported part of the worker's authority.

Instead, state should contain a controlled representation:

```text
namespace_metadata
```

rather than the live mutable namespace.

---

## 14. This also creates lifecycle problems

Suppose:

```text
Worker A
 ↓
state.namespace = Worker A namespace
 ↓
Worker A retired
```

Now the state still refers to an object belonging to a dead worker.

That creates stale-state semantics.

With worker reuse, it gets worse:

```text
Worker A
 ↓
state.namespace
 ↓
reset
 ↓
Worker A reused
```

The meaning of the namespace reference changes over time.

---

## 15. Better model

Instead of:

```python
state.namespace = self.kernel.namespace
```

use:

```text
state.namespace_snapshot = {
    "names": [...],
    "types": {...},
}
```

or simply:

```text
state.metadata["defined_names"] = ...
```

If an agent needs an object, use an explicit object/reference store with lifecycle controls.

---

## 16. `ParallelStep` introduces another security issue

The pipeline supports:

```text
ParallelStep
```

which runs multiple steps concurrently using:

```text
ThreadPoolExecutor
```

and deep-copies the state.This is important because the same execution resources can potentially be shared across concurrent branches.

---

## 17. If branches share an executor, security context must be explicit

Imagine:

```text
ParallelStep
 ├── branch A
 │     ↓
 │   ExecuteStep(kernel)
 │
 └── branch B
       ↓
     ExecuteStep(kernel)
```

Now two executions can reach the same kernel.

That creates potential:

```text
race conditions
namespace contamination
interleaved execution
capability confusion
```

Jupyter kernels are not automatically a safe concurrent execution container.

---

## 18. The pipeline currently doesn't enforce serialization

`Pipeline` itself is sequential.

But `ParallelStep` deliberately introduces concurrency.

Therefore the security model must define:

```text
one worker = one active execution
```

unless the executor explicitly guarantees safe concurrent execution.

For a Jupyter kernel, the conservative rule should be:

> **Never concurrently execute two agent code cells in the same kernel.**

---

## 19. `RetryStep` is another hidden execution multiplier

`RetryStep` runs a step repeatedly:

```text
max_retries
```If that step contains:

```text
ExecuteStep
```

then one logical agent action may produce:

```text
execution #1
execution #2
execution #3
...
```

This matters for:

- side effects
- network calls
- file writes
- database mutations
- API calls
- financial operations

---

## 20. Retry must not blindly repeat side effects

Example:

```python
charge_customer()
```

fails after successfully charging but before returning.

Retry:

```text
charge_customer()
```

can charge twice.

So Kerno needs to distinguish:

```text
pure computation
```

from:

```text
side-effecting execution
```

---

## 21. Capability model helps here too

A capability can declare:

```text
idempotent = true/false
```

or:

```text
side_effect_class = NONE | REVERSIBLE | EXTERNAL
```

Then retry policy can become:

```text
pure computation → automatic retry
external side effect → require idempotency key / explicit approval
```

---

## 22. `LoopStep` creates another execution amplification factor

The default maximum is:

```text
max_iterations = 50
```A loop containing:

```text
GenerateCodeStep
ExecuteStep
```

can therefore execute up to dozens of programs.

That isn't necessarily bad.

But security budgets must be attached to the **session**, not just individual cells.

---

## 23. We need an execution budget

For example:

```text
SessionBudget
    max_cells
    max_wall_time
    max_cpu_time
    max_memory
    max_network_bytes
    max_filesystem_bytes
    max_subprocesses
```

Then:

```text
LoopStep
```

can't reset the budget simply because it starts another iteration.

---

## 24. Current `ExecuteStep.timeout` is only per execution

Default:

```text
timeout = 120 seconds
```That's useful.

But it doesn't provide:

```text
session-wide wall clock
```

For example:

```text
50 × 120 seconds
```

could theoretically become a very long-running agent.

So we need:

```text
per-cell timeout
+
per-session deadline
```

---

## 25. `DryRunExecuteStep` is a good design feature

This is actually one of the stronger pieces.

`DryRunExecuteStep` explicitly doesn't execute anything and returns a synthetic output.That gives us a natural safe mode:

```text
policy = DRY_RUN
```

before enabling actual execution.

This can become part of the security model rather than just a test convenience.

---

## 26. Recommended execution modes

I'd formalize:

```text
DRY_RUN
READ_ONLY
RESTRICTED
STANDARD
PRIVILEGED
```

with progressively stronger capabilities.

For example:

```text
DRY_RUN
    no execution

READ_ONLY
    computation
    read approved inputs

RESTRICTED
    bounded filesystem
    no network

STANDARD
    selected capabilities

PRIVILEGED
    explicit administrator approval
```

---

## 27. The current architecture already has the right composability primitive

This is important because I wouldn't recommend rewriting Kerno.

The `Step` abstraction is good:

```text
Step.run(state)
```

The `Pipeline` abstraction is good:

```text
Pipeline([...])
```

The `ExecuteStep` abstraction is good.

The problem is **where authority lives**.

We can preserve almost all of the existing architecture by changing:

```text
ExecuteStep(kernel)
```

to:

```text
ExecuteStep(execution_controller)
```

---

## 28. Proposed minimal refactor

Current:

```python
class ExecuteStep:
    def __init__(self, kernel: Executor, ...):
        self.kernel = kernel
```

Target:

```python
class ExecuteStep:
    def __init__(self, executor: AuthorizedExecutor, ...):
        self.executor = executor
```

Then:

```python
output = self.executor.execute(
    code,
    timeout=self.timeout,
)
```

The controller—not the step—owns:

```text
authorization
capabilities
sandbox
worker
audit
budgets
```

---

## 29. This preserves tests

Existing tests can use:

```text
FakeAuthorizedExecutor
```

instead of requiring a real Jupyter kernel.

So we don't need to sacrifice testability.

---

## 30. Security should be enforced twice, but with different responsibilities

A useful architecture is:

### Pre-execution

```text
ExecutionController
 ↓
policy decision
```

### At execution boundary

```text
Sandbox/worker
 ↓
OS-enforced capabilities
```

The first prevents unauthorized requests.

The second prevents a compromised Python process from escaping.

---

## 31. Python-level AllowList becomes defense-in-depth

Then the existing AllowList is still useful:

```text
Policy
 ↓
AllowList
 ↓
Python environment
```

But it is no longer the primary boundary.

If the Python code bypasses it, the OS sandbox still prevents:

```text
network
filesystem
process creation
```

as configured.

---

## 32. This gives us defense in depth

```text
Layer 1 — API
    mandatory policy

Layer 2 — skill
    identity + capabilities

Layer 3 — execution controller
    authorization

Layer 4 — worker
    isolated lifecycle

Layer 5 — OS sandbox
    actual containment

Layer 6 — telemetry
    evidence
```

That is the architecture I'd target for Kerno.

---

## 33. Current audit verdict

We can now upgrade the earlier hypothesis:

### Previously

> "There may be a way to bypass the security transformer."

### Now

> **Confirmed: `ExecuteStep` directly invokes the executor, while the pipeline framework permits arbitrary/custom pipelines. Therefore pipeline-level security transformers cannot be treated as the authoritative execution boundary.**

The evidence is directly in:

- `kerno/steps/execute.py` — direct `self.kernel.execute(...)`.- `kerno/pipeline.py` — arbitrary `Step` composition and custom pipelines.- `kerno/compose.py` — configurable/custom pipeline and optional security.---

## 34. Revised P0 list

| ID | Finding | Confidence |
|---|---|---|
| **P0-01** | `Session` can run without mandatory security policy | **Confirmed** |
| **P0-02** | `ExecuteStep` directly reaches raw executor | **Confirmed** |
| **P0-03** | Pipeline composition does not enforce security | **Confirmed** |
| **P0-04** | Custom pipeline can omit default security transformers | **Confirmed architecturally** |
| **P0-05** | Skill loading has direct execution paths | **Confirmed** |
| **P0-06** | Raw `KernelRuntime` is not a security boundary | **Confirmed** |
| **P0-07** | Untrusted worker reuse through soft reset | **Confirmed design weakness** |
| **P0-08** | No demonstrated OS-level sandbox at execution boundary | **Not yet proven absent everywhere** |

That last distinction is important: **we should not claim an OS sandbox doesn't exist somewhere else until we inspect the worker/process launch code.**

---

## 35. Next: inspect the actual executor implementations

The next critical files are now:

```text
kerno/interfaces.py
kerno/kernel/runtime.py
kerno/kernel/pool.py
kerno/streaming/executor.py
kerno/steps/generate.py
kerno/steps/transform.py
kerno/loop/*
```

Especially:

```text
Executor
GenerateCodeStep
TransformCodeStep
Loop factories
streaming executor
```

The purpose is to establish the complete:

```text
LLM output
   ↓
generated code
   ↓
transformations
   ↓
ExecuteStep
   ↓
Executor
   ↓
process
   ↓
OS
```

chain.

At that point we can produce a **Kerno Security Boundary Map** with every execution sink, every policy layer, every bypass, and a concrete P0→P1 remediation sequence rather than continuing with isolated findings.

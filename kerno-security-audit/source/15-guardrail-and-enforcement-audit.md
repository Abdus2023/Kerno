# 15 — Guardrail And Enforcement Audit

## The executor layer exposes the real boundary

We have now inspected `KernelRuntime` and `interfaces.py`. This gives us an important correction to the previous assessment.

The repository **does already have an abstraction intended for sandboxing**:

```text
Executor
 ├── KernelRuntime
 ├── DryRunExecutor
 ├── RecordingExecutor
 ├── SandboxedExecutor
 └── MockExecutor
```

That is explicitly documented in `kerno/interfaces.py`.So the architecture is **not fundamentally missing an executor abstraction**.

The problem is that the abstraction currently treats all executors as equivalent from the pipeline's point of view.

---

## 1. `Executor` is a capability interface, but not a security interface

The protocol says:

```python
class Executor(Protocol):
    def execute(self, code: str, **kwargs) -> CellOutput: ...
```

and explicitly lists:

```text
KernelRuntime
DryRunExecutor
RecordingExecutor
SandboxedExecutor
MockExecutor
```

as interchangeable implementations.This is excellent for composability.

But it creates a security ambiguity:

```text
Executor
   │
   ├── safe sandbox
   │
   └── unrestricted Jupyter
```

Both satisfy the same protocol.

Therefore:

> **Type compatibility is currently stronger than security identity.**

---

## 2. `KernelRuntime` is definitely a host-process execution primitive

The implementation creates:

```python
jupyter_client.KernelManager(kernel_name="python3")
```

then calls:

```text
start_kernel()
```This means Kerno's default execution model is a separate Jupyter kernel process.

That's good isolation compared with executing Python inside the Kerno controller process.

But it is **process isolation, not necessarily sandbox isolation**.

---

## 3. Separate process ≠ security sandbox

Current architecture:

```text
Kerno controller
      │
      │ Jupyter protocol
      ▼
Python kernel process
      │
      ├── filesystem
      ├── network
      ├── subprocess
      ├── environment
      └── Python imports
```

Nothing in `KernelRuntime.start()` itself establishes:

```text
seccomp
namespace isolation
container
AppArmor
SELinux profile
chroot
network namespace
resource cgroup
```

It simply starts the Python kernel.

Therefore we should now phrase the finding precisely:

> **`KernelRuntime` provides process separation, but the inspected implementation does not itself establish OS-level capability confinement.**

That is a much stronger and more accurate statement than simply saying "there is no sandbox."

---

## 4. The repository anticipated `SandboxedExecutor`

This is an important positive architectural signal.

The interface documentation explicitly says:

```text
SandboxedExecutor
    executes in a container
```So the project designers already recognize that:

```text
Executor
```

can be backed by a stronger isolation mechanism.

The problem is now:

> **Where is `SandboxedExecutor`, and does `Session` require it for untrusted code?**

That is the next implementation question.

---

## 5. `KernelRuntime.execute()` has no policy parameter

Its signature is essentially:

```python
execute(
    code,
    timeout=120,
    silent=False,
    cancel_event=None,
)
```There is no:

```text
capabilities
policy
principal
skill_id
security_profile
```

parameter.

That means authorization cannot happen at the `KernelRuntime` level.

This is okay **if and only if** an upper-level controller guarantees that every call is authorized.

But we've already established that `ExecuteStep` can directly call the executor.

So the security guarantee currently depends on **which executor object was injected**.

---

## 6. This is the real root problem

The system effectively says:

```text
"Give me an Executor."
```

rather than:

```text
"Give me an Executor with security profile X."
```

That's a major distinction.

For example:

```text
ExecuteStep(KernelRuntime())
```

and:

```text
ExecuteStep(SandboxedExecutor())
```

are both structurally valid.

But their security properties are radically different.

---

## 7. The fix doesn't require removing `Executor`

Keep:

```text
Executor
```

as the low-level protocol.

Add:

```text
AuthorizedExecutor
```

or:

```text
ExecutionController
```

as the security-aware interface.

For example:

```text
Executor
    ↓
raw mechanism

AuthorizedExecutor
    ↓
policy-bound mechanism
```

Then:

```text
ExecuteStep
```

should consume the latter in production.

---

## 8. `AgentState` already has a place for policy

This is another very important discovery.

`AgentState` already contains:

```text
policy_state: dict
```

with the comment:

```text
"profile, capabilities"
```So Kerno already has a conceptual location for policy information.

The missing piece is enforcing that policy at the final execution sink.

---

## 9. This is a classic "policy exists, enforcement doesn't" problem

The current flow can be viewed as:

```text
AgentState
   │
   └── policy_state
          │
          X
          │
ExecuteStep
   │
   ▼
Executor
```

The policy state travels through the system, but `KernelRuntime.execute()` doesn't consume it.

We need:

```text
AgentState.policy_state
          │
          ▼
ExecutionController
          │
          ▼
Executor
```

---

## 10. `AgentState` also has execution provenance

There is already:

```text
execution_counter
kernel_generation
kernel_state_ref
provenance
```This is actually a strong foundation.

Kerno is already trying to answer:

```text
Which execution?
Which kernel generation?
Which artifacts?
```

The security model can extend that same provenance record with:

```text
policy_id
capabilities
skill_hash
executor_type
sandbox_profile
authorization_result
```

---

## 11. This suggests the architecture was designed for the correct direction

We now have:

```text
AgentState
 ├── policy_state
 ├── execution_counter
 ├── kernel_generation
 ├── kernel_state_ref
 └── provenance
```

and:

```text
Executor
 ├── KernelRuntime
 └── SandboxedExecutor
```

Those are exactly the primitives needed.

What's missing is the **binding layer**.

---

## 12. Proposed binding

At session initialization:

```text
ExecutionPolicy
       │
       ▼
ExecutionController
       │
       ├── Executor
       ├── capabilities
       ├── budget
       ├── provenance
       └── sandbox profile
```

Then:

```text
ExecuteStep(controller)
```

rather than:

```text
ExecuteStep(kernel)
```

---

## 13. The controller can select the executor

For example:

```text
UNTRUSTED
   ↓
SandboxedExecutor

TRUSTED_ANALYTICS
   ↓
RestrictedKernelExecutor

DRY_RUN
   ↓
DryRunExecutor

TEST
   ↓
MockExecutor
```

This is much better than allowing callers to choose an arbitrary `Executor`.

---

## 14. `KernelRuntime` itself should remain dumb

I would **not** put all policy logic into `KernelRuntime`.

It should remain responsible for:

```text
start
shutdown
interrupt
restart
execute
stream
inspect
```

That's a clean responsibility.

The controller should handle:

```text
authorization
capabilities
budgets
audit
sandbox selection
worker lifecycle
```

---

## 15. `KernelRuntime` has a useful timeout escalation mechanism

There is already:

```text
interrupt
   ↓
grace period
   ↓
process.kill()
   ↓
restart
```

in `_escalate_timeout()`.That's a good resilience feature.

But it shouldn't be confused with security isolation.

Timeout escalation protects against:

```text
infinite loops
hung execution
stuck kernel
```

It doesn't protect against:

```text
malicious filesystem access
network exfiltration
credential theft
subprocess creation
```

---

## 16. The kernel process can inspect its own host process

`memory_mb` executes:

```python
psutil.Process(os.getpid())
```

inside the Python kernel.That's normal instrumentation.

But it also demonstrates that the Python kernel has normal access to its process environment.

Again:

```text
Jupyter kernel process
```

is not inherently a restricted sandbox.

---

## 17. `execute_silent()` is another execution sink

This method simply calls:

```text
execute(..., silent=True)
```That means security must cover both:

```text
execute()
execute_silent()
```

A policy implemented only around `ExecuteStep.execute()` would potentially miss internal callers of `execute_silent()`.

---

## 18. `reset_namespace()` is also execution

This:

```text
%reset -f
```

is sent through:

```text
self.execute(...)
```That's okay internally.

But it reinforces a useful invariant:

> **All kernel code execution should ultimately pass through one controlled low-level path.**

Currently that part is actually good: `execute_silent()` and `reset_namespace()` converge on `execute()`.

---

## 19. `stream_execute()` is the exception to watch

`stream_execute()` directly does:

```text
self._kc.execute(code)
```It does **not** call `self.execute()`.

Therefore there are now two low-level execution paths:

```text
KernelRuntime.execute()
        │
        ▼
      _kc.execute()

KernelRuntime.stream_execute()
        │
        ▼
      _kc.execute()
```

Any future security instrumentation added to `execute()` will **not automatically protect streaming execution**.

This is an important concrete finding.

---

## 20. Security instrumentation needs one internal primitive

I'd refactor:

```text
_execute_message()
```

or similar:

```text
_execute_raw()
```

so both:

```text
execute()
stream_execute()
```

share:

```text
state validation
generation tracking
execution ID
policy context
telemetry
timeout
cancellation
```

---

## 21. More importantly, authorization should happen above this

The clean hierarchy:

```text
ExecutionController
        │
        ▼
Authorized Executor
        │
        ▼
KernelRuntime
        │
        ▼
Jupyter
```

Then `KernelRuntime` doesn't need to know the business meaning of:

```text
filesystem.read
network.connect
```

The OS sandbox handles that.

---

## 22. The missing piece is now `SandboxedExecutor`

This is the most valuable next file to inspect.

We need to determine:

1. Does it actually exist?
2. Does it use Docker/Podman?
3. Does it use subprocess isolation?
4. Does it restrict filesystem access?
5. Does it restrict networking?
6. Does it enforce CPU/memory limits?
7. Does it kill the worker on timeout?
8. Does it expose the same `Executor` interface?
9. Is it used by `Session`?
10. Is it the default for untrusted/generated code?

Those answers determine whether the P0 findings are exploitable in practice or primarily architectural.

---

## 23. We should also inspect `streaming/executor.py`

Because:

```text
ExecuteStep
```

may not be the only consumer.

We already know the low-level runtime has:

```text
execute()
stream_execute()
```

So we need to map every caller.

The goal is a complete execution-sink inventory:

```text
                 ┌── execute()
                 │
LLM / caller ────┼── stream_execute()
                 │
                 ├── execute_silent()
                 │
                 └── reset_namespace()
```

---

## 24. Revised security map

We can now confidently draw:

```text
                    LLM
                     │
                     ▼
              GenerateCodeStep
                     │
                     ▼
             Transform Pipeline
                     │
                     ▼
                ExecuteStep
                     │
                     ▼
                Executor
                     │
          ┌──────────┴──────────┐
          │                     │
          ▼                     ▼
   KernelRuntime        SandboxedExecutor?
          │
          ▼
   Jupyter Kernel
          │
          ▼
       OS / Host
```

The unresolved box is exactly where our next investigation should concentrate.

---

## 25. Important positive findings

This audit is not only finding problems.

Kerno already has several good architectural foundations:

### Good #1 — executor abstraction

`Executor` cleanly separates execution from pipeline logic.### Good #2 — explicit sandbox concept

The interface documentation explicitly anticipates `SandboxedExecutor`.### Good #3 — policy state

`AgentState` already carries policy/profile/capability information.### Good #4 — provenance

Execution counters, kernel generation, state references and provenance already exist.### Good #5 — process lifecycle

Kernel startup, shutdown, restart, interrupt and timeout escalation are explicit.These are excellent foundations for hardening rather than rewriting.

---

## 26. The central architectural correction

I would summarize the entire audit so far as:

```text
CURRENT

Policy
  ↓
AgentState
  ↓
Pipeline
  ↓
Executor
  ↓
Kernel

                 [policy is advisory]

TARGET

Policy
  ↓
ExecutionController
  ↓
AuthorizedExecutor
  ↓
Sandboxed Worker
  ↓
Kernel

                 [policy is mandatory]
```

That is the fundamental change.

---

## 27. One subtle but important rule

Do **not** simply add:

```python
if not state.policy_state:
    raise ...
```

inside `ExecuteStep`.

That would improve the situation, but it would still allow:

```text
custom Step
   ↓
executor.execute()
```

or:

```text
custom pipeline
   ↓
KernelRuntime.execute()
```

The invariant must live **below the composability layer**.

---

## 28. The correct security invariant

> **No component outside the trusted execution controller may obtain an unrestricted execution capability.**

That is the rule I'd encode into Kerno's architecture.

Then:

```text
Pipeline
Skill
Transformer
Loop
Retry
ParallelStep
LLM
```

can remain freely composable.

But none of them receives:

```text
unrestricted KernelRuntime
```

unless explicitly operating in a trusted/internal mode.

---

## 29. Current confidence level

At this stage:

**Confirmed:**

- direct Python execution exists;
- execution is performed in a separate Jupyter process;
- the executor interface is intentionally swappable;
- pipeline execution can directly reach an executor;
- policy state exists but is not intrinsically bound to the executor;
- `stream_execute()` is a separate low-level execution path;
- process isolation exists;
- OS capability confinement has not yet been established in `KernelRuntime`.

**Not yet confirmed:**

- whether `SandboxedExecutor` exists on this branch;
- whether it is actually used by the public API;
- whether it provides genuine OS-level containment;
- whether the default deployment is secure against malicious generated Python.

---

## Next step

The next audit should therefore focus narrowly on **`SandboxedExecutor` + executor construction/selection**.

That will let us answer the decisive question:

```text
Does Kerno merely HAVE a sandbox abstraction,
or does the actual agent execution path REQUIRE one?
```

If the sandbox exists but isn't selected by default, the remediation is relatively contained.

If it doesn't exist or is only a mock/documentation concept, then the execution boundary needs a substantially stronger isolation implementation.

---

## The sandbox question is becoming much clearer

We found an important piece that changes the severity assessment.

The branch **does have a hard pre-execution guardrail system**, but it is explicitly **optional**. The production-oriented `powerful_pack()` defaults to:

```text
redact_secrets = True
hard_guardrails = False
```

and only installs `HardGuardrailPlugin` when `hard_guardrails=True`.That means we should distinguish **guardrails** from **sandboxing**.

---

## 1. What `HardGuardrailPlugin` actually provides

The plugin parses generated Python using `ast` before execution and blocks calls such as:

```text
os.system
os.popen
subprocess.*
shutil.rmtree
os.remove
os.unlink
os.rmdir
eval
exec
compile
__import__
os.kill
os._exit
exit
quit
```

It also blocks imports including:

```text
ctypes
socket
subprocess
multiprocessing
asyncio.subprocess
```This is useful.

But it is **static code filtering**, not a security sandbox.

---

## 2. This distinction is critical

The current protection looks like:

```text
Generated Python
      │
      ▼
     AST
      │
      ▼
blocked patterns?
      │
   ┌──┴──┐
   │     │
 YES     NO
   │     │
 DENY    ▼
       Python
```

A real sandbox looks more like:

```text
Generated Python
      │
      ▼
Authorized execution
      │
      ▼
Isolated process/container
      │
      ▼
OS capability restrictions
      │
      ▼
Python
```

The first is **defense-in-depth**.

The second is the actual containment boundary.

---

## 3. The biggest problem: hard guardrails are opt-in

This line is decisive:

```text
hard_guardrails: bool = False
```So:

```python
powerful_pack()
```

does **not** install the hard blocking plugin.

It installs the normal:

```text
SafetyGuardrailPlugin
```

which is described as producing static safety warnings.

Therefore we cannot treat `powerful_pack()` as a mandatory execution security boundary.

---

## 4. Even enabling hard guardrails doesn't create isolation

Suppose you do:

```python
powerful_pack(hard_guardrails=True)
```

You now have:

```text
AST analysis
+
blocked-call list
```

But Python can still perform operations that aren't in that list.

This is the fundamental limitation of blacklist-based code security.

---

## 5. Example of the conceptual problem

A blacklist may block:

```python
import subprocess
```

But secure execution cannot rely on the assumption:

```text
"subprocess is blocked, therefore the process is safe."
```

Python has a huge runtime surface:

```text
filesystem
environment
dynamic objects
imports
native extensions
process APIs
IPC
networking
resource exhaustion
```

A security boundary should therefore be enforced **outside Python**, not merely by inspecting Python syntax.

---

## 6. `__import__` blocking is useful but incomplete

The plugin blocks explicit:

```python
__import__(...)
```

and import statements for certain modules.That's good against obvious generated code.

But it doesn't prove that the interpreter cannot access capabilities through:

```text
already-imported objects
existing handles
module references
environment objects
filesystem objects
native extensions
```

Again:

> AST filtering is not equivalent to capability isolation.

---

## 7. Secret redaction is a separate concern

The same plugin pack includes:

```text
SecretRedactionPlugin
```

which attempts to remove token-like strings before code reaches the kernel.That's valuable, but it should not be confused with preventing secret access.

For example:

```text
redacting an API key in generated source
```

doesn't prevent the Python process from reading:

```text
environment variables
configuration files
mounted credentials
```

So secrets need an **OS/process-level policy** too.

---

## 8. `powerful_pack()` is best understood as an observability/guardrail pack

The builder combines:

```text
SecretRedaction
Progress
Timing
Cost
Budget
Recovery
Safety warnings
Artifact tracking
Telemetry
Quality
Checkpointing
```That's actually a good production feature set.

But its purpose is primarily:

```text
governance
+
observability
+
pre-execution checks
```

not:

```text
host-level containment
```

---

## 9. This gives us a much more precise architecture

Current:

```text
                    Agent
                      │
                      ▼
                Generated code
                      │
                      ▼
              PluginRegistry
                      │
            ┌─────────┴─────────┐
            │                   │
       HardGuardrail        SafetyGuardrail
       (optional)             (warning)
            │                   │
            └─────────┬─────────┘
                      ▼
                 Executor
                      │
                      ▼
                Jupyter kernel
```

The missing layer is:

```text
                Executor
                   │
                   ▼
          Security Controller
                   │
                   ▼
           OS-level sandbox
```

---

## 10. This also resolves an earlier ambiguity

We previously had:

> "Maybe Kerno has a `SandboxedExecutor`."

The interface documentation indeed anticipates one, but our repository search did **not** find an implementation of `SandboxedExecutor` on this branch; the search returned only the interface reference.That's significant.

So at this point:

### Confirmed

```text
SandboxedExecutor
```

is part of the **documented conceptual interface**.

### Not demonstrated

```text
SandboxedExecutor
```

is an implemented, selected production executor in this branch.

That distinction should remain explicit in the audit.

---

## 11. Therefore the default execution path remains the concern

We already established:

```text
Session
 ↓
KernelRuntime
 ↓
Jupyter Python process
```

and:

```text
ExecuteStep
 ↓
executor.execute()
```

with no mandatory security-controller layer.

Meanwhile:

```text
HardGuardrailPlugin
```

is opt-in.

Therefore the effective default architecture appears to be:

```text
LLM-generated code
       ↓
normal pipeline
       ↓
KernelRuntime
       ↓
Python process
```

with optional guardrails layered around it.

---

## 12. That is the real P0/P1 boundary

I'd now classify the findings more precisely:

### P0 — if untrusted LLM code is intended to be executed

**No demonstrated mandatory OS-level containment on the default executor path.**

### P0

**Security enforcement can be omitted because hard guardrails are optional.**

### P1

**Guardrail blacklist is not a complete security boundary even when enabled.**

### P1

**`Executor` does not encode whether the implementation is sandboxed.**

### P1

**Custom pipeline composition can potentially bypass plugin-level controls.**

---

## 13. The good news: the remediation can be incremental

We don't need to rewrite Kerno.

I would introduce:

```text
ExecutionPolicy
ExecutionController
SandboxProfile
AuthorizedExecutor
```

and retain:

```text
Executor
KernelRuntime
PluginRegistry
Pipeline
ExecuteStep
```

---

## 14. New target architecture

```text
                         Session
                            │
                            ▼
                  ExecutionController
                            │
                 ┌──────────┴──────────┐
                 │                     │
            ExecutionPolicy       PluginRegistry
                 │                     │
                 └──────────┬──────────┘
                            ▼
                    AuthorizedExecutor
                            │
              ┌─────────────┴─────────────┐
              │                           │
        DryRunExecutor              SandboxedExecutor
              │                           │
              │                     isolated worker
              │                           │
              └─────────────┬─────────────┘
                            ▼
                       Python kernel
```

---

## 15. Guardrails still remain useful

We should **not remove** `HardGuardrailPlugin`.

Instead:

```text
OS sandbox
   +
HardGuardrail
   +
AllowList
   +
SecretRedaction
   +
Budgets
   +
Telemetry
```

becomes defense in depth.

Each layer has a different job.

---

## 16. Proposed security profiles

For this project, I'd define something like:

| Profile | Python | Filesystem | Network | Processes |
|---|---|---|---|---|
| `dry-run` | no | none | none | none |
| `analysis` | yes | read approved workspace | none | none |
| `restricted` | yes | bounded R/W | allowlist | none |
| `networked` | yes | bounded | allowlist | none |
| `privileged` | explicit approval | explicit | explicit | explicit |

The exact implementation can come later.

The important thing is making the policy explicit.

---

## 17. The executor should advertise security properties

Instead of:

```python
class Executor:
    ...
```

being the only relevant type, add something like:

```text
ExecutionCapabilities
```

containing:

```text
sandboxed
network
filesystem
subprocess
native_code
max_memory
max_cpu
```

Then Kerno can refuse:

```text
untrusted code
      ↓
unverified executor
```

---

## 18. This also fixes accidental unsafe configuration

Currently it's easy conceptually to do:

```text
Session
  ↓
KernelRuntime
  ↓
LLM code
```

The safer API should make this impossible unless explicitly overridden.

For example:

```text
Session(policy=UntrustedCodePolicy(...))
```

automatically chooses:

```text
SandboxedExecutor
```

and rejects:

```text
KernelRuntime
```

as the execution backend.

---

## 19. Trusted local development can remain easy

We shouldn't make development painful.

Provide an explicit:

```text
UnsafeLocalExecutor
```

or:

```text
DeveloperKernelExecutor
```

whose name makes the risk obvious.

Then:

```text
production
    → sandbox required

tests
    → MockExecutor

dry-run
    → DryRunExecutor

local experimentation
    → DeveloperKernelExecutor
```

This is much clearer than making `KernelRuntime` silently serve every trust level.

---

## 20. Another important issue: guardrails must be fail-closed

`HardGuardrailPlugin` raises:

```text
BlockedExecution
```

when it detects a forbidden call.That's good.

But the system must ensure that:

```text
BlockedExecution
```

cannot be converted into:

```text
"skip plugin and execute anyway"
```

by a generic plugin error handler.

This is the next thing I'd verify in the plugin registry.

---

## 21. Specifically, we need to inspect `PluginRegistry`

We need to establish:

```text
on_before_cell()
       ↓
plugin exception
       ↓
does registry stop execution?
```

and distinguish:

```text
BlockedExecution
```

from:

```text
ordinary plugin exception
```

The former must be a **hard deny**.

Otherwise:

```text
hard_guardrails=True
```

could give a false sense of security.

---

## 22. There is another architectural concern with plugins

Plugins are themselves dynamically registered:

```text
extra_plugins: list[BasePlugin]
```This is good extensibility.

But if an untrusted party can inject an `extra_plugin`, they may be able to modify:

```text
before execution
after execution
state
telemetry
```

Therefore plugin registration itself belongs to the **trusted control plane**.

---

## 23. Security hierarchy should be:

```text
Administrator
     │
     ▼
ExecutionPolicy
     │
     ▼
PluginRegistry configuration
     │
     ▼
Pipeline
     │
     ▼
Generated code
```

not:

```text
Generated code / skill
       ↓
choose plugins
       ↓
choose executor
```

---

## 24. The audit is converging

We started with:

```text
"Kerno has optional extras"
```

and have now reached the much more important architecture:

```text
Kerno
 ├── Skill composition
 ├── Pipeline composition
 ├── Plugin composition
 ├── LLM-generated Python
 └── Jupyter execution
```

All four composability mechanisms ultimately converge on:

```text
EXECUTION AUTHORITY
```

That is where the project needs its strongest invariant.

---

## 25. Current Kerno security model

I'd describe the branch today as:

> **A composable agentic Python execution framework with several useful pre-execution guardrails, telemetry, budgets, provenance, and a documented sandbox abstraction—but without evidence yet that sandboxing is mandatory on the default generated-code execution path.**

That's much more accurate than calling it simply "unsafe."

---

## 26. Current audit scorecard

| Area | Assessment |
|---|---|
| Executor abstraction |  Good |
| Separate Jupyter process |  Good |
| Timeout/restart handling |  Good |
| Policy state model |  Promising |
| Provenance |  Promising |
| AST hard guardrails |  Useful defense-in-depth |
| Secret redaction |  Useful |
| Plugin architecture |  Strong composability |
| Mandatory security |  Missing/Not demonstrated |
| OS sandbox default |  Not demonstrated |
| Executor trust typing |  Weak |
| Custom pipeline security |  Weak |
| Streaming execution centralization |  Needs hardening |
| Capability enforcement |  Not yet authoritative |

---

## 27. Next decisive inspection

The next file to audit should be:

```text
kerno/plugins/registry.py
```

because it determines whether:

```text
HardGuardrailPlugin
       ↓
BlockedExecution
```

actually creates an **unbypassable pre-execution deny**.

After that:

```text
kerno/plugins/pack/guardrails.py
kerno/streaming/executor.py
kerno/kernel/pool.py
```

will complete the execution-security map.

The end goal is now very concrete:

```text
                 ┌─────────────────────┐
                 │  Execution Policy   │
                 └──────────┬──────────┘
                            │
                     mandatory
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Execution Controller│
                 └──────────┬──────────┘
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
         Guardrails      Budget        Provenance
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                 ┌─────────────────────┐
                 │ Sandboxed Executor  │
                 └──────────┬──────────┘
                            ▼
                      Jupyter/Python
                            ▼
                       OS boundary
```

**That is the architecture I would now use as the target for the Kerno branch.**

---

## Important correction: the guardrail path is fail-closed, but only when explicitly installed

I checked the actual `PluginRegistry` implementation. There is an important nuance that improves the earlier assessment.

## 1. `on_before_cell()` really can block execution

`PluginRegistry.on_before_cell()` does **not** wrap plugin exceptions in the generic `_dispatch()` error handler.

It directly calls:

```text
plugin.on_before_cell(code)
```

and lets exceptions propagate.That means the `HardGuardrailPlugin` mechanism is not merely advisory when installed.

The flow is:

```text
generated code
     ↓
on_before_cell()
     ↓
HardGuardrailPlugin
     ↓
raise BlockedExecution
     ↓
exception propagates
     ↓
execution can be stopped
```

So our previous statement needs refinement:

> **The hard guardrail mechanism itself is capable of enforcing a pre-execution deny.**

The real problem is **whether it is mandatory and comprehensive enough**.

---

## 2. There is an interesting inconsistency in `PluginRegistry`

The class-level documentation says:

> "Exceptions in plugins are caught and logged — they never interrupt the session."

But `on_before_cell()` deliberately behaves differently and propagates exceptions.So the actual semantics are:

```text
Normal plugin hooks
    ↓
best effort
    ↓
exception swallowed

Pre-execution hook
    ↓
exception propagates
    ↓
can block execution
```

That's reasonable, but the documentation should explicitly say so.

Otherwise future maintainers could "fix" the apparent inconsistency by adding exception handling to `on_before_cell()` and accidentally destroy the security gate.

---

## 3. `SafetyGuardrailPlugin` is definitely advisory by default

This is now unambiguous.

Its documentation says:

> "defense-in-depth observability"

and:

> "It intentionally does not mutate or cancel execution."So:

```text
SafetyGuardrailPlugin
```

is **not** a security boundary.

That's correct design.

---

## 4. `HardGuardrailPlugin` is the blocking layer

The separate hard plugin is therefore important.

The architecture is effectively:

```text
SafetyGuardrailPlugin
       │
       └── observe / warn

HardGuardrailPlugin
       │
       └── deny
```

This separation is actually good.

The issue is that `powerful_pack()` sets:

```text
hard_guardrails=False
```

by default.---

## 5. So the real problem is configuration, not the hook mechanism

We should replace the earlier wording:

 "Hard guardrails don't actually block."

with:

 **"Hard guardrails can block, but the production pack does not enable them by default."**

That's a materially different finding.

---

## 6. But there is still a deeper issue: blacklist completeness

Even with:

```python
hard_guardrails=True
```

the plugin is inspecting Python syntax.

Its policy contains a finite list:

```text
os.system
subprocess.run
subprocess.Popen
subprocess.call
shutil.rmtree
os.remove
os.unlink
pathlib.Path.unlink
eval
exec
compile
__import__
```

and blocks imports such as:

```text
ctypes
socket
```That's useful, but it is still a blacklist.

---

## 7. The hard guardrail should therefore be called what it is

I'd rename the conceptual category from:

```text
"Sandbox"
```

to:

```text
"Python Static Execution Guard"
```

because that's what it really is.

Then:

```text
OS sandbox
```

remains a separate security layer.

This avoids dangerous terminology like:

> "Kerno is sandboxed because HardGuardrail is enabled."

It isn't.

---

## 8. There is another subtle problem in `SafetyGuardrailPlugin`

Notice that the advisory plugin analyzes code in:

```text
on_cell_complete()
```

not:

```text
on_before_cell()
```That means its warnings happen **after execution**.

That's perfectly valid for observability, but it means it cannot be relied upon to stop dangerous code.

The distinction is:

```text
SafetyGuardrail
     ↓
AFTER execution
     ↓
"this was dangerous"
```

versus:

```text
HardGuardrail
     ↓
BEFORE execution
     ↓
"this is forbidden"
```

---

## 9. This is actually a good layered design

I'd preserve it:

```text
                 Generated code
                       │
                       ▼
              ┌─────────────────┐
              │ HardGuardrail   │
              │   PRE-EXEC      │
              └────────┬────────┘
                       │
                       ▼
                   Executor
                       │
                       ▼
                 Python kernel
                       │
                       ▼
              ┌─────────────────┐
              │ SafetyGuardrail │
              │  POST-EXEC      │
              └─────────────────┘
```

But add:

```text
OS sandbox
```

between Executor and Python.

---

## 10. The most important architectural rule now becomes simple

```text
HardGuardrail
    = code-level deny

OS sandbox
    = capability-level deny
```

They solve different problems.

---

## 11. Another issue: `HardGuardrailPlugin` needs tests against bypasses

The current implementation checks AST nodes.

That means the test suite should explicitly test:

```text
direct forbidden calls
direct forbidden imports
attribute aliases
dynamic references
existing imported objects
path construction
nested expressions
```

For example, the conceptual test categories should be:

```text
blocked:
    os.system(...)
    subprocess.run(...)
    eval(...)
    exec(...)

blocked imports:
    import socket
    import ctypes

allowed:
    pandas
    numpy
    statistics
    matplotlib
```

But tests should not assume that passing these cases proves sandbox security.

---

## 12. `path_glob_denylist` is particularly weak as a security mechanism

The policy contains:

```text
/etc/*
/root/*
/usr/*
/boot/*
```This is useful for warnings.

But a path denylist is inherently fragile.

It doesn't mean:

```text
"filesystem access is restricted to X."
```

It means:

```text
"we recognize some suspicious strings."
```

The correct security primitive is an allowlist:

```text
filesystem:
    /workspace/input
    /workspace/output
```

enforced outside the Python interpreter.

---

## 13. Same problem with network

Blocking:

```text
socket
```

isn't equivalent to:

```text
network = DENY
```

The latter should be enforced at the worker/container/network namespace level.

So the security policy should describe:

```text
network:
    DENY
```

and the sandbox should enforce it.

The Python guard can additionally detect suspicious network code.

---

## 14. The executor abstraction now becomes the key integration point

We have:

```text
Executor
```

as the generic interface.

We should evolve the implementations into explicit security classes:

```text
DeveloperKernelExecutor
SandboxedKernelExecutor
DryRunExecutor
MockExecutor
```

rather than making:

```text
KernelRuntime
```

appear equally appropriate for every trust level.

---

## 15. Suggested trust matrix

| Executor | Generated code | Filesystem | Network | Intended use |
|---|---:|---:|---:|---|
| `MockExecutor` | no | no | no | tests |
| `DryRunExecutor` | no | no | no | preview |
| `KernelRuntime` | yes | host-level | host-level | trusted development |
| `SandboxedExecutor` | yes | restricted | restricted | untrusted agent |
| `AuthorizedExecutor` | yes | policy-controlled | policy-controlled | production |

This makes the architecture much easier to reason about.

---

## 16. `KernelRuntime` should probably be renamed or explicitly marked

I would strongly consider documenting:

```text
KernelRuntime
    TRUSTED / UNSANDBOXED
```

rather than allowing users to assume:

```text
KernelRuntime = secure runtime
```

That is especially important because the project is designed to execute LLM-generated Python.

---

## 17. The plugin system itself needs a trust boundary

`powerful_pack()` accepts:

```text
extra_plugins
```That's fine for application developers.

But plugins can hook:

```text
on_before_cell
on_cell_complete
on_error
on_session_complete
on_skill_load
```Therefore plugin code is itself **trusted application code**.

It should never be loaded from the same trust domain as an untrusted skill or LLM-generated code.

---

## 18. Another positive finding: ordering is deterministic

The registry says:

```text
Plugins are called in registration order.
```And `powerful_pack()` registers:

```text
SecretRedaction
HardGuardrail (if enabled)
Progress
Timing
Cost
Budget
Recovery
Safety
Artifacts
Telemetry
Quality
...
```So when hard guardrails are enabled, their placement near the front is sensible.

---

## 19. But ordering should become an explicit invariant

Security plugins shouldn't rely on:

```text
"we happened to register first."
```

A malicious or accidental configuration could register:

```text
MutatingPlugin
```

before the guard.

The safer design is:

```text
SecurityGate
     ↓
mandatory
     ↓
all user plugins
```

rather than relying on registry ordering.

---

## 20. Recommended registry model

Separate:

```text
SecurityHooks
```

from:

```text
ApplicationPlugins
```

For example:

```text
PluginRegistry
 ├── mandatory security hooks
 └── optional plugins
```

Then `unregister()` should never be able to remove mandatory security controls.

Currently:

```text
unregister(name)
```

can remove any plugin by name.That is another reason security controls should not live in the same mutable namespace.

---

## 21. This is a subtle but important P1

Imagine:

```python
registry.unregister("hard_guardrails")
```

If that plugin is the only pre-execution blocker, the security posture silently changes.

That's unacceptable for a production security boundary.

Security configuration should be immutable after session creation—or require an explicit privileged operation.

---

## 22. Recommended session lifecycle

```text
Session creation
      ↓
Resolve security policy
      ↓
Construct authorized executor
      ↓
Freeze security configuration
      ↓
Construct plugins
      ↓
Run
      ↓
Security cannot be downgraded
```

Not:

```text
Run
 ↓
plugins can be changed
 ↓
security changes
```

---

## 23. We can now define Kerno's security invariants

I'd make these explicit in the repository.

### Invariant K1

> Untrusted generated code must never execute through an unrestricted host executor.

### Invariant K2

> Every execution must have an effective security policy.

### Invariant K3

> Hard pre-execution denial cannot be disabled through ordinary plugin registration.

### Invariant K4

> Python guardrails are defense-in-depth, never the sole sandbox.

### Invariant K5

> Filesystem/network/process restrictions must be enforced outside Python.

### Invariant K6

> Every execution carries provenance and a policy identity.

### Invariant K7

> Retry and loop operations consume the same session-wide execution budget.

### Invariant K8

> Concurrent execution must not share an unsafe kernel.

---

## 24. Current audit status after this inspection

| Component | Result |
|---|---|
| `PluginRegistry.on_before_cell()` |  Can enforce pre-execution blocking |
| `SafetyGuardrailPlugin` |  Correctly advisory |
| `HardGuardrailPlugin` |  Real blocking mechanism |
| Hard guardrail default |  Disabled |
| Plugin removal protection |  Missing |
| Plugin ordering security |  Implicit |
| AST blacklist |  Defense-in-depth only |
| Path denylist |  Advisory/limited |
| OS sandbox |  Not demonstrated |
| Raw `KernelRuntime` |  Must be trust-classified |
| Policy → executor binding |  Missing |

---

## 25. The most important correction to our running audit

We should **not** say:

> "Kerno's plugin guardrails can be bypassed because PluginRegistry swallows exceptions."

That would be incorrect for `on_before_cell()`.

The accurate statement is:

> **Ordinary plugin hooks are best-effort, but `on_before_cell()` intentionally propagates exceptions, so a hard guardrail can stop execution. The remaining weakness is that the hard guardrail is optional, mutable through the general plugin architecture, and still only a Python-level blacklist rather than OS-level containment.**0turn86file

That's the evidence-backed conclusion.

---

## Next audit target

The next useful layer is **executor construction and worker isolation**, especially:

```text
kerno/kernel/pool.py
kerno/streaming/executor.py
```

and every reference to:

```text
KernelRuntime(...)
Executor(...)
SandboxedExecutor(...)
```

The objective now is very specific:

**Determine whether Kerno ever automatically converts an untrusted execution request into an isolated worker, or whether `KernelRuntime` remains the default all-purpose backend.**

That will let us assign the final severity to the sandbox finding rather than speculating.

---

## The kernel pool reveals a second, more concrete security boundary problem

We can now move beyond the abstract `Executor` issue.

The `KernelPool` implementation confirms that Kerno is deliberately designed around **warm, reusable Python kernels**. That is good for performance, but it introduces a much more important question:

> **What exactly separates one task from the next?**

The answer is: primarily **resetting the same Python process**, not replacing it every time.---

## 1. The pool reuses live Python processes

`KernelPool` creates `KernelRuntime` instances and keeps them available:

```text
KernelPool
 ├── k-0001 → Python kernel process
 ├── k-0002 → Python kernel process
 └── k-0003 → Python kernel process
```

A task acquires one:

```text
task A
  ↓
acquire()
  ↓
k-0001
```

When it finishes:

```text
release()
  ↓
soft reset
  ↓
k-0001 becomes AVAILABLE
```So the isolation boundary is **not task → process**.

It is:

```text
task
  ↓
same process
  ↓
attempted namespace reset
```

---

## 2. Soft reset is not security isolation

The normal `"complete"` path does:

```text
runtime.reset_namespace()
```

and then reloads skills.This is useful for reducing ordinary state contamination.

But:

```text
reset namespace
```

does not mean:

```text
destroy process
destroy OS resources
destroy file descriptors
destroy subprocesses
destroy network connections
destroy native state
destroy loaded libraries
destroy modified environment
```

Therefore:

> **A soft reset is lifecycle hygiene, not a security boundary.**

This is now a concrete finding rather than a theoretical concern.

---

## 3. The pool documentation itself identifies "state leaks" as a problem

`KernelPool` explicitly says it exists partly to solve:

```text
Kernel contamination between tasks (state leaks)
```That's good engineering awareness.

But the implementation solves it primarily through:

```text
soft reset
```

rather than:

```text
process destruction
```

For benign analytics workloads, that's reasonable.

For mutually untrusted agent workloads, it is insufficient.

---

## 4. A malicious task can change process-level state

Conceptually:

```text
Task A
 ↓
Python process
 ↓
modify process state
 ↓
Task completes
 ↓
soft reset
 ↓
Task B
```

Some changes aren't naturally undone by clearing Python variables.

Examples include:

```text
environment changes
open resources
background threads
child processes
network connections
native-library state
signal handlers
filesystem side effects
```

The exact exploitability depends on what the kernel process is permitted to do, but the architectural point is firm:

**namespace reset cannot provide process isolation.**

---

## 5. The pool's "hard reset" is much better

For:

```text
error
timeout
```

the pool calls:

```text
runtime.restart()
```That replaces the kernel process.

So the lifecycle currently has:

```text
complete
   ↓
soft reset

error/timeout
   ↓
hard reset
```

This is sensible operationally.

But it means **successful malicious execution gets the weakest reset path**.

---

## 6. That's backwards from a security perspective

If Kerno ever supports untrusted code, the security rule should be:

```text
untrusted execution
    ↓
process/container lifetime
    ↓
destroy after task
```

not:

```text
untrusted execution
    ↓
soft reset
    ↓
reuse
```

The safest architecture is:

```text
Task A → Worker A → destroy
Task B → Worker B → destroy
```

while the pool can still optimize trusted workloads:

```text
Trusted Task A → Worker 1
Trusted Task B → Worker 1
Trusted Task C → Worker 1
```

---

## 7. Introduce trust-aware pooling

I'd modify the pool conceptually to:

```text
KernelPool
 ├── trusted pool
 │     └── reusable kernels
 │
 └── untrusted pool
       └── one-shot isolated workers
```

or even simpler:

```text
SecurityProfile.REUSABLE
SecurityProfile.EPHEMERAL
```

Then the policy determines lifecycle.

---

## 8. There is another significant issue: overflow

The pool supports:

```text
overflow=True
max_overflow=10
```

and creates additional kernels when the normal pool is exhausted.That's good for throughput.

But security policy must apply equally to:

```text
pre-warmed worker
```

and:

```text
overflow worker
```

Otherwise an overloaded system can accidentally switch to a weaker execution mode.

---

## 9. The pool does not itself carry a security profile

`PooledKernel` contains:

```text
runtime
kernel_id
state
created_at
task_id
tasks_served
```

and lifecycle limits.But there is no visible:

```text
security_profile
principal
capabilities
tenant
policy_id
sandbox_id
```

attached to the pooled kernel.

That's a problem for multi-trust workloads.

A kernel should have an immutable security identity.

---

## 10. Recommended `PooledKernel`

Something like:

```text
PooledKernel
 ├── kernel_id
 ├── runtime
 ├── security_profile
 ├── capability_set
 ├── tenant_id
 ├── worker_generation
 └── lifecycle
```

Then:

```text
task A requires restricted
```

cannot accidentally acquire:

```text
privileged kernel
```

---

## 11. The current `acquire(task_id)` is security-blind

It receives only:

```text
task_id
```Conceptually, it should become:

```text
acquire(
    task_id,
    security_profile,
    capabilities,
)
```

or, better:

```text
acquire(execution_context)
```

where the security context has already been authorized.

---

## 12. This connects directly to the earlier `ExecuteStep` problem

We now have two independent ways security can get lost:

```text
                 Execution
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
   ExecuteStep              KernelPool
         │                       │
    raw Executor            raw KernelRuntime
         │                       │
         └───────────┬───────────┘
                     ▼
              Python process
```

Neither layer currently demonstrates:

```text
mandatory security profile
```

Therefore the missing control must sit **above both**.

---

## 13. Streaming execution confirms another bypass path

This is particularly important.

`StreamingExecuteStep` extracts the executor directly:

```text
kernel = self.inner.kernel
```

and then, when available, calls:

```text
kernel.stream_execute(...)
```So streaming does not go through the normal:

```text
ExecuteStep.run()
```

execution path.

---

## 14. This means security logic added only to `ExecuteStep` can be bypassed

Current conceptual flow:

```text
Normal:

ExecuteStep.run()
   ↓
kernel.execute()
```

Streaming:

```text
StreamingExecuteStep.run()
   ↓
kernel.stream_execute()
```Therefore:

> **The security boundary cannot be implemented only inside `ExecuteStep`.**

It must be below both paths—or, preferably, both must use the same authorized execution controller.

---

## 15. This also confirms the earlier `stream_execute()` finding

We previously noticed that `KernelRuntime.stream_execute()` directly accesses the Jupyter kernel client.

Now we have the caller:

```text
StreamingExecuteStep
       ↓
inner.kernel
       ↓
stream_execute()
       ↓
Jupyter
```

So this isn't hypothetical.

There is an actual alternate execution route.

---

## 16. The streaming wrapper also reconstructs execution state itself

It manually performs:

```text
state.history.append(cell)
state.namespace = kernel.namespace
```This duplicates part of `ExecuteStep`'s state-update responsibility.

That creates a maintenance/security risk:

```text
ExecuteStep
    ↓
security behavior A

StreamingExecuteStep
    ↓
security behavior B
```

Over time, the two can diverge.

---

## 17. Recommended refactor

Don't create two execution implementations.

Use:

```text
ExecutionController.execute(...)
```

and:

```text
ExecutionController.stream(...)
```

Both share:

```text
authorization
policy
budget
provenance
sandbox
worker
```

Then:

```text
ExecuteStep
     ↓
controller.execute()

StreamingExecuteStep
     ↓
controller.stream()
```

---

## 18. The controller owns the kernel

The pipeline should never directly own an unrestricted:

```text
KernelRuntime
```

Instead:

```text
Pipeline
   ↓
ExecutionController
   ↓
ExecutionLease
   ↓
KernelRuntime
```

The lease can expose only:

```text
execute()
stream()
interrupt()
```

according to the authorized capabilities.

---

## 19. This is also useful for concurrency

The pool currently ensures that one `task_id` gets one kernel, but the controller can enforce:

```text
one execution lease
=
one active execution
```

Then `ParallelStep` has to explicitly request multiple authorized leases.

That prevents accidental sharing of a single Jupyter process.

---

## 20. `ParallelStep` should not share a kernel by accident

The safe model is:

```text
ParallelStep
 ├── branch A → lease A → worker A
 ├── branch B → lease B → worker B
 └── branch C → lease C → worker C
```

not:

```text
ParallelStep
 ├── branch A ─┐
 ├── branch B ─┼→ same KernelRuntime
 └── branch C ─┘
```

The latter would create namespace and concurrency hazards.

---

## 21. Kernel lifecycle limits are good, but not security limits

The pool has:

```text
MAX_CELLS = 200
MAX_LIFETIME = 3600
MAX_MEMORY = 4096 MB
```These are useful reliability controls.

But they don't enforce:

```text
CPU quota
network bandwidth
filesystem quota
process count
open-file count
syscall restrictions
```

So these should be considered:

> **worker lifecycle limits**, not a complete resource sandbox.

---

## 22. Memory monitoring is advisory

`PooledKernel.is_expired` checks:

```text
runtime.memory_mb
```

and retires the worker if it exceeds the configured threshold.That's reactive.

A process can already allocate substantial memory before the monitor notices.

For hostile workloads, actual resource limits should be imposed by:

```text
cgroups
container limits
OS resource limits
```

rather than relying solely on polling.

---

## 23. Same issue with the one-hour runaway check

The monitor says:

```text
if acquired > 3600:
    warnings.warn(...)
```Notice the wording:

```text
warnings.warn(...)
```

It doesn't interrupt the task.

So this is an operational alarm, not an enforcement mechanism.

The real execution deadline needs to be enforced by the controller/runtime.

---

## 24. We therefore have three classes of controls

This distinction should become explicit in the project:

### Enforcement

```text
OS sandbox
execution authorization
hard deny
timeouts
quotas
```

### Lifecycle management

```text
kernel pool
restart
retirement
health checks
```

### Observability

```text
warnings
telemetry
metrics
events
provenance
```

Currently some of these are mixed conceptually.

---

## 25. Security finding update

We can now make the sandbox finding more concrete:

### **P0-08 — Default execution worker is reusable and not demonstrated to be OS-isolated**

Evidence:

```text
KernelPool
    ↓
KernelRuntime
    ↓
Jupyter Python process
```

and successful tasks use:

```text
reset_namespace()
```

before the worker is returned to the pool.For untrusted generated code, this is insufficient as a security isolation model.

---

## 26. New P1 finding

### **P1-STREAM — Streaming execution bypasses the normal ExecuteStep execution path**

Evidence:

```text
StreamingExecuteStep
    ↓
inner.kernel.stream_execute()
```

rather than delegating to the normal `ExecuteStep.run()`.Any security enforcement implemented exclusively in `ExecuteStep` would therefore not automatically cover streaming.

---

## 27. New P1 finding

### **P1-POOL — Kernel pool lacks explicit security identity**

`PooledKernel` has lifecycle metadata but no visible immutable security profile/capability set.Therefore a future multi-tenant/security-aware pool needs to prevent:

```text
restricted task
      ↓
privileged reusable kernel
```

---

## 28. New P1 finding

### **P1-RESET — Soft reset is being used as task isolation**

The `"complete"` release path performs:

```text
reset_namespace()
```

rather than destroying the worker.That's perfectly reasonable for trusted workloads, but it should not be presented as a security boundary for hostile code.

---

## 29. The architecture we should target is now very clear

```text
                         Agent
                           │
                           ▼
                     Pipeline
                           │
                           ▼
                 ExecutionController
                           │
                 ┌─────────┴─────────┐
                 │                   │
              policy             budget
                 │                   │
                 └─────────┬─────────┘
                           ▼
                    ExecutionLease
                           │
                 ┌─────────┴─────────┐
                 │                   │
              execute()           stream()
                 │                   │
                 └─────────┬─────────┘
                           ▼
                    Sandbox Worker
                           │
                           ▼
                    Jupyter Kernel
                           │
                           ▼
                      OS limits
```

---

## 30. Trust-aware worker lifecycle

For **trusted** code:

```text
Pool
 ↓
reuse
 ↓
soft reset
```

For **untrusted** code:

```text
create isolated worker
 ↓
execute
 ↓
destroy worker
```

For **highly privileged** code:

```text
explicit authorization
 ↓
dedicated worker
 ↓
strict audit
 ↓
destroy
```

This gives Kerno performance without pretending that all workloads have identical trust.

---

## 31. What we have proven so far

The audit has now moved from architectural suspicion to concrete execution-path evidence:

```text
LLM/generated code
        ↓
ExecuteStep
        ↓
Executor
        ↓
KernelRuntime
        ↓
Jupyter Python process
```

and:

```text
StreamingExecuteStep
        ↓
stream_execute
        ↓
same Jupyter process
```

while:

```text
KernelPool
        ↓
reuses those processes
        ↓
soft-resets successful tasks
```0turn89file

That's the core of Kerno's execution architecture.

---

## 32. Next decisive area: how sessions actually construct pipelines and executors

We've now inspected enough low-level code that the next question is no longer "does Kerno have a sandbox abstraction?"

It is:

> **Which executor does the real public `Session`/server/API path actually instantiate?**

We need to trace:

```text
Session
 ↓
default pipeline
 ↓
executor
 ↓
KernelRuntime / pool
```

and also:

```text
server request
 ↓
Session
 ↓
execution
```

That will let us produce the **final default-path verdict** rather than only auditing individual components.

The next targets are therefore:

```text
kerno/session.py
kerno/compose.py
kerno/server/*
kerno/_run.py
```

with special attention to every occurrence of:

```text
KernelRuntime(...)
KernelPool(...)
ExecuteStep(...)
Pipeline(...)
```

At that point we'll know whether the P0 is:

**"unsafe by default in the core API"**

or the narrower:

**"unsafe only when applications choose the low-level executor directly."**

---

## The next phase is the **default-construction audit**

We have reached the point where inspecting individual components is no longer enough. The decisive question is **how the real Kerno session composes them**.

The architecture currently looks like:

```text
User / Agent
     │
     ▼
   Session
     │
     ▼
 Pipeline
     │
     ├── ExecuteStep
     │
     └── StreamingExecuteStep
             │
             ▼
          Executor
             │
             ▼
        KernelRuntime
             │
             ▼
       KernelPool / Jupyter
```

The unresolved issue is the arrow:

```text
Session
   ↓
Executor
```

If that construction defaults to an unrestricted `KernelRuntime`, then the sandbox finding becomes a **default-path problem**. If it requires an explicit executor supplied by the application, the severity is narrower.

### What the previous inspection has already established

- `HardGuardrailPlugin` can genuinely abort execution through `on_before_cell()`.
- `SafetyGuardrailPlugin` is intentionally observational.
- `hard_guardrails=False` is the default in the powerful plugin pack.
- `KernelPool` reuses successful workers through namespace reset.
- Error/timeout paths can restart the kernel.
- `StreamingExecuteStep` has its own execution route.
- No demonstrated OS-level sandbox has yet been established.
- The documented `SandboxedExecutor` has not been found as a concrete implementation on this branch.

So the next audit should trace **construction, not implementation**.

---

## 1. The key invariant we want to prove

For untrusted generated Python:

```text
untrusted code
      ↓
mandatory policy
      ↓
mandatory sandbox
      ↓
isolated worker
```

The unsafe version would be:

```text
untrusted code
      ↓
default Session
      ↓
KernelRuntime
      ↓
host Python process
```

That distinction determines the final severity.

---

## 2. We should also trace the server boundary

If Kerno exposes an HTTP/API server, the security chain must be:

```text
HTTP request
     ↓
authentication / authorization
     ↓
session
     ↓
execution policy
     ↓
sandboxed executor
```

A common failure pattern is:

```text
HTTP request
     ↓
Session()
     ↓
KernelRuntime()
```

with policy only applied later.

That would mean the security decision happens **after the dangerous capability has already been constructed**.

---

## 3. Executor construction should therefore be centralized

The ideal implementation is:

```python
executor = execution_factory.create(
    policy=policy,
    trust_level=trust_level,
)
```

rather than allowing arbitrary code to do:

```python
KernelRuntime()
```

throughout the repository.

Then we can enforce:

```text
UNTRUSTED → SandboxExecutor
TRUSTED   → KernelRuntime
TEST      → MockExecutor
DRY_RUN   → DryRunExecutor
```

from one location.

---

## 4. This also solves future plugin mistakes

The current architecture lets plugins influence execution behavior.

A centralized executor factory means plugins can observe or constrain execution, but they cannot silently replace:

```text
SandboxedExecutor
```

with:

```text
KernelRuntime
```

without an explicit privileged operation.

That should be a core invariant.

---

## 5. Another thing to inspect: session ownership of kernels

The pool currently tracks:

```text
task_id
kernel_id
state
tasks_served
```

but security identity isn't part of the visible worker identity.

The session layer should therefore establish:

```text
Session
 ├── session_id
 ├── security_policy
 ├── executor
 └── kernel_pool
```

rather than:

```text
Session
 └── generic kernel pool
```

A worker should never migrate between incompatible security domains.

---

## 6. Recommended rule

**Security profile must be stronger than pool membership.**

For example:

```text
restricted pool
    ├── worker-1
    ├── worker-2
    └── worker-3
```

and:

```text
trusted pool
    ├── worker-4
    └── worker-5
```

A restricted execution must never borrow worker-4 merely because worker-4 is idle.

---

## 7. The same applies to overflow

Earlier we saw overflow workers:

```text
max_overflow=10
```

Those workers must inherit the exact same:

```text
security profile
capabilities
resource limits
network policy
filesystem policy
```

as the original worker class.

Otherwise:

```text
normal load
    → secure worker

high load
    → fallback worker
    → weaker security
```

would be a serious architectural bug.

---

## 8. Execution policy should be immutable

Once a session begins:

```text
policy = restricted
```

should not become:

```text
policy = privileged
```

because a plugin or generated skill requested it.

The correct sequence is:

```text
request
 ↓
authorize
 ↓
construct policy
 ↓
freeze policy
 ↓
construct worker
 ↓
execute
```

Any elevation should require a separate explicit authorization event.

---

## 9. The audit should also inspect retries

This matters because Kerno has recovery/retry functionality.

Suppose:

```text
attempt 1 → restricted worker
attempt 2 → retry
```

The retry must not accidentally do:

```text
attempt 2 → new unrestricted KernelRuntime
```

The execution context must survive retries:

```text
ExecutionContext
 ├── policy
 ├── capabilities
 ├── budget
 ├── provenance
 └── worker requirements
```

Every retry consumes the same security contract.

---

## 10. Same for parallel execution

Parallel branches should inherit the parent's policy:

```text
Parent policy:
    network = DENY
    filesystem = workspace-only

       │
       ├── branch A → same restrictions
       ├── branch B → same restrictions
       └── branch C → same restrictions
```

A branch should never be able to request a broader executor merely because it runs in parallel.

---

## 11. Same for skills

A skill can contain Python or cause Python execution.

Therefore:

```text
Skill
  ↓
ExecutionContext
  ↓
policy
```

must remain attached.

The dangerous design is:

```text
Skill
  ↓
direct KernelRuntime
```

because that bypasses the session-level authorization model.

---

## 12. The final architecture should separate three things

### Capability

What can the code do?

```text
filesystem.read
filesystem.write
network.connect
process.spawn
native_code
```

### Policy

What is allowed for this execution?

```text
network = deny
filesystem = workspace
process = deny
```

### Mechanism

How is it enforced?

```text
container
namespace
seccomp
cgroup
filesystem mount
network namespace
```

These should not be conflated.

---

## 13. Where the current Kerno design is strong

The project already has excellent places to attach these concepts:

```text
AgentState.policy_state
AgentState.provenance
Executor
KernelRuntime
KernelPool
PluginRegistry
```

So the likely remediation is architectural integration rather than rewriting the entire engine.

---

## 14. Proposed data structure

Conceptually:

```python
ExecutionPolicy(
    trust="untrusted",
    filesystem="workspace",
    network="deny",
    subprocess="deny",
    native_code="deny",
    max_memory_mb=512,
    max_cpu_seconds=60,
    max_execution_seconds=120,
    worker_lifetime="ephemeral",
)
```

Then:

```python
ExecutionController(policy)
```

chooses the correct worker.

---

## 15. And the worker receives the policy

```text
ExecutionPolicy
       │
       ▼
SandboxProfile
       │
       ├── filesystem mounts
       ├── network namespace
       ├── process restrictions
       ├── CPU limit
       ├── memory limit
       └── timeout
```

The Python AST guard then becomes an additional layer:

```text
Sandbox
   +
HardGuardrail
```

rather than the sandbox substitute.

---

## 16. Recommended final execution pipeline

```text
                ┌──────────────┐
                │     Agent    │
                └──────┬───────┘
                       ▼
                ┌──────────────┐
                │    Session   │
                └──────┬───────┘
                       ▼
                ┌──────────────┐
                │ Execution    │
                │   Policy     │
                └──────┬───────┘
                       ▼
             ┌────────────────────┐
             │ ExecutionController│
             └─────────┬──────────┘
                       ▼
             ┌────────────────────┐
             │ Authorized Executor│
             └─────────┬──────────┘
                       ▼
             ┌────────────────────┐
             │   OS Sandbox      │
             └─────────┬──────────┘
                       ▼
             ┌────────────────────┐
             │ Python/Jupyter     │
             └────────────────────┘
```

Plugins sit around this flow for:

```text
guardrails
telemetry
budget
artifacts
recovery
quality
```

but **cannot replace the security decision**.

---

## 17. Current verdict

At this stage I would **not** describe the repository as fundamentally badly designed.

Quite the opposite.

Its architecture has many of the right extension points:

```text
Executor abstraction       ✓
Plugin system              ✓
Policy state               ✓
Kernel lifecycle           ✓
Pool management             ✓
Provenance                  ✓
Hard pre-execution hook     ✓
Streaming abstraction      ✓
```

The missing piece is the **authoritative security/control plane** connecting them.

---

## 18. The biggest design transition

Kerno currently thinks primarily in terms of:

```text
"How do I execute this cell?"
```

The hardened architecture needs to think:

```text
"Under which authority is this cell allowed to execute,
with which capabilities, in which worker, under which limits?"
```

That is the conceptual transition from an execution framework to a secure agent runtime.

---

## Next

The next audit should trace the actual `Session`/composition path and locate every construction of:

```text
KernelRuntime(...)
KernelPool(...)
ExecuteStep(...)
StreamingExecuteStep(...)
```

Then we can produce a **complete execution graph for branch `arena/01a0064f-kerno`**, including:

- default executor,
- default plugin pack,
- default guardrail state,
- kernel lifecycle,
- streaming path,
- retry path,
- parallel path,
- server/API path,
- and exactly where an untrusted execution can escape the intended policy.

That will be the point where we can stop saying *"not demonstrated"* and give each security finding a definitive **confirmed / not confirmed** status.

---

## We found the actual security choke point

This is the most important discovery so far.

The branch **does have an `ExecutionEngine` specifically introduced as a universal execution choke point**, and the HTTP paths actually use it. That substantially changes the previous conclusion.

The architecture is not simply:

```text
HTTP → KernelRuntime → Python
```

It is, for the server paths:

```text
HTTP
 ↓
KernelPool
 ↓
KernelRuntime
 ↓
ExecutionEngine
 ├── capability authorization
 ├── allowlist
 ├── budget
 ├── audit/provenance
 └── event logging
 ↓
pipeline
 ↓
ExecutionEngine.execute()
 ↓
Python kernel
```

The engine explicitly states invariant **K-001**:

> no agent, loop, plugin, skill, checkpoint, or subsystem may execute code except through `ExecutionEngine.execute()`.That is a major architectural improvement.

---

## 1. The server path really wraps the raw kernel

`kerno/server/security.py` defines:

```text
make_server_engine(...)
```

which constructs:

```text
ExecutionEngine(
    kernel,
    allowlist=...,
    broker=...,
)
```

and optionally wraps it again in:

```text
BudgetedExecutor
```So the server is deliberately preventing the pipeline from seeing the raw kernel.

That's exactly the direction we wanted.

---

## 2. `/run` uses the choke point

In `server/app.py`, `/run` first acquires a kernel:

```text
pool.acquire(task_id)
```

but `_execute_task()` then creates:

```text
engine = make_server_engine(...)
```

and passes:

```text
kernel = engine
```

to `make_reactive()` / `make_reflect()`.So:

```text
ExecuteStep
   ↓
ExecutionEngine
   ↓
KernelRuntime
```

rather than:

```text
ExecuteStep
   ↓
KernelRuntime
```

This confirms the K-001 design is actually wired into the synchronous HTTP path.

---

## 3. Streaming is also wrapped

This is particularly important because we previously identified streaming as a possible bypass.

The OpenAI-compatible streaming path explicitly does:

```text
engine = make_server_engine(...)
```

then:

```text
pipeline = factory(
    kernel=engine,
    ...
)
```

and finally:

```text
StreamingExecutor(pipeline)
```So the streaming path is **not automatically a raw-kernel bypass**.

That's a significant correction to our earlier P1 finding.

---

## 4. Therefore we should downgrade the previous streaming finding

Previously:

> "Streaming execution bypasses the normal security path."

Now the evidence shows:

```text
HTTP streaming
 ↓
make_server_engine()
 ↓
ExecutionEngine
 ↓
StreamingExecutor
```

So for the HTTP/OpenAI paths:

### Previous finding

 Potential bypass

### Current status

 **Not confirmed as a security bypass**

The architectural duplication still exists, but the server explicitly wraps the executor before passing it to the streaming pipeline.

---

## 5. `ExecutionEngine` is much more than an allowlist

This is a real control plane.

The engine performs:

```text
1. authorization
2. policy
3. execution
4. audit record
5. event log
```And its execution record contains:

```text
execution_id
sequence
origin
allowed
code_preview
rule
capabilities
action_id
effects
duration_ms
had_error
timestamp
```That's a strong foundation for traceability.

---

## 6. Capability authorization is fail-closed in an important case

The engine explicitly handles:

```text
CAP_HUMAN_APPROVAL
```

and if that capability is requested without an installed approval gate:

```text
ApprovalDenied
```

is returned.

The documentation explicitly describes this as:

```text
FAIL CLOSED
```That is exactly the security behavior we want for privileged capabilities.

---

## 7. Policy violations don't reach the kernel

This is another very important property.

The engine states that authorization/policy violations produce a synthetic `CellOutput` error:

```text
CapabilityViolation
AllowListViolation
```

without touching the underlying kernel.So:

```text
LLM-generated code
       ↓
ExecutionEngine
       ↓
policy failure
       ↓
synthetic error
       X
       │
       └── kernel never receives the code
```

That's substantially stronger than post-execution monitoring.

---

## 8. The allowlist itself has two layers

`AllowList` says enforcement happens at:

```text
static analysis
+
runtime import hooks
```So:

```text
Generated code
   ↓
static pattern check
   ↓
restricted import mechanism
```

This is stronger than the earlier hard-guardrail-only architecture.

---

## 9. There is still an important weakness: `permissive`

The default server request says:

```text
security = "permissive"
```

in `server/app.py`.And the OpenAI-compatible API also defaults to:

```text
security = "permissive"
````AllowList.permissive()` describes itself as:

> suitable for trusted internal use.

It only blocks a small set of dangerous operations.So we now have:

```text
ExecutionEngine = mandatory on server
```

but:

```text
ExecutionEngine policy = potentially weak by default
```

Those are two different questions.

---

## 10. This is now the major remaining concern

The server can correctly enforce:

```text
ExecutionEngine
```

while still using:

```text
AllowList.permissive()
```

which is explicitly intended for trusted internal use.

That creates a mismatch:

```text
PUBLIC SERVER
      │
      ▼
ExecutionEngine       ✓
      │
      ▼
permissive policy     ⚠️
```

For a public-facing agent API, I'd want:

```text
PUBLIC SERVER
      │
      ▼
ExecutionEngine
      │
      ▼
data_analysis / read_only
```

unless the caller is authenticated and explicitly authorized for permissive execution.

---

## 11. `secure_app.py` is better configured

The dedicated secure server defaults to:

```text
default_security = "data_analysis"
```That's a better baseline.

It also authenticates users by default:

```text
enable_auth=True
```

and applies per-user cell limits.So there are actually two server tiers:

```text
create_app()
    general / development-oriented

create_secure_app()
    authenticated production-oriented
```

That distinction should be documented very clearly.

---

## 12. But `secure_app.py` has a subtle problem

It creates:

```text
engine = make_server_engine(...)
```

but it also executes:

```text
bootstrap(kernel)
```

before the engine is constructed.This isn't necessarily a vulnerability.

`bootstrap()` is trusted host initialization, not LLM-generated code.

But the invariant should be explicit:

```text
ORIGIN_RUNTIME
    → trusted setup only

ORIGIN_AGENT
    → mandatory ExecutionEngine
```

Otherwise someone could later reuse `bootstrap()` with untrusted material and accidentally bypass K-001.

---

## 13. The `ExecutionEngine` already has an origin model

This is excellent.

It defines:

```text
ORIGIN_AGENT
ORIGIN_RUNTIME
```

and explicitly states:

```text
ORIGIN_AGENT
    → policy enforced

ORIGIN_RUNTIME
    → trusted host code
```That is exactly the distinction we were looking for.

---

## 14. This means we should not force all host operations through the agent policy

For example:

```text
skill bootstrap
plugin initialization
communication setup
kernel setup
```

can legitimately operate as:

```text
ORIGIN_RUNTIME
```

while:

```text
LLM-generated Python
```

must be:

```text
ORIGIN_AGENT
```

The critical requirement is preventing untrusted code from being labeled `ORIGIN_RUNTIME`.

---

## 15. The next audit should therefore target origin assignment

We need to search for:

```text
origin=ORIGIN_RUNTIME
```

and:

```text
origin=ORIGIN_AGENT
```

throughout the repository.

The key question:

> **Can an ordinary agent/skill/pipeline component request runtime-origin execution?**

If yes, K-001 could be bypassed at the semantic level.

If no, the origin model is strong.

---

## 16. Another important observation: local `Session` is different

`compose.Session.run()` still directly constructs:

```text
KernelRuntime(kernel_name=kernel_name)
```

and then passes that raw kernel into:

```text
_build_pipeline(kernel)
```This is a major distinction.

The server path:

```text
server
 ↓
ExecutionEngine
```

is protected.

The basic local `Session()` path:

```text
Session
 ↓
KernelRuntime
 ↓
pipeline
```

does **not** visibly construct an `ExecutionEngine`.

This means K-001 is currently **not universal across the entire public API** despite the engine's stated invariant.

---

## 17. This is now our strongest confirmed finding

### K-001 INTEGRATION GAP

`ExecutionEngine` declares:

> no agent/loop/plugin/skill/subsystem may execute except through the engine.

But `Session.run()` directly creates a `KernelRuntime` and gives it to the pipeline.Meanwhile the loop factory accepts a generic:

```text
Executor
```

and constructs:

```text
ExecuteStep(kernel)
```Therefore the core composition API can still construct:

```text
Session
 ↓
raw KernelRuntime
 ↓
ExecuteStep
```

outside the K-001 choke point.

That's not speculative.

It's directly visible in the code.

---

## 18. This explains why the abstraction matters

The architecture currently has two worlds:

### Server world

```text
HTTP
 ↓
ExecutionEngine
 ↓
Pipeline
```

### Local composition world

```text
Session
 ↓
KernelRuntime
 ↓
Pipeline
```

They should converge.

---

## 19. Target fix

`Session.run()` should construct:

```text
raw_kernel
     ↓
ExecutionEngine
     ↓
pipeline
```

rather than:

```text
raw_kernel
     ↓
pipeline
```

Conceptually:

```python
raw_kernel = KernelRuntime(...)
engine = make_execution_engine(
    raw_kernel,
    policy=self._security_policy,
)
pipeline = self._pipeline or self._build_pipeline(engine)
```

Then:

```text
server
  → ExecutionEngine

local Session
  → ExecutionEngine

streaming
  → ExecutionEngine
```

All roads converge.

---

## 20. Custom pipelines require special attention

`Session.with_pipeline()` explicitly allows:

```text
custom pipeline
```

and the documentation example constructs:

```text
ExecuteStep(kernel)
```

directly.This is powerful composability.

But it means the API cannot rely on users voluntarily inserting:

```text
ExecutionEngine
```

into their custom pipeline.

The Session itself should wrap/authorize the executor before handing it to the custom pipeline.

---

## 21. This is exactly where the abstraction should enforce security

Instead of:

```text
with_pipeline(Pipeline([... ExecuteStep(kernel) ...]))
```

being allowed to bypass the engine, the session should expose:

```text
authorized_executor
```

to the pipeline construction layer.

Then even a custom pipeline receives:

```text
ExecutionEngine
```

instead of:

```text
KernelRuntime
```

---

## 22. Proposed API semantics

Current:

```python
Session().with_kernel()
```

could internally mean:

```text
KernelRuntime
```

but the pipeline should receive:

```text
ExecutionEngine
```

So:

```text
user-level kernel
       │
       ▼
raw runtime
       │
       ▼
security wrapper
       │
       ▼
pipeline-visible executor
```

This preserves backwards-compatible ergonomics while strengthening the boundary.

---

## 23. The `with_security()` method also needs integration

Currently:

```text
with_security(allowlist)
```

stores:

```text
self._allowlist
```

Then `run()` injects the allowlist into the raw kernel:

```text
kernel.execute(kcode, silent=True)
```

and later `_build_pipeline()` adds:

```text
AllowListTransformer
```This is weaker than using the centralized `ExecutionEngine`.

The policy should become:

```text
Session._allowlist
       ↓
ExecutionEngine(allowlist=...)
```

rather than relying on transformer insertion.

---

## 24. Why this matters

A transformer is composable:

```text
Generate
 ↓
Transform
 ↓
Execute
```

A security engine is authoritative:

```text
Execute
 ↓
ExecutionEngine
 ↓
policy
 ↓
kernel
```

If the transformer is omitted by a custom pipeline, policy disappears.

If the executor is the engine, policy remains.

That is the key distinction.

---

## 25. Revised security architecture

We now have enough evidence to draw the real current architecture:

```text
                         Kerno
                           │
             ┌─────────────┴─────────────┐
             │                           │
        HTTP/server                  Local Session
             │                           │
             ▼                           ▼
     make_server_engine             KernelRuntime
             │                           │
             ▼                           ▼
     ExecutionEngine                 Pipeline
             │                           │
             └─────────────┬─────────────┘
                           │
                     DIFFERENT
                   security paths
```

The target is:

```text
                         Kerno
                           │
             ┌─────────────┴─────────────┐
             │                           │
        HTTP/server                  Local Session
             │                           │
             └─────────────┬─────────────┘
                           ▼
                  ExecutionController
                           │
                    ExecutionEngine
                           │
                       Pipeline
                           │
                     KernelRuntime
```

---

## 26. This changes our P0 assessment

We can now say:

### Server execution boundary

** Strong architectural enforcement**

The server routes wrap the kernel in `ExecutionEngine`.

### Local Session execution boundary

** Confirmed integration gap**

`Session.run()` still exposes a raw `KernelRuntime` to the pipeline.

### OS sandbox

** Still not demonstrated**

The execution engine controls code-level policy and authorization but does not itself establish OS-level containment.

So we should no longer label the entire Kerno project "missing an execution choke point."

It has one.

The problem is **incomplete adoption**.

---

## 27. Updated findings

| Finding | Status |
|---|---|
| ExecutionEngine exists |  Confirmed |
| Server uses it |  Confirmed |
| HTTP streaming uses it |  Confirmed |
| Capability checks |  Confirmed |
| Policy checks before kernel |  Confirmed |
| Audit records/events |  Confirmed |
| Local `Session` uses it |  **No** |
| Custom local pipelines protected automatically |  **No** |
| Default server policy |  `permissive` |
| Secure server default |  `data_analysis` |
| OS sandbox |  Not demonstrated |
| Raw KernelRuntime remains constructible |  Yes |

---

## 28. This is now the next implementation priority

Before adding a sophisticated container sandbox, I would first fix the **K-001 adoption gap**.

### Priority order

```text
1. Make ExecutionEngine universal
        ↓
2. Prevent raw executor leakage
        ↓
3. Make security policy mandatory
        ↓
4. Change public-server default to restrictive
        ↓
5. Add OS-level sandbox
        ↓
6. Add security-profile-aware KernelPool
```

That order avoids building a powerful sandbox while leaving an alternate execution route around it.

---

## 29. One more critical search remains

We need to inventory direct execution outside `ExecutionEngine`:

```text
.kernel.execute(
runtime.execute(
runtime.stream_execute(
_executor.execute(
```

The important question is not merely whether those calls exist.

It is:

> **Which are trusted runtime operations, and which can receive LLM/agent-generated code?**

The `ExecutionEngine` itself explicitly recognizes this distinction through `ORIGIN_RUNTIME` vs `ORIGIN_AGENT`.That will be the next major phase of the audit.

At this point, however, we have a concrete architectural conclusion:

> **Kerno has already implemented the right execution-control concept. The branch's primary security defect is that the core `Session`/custom-composition path does not universally route execution through that choke point, while the server paths largely do.**

---

## The local `Session` path is now **confirmed** as a real K-001 gap

I re-checked the actual branch rather than relying on the previous summary. The strongest evidence is `kerno/compose.py` itself.

The file explicitly documents the intended security composition:

```text
Session = LLM + Kernel + Skills + Pipeline + Memory + Security
```

but its `run()` implementation still constructs a raw `KernelRuntime` and passes that object directly into the pipeline.That makes this finding **confirmed**, not hypothetical.

---

## 1. Exact current local execution path

The current `Session.run()` does:

```text
Session.run()
    │
    ├── KernelRuntime(kernel_name=...)
    │
    ├── kernel.start()
    │
    ├── allowlist.to_kernel_code()
    │       └── kernel.execute(...)
    │
    ├── _load_skills(kernel)
    │
    ├── _build_pipeline(kernel)
    │
    └── pipeline.run(state)
```

The critical part is:

```text
kernel = self._kernel or KernelRuntime(...)
...
pipeline = self._pipeline or self._build_pipeline(kernel)
```There is **no `ExecutionEngine` inserted between `KernelRuntime` and the pipeline in this path**.

---

## 2. This is different from the server path

So the repository currently has two security architectures:

### Server

```text
HTTP
 ↓
make_server_engine()
 ↓
ExecutionEngine
 ↓
Pipeline
```

### Local `Session`

```text
Session
 ↓
KernelRuntime
 ↓
Pipeline
```

That is architectural fragmentation.

The security boundary exists, but it isn't universal.

---

## 3. `with_security()` does not solve this

This is particularly important.

`Session.with_security()` merely stores:

```python
self._allowlist = allowlist
```

Then `run()` does:

```text
allowlist.to_kernel_code()
    ↓
kernel.execute(...)
```

and `_build_pipeline()` optionally adds:

```text
AllowListTransformer
```So security is implemented partly as:

```text
bootstrap code
+
transformer
```

rather than through the authoritative `ExecutionEngine`.

---

## 4. The custom-pipeline path is even more exposed

The documentation itself gives this pattern:

```text
Session()
  .with_kernel()
  .with_pipeline(
      Pipeline([
          ...
          ExecuteStep(kernel),
          ...
      ])
  )
```That means the composability API explicitly permits a caller to construct an `ExecuteStep` around the kernel.

There is no central enforcement layer preventing that.

So:

```text
K-001:
"everything executes through ExecutionEngine"
```

is **not true for the local composition API**.

---

## 5. There is a second direct-execution problem before the pipeline

Even worse, `Session.run()` executes security/bootstrap code directly:

```text
allowlist.to_kernel_code()
        ↓
kernel.execute()
```

before the pipeline is constructed.And `_load_skills()` can directly execute a file:

```text
Path(self._skills).read_text()
        ↓
kernel.execute(...)
```These are probably intended as **trusted runtime operations**, but the architecture needs to label them explicitly as such.

Otherwise K-001 becomes:

```text
"all agent execution must use ExecutionEngine"
```

while the code actually has multiple direct kernel routes.

---

## 6. The crucial distinction: trusted bootstrap vs agent code

The direct calls aren't automatically vulnerabilities.

For example:

```text
kernel.start()
bootstrap(kernel)
```

can legitimately be runtime initialization.

The security model should therefore distinguish:

```text
ORIGIN_RUNTIME
```

from:

```text
ORIGIN_AGENT
```

The existing execution-control design already appears to have this conceptual distinction.

The problem is that `Session.run()` does not visibly establish that boundary through the same centralized engine.

---

## 7. The clean solution is **not** "wrap everything blindly"

We shouldn't simply do:

```text
EVERY kernel.execute()
    → ExecutionEngine
```

because trusted bootstrap operations may legitimately need privileges.

Instead, make the distinction explicit:

```text
Runtime bootstrap
    → trusted runtime executor

Agent-generated execution
    → mandatory ExecutionEngine
```

That gives us a real security model instead of merely adding another wrapper.

---

## 8. Proposed `Session` structure

Current:

```text
Session
 │
 └── raw KernelRuntime
       │
       ├── bootstrap
       ├── skills
       └── pipeline
```

Target:

```text
Session
 │
 ├── RuntimeExecutor
 │      └── trusted initialization
 │
 └── ExecutionEngine
        └── all agent execution
```

The raw kernel should not escape the session's internal construction boundary.

---

## 9. Better still: use an `ExecutionContext`

I'd introduce:

```python
ExecutionContext(
    session_id=...,
    origin=ORIGIN_AGENT,
    security_policy=...,
    capabilities=...,
    budget=...,
    provenance=...,
)
```

Then:

```text
Session
  ↓
ExecutionContext
  ↓
ExecutionEngine
  ↓
Pipeline
```

The pipeline receives an authorized executor, not the raw kernel.

---

## 10. This also fixes custom pipelines

Instead of documentation encouraging:

```python
ExecuteStep(kernel)
```

the API should encourage:

```python
ExecuteStep(executor)
```

where:

```text
executor = ExecutionEngine(...)
```

Then even a custom pipeline automatically gets:

```text
policy
authorization
audit
budget
provenance
```

---

## 11. `with_kernel()` should not mean "give pipeline the kernel"

It should mean:

```text
with_kernel()
     ↓
construct runtime
     ↓
construct authorized execution layer
```

So internally:

```text
KernelRuntime
    ↓
ExecutionEngine
    ↓
Session pipeline
```

The raw kernel becomes an implementation detail.

---

## 12. The security configuration should be required, not optional

Currently:

```text
Session()
    ↓
_allowlist = None
```

is valid.

Then execution can proceed directly against `KernelRuntime`.For an agent execution framework, I'd prefer:

```text
Session()
    ↓
default restrictive policy
```

rather than:

```text
Session()
    ↓
no policy
```

A caller can explicitly request:

```text
trusted/permissive
```

but it should be a conscious decision.

---

## 13. Recommended defaults

For local development:

```text
security = data_analysis
```

For server:

```text
security = data_analysis
```

For explicitly trusted internal workloads:

```text
security = permissive
```

For hostile/untrusted workloads:

```text
security = restricted
```

And:

```text
worker_lifecycle = ephemeral
```

for the last category.

---

## 14. The current server default is therefore worth fixing too

Earlier we established that the general server uses:

```text
security="permissive"
```

while the dedicated secure server defaults to:

```text
data_analysis
```

That is an unfortunate split.

A public API should default to the secure behavior.

If developers need permissive mode, make it explicit:

```text
security="permissive"
```

rather than silently receiving it.

---

## 15. Current security model after this deeper pass

```text
                   Kerno
                     │
        ┌────────────┴────────────┐
        │                         │
      Server                   Session
        │                         │
        ▼                         ▼
ExecutionEngine             KernelRuntime
        │                         │
        ▼                         ▼
    Pipeline                  Pipeline
        │                         │
        ▼                         ▼
     Python                    Python
```

The right side is the defect.

---

## 16. Target model

```text
                   Kerno
                     │
        ┌────────────┴────────────┐
        │                         │
      Server                   Session
        │                         │
        └────────────┬────────────┘
                     ▼
             ExecutionContext
                     │
                     ▼
             ExecutionEngine
                     │
                     ▼
                  Pipeline
                     │
                     ▼
               KernelRuntime
```

Now there is one security architecture.

---

## 17. Severity assessment

I'd classify the confirmed issue as:

### **P1 — Security-control bypass in local composition API**

Why P1 rather than automatically P0?

Because:

1. The server path does have the intended execution choke point.
2. The dedicated secure server has stronger defaults.
3. The vulnerable path is the local/composable API.
4. The actual impact depends on whether an application exposes that path to untrusted agent-generated code.

If `Session` is advertised as a general public API for untrusted agents, this could reasonably become **P0**.

---

## 18. The previous "streaming bypass" finding should stay downgraded

The server streaming path explicitly constructs the security engine before constructing the streaming pipeline.

So:

```text
HTTP streaming → ExecutionEngine
```

is covered.

The problem is not "streaming inherently bypasses security."

The real problem is:

> **Any composition path that receives a raw `KernelRuntime` can bypass the central execution policy.**

That's much more precise.

---

## 19. We should now search for all raw kernel escape points

The important inventory is:

```text
KernelRuntime(...)
```

```text
kernel.execute(...)
```

```text
kernel.stream_execute(...)
```

```text
ExecuteStep(kernel)
```

```text
StreamingExecuteStep(kernel)
```

```text
Pipeline(... kernel ...)
```

and:

```text
executor=kernel
```

Then classify every result:

| Call site | Origin | Agent-controlled? | Engine required? |
|---|---|---:|---:|
| bootstrap | runtime | No | No |
| security setup | runtime | No | No/controlled |
| skill loading | depends | potentially | Yes if untrusted |
| ExecuteStep | agent | Yes | **Yes** |
| streaming | agent | Yes | **Yes** |
| custom pipeline | depends | Yes | **Yes** |
| tests | test | No | No |

This is the next decisive audit.

---

## 20. One especially important issue: skills

`_load_skills()` supports a string path:

```text
skills = "/path/to/file.py"
```

then reads the entire file and executes it in the kernel:

```text
Path(self._skills).read_text()
        ↓
kernel.execute(...)
```This means the security model must explicitly define whether a skill is:

```text
trusted extension code
```

or:

```text
untrusted executable content
```

Those are radically different trust models.

---

## 21. Recommended skill model

### Trusted skill

```text
installed package
signed/approved
runs as ORIGIN_RUNTIME
```

### Untrusted/generated skill

```text
treated as agent code
runs through ExecutionEngine
restricted capabilities
```

Do not let:

```text
"skill"
```

automatically imply:

```text
"trusted"
```

if skills can be supplied dynamically.

---

## 22. The same applies to `extra_plugins`

The plugin system is powerful, but plugins can run before/after execution.

Therefore:

```text
plugin = trusted host extension
```

should be the explicit assumption.

Generated code should never be able to install an arbitrary plugin into the process.

That would destroy the security boundary.

---

## 23. The architectural principle we should record

### **Kerno Security Invariant K-001**

> A `KernelRuntime` may exist inside the runtime, but an agent-controlled execution path must never receive the raw kernel. Agent execution receives only an authorized `ExecutionEngine`/executor bound to an immutable `ExecutionContext`.

That is stronger and more implementable than simply saying:

> "all execution goes through ExecutionEngine."

---

## 24. And K-002

> **Security policy is selected before execution and cannot be weakened by generated code, skills, plugins, retries, streaming, or custom pipeline composition.**

This closes the loopholes around the composability model.

---

## 25. K-003

> **Every executor handed to a pipeline carries its security identity and capability policy.**

Therefore:

```text
Pipeline(kernel)
```

should eventually become impossible or at least explicitly marked unsafe.

Instead:

```text
Pipeline(executor)
```

where:

```text
executor.security_context
```

is inspectable.

---

## 26. K-004

> **Kernel reuse is an optimization, never an authorization mechanism.**

So:

```text
pool.acquire()
```

must select workers based on security profile.

Not simply:

```text
any idle worker
```

---

## 27. K-005

> **OS isolation remains mandatory for genuinely hostile workloads.**

Even after fixing the Session gap:

```text
ExecutionEngine
```

is still primarily code-level policy.

It should not be represented as a replacement for:

```text
container
namespace
cgroup
seccomp
filesystem isolation
network isolation
```

---

## 28. Bottom line

The audit is becoming much more precise:

### What Kerno already does well

- Has a real execution-control abstraction.
- Server paths actually use it.
- Capability checks can fail closed.
- Policy violations can stop code before kernel execution.
- Execution records contain useful provenance/security metadata.
- Streaming server execution is also wrapped.

### What is definitely broken/incomplete

- `Session.run()` still creates and exposes a raw `KernelRuntime`.
- Local custom pipelines can receive that raw kernel.
- `with_security()` does not automatically turn the kernel into an authoritative security executor.
- Skill loading has a direct `kernel.execute()` route whose trust classification needs to be explicit.
- Security defaults are inconsistent between general and secure server APIs.
- OS-level containment is still a separate, unresolved layer.

**The highest-value fix is therefore not another blacklist. It is to make the `ExecutionEngine` universal at the executor boundary and prevent raw `KernelRuntime` objects from crossing into agent-controlled pipelines.**

Reference: the `Abdus2023/Kerno` repository, branch `arena/01a0064f-kerno`.

---

## Next: complete the **raw-kernel escape-point audit**

We have the main finding. Now the next step is to prove whether there are **any additional paths around `ExecutionEngine`**, not just `Session.run()`.

### Audit sequence

```text
1. KernelRuntime construction
        ↓
2. direct kernel.execute()
        ↓
3. direct stream_execute()
        ↓
4. ExecuteStep / StreamingExecuteStep
        ↓
5. skills
        ↓
6. plugins
        ↓
7. retries / recovery
        ↓
8. parallel execution
        ↓
9. custom pipelines
        ↓
10. server + CLI + local APIs
```

For every occurrence, classify it:

| Path | Trusted? | Agent-controlled? | ExecutionEngine mandatory? |
|---|---|---|---|
| Runtime bootstrap | likely yes | No | No |
| Skill loading | **needs proof** | potentially | **must decide** |
| `Session.run()` | No | Yes | **currently NO → defect** |
| `ExecuteStep` | Yes | Yes | **must be yes** |
| Streaming | Yes | Yes | server path already yes |
| Custom pipeline | Yes | potentially | **currently bypassable** |
| Plugin execution | depends | potentially | must be classified |
| Retry/recovery | depends | Yes | must inherit policy |
| Parallel branches | depends | Yes | must inherit policy |

### Then we move to the actual remediation

The target should be:

```text
                 Session / Server
                        │
                        ▼
                ExecutionContext
                        │
              ┌─────────┴─────────┐
              │                   │
          policy              capabilities
              │                   │
              └─────────┬─────────┘
                        ▼
                 ExecutionEngine
                        │
                        ▼
                     Pipeline
                        │
                        ▼
                 KernelRuntime
```

with this invariant:

> **Raw `KernelRuntime` never crosses into agent-controlled pipeline code.**

And for hostile workloads:

```text
ExecutionEngine
      ↓
Sandboxed worker
      ↓
isolated Python/Jupyter process
      ↓
OS resource/network/filesystem restrictions
```

### The next concrete deliverable

I'll treat the next stage as a **repository-wide execution-flow matrix**:

**`origin → caller → executor → kernel → policy → sandbox → audit → lifecycle`**

That will let us distinguish three things cleanly:

-  **Confirmed safe**
-  **Needs hardening / trust assumption**
-  **Confirmed bypass**

Then we can turn the confirmed  findings into a minimal patch plan rather than redesigning Kerno unnecessarily.

---

## The repository-wide scan gives us a sharper result

I traced the execution-related symbols on the actual `arena/01a0064f-kerno` branch rather than treating the earlier architecture as sufficient evidence.

The important result is:

> **Kerno's primary `run()` and `run_with_pool()` paths do use `ExecutionEngine`. The major remaining escape route is the older/composable `Session` API, plus a few deliberately trusted raw-kernel bootstrap operations.**

That lets us narrow the remediation considerably.

---

## 1. Main `run()` path:  protected

`kerno/_run.py` explicitly constructs:

```text
KernelRuntime
     ↓
ExecutionEngine
     ↓
loop
     ↓
ExecuteStep
```

The loop receives:

```python
common = dict(kernel=engine, llm=llm, verbose=verbose)
```

not the raw kernel.This is exactly what K-001 requires.

### Result

** Confirmed**

For the principal `kerno.run()` API, agent-generated cells go through `ExecutionEngine`.

---

## 2. `run_with_pool()` is also protected

This is important because pooling was one of our biggest concerns.

Each acquired kernel is wrapped:

```text
pool.acquire()
      ↓
KernelRuntime
      ↓
ExecutionEngine
      ↓
Reactive/Reflect/Plan loop
```

The code explicitly comments that pool workers execute agent code exclusively through the engine.So our earlier concern:

> "Does pooling create an alternate raw execution path?"

For the main pool API:

** No.**

---

## 3. The isolated multi-agent path is also correctly wrapped

The isolated factory does:

```text
new KernelRuntime
       ↓
start
       ↓
allowlist bootstrap
       ↓
ExecutionEngine
```

and returns the `ExecutionEngine`, not the raw kernel.That's a good design.

So:

```text
multi-agent
   ↓
isolated worker
   ↓
ExecutionEngine
```

is structurally correct.

---

## 4. `ExecuteStep` itself is intentionally generic

`ExecuteStep` accepts:

```python
kernel: Executor
```

and simply does:

```text
self.kernel.execute(...)
```This is actually a good abstraction.

The security responsibility should be:

```text
what Executor did we give ExecuteStep?
```

rather than putting security logic inside `ExecuteStep`.

That means our remediation should **not** turn `ExecuteStep` into a giant security component.

---

## 5. The real invariant should therefore be enforced at composition

Current:

```text
ExecuteStep(Executor)
```

is fine.

But this is dangerous:

```text
ExecuteStep(raw KernelRuntime)
```

while this is correct:

```text
ExecuteStep(ExecutionEngine)
```

So the architectural rule becomes:

> **Agent-controlled composition must only be able to obtain an authorized Executor.**

---

## 6. `Session` is the remaining major exception

The composable API still does:

```text
kernel = self._kernel or KernelRuntime(...)
```

then:

```text
pipeline = self._pipeline or self._build_pipeline(kernel)
```This is the concrete K-001 integration gap.

---

## 7. Why this matters more than just one class

`Session` is deliberately presented as the high-level composition API:

```text
Session =
LLM
+
Kernel
+
Skills
+
Pipeline
+
Memory
+
Security
```So an application developer could reasonably choose:

```python
Session().with_llm(...).with_kernel().run(...)
```

instead of the lower-level `run()` function.

If that session is used with untrusted agent code, the security model is inconsistent.

---

## 8. The custom pipeline example makes the problem explicit

The module documentation itself shows:

```text
ExecuteStep(kernel)
```

inside a custom pipeline.Therefore this isn't merely an obscure internal escape.

It is part of the intended composability model.

---

## 9. There is a second issue: security is optional on `run()`

The main `run()` does construct `ExecutionEngine`, which is excellent.

But if:

```text
allowlist = None
capability_broker = None
```

then the engine has no active authorization broker and no allowlist.

`ExecutionEngine` itself describes:

```text
allowlist → optional
broker → optional
```So:

```text
ExecutionEngine
```

is mandatory for the main path, but:

```text
security policy
```

is not necessarily mandatory.

That's a separate issue from K-001.

---

## 10. Distinguish **execution control** from **security policy**

This is important.

### Execution control

```text
ExecutionEngine
```

means:

> all agent execution is observable, auditable and routed through one mechanism.

### Security policy

```text
AllowList
CapabilityBroker
ApprovalGate
EffectLedger
```

means:

> what the execution is actually allowed to do.

Kerno has the first in the main API.

The second remains configurable.

---

## 11. This creates three modes

### Mode A — engine only

```text
ExecutionEngine
allowlist=None
broker=None
```

Agent code is centralized/audited, but largely unrestricted.

### Mode B — policy enabled

```text
ExecutionEngine
+
AllowList
+
CapabilityBroker
```

Agent code is constrained.

### Mode C — isolated

```text
ExecutionEngine
+
policy
+
isolated worker
```

This is the strongest architecture.

---

## 12. Therefore I would not call `ExecutionEngine` itself a sandbox

The repository's terminology needs to remain precise.

`ExecutionEngine` provides:

```text
authorization
policy
audit
events
provenance
redaction
effect observation
```

It does **not**, by itself, turn Python into an OS sandbox.

The underlying `KernelRuntime` still launches a Jupyter Python kernel directly.---

## 13. This confirms our earlier OS-isolation conclusion

`KernelRuntime.start()` directly performs:

```text
jupyter_client.KernelManager(...)
        ↓
start_kernel()
```There is no container/cgroup/network namespace/filesystem namespace shown here.

So:

### OS sandbox

** Not demonstrated**

That remains an independent hardening task.

---

## 14. Timeout handling is actually fairly mature

There is a good feature here that should not get lost in the security critique.

`KernelRuntime` supports:

```text
interrupt
   ↓
grace period
   ↓
process kill
   ↓
restart
```

when `timeout_policy="escalate"`.That's a solid reliability boundary.

But again:

```text
timeout protection ≠ sandboxing
```

---

## 15. Pool reuse remains a lifecycle concern, not an engine bypass

We now have:

```text
KernelPool
   ↓
KernelRuntime
   ↓
ExecutionEngine
   ↓
agent
```

So the pool does not bypass the engine in `run_with_pool()`.

However, successful completion still returns the kernel for reuse.

Therefore:

```text
ExecutionEngine
+
soft reset
```

still isn't equivalent to:

```text
destroy worker
```

For trusted workloads: acceptable.

For hostile multi-tenant workloads: still insufficient.

---

## 16. Updated execution matrix

| Path | Raw kernel reaches agent? | Engine? | Policy? | Verdict |
|---|---:|---:|---:|---|
| `kerno.run()` | No |  | optional |  |
| `run_with_pool()` | No |  | optional |  |
| isolated multi-agent | No |  | optional |  |
| HTTP server | No |  | server-configured |  |
| HTTP streaming | No |  | server-configured |  |
| `Session.run()` | **Yes** |  | transformer/bootstrap |  |
| custom `Session` pipeline | **Yes** |  | caller-dependent |  |
| runtime bootstrap | Yes | intentionally | trusted | * |
| skill file loading | Yes | direct | depends on trust |  |

`*` assuming bootstrap remains trusted host code.

---

## 17. This is much better than the initial picture

We should explicitly correct the earlier broad conclusion.

It would be inaccurate to say:

> "Kerno generally executes agent code directly against the raw Jupyter kernel."

The actual evidence says:

> **The principal execution APIs have already been migrated to the ExecutionEngine choke point; the legacy/composable `Session` API has not.**

That's a much more useful finding.

---

## 18. The remediation is now small and surgical

### Change 1 — `Session.run()`

Replace:

```text
KernelRuntime
    ↓
pipeline
```

with:

```text
KernelRuntime
    ↓
ExecutionEngine
    ↓
pipeline
```

### Change 2 — `Session._build_pipeline()`

Pass:

```text
executor
```

rather than:

```text
raw kernel
```

### Change 3 — custom pipelines

Ensure the session supplies the authorized executor to the custom pipeline or rejects a pipeline that exposes a raw kernel.

---

## 19. `with_security()` should feed the engine

Current:

```text
with_security(allowlist)
       ↓
transformer
       +
kernel bootstrap
```

Target:

```text
with_security(allowlist)
       ↓
ExecutionEngine(allowlist=...)
       ↓
pipeline
```

The transformer can remain as defense-in-depth, but it should no longer be the authoritative enforcement layer.

---

## 20. Add a regression test that proves K-001

This should become a mandatory test.

Something like:

```text
Session
  ↓
custom pipeline
  ↓
attempt direct raw-kernel execution
```

must either:

```text
be impossible
```

or:

```text
be forced through ExecutionEngine
```

Then a test can assert:

```text
ExecutionEngine.records == 1
```

for every agent cell.

---

## 21. Add a stronger invariant test

For every public execution entry point:

```text
run()
run_with_pool()
Session.run()
server /run
server streaming
multi-agent
debate
hierarchical
custom pipeline
```

execute one known cell and verify:

```text
execution_id != None
ExecutionRecord exists
origin == agent
```

That converts K-001 from documentation into executable proof.

---

## 22. Next major issue: `ORIGIN_RUNTIME`

There is one more thing I want to audit before proposing the patch.

`ExecutionEngine` deliberately has:

```text
ORIGIN_AGENT
ORIGIN_RUNTIME
```

and runtime-origin execution bypasses policy.That's reasonable.

But we need to find every place that can call:

```text
engine.execute(..., origin=ORIGIN_RUNTIME)
```

because that is effectively a privileged execution capability.

If an agent-controlled path can reach it, then we have a **much more serious privilege-escalation issue** than the current Session gap.

---

## 23. So the next audit target is now very precise

Search for:

```text
origin=ORIGIN_RUNTIME
```

and:

```text
ORIGIN_RUNTIME
```

throughout the branch.

Then classify every caller:

```text
bootstrap → trusted?
plugin → trusted?
skill → trusted?
checkpoint → trusted?
server request → impossible?
LLM-generated path → RED FLAG
```

If all runtime-origin calls are genuinely host-controlled, the model is strong.

If an agent can select that origin, **that becomes the next P0/P1 candidate**.

---

## Current status

```text
K-001 engine implementation       🟢
Main run() integration             🟢
Pool integration                   🟢
Isolated multi-agent integration   🟢
Server integration                 🟢
Streaming server integration       🟢
Local Session integration          🔴
Custom Session pipeline            🔴
Policy mandatory by default        🟠
OS sandbox                         🟠
Runtime-origin privilege boundary  🔎 NEXT
```

So **the next step is not another broad architectural redesign**.

It is the **`ORIGIN_RUNTIME` privilege audit**. That will tell us whether Kerno has merely one local composition gap, or whether there is a second path capable of deliberately bypassing the security policy.

---

## Next: audit the privileged `ORIGIN_RUNTIME` path

The next question is the most security-sensitive one left:

> **Can agent-controlled code ever obtain `ORIGIN_RUNTIME` execution?**

Kerno intentionally distinguishes:

```text
ORIGIN_AGENT
    ↓
security policy applies

ORIGIN_RUNTIME
    ↓
trusted host operation
```

That is a valid design **only if the second path is unreachable from untrusted agent code**.

### The security model we want

```text
                 ExecutionEngine
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
   ORIGIN_AGENT              ORIGIN_RUNTIME
          │                         │
          ▼                         ▼
 policy + audit              trusted host only
          │
          ▼
      KernelRuntime
```

The dangerous situation would be:

```text
LLM / Agent
    ↓
skill/plugin
    ↓
ORIGIN_RUNTIME
    ↓
policy bypass
    ↓
KernelRuntime
```

That would turn a policy bypass into a privilege escalation.

---

## What I would verify next

Search every occurrence of:

```text
ORIGIN_RUNTIME
```

and classify the caller.

### Safe candidates

```text
kernel bootstrap
internal initialization
trusted plugin setup
server infrastructure
kernel lifecycle management
```

### Suspicious candidates

```text
agent loop
skill execution
generated Python
custom pipeline
tool callback
LLM response handler
user-supplied plugin
```

The key isn't merely whether `ORIGIN_RUNTIME` exists.

It's whether **the origin is caller-controlled**.

---

## One design rule should be enforced

The origin should **never** come from generated code or ordinary user input:

```python
## Dangerous
engine.execute(code, origin=request.origin)
```

Instead:

```python
## Better
engine.execute(
    code,
    origin=ExecutionOrigin.AGENT,
)
```

and runtime-origin execution should only be available through an internal/trusted interface.

Even better:

```text
AgentExecutor
    → always ORIGIN_AGENT

RuntimeExecutor
    → always ORIGIN_RUNTIME
```

Then callers don't choose the origin at all.

---

## This leads to a stronger API design

Instead of:

```python
engine.execute(code, origin=...)
```

use separate capabilities:

```text
AgentExecutionEngine.execute()
RuntimeExecutionEngine.execute()
```

or make `ORIGIN_RUNTIME` impossible to construct outside an internal module.

That eliminates an entire class of confused-deputy bugs.

---

## Combined with the previous finding

The final architecture should become:

```text
                    Kerno
                      │
          ┌───────────┴───────────┐
          │                       │
       trusted                  agent
       runtime                  code
          │                       │
          ▼                       ▼
 RuntimeExecutor           ExecutionEngine
          │                       │
          │                policy + audit
          │                       │
          └───────────┬───────────┘
                      ▼
                 KernelRuntime
```

And the raw kernel must remain private to these layers.

---

## Then the audit is nearly complete

After the `ORIGIN_RUNTIME` search, the remaining work is:

### 1. Fix local `Session`

```text
Session
 ↓
ExecutionEngine
 ↓
Pipeline
```

### 2. Make security defaults consistent

Prefer restrictive/data-analysis defaults rather than `permissive` for public-facing execution.

### 3. Separate trusted and untrusted workers

```text
trusted → reusable
untrusted → ephemeral/isolated
```

### 4. Add OS-level containment

```text
container / namespace
filesystem restrictions
network restrictions
CPU/memory/process limits
```

### 5. Turn K-001 into tests

Every public execution entry point should produce an `ExecutionRecord`.

---

## The most important conclusion so far

Kerno is **not starting from an insecure raw-kernel architecture**.

It already has a serious execution-control layer and has integrated it into the main, pooled, isolated, server, and streaming execution paths.

The remaining architectural problem is **incomplete enforcement at the composability boundary**, plus the need to prove that `ORIGIN_RUNTIME` is genuinely unreachable from agent-controlled code.

That is the correct place to continue the audit.

---

## Now turn the audit into an implementation plan

At this point the findings are sufficiently precise that we should stop expanding the architecture unnecessarily and define the **minimum hardening patch**.

### Current state

```text
Main run()                    🟢 ExecutionEngine
run_with_pool()               🟢 ExecutionEngine
isolated execution            🟢 ExecutionEngine
HTTP /run                     🟢 ExecutionEngine
HTTP streaming                🟢 ExecutionEngine
Local Session                 🔴 raw KernelRuntime can escape
Custom Session pipeline       🔴 raw executor can be supplied
Security default              🟠 inconsistent
OS isolation                  🟠 not demonstrated
ORIGIN_RUNTIME boundary       🔎 must be proven
```

---

## Phase 1 — Close the raw-kernel escape

The most important change is:

```text
Session
  ↓
KernelRuntime
  ↓
ExecutionEngine
  ↓
Pipeline
```

instead of:

```text
Session
  ↓
KernelRuntime
  ↓
Pipeline
```

### Do not modify `ExecuteStep` into a security monster.

Keep:

```python
class ExecuteStep:
    def __init__(self, kernel: Executor):
        self.kernel = kernel
```

That abstraction is correct.

The security guarantee belongs at the point where the executor is supplied.

---

## Phase 2 — Introduce an explicit execution context

The clean interface is something like:

```python
@dataclass(frozen=True)
class ExecutionContext:
    origin: ExecutionOrigin
    policy: SecurityPolicy
    capabilities: frozenset[str]
    budget: ExecutionBudget
    session_id: str
```

Then:

```text
Session
    ↓
ExecutionContext
    ↓
ExecutionEngine
    ↓
Pipeline
```

This makes the security state explicit instead of scattered across:

```text
allowlist
broker
plugins
transformers
session flags
```

---

## Phase 3 — Make raw `KernelRuntime` private to execution infrastructure

This is the architectural rule I'd adopt:

> **`KernelRuntime` is an infrastructure implementation; `Executor` is the agent-facing abstraction.**

So internal code may hold:

```text
KernelRuntime
```

but agent pipelines should receive:

```text
Executor
```

and normally that executor is:

```text
ExecutionEngine
```

This eliminates accidental bypasses.

---

## Phase 4 — Fix `Session.with_security()`

Currently its security configuration can become a transformer/bootstrap operation.

Instead:

```text
Session.with_security(policy)
        ↓
ExecutionEngine(policy=policy)
```

The transformer can remain as defense-in-depth:

```text
ExecutionEngine
     +
AllowListTransformer
```

but the transformer should never be the only enforcement layer.

---

## Phase 5 — Fix custom pipelines

This is critical.

A custom pipeline should receive:

```text
ExecutionEngine
```

not:

```text
KernelRuntime
```

Therefore:

```python
pipeline = custom_pipeline(executor)
```

rather than:

```python
pipeline = custom_pipeline(kernel)
```

The custom pipeline remains completely composable while security stays centralized.

---

## Phase 6 — Add a raw-kernel guard

For development builds, I would add an assertion at the pipeline boundary:

```python
if isinstance(executor, KernelRuntime):
    raise SecurityError(
        "Raw KernelRuntime cannot be used for agent execution"
    )
```

This should initially be a hard failure.

Why?

Because otherwise another developer can accidentally reintroduce:

```text
ExecuteStep(kernel)
```

six months later.

---

## Phase 7 — Don't rely on `isinstance()` forever

The long-term solution is stronger typing/API design:

```text
AgentExecutor
```

could be a separate protocol.

For example:

```python
class AgentExecutor(Protocol):
    def execute(...): ...
    def stream_execute(...): ...
```

`KernelRuntime` should not implement the public agent-facing interface directly.

Instead:

```text
KernelRuntime
      ↓
KernelAdapter
      ↓
ExecutionEngine
      ↓
AgentExecutor
```

Then the type system reinforces the security architecture.

---

## Phase 8 — Prove `ORIGIN_RUNTIME` cannot be selected by agents

This needs a test like:

```text
agent code
   ↓
attempt ORIGIN_RUNTIME
   ↓
DENIED
```

And:

```text
trusted runtime
   ↓
ORIGIN_RUNTIME
   ↓
allowed
```

The origin should be assigned by the executor itself, not supplied by generated code.

---

## Phase 9 — Change public defaults

I'd recommend:

```text
general API       → data_analysis
secure API        → data_analysis
explicit trusted  → permissive
```

rather than:

```text
general API       → permissive
secure API        → data_analysis
```

The secure behavior should be the default.

---

## Phase 10 — Worker security profiles

The pool should eventually become:

```text
KernelPool
   │
   ├── trusted profile
   │     └── reusable
   │
   ├── restricted profile
   │     └── reusable with strong reset
   │
   └── hostile profile
         └── ephemeral
```

A task should never choose a worker solely because it is idle.

Selection should include:

```text
security_profile
capabilities
tenant
resource policy
```

---

## Phase 11 — OS isolation

Only after the above is fixed should we make the jump to real hostile-code isolation.

Target:

```text
ExecutionEngine
      ↓
SandboxLauncher
      ↓
isolated worker
      ├── filesystem restriction
      ├── network restriction
      ├── process restriction
      ├── memory limit
      ├── CPU limit
      └── execution timeout
```

Potential Linux mechanisms include:

```text
namespaces
cgroups
seccomp
read-only root filesystem
private temporary filesystem
network namespace
```

The exact mechanism should depend on Kerno's deployment targets.

---

## Phase 12 — Test the complete invariant

The final test matrix should be:

```text
                    Engine   Policy   Audit   Sandbox
run()                 ✓        ✓        ✓       config
run_with_pool()       ✓        ✓        ✓       config
Session.run()         ✓        ✓        ✓       config
custom pipeline       ✓        ✓        ✓       config
streaming             ✓        ✓        ✓       config
multi-agent           ✓        ✓        ✓       config
retry                 ✓        ✓        ✓       same
parallel              ✓        ✓        ✓       same
skill                 ✓        ✓        ✓       same
plugin                 ✓        ✓        ✓       same
```

The important part is that **every row uses the same execution authority**.

---

## The final architecture

```text
                       ┌──────────────┐
                       │     Agent    │
                       └──────┬───────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ ExecutionContext │
                    └────────┬─────────┘
                             │
             ┌───────────────┴────────────────┐
             │                                │
             ▼                                ▼
       SecurityPolicy                    Capabilities
             │                                │
             └───────────────┬────────────────┘
                             ▼
                    ┌──────────────────┐
                    │ ExecutionEngine  │
                    └────────┬─────────┘
                             │
                       authorized
                         Executor
                             │
                             ▼
                    ┌──────────────────┐
                    │ SandboxLauncher  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Jupyter/Python   │
                    └──────────────────┘
```

---

## What I would **not** do

Don't:

- rewrite `ExecuteStep`;
- remove the pool;
- eliminate composable pipelines;
- replace every kernel with a container immediately;
- make the plugin system responsible for security;
- depend exclusively on AST blacklists;
- treat `reset_namespace()` as a sandbox;
- make `permissive` the public default.

The existing architecture is close enough that a **small security-boundary refactor** is preferable to a rewrite.

### The next concrete step

**Patch `Session` first**, then add regression tests proving:

```text
Session
→ ExecutionEngine
→ ExecutionRecord
→ no raw KernelRuntime exposed
```

After that, audit `ORIGIN_RUNTIME` and the skill/plugin paths. Those are the last places where a genuinely privileged execution route could undermine the otherwise solid `ExecutionEngine` design.

---

## Important correction: the `ORIGIN_RUNTIME` audit is revealing a **branch-version mismatch**

I checked the actual branch `arena/01a0064f-kerno` directly.

There is **no `ExecutionEngine` exported from `kerno.security` on this branch**. The security package currently exports `AllowList`, `CapabilityBroker`, capability profiles, `SecretBroker`, and related primitives, but not an `ExecutionEngine`.That means I need to correct an important part of the previous audit: some of the earlier `ExecutionEngine` evidence was evidently from a different repository state/commit than the exact branch you gave me.

### This changes the audit status

We should **not** claim:

> "the main `run()` path is confirmed protected by `ExecutionEngine`"

until we verify that against the exact branch.

The branch itself currently shows:

```text
kerno.security
 ├── AllowList
 ├── CapabilityBroker
 ├── SecretBroker
 ├── InputSanitizer
 └── capability profiles
```

with no exported `ExecutionEngine`.---

## 1. This is actually more important than the previous finding

The correct question is now:

```text
Where is ExecutionEngine defined, if anywhere,
on arena/01a0064f-kerno?
```

The repository-wide search for the literal `ExecutionEngine` did not return a result on the connected GitHub index.

So there are three possibilities:

### A

It doesn't exist on this branch.

### B

It exists under a different name.

### C

The previous implementation existed on another commit/branch and was not merged into `arena/01a0064f-kerno`.

We must distinguish these before changing anything.

---

## 2. What definitely exists

The branch has a substantial capability system.

`kerno.security.capabilities` exports profiles including:

```text
PROFILE_READ_ONLY
PROFILE_DATA_ANALYSIS
PROFILE_RESEARCH
PROFILE_TRUSTED
```

and capabilities such as:

```text
CAP_KERNEL_EXECUTE
CAP_FILESYSTEM_READ
CAP_FILESYSTEM_WRITE
CAP_NETWORK_CONNECT
CAP_PROCESS_SPAWN
CAP_PACKAGE_IMPORT
CAP_SECRET_READ
CAP_HUMAN_APPROVAL
```That's useful—but a capability vocabulary is not automatically an execution enforcement point.

---

## 3. Capability declaration ≠ capability enforcement

The intended model appears to be:

```text
Capability
     ↓
CapabilityBroker
     ↓
authorization
```

But we still need to prove:

```text
agent-generated code
     ↓
CAP_KERNEL_EXECUTE
     ↓
broker
     ↓
KernelRuntime
```

rather than:

```text
agent-generated code
     ↓
KernelRuntime.execute()
```

directly.

That is the decisive question.

---

## 4. So we're going one layer lower

The next audit should trace:

```text
CAP_KERNEL_EXECUTE
```

from definition → grant → check → actual kernel execution.

Specifically:

```text
CAP_KERNEL_EXECUTE
       │
       ▼
CapabilityBroker
       │
       ▼
authorize()
       │
       ▼
Executor
       │
       ▼
KernelRuntime.execute()
```

If one link is missing, the capability system may be mostly declarative.

---

## 5. The security package layout is revealing

The exact branch contains:

```text
kerno/security/
    __init__.py
    allowlist.py
    capabilities.py
    sanitizer.py
    secrets.py
```There is no obvious:

```text
execution.py
executor.py
engine.py
sandbox.py
```

inside that package.

That strongly suggests the security architecture is currently **policy primitives + execution integration**, rather than a dedicated central engine.

---

## 6. This makes the `Session` concern more serious

Previously we classified the local session as a bypass around `ExecutionEngine`.

The more accurate statement now is:

> **The branch appears to have no universally exported execution choke point at all, unless another module provides an equivalent mechanism under a different name.**

So the audit must identify the actual equivalent before assigning severity.

---

## 7. The next search target is therefore `CAP_KERNEL_EXECUTE`

This is much more reliable than searching for `ORIGIN_RUNTIME`.

We need to find:

```text
CAP_KERNEL_EXECUTE
```

and inspect every use.

The classification will be:

| Location | What it does |
|---|---|
| definition | declares capability |
| profile | grants capability |
| broker | authorizes capability |
| executor | enforces capability |
| kernel | performs execution |
| test | proves invariant |

The most important row is **executor/enforcement**.

---

## 8. The ideal result

We want to find something like:

```python
if not broker.authorize(CAP_KERNEL_EXECUTE):
    raise CapabilityViolation(...)
```

immediately before:

```python
kernel.execute(code)
```

Then we can say:

```text
🟢 capability enforcement exists
```

If instead we find:

```python
kernel.execute(code)
```

without a preceding broker check:

```text
🔴 capability declaration is not an execution boundary
```

---

## 9. We also need to inspect `PROFILE_TRUSTED`

This is potentially the most dangerous profile.

The branch exports:

```text
PROFILE_TRUSTED
```That's perfectly legitimate for infrastructure.

But the critical question is:

> Who can obtain a trusted grant?

The dangerous design would be:

```text
Agent
 ↓
skill
 ↓
grant_profile(PROFILE_TRUSTED)
 ↓
CAP_PROCESS_SPAWN
CAP_NETWORK_CONNECT
CAP_FILESYSTEM_WRITE
...
```

The safe design is:

```text
Host administrator
 ↓
trusted configuration
 ↓
PROFILE_TRUSTED
```

and agents cannot mint it.

---

## 10. `grant_profile()` deserves special attention

The public export:

```text
grant_profile
```

is interesting.

It suggests callers can construct a capability grant from a profile.

That's not necessarily unsafe.

But we need to determine whether:

```text
grant_profile(PROFILE_TRUSTED)
```

is available to arbitrary application/agent code.

If it is, then the capability system has a **privilege minting problem**.

---

## 11. Security profile should not be a self-service capability

The safe rule is:

```text
agent requests capability
        ↓
broker evaluates policy
        ↓
broker grants/denies
```

Not:

```text
agent chooses profile
        ↓
profile grants capabilities
```

In other words:

> **Profiles are policy inputs, not privileges that an agent should be able to manufacture.**

---

## 12. We should also inspect `CAP_HUMAN_APPROVAL`

This capability is especially useful because it tells us whether the project has a genuine privileged-action model.

The expected flow is:

```text
agent
 ↓
requests privileged capability
 ↓
CapabilityBroker
 ↓
human approval
 ↓
temporary grant
 ↓
execution
```

If that exists, it gives us a strong foundation for privileged execution.

---

## 13. The current architectural picture should therefore be revised

Instead of the previously stated:

```text
Agent
 ↓
ExecutionEngine
 ↓
Kernel
```

the verified branch currently looks more like:

```text
Agent
 │
 ▼
Pipeline / Executor
 │
 ├── AllowList
 ├── CapabilityBroker
 ├── SecretBroker
 └── KernelRuntime
```

The question is whether those components are **actually mandatory** or merely available.

---

## 14. This distinction is crucial

Having:

```text
AllowList
CapabilityBroker
SecretBroker
```

in the repository is not sufficient.

We need:

```text
                    Agent
                      │
                      ▼
              Mandatory Executor
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
      AllowList   Capability   Secret
                   Broker       Broker
          │           │           │
          └───────────┼───────────┘
                      ▼
                KernelRuntime
```

If a custom pipeline can skip that layer, security remains optional.

---

## 15. New audit status

I would now record:

### **A-SEC-01 — Central execution authority**

**Status:  unresolved**

We cannot yet prove that this branch has a universal execution choke point.

### **A-SEC-02 — Capability model**

**Status:  confirmed**

Capability definitions/profiles exist.### **A-SEC-03 — Capability enforcement**

**Status:  unresolved**

Need to trace `CAP_KERNEL_EXECUTE`.

### **A-SEC-04 — Trusted-profile acquisition**

**Status:  unresolved**

Need to trace `grant_profile()`.

### **A-SEC-05 — OS sandbox**

**Status:  not demonstrated**

Still unresolved.

---

## 16. This is actually a better audit position

Rather than prematurely saying:

> "ExecutionEngine protects the project"

we now have an evidence-based statement:

> **The branch contains substantial security primitives, but the existence of those primitives alone does not prove that all agent execution is forced through them.**

That's exactly the distinction a deep repository audit should make.

---

## 17. Next target

The next concrete trace is:

```text
CAP_KERNEL_EXECUTE
        ↓
CapabilityBroker
        ↓
grant_profile()
        ↓
Executor / ExecuteStep
        ↓
KernelRuntime.execute()
```

Then immediately after that:

```text
PROFILE_TRUSTED
PROFILE_RESEARCH
PROFILE_DATA_ANALYSIS
PROFILE_READ_ONLY
```

and finally:

```text
Session
run()
run_with_pool()
server
streaming
skills
plugins
custom pipeline
```

Only after this trace will we assign the final severity.

**This is the right next step because it will tell us whether Kerno has a real mandatory security boundary—or only a collection of security components that callers can choose to use.**

---

## The audit should now move from **security components → actual enforcement**

We have enough evidence to stop discussing `ExecutionEngine` as if it were confirmed on this branch. The next phase is to establish the **actual execution chain** on `arena/01a0064f-kerno`.

### Target chain

```text
Agent
  │
  ▼
Pipeline / Step
  │
  ▼
Executor
  │
  ├── AllowList?
  ├── CapabilityBroker?
  ├── SecretBroker?
  └── Audit?
  │
  ▼
KernelRuntime.execute()
```

The critical question is:

> **What object actually sits immediately before `KernelRuntime.execute()`?**

---

## 1. First invariant: `CAP_KERNEL_EXECUTE`

The capability exists:

```text
CAP_KERNEL_EXECUTE
```

But its presence in `capabilities.py` proves only that Kerno **defines the concept**.

We need this:

```python
if not broker.authorize(CAP_KERNEL_EXECUTE, ...):
    raise CapabilityError(...)
```

before execution.

If instead execution looks like:

```python
kernel.execute(code)
```

with the broker never consulted, then:

```text
Capability system = declarative
Execution boundary = missing
```

That would be a major finding.

---

## 2. Second invariant: capability grants

The profile hierarchy needs to be treated as policy:

```text
PROFILE_READ_ONLY
PROFILE_DATA_ANALYSIS
PROFILE_RESEARCH
PROFILE_TRUSTED
```

A safe architecture is:

```text
Application policy
       ↓
selected profile
       ↓
CapabilityBroker
       ↓
temporary authorization
       ↓
execution
```

An unsafe architecture would allow:

```text
Agent
  ↓
grant_profile(PROFILE_TRUSTED)
  ↓
CAP_PROCESS_SPAWN
CAP_NETWORK_CONNECT
CAP_FILESYSTEM_WRITE
```

So `grant_profile()` must be treated as a **privilege boundary**, not a convenience helper.

---

## 3. Third invariant: the raw kernel

The most important API boundary should eventually be:

```text
KernelRuntime
    │
    │ private
    ▼
Kerno execution layer
    │
    ▼
Agent-facing Executor
```

not:

```text
KernelRuntime
    ↓
custom Pipeline
    ↓
agent
```

If `KernelRuntime` is freely accepted by public pipeline APIs, security is opt-in.

---

## 4. `Session` remains the key composability test

The `Session` API is where we should prove the invariant.

We need to answer:

```text
Session.with_kernel()
       ↓
what object is passed to ExecuteStep?
```

If the answer is:

```text
KernelRuntime
```

then the local composition API is bypassing whatever capability machinery exists elsewhere.

If the answer is:

```text
authorized Executor
```

then Session is protected.

---

## 5. Skills are the second major boundary

Kerno supports skills, so we need to distinguish:

```text
trusted installed skill
```

from:

```text
agent-generated skill
```

A trusted skill can legitimately operate with elevated privileges.

A generated skill should be treated as agent code.

The dangerous model is:

```text
skill file
 ↓
kernel.execute()
```

with no policy check.

The safe model is:

```text
skill
 ↓
agent executor
 ↓
policy
 ↓
kernel
```

---

## 6. Plugins require the same distinction

Plugins are different from skills because plugins can potentially extend the runtime itself.

Therefore:

```text
Plugin = trusted host extension
```

should be the default assumption.

An LLM should not be able to turn:

```text
generated code
```

into:

```text
runtime plugin
```

without a host-level approval boundary.

---

## 7. Secrets are another independent boundary

The repository has `SecretBroker`.

That is good, but we need to ensure that:

```text
CAP_SECRET_READ
```

doesn't simply become:

```text
environment.get(...)
```

inside arbitrary Python.

The desired flow is:

```text
Agent
 ↓
SecretBroker
 ↓
authorized secret
 ↓
redacted/audited result
```

not:

```text
Agent Python
 ↓
os.environ
 ↓
API_KEY
```

This is especially important because Python kernel execution inherently has access to the process environment unless OS isolation is added.

---

## 8. Therefore capability control has two layers

### Logical layer

```text
AllowList
CapabilityBroker
SecretBroker
```

### OS layer

```text
process
filesystem
environment
network
subprocess
```

The first cannot fully replace the second.

For example:

```text
CAP_NETWORK_CONNECT = denied
```

doesn't physically prevent:

```python
socket.connect(...)
```

unless the execution layer intercepts it **or** the worker is OS-isolated.

---

## 9. The security model should explicitly state this

I'd document:

> **Kerno's capability system is an authorization mechanism, not a Python sandbox.**

And:

> **Untrusted Python execution requires process/OS isolation in addition to logical capability enforcement.**

That prevents users from interpreting `PROFILE_READ_ONLY` as equivalent to a hardened sandbox.

---

## 10. The final architecture should have three boundaries

```text
                 ┌──────────────────┐
                 │       Agent      │
                 └────────┬─────────┘
                          │
                 Logical security
                          │
                          ▼
                 ┌──────────────────┐
                 │ CapabilityBroker │
                 └────────┬─────────┘
                          │
                    authorized
                          │
                          ▼
                 ┌──────────────────┐
                 │    Executor      │
                 └────────┬─────────┘
                          │
                     OS boundary
                          │
                          ▼
                 ┌──────────────────┐
                 │ isolated worker  │
                 └────────┬─────────┘
                          │
                          ▼
                   Python kernel
```

---

## 11. What counts as a real PASS

We should only mark the execution-security gate **PASS** if all of these are demonstrated:

```text
[ ] CAP_KERNEL_EXECUTE is checked
[ ] Capability grants cannot be self-escalated
[ ] raw KernelRuntime cannot enter agent pipelines
[ ] Session uses the same enforcement path
[ ] custom pipelines cannot bypass it
[ ] skills have an explicit trust model
[ ] plugins cannot be agent-created privileged extensions
[ ] secrets do not leak through direct environment access
[ ] privileged/runtime operations are host-controlled
[ ] execution produces an auditable record
[ ] hostile workloads have OS-level isolation
```

Anything else should remain:

```text
UNVERIFIED
```

rather than `PASS`.

---

## 12. This also gives us a clean remediation order

### P0 — execution bypass

Fix if raw agent execution can reach the kernel without authorization.

### P1 — privilege escalation

Fix if an agent can obtain:

```text
PROFILE_TRUSTED
CAP_PROCESS_SPAWN
CAP_NETWORK_CONNECT
CAP_FILESYSTEM_WRITE
CAP_SECRET_READ
```

without host authorization.

### P1 — secret exposure

Fix any path from:

```text
agent Python → environment/filesystem → secret
```

that bypasses `SecretBroker`.

### P2 — sandboxing

Add OS isolation for genuinely untrusted workloads.

### P2 — lifecycle

Ensure pooled workers cannot leak state between security principals.

---

## 13. Most important next repository operation

The next inspection should be extremely narrow:

```text
CAP_KERNEL_EXECUTE
```

Trace every occurrence.

Then:

```text
grant_profile
```

Then:

```text
KernelRuntime.execute
```

Then:

```text
Session
ExecuteStep
skills
plugins
```

That produces the **actual call graph**.

Only after that should we modify the code.

---

## Updated audit principle

We are now following a stricter evidence rule:

```text
Declared capability
       ≠
enforced capability

Security object exists
       ≠
security boundary exists

Sandbox terminology
       ≠
OS isolation

Test exists
       ≠
test passed

Documentation says protected
       ≠
runtime is protected
```

That standard is especially important for Kerno because the project is explicitly trying to provide a programmable agent execution environment.

**Next: trace `CAP_KERNEL_EXECUTE → CapabilityBroker → actual `KernelRuntime.execute()` call sites, then produce the definitive execution/security call graph.**

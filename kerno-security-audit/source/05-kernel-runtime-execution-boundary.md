# 05 — Kernel Runtime Execution Boundary

## Next stage: `KernelRuntime` — the real execution boundary

I checked the actual `kerno/kernel/runtime.py` on your `arena/01a0064f-kerno` branch. This confirms several important things and changes the risk assessment.

The runtime is a **real Jupyter kernel process**, managed through `jupyter_client.KernelManager`/`KernelClient`, not an in-process `exec()` wrapper. <sup>[source]</sup>

That is a strong architectural choice.

---

## 1. Kerno has a process boundary

The lifecycle is:

```text
Kerno process
     │
     ▼
KernelManager
     │
     ▼
Python kernel process
     │
     ▼
KernelClient
     │
     ▼
execute(code)
```

`start()` creates a `KernelManager`, starts the kernel, creates its client, starts channels, and waits for readiness. <sup>[source]</sup>

So Kerno's model is not:

```python
exec(code)
```

inside the agent's own process.

It is:

```text
Agent
 │
 ├── Kerno runtime
 │
 │     IPC
 │
 ▼
separate Python kernel
```

That provides a useful **fault-containment boundary**.

It does **not**, however, constitute a security sandbox by itself. The kernel process still has the host's permissions.

---

## 2. This explains the SkillRegistry design

Earlier we saw:

```text
SkillRegistry
     │
     ▼
KernelRuntime.execute()
     │
     ▼
Jupyter kernel
```

Now we can see the actual boundary:

```text
                 Agent
                   │
                   ▼
             SkillRegistry
                   │
              generated code
                   │
                   ▼
             KernelRuntime
                   │
             Jupyter IPC
                   │
                   ▼
           separate Python
              process
```

This is a much better architecture than executing arbitrary generated code directly inside the Kerno controller.

---

## 3. Timeout handling is surprisingly mature

`KernelRuntime` has two timeout policies:

```text
interrupt
escalate
```

and rejects anything else during initialization. <sup>[source]</sup>

### `interrupt`

The normal path is:

```text
execute
  │
  ▼
collect(...)
  │
  ▼
timeout
  │
  ▼
interrupt()
  │
  ▼
SIGINT / kernel interrupt
```

### `escalate`

There is an explicit escalation ladder:

```text
timeout
   │
   ▼
soft interrupt
   │
   ▼
grace period
   │
   ▼
kernel still alive?
   │
   ├── no → recovery path
   │
   └── yes
         │
         ▼
       kill
         │
         ▼
       restart
```

The implementation calls `proc.kill()` and then attempts a kernel restart. <sup>[source]</sup>

This is substantially better than simply allowing an agent-generated infinite loop to hang forever.

---

## 4. But `_escalate_timeout()` has an important weakness

The code does:

```python
proc.kill()
proc.wait(...)
```

and then:

```python
self.restart()
```

But the restart operation depends on `self._km` still being in a usable state.

If the underlying process has been forcibly killed, the behavior of:

```python
KernelManager.restart_kernel()
```

needs an integration test.

The code does catch failure and marks:

```text
DEAD
```

which is good. <sup>[source]</sup>

But we should explicitly test:

```text
infinite loop
    ↓
timeout
    ↓
SIGINT
    ↓
SIGKILL
    ↓
restart
    ↓
READY
```

and:

```text
kernel refuses restart
    ↓
DEAD
```

before declaring this recovery mechanism proven.

---

## 5. Kernel state management is well thought out

The runtime has explicit states:

```text
CLOSED
STARTING
READY
BUSY
INTERRUPTING
RESTARTING
DEAD
```

The `state` property also implements **sticky death**.

Once the runtime observes:

```text
kernel process = dead
```

it transitions to:

```text
DEAD
```

rather than repeatedly reporting `READY`. <sup>[source]</sup>

That is a good reliability decision.

---

## 6. Generation numbers are also important

Every restart increments:

```python
self._generation += 1
```

<sup>[source]</sup>

So Kerno can distinguish:

```text
kernel generation 1
```

from:

```text
kernel generation 2
```

This is valuable for agent memory and observability.

For example:

```text
Task #42
  kernel_generation = 7
```

means something very different from:

```text
Task #42
  kernel_generation = 1
```

if the task is trying to reason about state persistence.

---

## 7. But kernel restart destroys in-memory state

This is a critical semantic consequence.

Suppose:

```python
x = 42
```

exists in generation 1.

Then:

```text
kernel dies
   ↓
restart
   ↓
generation 2
```

and:

```python
x
```

will no longer exist unless Kerno restores it.

Therefore:

```text
generation
```

should eventually become part of the state/memory contract.

The architecture needs to distinguish:

```text
Kerno persistent state
```

from:

```text
kernel ephemeral state
```

Something like:

```text
                Kerno
                  │
        ┌─────────┴─────────┐
        │                   │
   persistent            kernel
     state                state
        │                   │
        │              generation N
        │                   │
        │              generation N+1
        │                   │
        └────── restore ────┘
```

Otherwise an agent can believe that a variable/tool/result still exists when a kernel restart silently removed it.

---

## 8. `reset_namespace()` is intentionally destructive

The runtime exposes:

```python
reset_namespace()
```

implemented through:

```text
%reset -f
```

<sup>[source]</sup>

This is useful, but it should be treated as a **state-destroying operation**.

For an agent, I'd want the event stream to record:

```text
namespace_reset
kernel_id
generation
timestamp
```

Otherwise debugging becomes difficult:

```text
Why did my agent lose variable X?
```

Possible answer:

```text
An implicit namespace reset occurred 4 turns earlier.
```

---

## 9. `execute()` has good telemetry

Each execution records:

```text
kernel.id
kernel.generation
cell.num
cell.code_preview
cell.silent
```

and later:

```text
cell.duration_ms
cell.had_error
cell.output_bytes
cell.n_images
error.ename
error.evalue
```

<sup>[source]</sup>

This is excellent for observability.

The execution pipeline is essentially:

```text
code
 │
 ▼
trace span
 │
 ▼
Jupyter execute_request
 │
 ▼
collect outputs
 │
 ▼
duration/error metrics
 │
 ▼
telemetry
```

That means Kerno can eventually answer questions like:

```text
Which skill generated the slowest cells?
Which agent loop caused most errors?
How often does kernel generation change?
How many cells execute before failure?
```

---

## 10. But `code_preview` creates a telemetry privacy/security consideration

The runtime records:

```python
"cell.code_preview": code[:80]
```

<sup>[source]</sup>

This is useful for debugging.

But code can contain:

```text
API keys
tokens
passwords
PII
private paths
database credentials
```

For example:

```python
api_key = "sk-..."
```

The first 80 characters could potentially enter telemetry.

So the telemetry layer should eventually have:

```text
redaction
```

before recording arbitrary cell source.

I'd recommend:

```text
raw code
   │
   ▼
secret redactor
   │
   ▼
safe preview
   │
   ▼
telemetry
```

rather than sending raw previews to tracing backends.

This becomes especially important because Kerno is an **agent runtime**, where generated code may contain dynamically constructed secrets.

---

## 11. `execute_silent()` is useful but semantically important

It calls:

```python
execute(..., silent=True)
```

and returns:

```text
stdout.strip()
```

<sup>[source]</sup>

This is convenient for internal operations.

But the runtime currently uses `silent` for both:

```text
execution output behavior
```

and:

```text
cell accounting/metrics behavior
```

because the cell counter/metrics path is conditional on `not silent`.

That deserves clarification.

A cell executed silently is still an execution.

I'd prefer metrics to distinguish:

```text
cell.silent = true
```

rather than excluding it from the primary execution accounting.

Otherwise:

```text
cells_executed
```

may mean:

> visible/non-silent cells

rather than:

> all cells actually executed.

That semantic difference can produce misleading telemetry.

---

## 12. `stream_execute()` has another accounting inconsistency

`execute()` increments `_cell_count` only on the non-silent path.

But:

```python
stream_execute()
```

immediately does:

```python
self._cell_count += 1
```

<sup>[source]</sup>

So the runtime currently has multiple execution paths with slightly different accounting semantics.

This should be normalized.

Ideal model:

```text
_every_ execution
      │
      ├── cell ID
      ├── cell count
      ├── generation
      ├── duration
      ├── errors
      └── telemetry
```

regardless of whether the caller requests streaming or silent output.

---

## 13. Cancellation deserves explicit testing

`execute()` accepts:

```python
cancel_event
```

and passes it to `collect()`. <sup>[source]</sup>

That is good.

But we need to verify the complete path:

```text
agent cancellation
       │
       ▼
cancel_event.set()
       │
       ▼
collect()
       │
       ▼
interrupt
       │
       ▼
execution terminates
       │
       ▼
runtime READY
```

Potential failure:

```text
cancel
  ↓
kernel interrupted
  ↓
runtime state incorrectly remains BUSY
```

The `finally` block makes the normal `execute()` path return to `READY`, which is good. <sup>[source]</sup>

Still, this should be an integration test rather than an assumption.

---

## 14. The biggest architectural distinction: execution safety vs isolation

At this point we can state this precisely.

Kerno has:

### Process isolation

```text
controller
   │
   │ IPC
   ▼
kernel process
```

### Timeout containment

```text
hung code
   ↓
interrupt
   ↓
kill/restart
```

### Namespace protection

```text
registered skill names
       ↓
protected namespace
```

### Integrity metadata

```text
skill source
   ↓
hash
```

But it does **not automatically have**:

```text
OS sandbox
container isolation
seccomp
filesystem sandbox
network policy
privilege dropping
resource quotas
capability-based Python runtime
```

So the accurate security statement should be:

> **Kerno provides a managed kernel execution boundary with timeout/restart controls and skill namespace protection; it is not yet an OS-level sandbox.**

That distinction should probably appear in the project documentation.

---

## 15. Recommended security model

For an agent runtime, I'd evolve the architecture toward:

```text
                    Agent
                      │
                      ▼
                Skill Registry
                      │
               trust decision
                      │
          ┌───────────┴───────────┐
          │                       │
       trusted                 untrusted
          │                       │
          ▼                       ▼
    normal kernel          restricted kernel
                                  │
                         ┌────────┼────────┐
                         ▼        ▼        ▼
                       FS       network   CPU/RAM
                      policy     policy    limits
```

The kernel itself can then be treated as:

```text
ephemeral compute sandbox
```

while persistence lives outside it.

---

## 16. Revised audit priorities

After inspecting the runtime, I would change the priorities.

### P0 — Fix

**Skill integrity verification**

The source hash/runtime-object hash mismatch identified earlier needs correction before integrity verification is considered reliable.

### P1 — Verify with real integration tests

1. Kernel timeout → interrupt.
2. Timeout escalation → kill → restart.
3. Dead kernel → `DEAD`.
4. Restart → generation increment.
5. Namespace protection inside real IPython.
6. Cancellation.
7. State loss across restart.
8. Concurrent/overlapping execution behavior.

### P1 — Security

Add explicit documentation:

```text
Kerno kernel ≠ security sandbox
```

and define the threat model.

### P2 — Reliability

Normalize execution accounting between:

```text
execute()
execute_silent()
stream_execute()
```

### P2 — Observability

Add telemetry redaction for:

```text
cell.code_preview
error.evalue
```

because generated code/errors may contain secrets.

---

## 17. The architecture is stronger than it initially appeared

The current picture is now:

```text
                         KERNO
                           │
                           ▼
                     Agent / Loop
                           │
                    Skill Composer
                           │
                    Skill Registry
                           │
                 trust + dependencies
                           │
                           ▼
                    Kernel Runtime
                           │
             ┌─────────────┴─────────────┐
             │                           │
          telemetry                 lifecycle
             │                           │
             │                ┌──────────┼──────────┐
             │                ▼          ▼          ▼
             │              start     timeout    restart
             │                           │
             ▼                           ▼
        observability             Jupyter Kernel
                                         │
                                  Python execution
                                         │
                           ┌─────────────┼─────────────┐
                           ▼             ▼             ▼
                         Data         Analysis       Tools
```

That's a credible foundation for a **kernel-native agent runtime**.

The most important thing now is not adding more features. It's making the **execution contract, dependency contract, integrity contract, and recovery contract formally correct and testable**.

The next logical layer is the **kernel pool and multi-agent/loop interaction** (`kerno/kernel/pool.py`, `kerno/loop/*`, and the communication layer). That's where we'll find out whether multiple agents can safely share or acquire kernels, how state is isolated between agents, and whether the current lifecycle guarantees remain valid under concurrency. <sup>[source]</sup>

[← Back to index](./README.md) | [Next section →](./07-isolation-and-communication.md)

## [20] USER

Continue 

---

## [21] CHATGPT (gpt-5-6)

<details>
<summary><strong>🛠️ api_tool.list_resources</strong></summary>

**Input:**

```json
{"paths":["GitHub"],"query":"fetch_file"}
```

</details>

*(Tool execution: api_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/kernel/pool.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

---

## [22] CHATGPT (gpt-5-6)

## Next: `KernelPool` — concurrency, isolation, and lifecycle audit

I inspected the actual `kerno/kernel/pool.py`. This is a substantial subsystem: it tries to solve **cold starts, state contamination, memory growth, hung kernels, and kernel replacement** simultaneously. <sup>[source]</sup>

The design is good in principle, but I found several issues that are more important than the earlier dependency concerns.

---

# 1. The intended pool model

The architecture is:

<details>
<summary><strong>💻 Code Block (text) — 26 lines</strong></summary>

```text
                         KernelPool
                             │
             ┌───────────────┼───────────────┐
             ▼               ▼               ▼
          Kernel 1         Kernel 2        Kernel 3
             │               │               │
          AVAILABLE       AVAILABLE       AVAILABLE
             │
             ▼
          acquire()
             │
             ▼
          ACQUIRED
             │
          task-123
             │
             ▼
          release()
             │
       ┌─────┴─────┐
       ▼           ▼
    soft reset   hard reset
       │           │
       └─────┬─────┘
             ▼
         AVAILABLE
```

</details>

The pool also supports overflow kernels and automatic retirement. <sup>[source]</sup>

That is a sensible architecture for an agent system where kernel startup takes seconds.

---

# 2. Good: task ownership is explicit

`acquire(task_id)` associates a kernel with a specific task:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
task-123 → k-0001
```

</details>

and `_active` tracks the relationship.

It also rejects duplicate acquisition:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if task_id in self._active:
    raise ValueError(...)
```

</details>

This is good because it prevents:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
task A
  │
  ├── kernel 1
  │
  └── accidentally acquire kernel 2
```

</details>

under the same logical task.

---

# 3. Good: release has semantic reasons

The API distinguishes:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
complete
error
timeout
oom
```

</details>

That is excellent.

The policy is:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

```text
complete
   │
   ├── expired → retire
   └── healthy → soft reset

error / timeout
   │
   └── hard reset

oom
   │
   └── retire without replacement
```

</details>

<sup>[source]</sup>

This is much better than treating every task completion identically.

---

# 4. Critical issue: stale kernels can remain in `_available`

This is the most important bug I found in the pool.

The monitor does:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if pk.state == KernelState.AVAILABLE and pk.is_expired:
    self._retire(pk, replace=True)
```

</details>

But `_retire()` removes the kernel from:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._all
```

</details>

It does **not remove it from**:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._available
```

</details>

<sup>[source]</sup>

So consider:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
_available:
[k-0001, k-0002, k-0003]
```

</details>

Monitor sees:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
k-0001 expired
```

</details>

and retires it.

Now:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
_all:
[k-0002, k-0003]
```

</details>

but:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
_available:
[k-0001, k-0002, k-0003]
```

</details>

The queue still contains the dead kernel.

Later:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk = self._available.get(...)
```

</details>

can return `k-0001`.

The health check notices it's unhealthy:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
if not pk.is_healthy:
```

</details>

and attempts to create a replacement.

So there is some recovery.

But this leaves the queue containing stale objects and creates a subtle lifecycle/accounting problem.

### Better design

Never directly remove an available object from the pool without also removing/invalidating its queue entry.

A robust approach is **generation/state validation at dequeue**:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
queue item
    │
    ▼
is object still AVAILABLE?
    │
    ├── yes → acquire
    └── no  → discard and retry
```

</details>

The current health check partially provides this, but the queue should explicitly tolerate stale entries.

---

# 5. More serious: `_create_kernel()` can return DEAD

This path is problematic:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk = self._create_kernel()
```

</details>

`_create_kernel()` catches startup/bootstrap failure and does:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
pk.state = DEAD
```

</details>

but still returns `pk`. <sup>[source]</sup>

Then `acquire()` does:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
health check
    │
    ▼
not healthy
    │
    ▼
shutdown
    │
    ▼
_create_kernel()
```

</details>

But there is **no second guaranteed health validation** after that replacement.

So the logic can theoretically become:

<details>
<summary><strong>💻 Code Block (text) — 17 lines</strong></summary>

```text
create kernel
   │
   └── startup fails
          │
          ▼
       DEAD
          │
          ▼
     acquire receives it
          │
          ▼
   create replacement
          │
          └── replacement also fails
                  │
                  ▼
              DEAD kernel returned
```

</details>

The API should instead have `_create_kernel()` return either:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
PooledKernel
```

</details>

that is definitely `AVAILABLE`, or:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
None / exception
```

</details>

on failure.

For example:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
_create_kernel()
      │
      ├── success → AVAILABLE
      │
      └── failure → PoolKernelStartError
```

</details>

Then `acquire()` can properly decide whether to retry.

---

# 6. Overflow accounting is ambiguous

The code says:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
max_overflow = 10
```

</details>

and checks:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
len(self._active) < self.max_overflow
```

</details>

before creating an overflow kernel. <sup>[source]</sup>

But this does **not mean "at most 10 overflow kernels."**

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
size = 3
max_overflow = 10
```

</details>

The pool can have:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
3 warm kernels
+
10 active overflow kernels
=
13 kernels
```

</details>

which may be what was intended.

But the name `max_overflow` could also be interpreted as:

> maximum total kernels beyond the configured pool size.

The implementation currently means:

> maximum number of simultaneously active tasks allowed through this particular condition.

That should be made explicit.

I would define:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
max_overflow_kernels
```

</details>

and enforce:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
len(all) - size < max_overflow_kernels
```

</details>

instead.

---

# 7. Memory limits are not actually enforcement

`PooledKernel` defines:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
MAX_MEMORY = 4096.0
```

</details>

and considers the kernel expired if:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
memory > MAX_MEMORY
```

</details>

<sup>[source]</sup>

But this only **detects** excessive memory.

It does not prevent the process from consuming 4 GB.

So:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
MAX_MEMORY
```

</details>

is really:

> retirement threshold

not:

> memory limit.

This distinction matters enormously.

A malicious or buggy skill can still do:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
allocate memory
    ↓
4 GB
    ↓
8 GB
    ↓
16 GB
    ↓
host OOM
```

</details>

before the monitor necessarily notices.

For actual containment, the kernel process needs an OS-level resource limit, cgroup/container, or similar mechanism.

---

# 8. The monitor interval makes lifecycle limits approximate

The monitor runs:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
time.sleep(30)
```

</details>

<sup>[source]</sup>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
MAX_LIFETIME = 3600
```

</details>

does not mean:

> kernel is retired exactly at 3600 seconds.

It means approximately:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
3600 → 3630 seconds
```

</details>

depending on scheduling.

That's fine if documented as a **soft lifecycle threshold**.

It becomes a problem only if callers treat it as a hard guarantee.

---

# 9. Acquired kernels can exceed lifetime indefinitely

This is subtle.

The monitor checks:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
if pk.state == KernelState.ACQUIRED:
```

</details>

and only warns if the task has run for more than one hour:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
"Consider interrupting."
```

</details>

It does **not actually terminate it**. <sup>[source]</sup>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 22 lines</strong></summary>

```text
task starts
   │
   ▼
kernel ACQUIRED
   │
   ▼
1 hour
   │
   ▼
warning
   │
   ▼
2 hours
   │
   ▼
still ACQUIRED
   │
   ▼
3 hours
   │
   ▼
still ACQUIRED
```

</details>

So `MAX_LIFETIME` applies to retirement of available kernels, but not really to active task execution.

That should be documented or changed.

---

# 10. `release()` starts reset threads asynchronously

For a successful task:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
threading.Thread(
    target=self._soft_reset,
    ...
).start()
```

</details>

<sup>[source]</sup>

This is intentional because the caller doesn't have to wait for cleanup.

But it introduces a state transition:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

```text
release()
   │
   ▼
_active removed
   │
   ▼
RESETTING
   │
   ▼
background reset
   │
   ▼
AVAILABLE
```

</details>

During that window:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
task no longer owns kernel
kernel isn't available
```

</details>

which is okay.

However, there is no explicit reset queue or bounded reset worker pool.

Under heavy load:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
1000 completed tasks
       │
       ▼
1000 reset threads
```

</details>

could theoretically be created.

The pool should eventually use a bounded executor or dedicated reset worker.

---

# 11. `shutdown()` doesn't join the monitor/reset workers

`shutdown()` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._running = False
```

</details>

then shuts down kernels. <sup>[source]</sup>

But the monitor thread is not joined.

So:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
shutdown()
   │
   ├── _running = False
   └── shutdown kernels
          │
          ▼
       returns
          │
          ▼
monitor thread may still be sleeping
```

</details>

Eventually it wakes and exits.

Usually harmless, but a deterministic lifecycle API should ideally provide:

<details>
<summary><strong>💻 Code Block (text) — 19 lines</strong></summary>

```text
shutdown()
   │
   ▼
stop accepting work
   │
   ▼
wait for reset workers
   │
   ▼
stop monitor
   │
   ▼
shutdown kernels
   │
   ▼
join threads
   │
   ▼
return
```

</details>

That matters for tests and clean application shutdown.

---

# 12. `skills_path` is a trust boundary

This is another important security observation.

Bootstrap does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
path.read_text()
```

</details>

and then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
runtime.execute(code, silent=True, timeout=60)
```

</details>

<sup>[source]</sup>

So `skills_path` is effectively:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
filesystem file
       │
       ▼
arbitrary Python source
       │
       ▼
kernel execution
```

</details>

Therefore `skills_path` must be treated as **trusted code**.

The pool should not accept an arbitrary agent-controlled path and execute it.

If Kerno later exposes something like:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pool = KernelPool(skills_path=user_input)
```

</details>

that could become an obvious arbitrary-code-execution vector.

---

# 13. The biggest isolation question: can kernels be reused safely?

The pool's answer is:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
task A
  ↓
kernel 1
  ↓
release
  ↓
reset namespace
  ↓
task B
  ↓
kernel 1
```

</details>

This is efficient.

But safety depends completely on the effectiveness of:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
runtime.reset_namespace()
```

</details>

We need to distinguish:

### Python namespace contamination

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
x = secret
```

</details>

from:

### External side effects

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
write_file(...)
database modification
network request
subprocess
environment changes
```

</details>

A namespace reset cannot undo those.

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
namespace reset ≠ task isolation
```

</details>

This is one of the most important conclusions from the pool audit.

---

# 14. Example of a real contamination problem

Task A:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
import os
os.environ["MODE"] = "production"
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
release
   ↓
reset_namespace
   ↓
task B
```

</details>

The variable/import may disappear.

But:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
process environment
```

</details>

may remain changed.

Likewise:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
open("/tmp/shared", "w").write(...)
```

</details>

is not undone.

And:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
subprocess.run(...)
```

</details>

can modify arbitrary external resources.

Therefore kernel reuse is only safe if Kerno's task model explicitly says:

> **Tasks share the kernel's OS-level side effects.**

or if the kernel process is actually recreated between trust boundaries.

---

# 15. This suggests two pool modes

A very useful architectural refinement would be:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
KernelPool
│
├── warm/reusable
│     │
│     └── fast, trusted tasks
│
└── isolated
      │
      └── fresh kernel per trust boundary
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
REUSE
```

</details>

for:

- internal analytics
- trusted skills
- same-agent sequential work

and:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
FRESH
```

</details>

for:

- untrusted generated code
- different tenants
- sensitive data boundaries
- external plugins

That gives Kerno a meaningful security/performance tradeoff.

---

# 16. Pool invariants should be formalized

The current implementation would benefit enormously from explicit invariants.

For example:

### Invariant A

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Every ACTIVE task has exactly one kernel.
```

</details>

### Invariant B

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
A kernel can belong to at most one ACTIVE task.
```

</details>

### Invariant C

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
AVAILABLE kernels must be healthy.
```

</details>

### Invariant D

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
DEAD kernels cannot appear in AVAILABLE.
```

</details>

### Invariant E

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
A kernel in RESETTING cannot be acquired.
```

</details>

### Invariant F

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Every kernel in _all has exactly one lifecycle state.
```

</details>

### Invariant G

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_shutdown means no future kernel creation.
```

</details>

The current code does not enforce all of these strongly enough.

---

# 17. Recommended pool state machine

I'd formalize:

<details>
<summary><strong>💻 Code Block (text) — 23 lines</strong></summary>

```text
                 ┌─────────────┐
                 │   WARMING   │
                 └──────┬──────┘
                        │ success
                        ▼
                 ┌─────────────┐
          ┌──────│  AVAILABLE  │──────┐
          │      └──────┬──────┘      │
          │             │ acquire      │ expire
          │             ▼              ▼
          │      ┌─────────────┐    RETIRING
          │      │  ACQUIRED   │
          │      └──────┬──────┘
          │             │
          │          release
          │             ▼
          │      ┌─────────────┐
          └──────│  RESETTING  │
                 └──────┬──────┘
                        │
                 ┌──────┴──────┐
                 ▼             ▼
             AVAILABLE       DEAD
```

</details>

And **no direct transition** should allow:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
DEAD → AVAILABLE
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
RESETTING → ACQUIRED
```

</details>

without explicit successful completion.

---

# 18. The pool + runtime now gives us a much clearer security picture

<details>
<summary><strong>💻 Code Block (text) — 23 lines</strong></summary>

```text
                         Agent
                           │
                           ▼
                    Skill Registry
                           │
                    generated Python
                           │
                           ▼
                      Kernel Pool
                           │
                ┌──────────┴──────────┐
                ▼                     ▼
          reusable kernel       fresh kernel
                │                     │
                ▼                     ▼
          KernelRuntime          KernelRuntime
                │                     │
                ▼                     ▼
           Python process       Python process
                │                     │
                └──────────┬──────────┘
                           ▼
                     OS resources
```

</details>

The **real security boundary is still the OS process/environment**, not the skill registry or namespace.

---

# 19. Audit verdict for `KernelPool`

### 🟢 Strong design

- Warm kernel pool.
- Explicit acquire/release ownership.
- Task IDs.
- Overflow support.
- Health monitoring.
- Lifecycle retirement.
- Soft vs hard reset.
- Generation-aware runtime.
- Timeout/interrupt propagation.
- Health reporting.
- Context-manager support.

### 🟠 Correctness issues

- Stale `_available` entries after retirement.
- `_create_kernel()` can return a DEAD object.
- Overflow semantics are ambiguous.
- Reset operations spawn unbounded threads.
- Shutdown is not fully synchronized.
- Lifecycle thresholds are soft, not hard.
- Active tasks aren't actually retired at lifetime expiry.
- Pool invariants aren't explicitly enforced.

### 🔴 Security/architecture issues

- Namespace reset is **not true task isolation**.
- `skills_path` is arbitrary Python execution and must be trusted.
- Memory threshold is detection/retirement, not resource enforcement.
- Reusing a kernel preserves OS-level side effects.
- There is no OS-level sandbox/resource boundary yet.

---

## The next critical subsystem is now clear

We should move from:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
KernelRuntime
      ↓
KernelPool
```

</details>

to:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
KernelPool
      ↓
Agent Loop
      ↓
Observe → Plan → Execute → Reflect → Checkpoint
```

</details>

because that's where **task ownership, cancellation, kernel acquisition, state persistence, and agent memory meet**.

The key question will be:

> **Can Kerno's agent loop guarantee that a task's kernel, skills, state, cancellation, and checkpoint remain consistent when execution fails, times out, or the kernel is restarted?**

That is effectively the **transaction/consistency model of Kerno**, and it is the next major architectural gate.

---

## [23] USER

Continue 

---

## [24] CHATGPT (gpt-5-6)

<details>
<summary><strong>🛠️ api_tool.list_resources</strong></summary>

**Input:**

```json
{"paths":["GitHub"],"query":"fetch_file"}
```

</details>

*(Tool execution: api_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"class AgentLoop","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/loop/multi_agent.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

## Next: Multi-Agent Loop — the consistency model

This is the most consequential layer so far.

The branch explicitly implements **two different multi-agent isolation models**:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
shared
isolated
```

</details>

and also has a separate `SharedMemory`/`AgentBus` mechanism. <sup>[source]</sup>

That means Kerno is already trying to solve the problem we identified in the pool audit:

> How do multiple agents share information without accidentally sharing everything?

---

# 1. Shared mode

The simple mode is:

<details>
<summary><strong>💻 Code Block (text) — 14 lines</strong></summary>

```text
Agent A
   │
   ▼
┌──────────────────────┐
│   SAME KERNEL        │
│                      │
│ results_*            │
│ model_*              │
│ critique_*           │
│ df_*                 │
└──────────────────────┘
   ▲
   │
Agent B
```

</details>

The documentation is explicit:

> "multiple specialized LLMs operating on one shared kernel."

Agent A writes `results_summary`; Agent B reads it. <sup>[source]</sup>

This is elegant.

It makes the kernel itself the communication medium.

### Advantages

- Very fast.
- No serialization required.
- Pandas/DataFrame/model objects can remain live.
- Agents can inspect each other's actual Python state.
- Natural for notebook-style workflows.

### But the security assumption is strong

The code itself says:

> `shared — all agents share one kernel ... only for trusted roles`

That qualifier is exactly right. <sup>[source]</sup>

Because in shared mode:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Agent A
   │
   ├── can read Agent B's variables
   ├── can modify Agent B's variables
   ├── can import modules
   ├── can mutate objects
   └── can affect kernel-global state
```

</details>

The `writes` declarations do not magically isolate Python objects when everyone operates in the same namespace.

---

# 2. Isolated mode is much more interesting

The isolated model is:

<details>
<summary><strong>💻 Code Block (text) — 19 lines</strong></summary>

```text
Agent A
   │
   ▼
Kernel A
   │
   ▼
explicit export
   │
   ▼
SharedMemory
   │
   ▼
explicit seed
   │
   ▼
Kernel B
   │
   ▼
Agent B
```

</details>

The code explicitly says:

> state crosses agent boundaries ONLY through the SharedMemory

and describes those transfers as explicit, attributable, immutable JSON copies. <sup>[source]</sup>

That's a substantially stronger design.

---

# 3. The export boundary is the key security mechanism

Each role declares:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
writes = [...]
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

```text
analyst
 ├── results_
 ├── model_
 ├── df_
 └── analysis_

critic
 └── critique_

narrator
 ├── narrative_
 └── key_findings
```

</details>

<sup>[source]</sup>

Then `_export_turn()` calls:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
export_code(role.writes)
```

</details>

inside the turn kernel.

The resulting data is parsed and transferred into `SharedMemory`. <sup>[source]</sup>

This creates an explicit data-flow boundary:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

```text
Python object
     │
     ▼
declared export
     │
     ▼
JSON-safe representation
     │
     ▼
SharedMemory
     │
     ▼
next agent
```

</details>

That's exactly the kind of boundary an agent runtime needs.

---

# 4. Excellent: agent provenance is preserved

The export calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self.shared.put(key, value, producer=role.name)
```

</details>

<sup>[source]</sup>

So Kerno can know:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
results_summary
producer = analyst
```

</details>

rather than merely:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
results_summary
value = ...
```

</details>

This is important for:

- audit trails
- debugging
- attribution
- trust
- conflict resolution
- future checkpointing

I'd preserve this design.

---

# 5. But the word "immutable" needs careful verification

The source documentation says the isolated path uses:

> "explicit, attributable, immutable JSON copies." <sup>[source]</sup>

That is only truly true if `SharedMemory.put()` performs a defensive copy.

If it stores the exact Python object:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
shared[key] = value
```

</details>

then a mutable dictionary/list could still be modified later.

If it serializes and deserializes:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
value
 ↓
json.dumps()
 ↓
json.loads()
```

</details>

then the receiving agent gets a new object.

That would be genuinely isolated.

**This is therefore one of the next files I would verify directly:**

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kerno/isolation.py
```

</details>

because it determines whether the advertised isolation guarantee is real or merely conceptual.

---

# 6. Namespace violations are detected, but the response is weak

The loop does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
violations = self.partition.violations(...)
```

</details>

and records:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
self._isolation_violations.append(...)
```

</details>

<sup>[source]</sup>

This is good observability.

But notice what happens afterward:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
violation
   │
   ├── record
   └── log warning
```

</details>

It doesn't necessarily:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
block the agent
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
terminate the turn
```

</details>

So K-009 currently appears to be a **detection/audit mechanism**, not a hard security policy.

That's an important distinction.

For a trusted cooperative multi-agent workflow, that's fine.

For adversarial agents, it isn't enough.

---

# 7. A stronger policy model would be useful

I'd define:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
NamespacePolicy
├── WARN
├── BLOCK_EXPORT
├── FAIL_TURN
└── TERMINATE_SESSION
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

```text
agent writes forbidden key
          │
          ▼
      policy check
          │
     ┌────┼────┬────────┐
     ▼    ▼    ▼        ▼
   warn  block fail   terminate
```

</details>

That gives Kerno flexibility depending on trust level.

---

# 8. Agent budgets are a particularly good addition

The code has:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
BudgetTracker
ExecutionBudget
```

</details>

and explicitly creates a tracker per agent:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
agent A → BudgetTracker A
agent B → BudgetTracker B
agent C → BudgetTracker C
```

</details>

The comment explains the intent:

> a child agent cannot consume the session's shared resources. <sup>[source]</sup>

This is a very good design direction.

It prevents:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Agent A
   │
   ├── cell
   ├── cell
   ├── cell
   ├── ...
   └── exhaust entire session budget
```

</details>

from automatically starving every other role.

---

# 9. But there are two different resource layers

The architecture now has:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
ExecutionBudget
       │
       ▼
logical agent budget
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
KernelPool
       │
       ▼
physical process/resource management
```

</details>

These should eventually be connected.

For example:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Agent budget:
  max_cells = 20

Kernel resource:
  max CPU = X
  max RAM = Y
  max wall time = Z
```

</details>

Otherwise an agent could obey:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
20 cells
```

</details>

while one cell consumes enormous resources.

---

# 10. Cancellation is only checked between turns

The code explicitly checks:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
cancel_token.is_set()
```

</details>

at the beginning of each turn. <sup>[source]</sup>

So:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
Turn 1
   │
   ▼
20 cells
   │
   ▼
Turn ends
   │
   ▼
cancellation checked
```

</details>

This means cancellation is **not necessarily immediate during a turn**.

If cell 17 is executing a long operation:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

```text
cancel()
   │
   ▼
agent may continue
   │
   ▼
cell completes / times out
   │
   ▼
turn ends
   │
   ▼
cancellation observed
```

</details>

The runtime underneath supports cancellation, so the architecture could be improved by propagating the cancellation token into individual cell execution.

---

# 11. There is a subtle isolated-mode failure hazard

Look at the structure:

<details>
<summary><strong>💻 Code Block (python) — 6 lines</strong></summary>

```python
try:
    turn = self._run_turn(...)
finally:
    if self.isolation == "isolated":
        self._export_turn(...)
        self._shutdown_turn_kernel(...)
```

</details>

<sup>[source]</sup>

This means `_export_turn()` runs even when `_run_turn()` raises an exception.

That can be desirable for partial results.

But it creates an important semantic question:

> Should a failed/aborted agent turn be allowed to export its partial state?

Imagine:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
Agent A
  │
  ├── result_1 = valid
  ├── result_2 = valid
  ├── result_3 = corrupt
  └── exception
```

</details>

Then the `finally` path may export data.

Agent B could consume:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
result_1
result_2
result_3
```

</details>

without knowing that the producing turn failed.

That's dangerous for analytical correctness.

---

# 12. This needs transactional export semantics

I strongly recommend:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

```text
TURN START
    │
    ▼
working state
    │
    ├── success ─────► COMMIT exports
    │
    ├── cancelled ───► ROLLBACK
    │
    ├── timeout ─────► ROLLBACK
    │
    └── error ───────► ROLLBACK
```

</details>

or, if partial exports are intentional:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
partial export
    │
    ▼
status = PARTIAL
producer_status = FAILED
```

</details>

Then the receiving agent knows:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
results_summary
producer = analyst
status = partial
```

</details>

rather than treating it as authoritative.

This is the beginning of a **transaction model for agent state**.

---

# 13. Multi-agent communication has two channels

The code supports both:

### SharedMemory

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
structured state
```

</details>

and:

### AgentBus

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
messages_<kind>
       │
       ▼
AgentMessage
       │
       ▼
next agent / broadcast
```

</details>

<sup>[source]</sup>

This is actually a good separation:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
SharedMemory
    = durable-ish state/data

AgentBus
    = events/messages
```

</details>

I would retain that distinction.

---

# 14. The `messages_*` mechanism is elegant

An agent writes:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
messages_warning = {
    "severity": "high",
    "reason": "...",
}
```

</details>

and Kerno converts it into:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
AgentMessage
    sender = analyst
    recipient = critic
    kind = warning
    payload = {...}
```

</details>

<sup>[source]</sup>

This lets LLM agents communicate using normal kernel code while Kerno handles the transport semantics.

That's a clever bridge between:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Python namespace
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
agent protocol
```

</details>

---

# 15. But `messages_*` should probably not live in the general data namespace

There's a conceptual collision risk:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
messages_warning
```

</details>

is currently just another exported key.

I would eventually use a reserved namespace:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
__kerno__.messages.*
```

</details>

or a structured API:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
kerno.send(...)
```

</details>

because otherwise an agent could accidentally overwrite communication state.

For example:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
messages_warning = 42
```

</details>

would be interpreted differently from:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
messages_warning = {"severity": ...}
```

</details>

The current code handles non-dict payloads by logging a warning, which is good, but a reserved protocol namespace would be cleaner.

---

# 16. Turn ordering is deterministic

The loop uses:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
agent_name = self.turn_order[
    turn_idx % len(self.turn_order)
]
```

</details>

<sup>[source]</sup>

So:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
analyst
critic
narrator
analyst
critic
narrator
...
```

</details>

until:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
max_turns
```

</details>

This is deterministic and easy to test.

But the docstring mentions:

> "Optional: planner assesses and decides next agent"

while the visible implementation defaults to a static turn order.

So there is an architectural gap between:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
fixed orchestration
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
dynamic agent planning
```

</details>

That isn't necessarily bad. Deterministic orchestration is safer.

I'd actually recommend keeping fixed mode as the default and making dynamic planning explicit:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
mode = "fixed"
mode = "planner"
```

</details>

---

# 17. `max_turns` is an important safety limit

Without it:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Agent A → B → C → A → B → C → ...
```

</details>

could continue indefinitely.

The loop defaults to:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
max_turns = 6
```

</details>

which is good.

Combined with:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
max_cells
cell_timeout
budget
cancel_token
```

</details>

Kerno has multiple termination controls:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

```text
             Multi-Agent Safety
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
   max_turns     max_cells    timeout
       │            │            │
       └────────────┼────────────┘
                    ▼
                 budget
                    │
                    ▼
                cancellation
```

</details>

That's a strong safety pattern.

---

# 18. But these limits need a clear precedence model

Suppose simultaneously:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
cell timeout
budget exhausted
cancel requested
```

</details>

Which status wins?

The architecture needs a deterministic precedence such as:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

```text
CANCELLED
   >
TIMEOUT
   >
BUDGET_EXCEEDED
   >
ERROR
   >
MAX_CELLS
   >
MAX_TURNS
   >
COMPLETE
```

</details>

or whatever semantics Kerno chooses.

Otherwise two executions can report different outcomes depending on timing.

This matters for checkpoint/recovery logic.

---

# 19. The critical new concept: agent state transaction

After looking at the runtime, pool, and multi-agent loop together, I think Kerno needs an explicit concept:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
AgentTurnTransaction
```

</details>

Something like:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

```text
TurnTransaction
├── session_id
├── turn_id
├── agent_id
├── kernel_generation
├── started_at
├── budget_snapshot
├── input_snapshot
├── produced_exports
├── messages
├── status
└── commit_id
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 16 lines</strong></summary>

```text
Agent turn
    │
    ▼
transaction begins
    │
    ├── execute
    ├── collect
    ├── validate exports
    ├── validate messages
    └── validate result
             │
             ▼
          COMMIT
             │
             ▼
       SharedMemory
```

</details>

Now the agent loop becomes much easier to reason about.

---

# 20. The resulting architecture is becoming very strong

The whole system now looks like:

<details>
<summary><strong>💻 Code Block (text) — 30 lines</strong></summary>

```text
                         KERNO
                           │
                    ┌──────┴──────┐
                    ▼             ▼
                 Skills        Agents
                    │             │
                    ▼             ▼
               Registry      MultiAgentLoop
                    │             │
                    └──────┬──────┘
                           ▼
                      KernelPool
                           │
                           ▼
                    KernelRuntime
                           │
                           ▼
                    Jupyter Kernel
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
         execution      namespace     telemetry
                           │
                    ┌──────┴──────┐
                    ▼             ▼
               SharedMemory    AgentBus
                    │             │
                    └──────┬──────┘
                           ▼
                     next agent
```

</details>

The key architectural principle is emerging:

> **The kernel is execution state; SharedMemory is explicit inter-agent state; AgentBus is communication; the registry is capability metadata; the pool is lifecycle management.**

That's a very coherent model.

---

# 🔴 Current highest-priority finding

The next thing I'd audit is **`kerno/isolation.py`**, because it determines whether the most important promise of isolated multi-agent execution actually holds:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
Agent A
   │
   ▼
export
   │
   ▼
SharedMemory
   │
   ▼
Agent B
```

</details>

We need to verify:

1. Are values actually deep-copied?
2. Are mutable objects converted to immutable/JSON-safe representations?
3. Can an agent export undeclared variables?
4. Can an agent read another agent's private state?
5. Can `SharedMemory` be mutated after insertion?
6. Does producer attribution survive copies?
7. Can stale data survive a failed turn?
8. Is there a true commit/rollback boundary?
9. Can two agents race on the same key?
10. What happens when two agents export the same variable?

That file is effectively the **data-isolation boundary** of Kerno.

If it passes, the isolated architecture is substantially stronger than the shared-kernel design. If it doesn't, then "isolated" is currently more of a workflow convention than a security boundary.

---

---
[← Previous section](./05-kernel-runtime-execution-boundary.md) | [Back to index](./README.md) | [Next section →](./07-isolation-and-communication.md)

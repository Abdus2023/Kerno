# 06 — Kernel Pool And Concurrency

---

## Next: `KernelPool` — concurrency, isolation, and lifecycle audit

I inspected the actual `kerno/kernel/pool.py`. This is a substantial subsystem: it tries to solve **cold starts, state contamination, memory growth, hung kernels, and kernel replacement** simultaneously. <sup>[source]</sup>

The design is good in principle, but I found several issues that are more important than the earlier dependency concerns.

---

## 1. The intended pool model

The architecture is:

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

The pool also supports overflow kernels and automatic retirement. <sup>[source]</sup>

That is a sensible architecture for an agent system where kernel startup takes seconds.

---

## 2. Good: task ownership is explicit

`acquire(task_id)` associates a kernel with a specific task:

```text
task-123 → k-0001
```

and `_active` tracks the relationship.

It also rejects duplicate acquisition:

```python
if task_id in self._active:
    raise ValueError(...)
```

This is good because it prevents:

```text
task A
  │
  ├── kernel 1
  │
  └── accidentally acquire kernel 2
```

under the same logical task.

---

## 3. Good: release has semantic reasons

The API distinguishes:

```text
complete
error
timeout
oom
```

That is excellent.

The policy is:

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

<sup>[source]</sup>

This is much better than treating every task completion identically.

---

## 4. Critical issue: stale kernels can remain in `_available`

This is the most important bug I found in the pool.

The monitor does:

```python
if pk.state == KernelState.AVAILABLE and pk.is_expired:
    self._retire(pk, replace=True)
```

But `_retire()` removes the kernel from:

```python
self._all
```

It does **not remove it from**:

```python
self._available
```

<sup>[source]</sup>

So consider:

```text
_available:
[k-0001, k-0002, k-0003]
```

Monitor sees:

```text
k-0001 expired
```

and retires it.

Now:

```text
_all:
[k-0002, k-0003]
```

but:

```text
_available:
[k-0001, k-0002, k-0003]
```

The queue still contains the dead kernel.

Later:

```python
pk = self._available.get(...)
```

can return `k-0001`.

The health check notices it's unhealthy:

```python
if not pk.is_healthy:
```

and attempts to create a replacement.

So there is some recovery.

But this leaves the queue containing stale objects and creates a subtle lifecycle/accounting problem.

### Better design

Never directly remove an available object from the pool without also removing/invalidating its queue entry.

A robust approach is **generation/state validation at dequeue**:

```text
queue item
    │
    ▼
is object still AVAILABLE?
    │
    ├── yes → acquire
    └── no  → discard and retry
```

The current health check partially provides this, but the queue should explicitly tolerate stale entries.

---

## 5. More serious: `_create_kernel()` can return DEAD

This path is problematic:

```python
pk = self._create_kernel()
```

`_create_kernel()` catches startup/bootstrap failure and does:

```text
pk.state = DEAD
```

but still returns `pk`. <sup>[source]</sup>

Then `acquire()` does:

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

But there is **no second guaranteed health validation** after that replacement.

So the logic can theoretically become:

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

The API should instead have `_create_kernel()` return either:

```text
PooledKernel
```

that is definitely `AVAILABLE`, or:

```text
None / exception
```

on failure.

For example:

```text
_create_kernel()
      │
      ├── success → AVAILABLE
      │
      └── failure → PoolKernelStartError
```

Then `acquire()` can properly decide whether to retry.

---

## 6. Overflow accounting is ambiguous

The code says:

```python
max_overflow = 10
```

and checks:

```python
len(self._active) < self.max_overflow
```

before creating an overflow kernel. <sup>[source]</sup>

But this does **not mean "at most 10 overflow kernels."**

Suppose:

```text
size = 3
max_overflow = 10
```

The pool can have:

```text
3 warm kernels
+
10 active overflow kernels
=
13 kernels
```

which may be what was intended.

But the name `max_overflow` could also be interpreted as:

> maximum total kernels beyond the configured pool size.

The implementation currently means:

> maximum number of simultaneously active tasks allowed through this particular condition.

That should be made explicit.

I would define:

```text
max_overflow_kernels
```

and enforce:

```text
len(all) - size < max_overflow_kernels
```

instead.

---

## 7. Memory limits are not actually enforcement

`PooledKernel` defines:

```python
MAX_MEMORY = 4096.0
```

and considers the kernel expired if:

```python
memory > MAX_MEMORY
```

<sup>[source]</sup>

But this only **detects** excessive memory.

It does not prevent the process from consuming 4 GB.

So:

```text
MAX_MEMORY
```

is really:

> retirement threshold

not:

> memory limit.

This distinction matters enormously.

A malicious or buggy skill can still do:

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

before the monitor necessarily notices.

For actual containment, the kernel process needs an OS-level resource limit, cgroup/container, or similar mechanism.

---

## 8. The monitor interval makes lifecycle limits approximate

The monitor runs:

```python
time.sleep(30)
```

<sup>[source]</sup>

Therefore:

```text
MAX_LIFETIME = 3600
```

does not mean:

> kernel is retired exactly at 3600 seconds.

It means approximately:

```text
3600 → 3630 seconds
```

depending on scheduling.

That's fine if documented as a **soft lifecycle threshold**.

It becomes a problem only if callers treat it as a hard guarantee.

---

## 9. Acquired kernels can exceed lifetime indefinitely

This is subtle.

The monitor checks:

```python
if pk.state == KernelState.ACQUIRED:
```

and only warns if the task has run for more than one hour:

```text
"Consider interrupting."
```

It does **not actually terminate it**. <sup>[source]</sup>

Therefore:

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

So `MAX_LIFETIME` applies to retirement of available kernels, but not really to active task execution.

That should be documented or changed.

---

## 10. `release()` starts reset threads asynchronously

For a successful task:

```python
threading.Thread(
    target=self._soft_reset,
    ...
).start()
```

<sup>[source]</sup>

This is intentional because the caller doesn't have to wait for cleanup.

But it introduces a state transition:

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

During that window:

```text
task no longer owns kernel
kernel isn't available
```

which is okay.

However, there is no explicit reset queue or bounded reset worker pool.

Under heavy load:

```text
1000 completed tasks
       │
       ▼
1000 reset threads
```

could theoretically be created.

The pool should eventually use a bounded executor or dedicated reset worker.

---

## 11. `shutdown()` doesn't join the monitor/reset workers

`shutdown()` does:

```python
self._running = False
```

then shuts down kernels. <sup>[source]</sup>

But the monitor thread is not joined.

So:

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

Eventually it wakes and exits.

Usually harmless, but a deterministic lifecycle API should ideally provide:

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

That matters for tests and clean application shutdown.

---

## 12. `skills_path` is a trust boundary

This is another important security observation.

Bootstrap does:

```python
path.read_text()
```

and then:

```python
runtime.execute(code, silent=True, timeout=60)
```

<sup>[source]</sup>

So `skills_path` is effectively:

```text
filesystem file
       │
       ▼
arbitrary Python source
       │
       ▼
kernel execution
```

Therefore `skills_path` must be treated as **trusted code**.

The pool should not accept an arbitrary agent-controlled path and execute it.

If Kerno later exposes something like:

```python
pool = KernelPool(skills_path=user_input)
```

that could become an obvious arbitrary-code-execution vector.

---

## 13. The biggest isolation question: can kernels be reused safely?

The pool's answer is:

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

This is efficient.

But safety depends completely on the effectiveness of:

```python
runtime.reset_namespace()
```

We need to distinguish:

### Python namespace contamination

```text
x = secret
```

from:

### External side effects

```text
write_file(...)
database modification
network request
subprocess
environment changes
```

A namespace reset cannot undo those.

Therefore:

```text
namespace reset ≠ task isolation
```

This is one of the most important conclusions from the pool audit.

---

## 14. Example of a real contamination problem

Task A:

```python
import os
os.environ["MODE"] = "production"
```

Then:

```text
release
   ↓
reset_namespace
   ↓
task B
```

The variable/import may disappear.

But:

```text
process environment
```

may remain changed.

Likewise:

```python
open("/tmp/shared", "w").write(...)
```

is not undone.

And:

```python
subprocess.run(...)
```

can modify arbitrary external resources.

Therefore kernel reuse is only safe if Kerno's task model explicitly says:

> **Tasks share the kernel's OS-level side effects.**

or if the kernel process is actually recreated between trust boundaries.

---

## 15. This suggests two pool modes

A very useful architectural refinement would be:

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

For example:

```text
REUSE
```

for:

- internal analytics
- trusted skills
- same-agent sequential work

and:

```text
FRESH
```

for:

- untrusted generated code
- different tenants
- sensitive data boundaries
- external plugins

That gives Kerno a meaningful security/performance tradeoff.

---

## 16. Pool invariants should be formalized

The current implementation would benefit enormously from explicit invariants.

For example:

### Invariant A

```text
Every ACTIVE task has exactly one kernel.
```

### Invariant B

```text
A kernel can belong to at most one ACTIVE task.
```

### Invariant C

```text
AVAILABLE kernels must be healthy.
```

### Invariant D

```text
DEAD kernels cannot appear in AVAILABLE.
```

### Invariant E

```text
A kernel in RESETTING cannot be acquired.
```

### Invariant F

```text
Every kernel in _all has exactly one lifecycle state.
```

### Invariant G

```text
_shutdown means no future kernel creation.
```

The current code does not enforce all of these strongly enough.

---

## 17. Recommended pool state machine

I'd formalize:

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

And **no direct transition** should allow:

```text
DEAD → AVAILABLE
```

or:

```text
RESETTING → ACQUIRED
```

without explicit successful completion.

---

## 18. The pool + runtime now gives us a much clearer security picture

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

The **real security boundary is still the OS process/environment**, not the skill registry or namespace.

---

## 19. Audit verdict for `KernelPool`

###  Strong design

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

###  Correctness issues

- Stale `_available` entries after retirement.
- `_create_kernel()` can return a DEAD object.
- Overflow semantics are ambiguous.
- Reset operations spawn unbounded threads.
- Shutdown is not fully synchronized.
- Lifecycle thresholds are soft, not hard.
- Active tasks aren't actually retired at lifetime expiry.
- Pool invariants aren't explicitly enforced.

###  Security/architecture issues

- Namespace reset is **not true task isolation**.
- `skills_path` is arbitrary Python execution and must be trusted.
- Memory threshold is detection/retirement, not resource enforcement.
- Reusing a kernel preserves OS-level side effects.
- There is no OS-level sandbox/resource boundary yet.

---

## The next critical subsystem is now clear

We should move from:

```text
KernelRuntime
      ↓
KernelPool
```

to:

```text
KernelPool
      ↓
Agent Loop
      ↓
Observe → Plan → Execute → Reflect → Checkpoint
```

because that's where **task ownership, cancellation, kernel acquisition, state persistence, and agent memory meet**.

The key question will be:

> **Can Kerno's agent loop guarantee that a task's kernel, skills, state, cancellation, and checkpoint remain consistent when execution fails, times out, or the kernel is restarted?**

That is effectively the **transaction/consistency model of Kerno**, and it is the next major architectural gate.

---

## Next: Multi-Agent Loop — the consistency model

This is the most consequential layer so far.

The branch explicitly implements **two different multi-agent isolation models**:

```text
shared
isolated
```

and also has a separate `SharedMemory`/`AgentBus` mechanism. <sup>[source]</sup>

That means Kerno is already trying to solve the problem we identified in the pool audit:

> How do multiple agents share information without accidentally sharing everything?

---

## 1. Shared mode

The simple mode is:

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

```text
Agent A
   │
   ├── can read Agent B's variables
   ├── can modify Agent B's variables
   ├── can import modules
   ├── can mutate objects
   └── can affect kernel-global state
```

The `writes` declarations do not magically isolate Python objects when everyone operates in the same namespace.

---

## 2. Isolated mode is much more interesting

The isolated model is:

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

The code explicitly says:

> state crosses agent boundaries ONLY through the SharedMemory

and describes those transfers as explicit, attributable, immutable JSON copies. <sup>[source]</sup>

That's a substantially stronger design.

---

## 3. The export boundary is the key security mechanism

Each role declares:

```python
writes = [...]
```

For example:

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

<sup>[source]</sup>

Then `_export_turn()` calls:

```text
export_code(role.writes)
```

inside the turn kernel.

The resulting data is parsed and transferred into `SharedMemory`. <sup>[source]</sup>

This creates an explicit data-flow boundary:

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

That's exactly the kind of boundary an agent runtime needs.

---

## 4. Excellent: agent provenance is preserved

The export calls:

```python
self.shared.put(key, value, producer=role.name)
```

<sup>[source]</sup>

So Kerno can know:

```text
results_summary
producer = analyst
```

rather than merely:

```text
results_summary
value = ...
```

This is important for:

- audit trails
- debugging
- attribution
- trust
- conflict resolution
- future checkpointing

I'd preserve this design.

---

## 5. But the word "immutable" needs careful verification

The source documentation says the isolated path uses:

> "explicit, attributable, immutable JSON copies." <sup>[source]</sup>

That is only truly true if `SharedMemory.put()` performs a defensive copy.

If it stores the exact Python object:

```python
shared[key] = value
```

then a mutable dictionary/list could still be modified later.

If it serializes and deserializes:

```text
value
 ↓
json.dumps()
 ↓
json.loads()
```

then the receiving agent gets a new object.

That would be genuinely isolated.

**This is therefore one of the next files I would verify directly:**

```text
kerno/isolation.py
```

because it determines whether the advertised isolation guarantee is real or merely conceptual.

---

## 6. Namespace violations are detected, but the response is weak

The loop does:

```python
violations = self.partition.violations(...)
```

and records:

```text
self._isolation_violations.append(...)
```

<sup>[source]</sup>

This is good observability.

But notice what happens afterward:

```text
violation
   │
   ├── record
   └── log warning
```

It doesn't necessarily:

```text
block the agent
```

or:

```text
terminate the turn
```

So K-009 currently appears to be a **detection/audit mechanism**, not a hard security policy.

That's an important distinction.

For a trusted cooperative multi-agent workflow, that's fine.

For adversarial agents, it isn't enough.

---

## 7. A stronger policy model would be useful

I'd define:

```text
NamespacePolicy
├── WARN
├── BLOCK_EXPORT
├── FAIL_TURN
└── TERMINATE_SESSION
```

Then:

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

That gives Kerno flexibility depending on trust level.

---

## 8. Agent budgets are a particularly good addition

The code has:

```python
BudgetTracker
ExecutionBudget
```

and explicitly creates a tracker per agent:

```text
agent A → BudgetTracker A
agent B → BudgetTracker B
agent C → BudgetTracker C
```

The comment explains the intent:

> a child agent cannot consume the session's shared resources. <sup>[source]</sup>

This is a very good design direction.

It prevents:

```text
Agent A
   │
   ├── cell
   ├── cell
   ├── cell
   ├── ...
   └── exhaust entire session budget
```

from automatically starving every other role.

---

## 9. But there are two different resource layers

The architecture now has:

```text
ExecutionBudget
       │
       ▼
logical agent budget
```

and:

```text
KernelPool
       │
       ▼
physical process/resource management
```

These should eventually be connected.

For example:

```text
Agent budget:
  max_cells = 20

Kernel resource:
  max CPU = X
  max RAM = Y
  max wall time = Z
```

Otherwise an agent could obey:

```text
20 cells
```

while one cell consumes enormous resources.

---

## 10. Cancellation is only checked between turns

The code explicitly checks:

```python
cancel_token.is_set()
```

at the beginning of each turn. <sup>[source]</sup>

So:

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

This means cancellation is **not necessarily immediate during a turn**.

If cell 17 is executing a long operation:

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

The runtime underneath supports cancellation, so the architecture could be improved by propagating the cancellation token into individual cell execution.

---

## 11. There is a subtle isolated-mode failure hazard

Look at the structure:

```python
try:
    turn = self._run_turn(...)
finally:
    if self.isolation == "isolated":
        self._export_turn(...)
        self._shutdown_turn_kernel(...)
```

<sup>[source]</sup>

This means `_export_turn()` runs even when `_run_turn()` raises an exception.

That can be desirable for partial results.

But it creates an important semantic question:

> Should a failed/aborted agent turn be allowed to export its partial state?

Imagine:

```text
Agent A
  │
  ├── result_1 = valid
  ├── result_2 = valid
  ├── result_3 = corrupt
  └── exception
```

Then the `finally` path may export data.

Agent B could consume:

```text
result_1
result_2
result_3
```

without knowing that the producing turn failed.

That's dangerous for analytical correctness.

---

## 12. This needs transactional export semantics

I strongly recommend:

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

or, if partial exports are intentional:

```text
partial export
    │
    ▼
status = PARTIAL
producer_status = FAILED
```

Then the receiving agent knows:

```text
results_summary
producer = analyst
status = partial
```

rather than treating it as authoritative.

This is the beginning of a **transaction model for agent state**.

---

## 13. Multi-agent communication has two channels

The code supports both:

### SharedMemory

```text
structured state
```

and:

### AgentBus

```text
messages_<kind>
       │
       ▼
AgentMessage
       │
       ▼
next agent / broadcast
```

<sup>[source]</sup>

This is actually a good separation:

```text
SharedMemory
    = durable-ish state/data

AgentBus
    = events/messages
```

I would retain that distinction.

---

## 14. The `messages_*` mechanism is elegant

An agent writes:

```python
messages_warning = {
    "severity": "high",
    "reason": "...",
}
```

and Kerno converts it into:

```text
AgentMessage
    sender = analyst
    recipient = critic
    kind = warning
    payload = {...}
```

<sup>[source]</sup>

This lets LLM agents communicate using normal kernel code while Kerno handles the transport semantics.

That's a clever bridge between:

```text
Python namespace
```

and:

```text
agent protocol
```

---

## 15. But `messages_*` should probably not live in the general data namespace

There's a conceptual collision risk:

```text
messages_warning
```

is currently just another exported key.

I would eventually use a reserved namespace:

```text
__kerno__.messages.*
```

or a structured API:

```python
kerno.send(...)
```

because otherwise an agent could accidentally overwrite communication state.

For example:

```python
messages_warning = 42
```

would be interpreted differently from:

```python
messages_warning = {"severity": ...}
```

The current code handles non-dict payloads by logging a warning, which is good, but a reserved protocol namespace would be cleaner.

---

## 16. Turn ordering is deterministic

The loop uses:

```python
agent_name = self.turn_order[
    turn_idx % len(self.turn_order)
]
```

<sup>[source]</sup>

So:

```text
analyst
critic
narrator
analyst
critic
narrator
...
```

until:

```text
max_turns
```

This is deterministic and easy to test.

But the docstring mentions:

> "Optional: planner assesses and decides next agent"

while the visible implementation defaults to a static turn order.

So there is an architectural gap between:

```text
fixed orchestration
```

and:

```text
dynamic agent planning
```

That isn't necessarily bad. Deterministic orchestration is safer.

I'd actually recommend keeping fixed mode as the default and making dynamic planning explicit:

```text
mode = "fixed"
mode = "planner"
```

---

## 17. `max_turns` is an important safety limit

Without it:

```text
Agent A → B → C → A → B → C → ...
```

could continue indefinitely.

The loop defaults to:

```text
max_turns = 6
```

which is good.

Combined with:

```text
max_cells
cell_timeout
budget
cancel_token
```

Kerno has multiple termination controls:

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

That's a strong safety pattern.

---

## 18. But these limits need a clear precedence model

Suppose simultaneously:

```text
cell timeout
budget exhausted
cancel requested
```

Which status wins?

The architecture needs a deterministic precedence such as:

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

or whatever semantics Kerno chooses.

Otherwise two executions can report different outcomes depending on timing.

This matters for checkpoint/recovery logic.

---

## 19. The critical new concept: agent state transaction

After looking at the runtime, pool, and multi-agent loop together, I think Kerno needs an explicit concept:

```text
AgentTurnTransaction
```

Something like:

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

Then:

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

Now the agent loop becomes much easier to reason about.

---

## 20. The resulting architecture is becoming very strong

The whole system now looks like:

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

The key architectural principle is emerging:

> **The kernel is execution state; SharedMemory is explicit inter-agent state; AgentBus is communication; the registry is capability metadata; the pool is lifecycle management.**

That's a very coherent model.

---

##  Current highest-priority finding

The next thing I'd audit is **`kerno/isolation.py`**, because it determines whether the most important promise of isolated multi-agent execution actually holds:

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

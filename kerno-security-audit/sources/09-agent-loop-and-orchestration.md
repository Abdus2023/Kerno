[← Back to index](./README.md) | [Next section →](./10-prompt-error-persistence.md)

## [36] USER

Continue 

---

## [37] CHATGPT (gpt-5-6)

## Continue — next audit layer: `MultiAgentLoop`

We should now move from **kernel/resource correctness** into **agent execution semantics**.

One correction first: I don't currently have the contents of `kerno/agent/loop.py` in the visible tool results, so I won't invent findings about that file. The previous audit established the exact contract that this layer must satisfy.

### The contract going upward

<details>
<summary><strong>💻 Code Block (text) — 20 lines</strong></summary>

```text
Agent
  │
  ▼
MultiAgentLoop
  │
  ├── budget
  ├── cancellation
  ├── turn lifecycle
  ├── agent state
  ├── tool execution
  └── failure handling
          │
          ▼
     KernelPool
          │
          ▼
     KernelRuntime
          │
          ▼
   OutputCollector
```

</details>

The critical question is:

> **Does one agent turn correspond to one well-defined transaction whose success/failure/cancellation is reflected consistently in agent state, budgets, and kernel state?**

---

# 1. What we need to verify

A correct loop should behave approximately like:

<details>
<summary><strong>💻 Code Block (text) — 14 lines</strong></summary>

```text
START TURN
    │
    ├── check cancellation
    ├── check budget
    ├── select/prepare agent
    ├── acquire resources
    ├── execute work
    ├── collect observation
    ├── update state
    ├── account budget
    └── release/reset resources
         │
         ▼
      END TURN
```

</details>

The dangerous implementation is:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
START TURN
   ↓
execute
   ↓
exception
   ↓
skip state/accounting
   ↓
next turn
```

</details>

because then the agent's logical state can diverge from the actual execution state.

---

# 2. Cancellation must be checked at multiple boundaries

From the lower layers we already know that kernel cancellation can propagate into an actual Jupyter interrupt.

The agent loop should therefore have at least three cancellation checkpoints:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
before turn
    ↓
before tool/kernel call
    ↓
after execution / before committing state
```

</details>

Why the third one matters:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
kernel finishes
      ↓
cancel arrives
      ↓
agent commits observation
```

</details>

Without a post-execution cancellation check, a cancelled turn may still mutate the agent's durable state.

---

# 3. Budget enforcement must be transactional

Suppose the loop has:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
max_turns = 10
```

</details>

and is currently at:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
turn = 10
```

</details>

The loop must not do:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
turn 10
   ↓
start execution
   ↓
discover budget exhausted
```

</details>

Instead:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
budget check
    ↓
allowed?
 ┌──┴──┐
NO    YES
│      │
stop   execute
```

</details>

The same applies to:

- token budget,
- wall-clock budget,
- tool-call budget,
- kernel execution budget.

A budget should be treated as a **precondition**, not merely a counter reported after the fact.

---

# 4. Turn accounting needs a precise definition

The runtime already has a subtle distinction between:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
submitted
completed
failed
silent
```

</details>

The agent loop should similarly distinguish:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
turn_started
turn_completed
turn_failed
turn_cancelled
turn_timed_out
```

</details>

Otherwise a metric like:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
turn_count = 5
```

</details>

is ambiguous.

For agent orchestration, I'd strongly prefer:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
TurnRecord
├── turn_id
├── agent_id
├── started_at
├── completed_at
├── status
├── tool_calls
├── kernel_executions
├── tokens
├── error
└── cancellation
```

</details>

---

# 5. Kernel failure must not automatically mean agent failure

There are at least four distinct situations:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
Kernel execution failed
Kernel timed out
Kernel was interrupted
Kernel died
```

</details>

These should not necessarily produce the same agent-level result.

For example:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Python exception
    ↓
recoverable tool failure
    ↓
agent can reason about error
```

</details>

whereas:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
kernel process died
    ↓
resource failure
    ↓
pool restart
    ↓
agent may retry
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
budget exceeded
    ↓
agent must stop
```

</details>

These are semantically different.

---

# 6. The pool/runtime architecture already supports recovery

This is important.

We have:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
KernelPool
    │
    ├── restart(task)
    ├── interrupt(task)
    ├── release(task)
    └── health_check()
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
KernelRuntime
    │
    ├── execute()
    ├── interrupt()
    ├── restart()
    └── timeout escalation
```

</details>

So the agent loop shouldn't implement its own kernel recovery logic.

It should delegate:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
AgentLoop
    ↓
KernelPool
    ↓
KernelRuntime
```

</details>

Otherwise we'd get duplicated recovery policies.

---

# 7. Resource ownership should surround the entire tool execution

The ideal pattern is:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
acquire(task)
    │
    ├── execute
    ├── collect
    ├── process output
    └── release(task)
```

</details>

with release guaranteed even when:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
execute → exception
execute → timeout
execute → cancellation
agent → exception
```

</details>

Conceptually:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
kernel = pool.acquire(task_id)
try:
    ...
finally:
    pool.release(task_id, reason=...)
```

</details>

The `finally` equivalent is essential.

Without it:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
exception
   ↓
release skipped
   ↓
kernel remains ACQUIRED
   ↓
pool capacity leaks
```

</details>

---

# 8. This connects directly to the P0 pool finding

We identified:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
release(reason="unknown")
```

</details>

can orphan a kernel.

Therefore the agent loop must **never manufacture arbitrary release reasons**.

The contract should use an enum:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
COMPLETE
ERROR
TIMEOUT
CANCELLED
OOM
KERNEL_DEAD
```

</details>

rather than free-form strings.

That lets the type system enforce the lifecycle.

---

# 9. Agent state should only commit after successful observation

Consider:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
Agent decides:
    execute Python

Kernel:
    runs successfully

Collector:
    receives output

Agent:
    parses output
```

</details>

The state transition should be:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
PLANNED
   ↓
EXECUTING
   ↓
OBSERVED
   ↓
STATE_COMMITTED
```

</details>

not:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
PLANNED
   ↓
STATE_COMMITTED
   ↓
execute
```

</details>

This gives you a clean transactional boundary.

---

# 10. Failed observations should be represented, not erased

A robust agent state model should retain:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
observation:
    status = error
    error_type = ...
    message = ...
```

</details>

rather than simply returning:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
None
```

</details>

Otherwise the next agent turn cannot distinguish:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
no observation
```

</details>

from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
execution failed
```

</details>

That's particularly important for autonomous retry behavior.

---

# 11. Retry policy belongs above the kernel

The kernel runtime can say:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
TIMEOUT
```

</details>

The pool can say:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kernel restarted
```

</details>

But the agent loop should decide:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
retry?
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
Python exception
    → probably don't automatically retry

kernel death
    → retry may be appropriate

transient communication failure
    → retry may be appropriate

budget exhausted
    → never retry
```

</details>

This separation keeps infrastructure deterministic.

---

# 12. The agent loop should have an explicit terminal state

A clean state machine is:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
CREATED
   ↓
RUNNING
   ↓
 ┌─┼───────────────┐
 ▼ ▼               ▼
DONE ERROR       CANCELLED
   │
   └──→ TERMINATED
```

</details>

With budget exhaustion:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
RUNNING
   ↓
BUDGET_EXCEEDED
   ↓
TERMINATED
```

</details>

This is better than relying on:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
for turn in range(...)
```

</details>

alone.

---

# 13. Why this matters for Kerno specifically

Kerno is not just a notebook executor.

The architecture we've seen is aiming toward:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

```text
LLM
 ↓
Agent
 ↓
planning
 ↓
tool/kernel execution
 ↓
observation
 ↓
reflection
 ↓
next action
```

</details>

Therefore correctness isn't merely:

> "Did Python execute?"

It's:

> **"Did the agent's causal state advance exactly once in response to the correct execution result?"**

That is a much stronger requirement.

---

# 14. The ideal causal chain

I'd make this invariant explicit:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

```text
Decision #N
     │
     ▼
Execution #N
     │
     ▼
Observation #N
     │
     ▼
State transition #N
     │
     ▼
Decision #N+1
```

</details>

Never:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
Decision #N
   ├── Execution A
   ├── Execution B
   └── State transition
```

</details>

unless parallel execution is explicitly part of the agent model.

---

# 15. The next thing to inspect in the repository

The most useful files now are:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
kerno/agent/loop.py
kerno/agent/agent.py
kerno/agent/state.py
kerno/agent/budget.py
```

</details>

and whichever module defines the tool/execution interface.

The purpose isn't just to read them individually.

We need to construct one **end-to-end causal trace**:

<details>
<summary><strong>💻 Code Block (text) — 21 lines</strong></summary>

```text
user request
   ↓
agent creation
   ↓
loop iteration
   ↓
LLM decision
   ↓
tool invocation
   ↓
KernelPool.acquire()
   ↓
KernelRuntime.execute()
   ↓
OutputCollector.collect()
   ↓
observation
   ↓
agent state update
   ↓
next iteration
```

</details>

Then test the four exceptional paths:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
                 ┌── success
                 │
execution ───────┼── Python error
                 │
                 ├── timeout
                 │
                 ├── cancellation
                 │
                 └── kernel death
```

</details>

That will give us the first genuinely **end-to-end correctness audit** of this Kerno branch rather than another isolated file review.

---

## [38] USER

Continue 

---

## [39] CHATGPT (gpt-5-6)

<details>
<summary><strong>🛠️ api_tool.list_resources</strong></summary>

**Input:**

```json
{"paths":["GitHub"],"query":"search_code"}
```

</details>

*(Tool execution: api_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"MultiAgentLoop","topn":20}}
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

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/loop/multi_agent.py","ref":"arena/01a0064f-kerno","start_line":180,"end_line":520}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>💭 Thinking Process</strong></summary>

> Reviewed session runner implementation and evaluated isolation handling bugs

</details>



---

## [40] CHATGPT (gpt-5-6)

# Continue — deep audit of `kerno/loop/multi_agent.py`

We now have the actual implementation, and this changes the assessment substantially. The loop contains several thoughtful security/isolation features, but there are also **real lifecycle bugs** at the agent-loop boundary.

The file is `kerno/loop/multi_agent.py` on the requested `arena/01a0064f-kerno` branch. <sup>[source]</sup>

---

## 1. Architecture: genuinely interesting

Kerno supports two fundamentally different execution models:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
SHARED
──────
Agent A ──┐
          ├── same KernelRuntime
Agent B ──┤
Agent C ──┘
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
ISOLATED
────────
Agent A → fresh kernel
              │
              ▼
        SharedMemory
              │
Agent B → fresh kernel
              │
              ▼
        SharedMemory
```

</details>

The isolated model is particularly interesting because it explicitly rejects implicit mutable kernel sharing.

The code documents the intended invariant:

> only explicitly shared state crosses an agent boundary. <sup>[source]</sup>

That is a strong design decision.

---

# 2. Agent identity is treated as a security principal

This is one of the best aspects.

`AgentRole` contains:

<details>
<summary><strong>💻 Code Block (python) — 6 lines</strong></summary>

```python
name
llm
system
max_cells
reads
writes
```

</details>

and the kernel factory can receive:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
kernel_factory(agent)
```

</details>

rather than merely:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
kernel_factory()
```

</details>

<sup>[source]</sup>

That means the architecture can eventually implement:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
analyst
   ↓
capabilities: data-read, model-write

critic
   ↓
capabilities: results-read, critique-write

narrator
   ↓
capabilities: results-read, narrative-write
```

</details>

This is much more powerful than merely having different prompts.

---

# 3. `NamespacePartition` reinforces that model

The isolation layer registers:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
analyst → results_, model_, df_, analysis_
critic  → critique_
narrator → narrative_, key_findings
```

</details>

<sup>[source]</sup>

Then the namespace is checked after a turn.

The underlying implementation explicitly treats undeclared keys as violations unless they were intentionally shared. <sup>[source]</sup>

That's a good security boundary.

---

# 4. But there is an important conceptual limitation

The namespace partition is **detective**, not preventive.

The sequence is:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
Agent writes forbidden variable
        ↓
kernel allows it
        ↓
turn completes
        ↓
NamespacePartition detects violation
        ↓
variable isn't exported
```

</details>

So:

> An isolated agent can still mutate its own temporary kernel arbitrarily during execution.

The system only prevents that state from crossing the boundary.

That's actually a reasonable design.

But the documentation should say:

**"write isolation across turns"**

rather than implying:

**"agents cannot write undeclared variables."**

---

# 5. Shared memory implementation is clean

`SharedValue` contains:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
key
value
producer
timestamp
```

</details>

<sup>[source]</sup>

This is exactly the metadata we want for cross-agent state:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
results_summary
    producer = analyst
    timestamp = ...
```

</details>

rather than an anonymous dictionary.

That gives us provenance.

---

# 6. But `SharedMemory` isn't actually immutable

The docstring says shared values are:

> immutable JSON copies. <sup>[source]</sup>

The **cross-boundary copy** is immutable from the originating kernel's perspective, which is good.

But on the host side:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._values[key] = sv
```

</details>

allows the whole `SharedMemory` object to be overwritten.

And `SharedValue.value` is typed as:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
Any
```

</details>

so nested Python structures aren't deeply immutable.

For correctness, I'd treat the host store as:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
append-only versioned values
```

</details>

or use deep-copy/frozen structures.

---

# 7. A more serious issue: shared values can be overwritten silently

This:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._values[key] = sv
```

</details>

means:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
analyst:
results_summary = A

later:

critic:
results_summary = B
```

</details>

simply replaces A.

The original producer disappears from the current mapping.

The `timestamp` and producer tell you who produced the **current** value, but not the history.

For multi-agent reasoning, versioning would be much stronger:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
results_summary@1 → analyst
results_summary@2 → critic
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
SharedValue
├── version
├── producer
├── previous_version
└── timestamp
```

</details>

---

# 8. Major bug: `finally` can mask the actual exception

This is the first concrete P0/P1 issue in `run()`.

The code does:

<details>
<summary><strong>💻 Code Block (python) — 7 lines</strong></summary>

```python
try:
    ...
    turn = self._run_turn(...)
finally:
    if self.isolation == "isolated":
        self._export_turn(role, turn_kernel, next_agent)
        self._shutdown_turn_kernel(turn_kernel)
```

</details>

<sup>[source]</sup>

If `_run_turn()` raises before assigning:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
turn = ...
```

</details>

then the `finally` block runs, which is fine.

But afterward Python re-raises the original exception.

However, `_export_turn()` itself can execute another kernel operation during failure handling.

That creates a dangerous sequence:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
LLM/kernel execution fails
       ↓
finally
       ↓
execute export code
       ↓
export also fails
```

</details>

Although `_export_turn()` catches its own exception, it can still perform additional kernel execution after a failed turn.

That is questionable transactional semantics.

---

# 9. Worse: cancellation triggers export

This is more important.

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
cancel_token.set()
```

</details>

during an isolated agent execution.

`kernel.execute()` can react to the cancellation.

Then:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
_run_turn()
    ↓
exception / termination
    ↓
finally
    ↓
_export_turn()
```

</details>

So a cancelled agent can still execute:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
export_code(...)
```

</details>

after cancellation.

That violates a strong cancellation invariant:

> After cancellation, no new agent work should begin.

The export is not merely bookkeeping—it executes Python inside the kernel.

I would change the logic to:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
normal completion
    → export

error
    → optionally export diagnostic state

cancellation
    → DO NOT export

timeout
    → DO NOT export
```

</details>

---

# 10. The isolated kernel is shut down correctly in principle

The finalizer calls:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
raw_kernel.shutdown()
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kernel.shutdown()
```

</details>

<sup>[source]</sup>

That is good.

The lifecycle is therefore:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
fresh kernel
    ↓
seed
    ↓
agent turn
    ↓
export
    ↓
shutdown
```

</details>

This strongly enforces isolation.

---

# 11. But isolated kernel creation has no startup cleanup guarantee

If:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
kernel = self.kernel_factory(agent)
```

</details>

succeeds partially and then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
shared.seed_code()
```

</details>

fails,

the `finally` block still attempts shutdown.

Good.

But if `kernel_factory()` itself starts a kernel and throws after partial creation, Kerno has no object to put into the `finally`.

That resource leak is owned by the factory contract.

I'd document:

> `kernel_factory` must be transactional: either return a fully initialized executor or clean up all resources before raising.

---

# 12. `TypeError` fallback is dangerous

This is subtle:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
try:
    kernel = self.kernel_factory(agent)
except TypeError:
    kernel = self.kernel_factory()
```

</details>

<sup>[source]</sup>

Suppose the factory correctly accepts `agent`, but its internal implementation contains:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
def factory(agent):
    something_that_raises_TypeError()
```

</details>

Kerno interprets that as:

> factory doesn't accept an argument.

Then it calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
factory()
```

</details>

and produces a second, misleading error.

This is a classic exception-swallowing problem.

Better inspect the callable signature once, or require one canonical interface:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
Callable[[str], KernelRuntime]
```

</details>

---

# 13. Turn ordering is deterministic, which is good

The loop uses:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self.turn_order[turn_idx % len(self.turn_order)]
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

This is deterministic.

That's good for reproducibility.

But it isn't really "multi-agent planning."

It's a **round-robin coordinator** with optional handoff signals.

That's an important architectural distinction.

---

# 14. `next_agent` is calculated but not actually used for scheduling

The code computes:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
next_agent = ...
```

</details>

and passes it to:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
_export_turn(...)
```

</details>

which uses it for message routing. <sup>[source]</sup>

But it does not change the next scheduled role.

So if analyst sends:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
HANDOFF: narrator
```

</details>

the loop doesn't actually route execution to narrator.

It still uses:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
turn_order[(turn_idx + 1) % len(turn_order)]
```

</details>

This means **handoff is communication metadata, not control flow**.

If the design intends actual dynamic delegation, this is incomplete.

---

# 15. `HANDOFF_SIGNAL` is therefore currently advisory

The code extracts:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
# HANDOFF:
```

</details>

into:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
turn.handoff_context
```

</details>

but nothing in the visible scheduling logic consumes that context to choose the next agent.

So:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
Agent A:
    # HANDOFF: critic
```

</details>

doesn't mean:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
next = critic
```

</details>

unless critic was already next in `turn_order`.

That's a functional limitation worth documenting.

---

# 16. The biggest semantic weakness: LLM output becomes executable code directly

This line is the heart of the loop:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
code = role.llm(messages)
```

</details>

followed by:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
output = kernel.execute(code, ...)
```

</details>

<sup>[source]</sup>

There is no visible intermediate:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
LLM response
    ↓
parse
    ↓
validate
    ↓
extract Python
    ↓
execute
```

</details>

The architecture assumes:

> the LLM callable returns valid executable Python.

That's simple, but fragile.

A malformed response:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Here is what I would do:
1. load pandas
2. inspect data
```

</details>

becomes a Python execution attempt.

---

# 17. A structured agent action protocol would be much stronger

Instead of:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
code = role.llm(messages)
```

</details>

I'd eventually want:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
AgentAction
├── kind = EXECUTE
├── code
├── reasoning_summary
├── requested_outputs
└── handoff
```

</details>

or:

<details>
<summary><strong>💻 Code Block (json) — 5 lines</strong></summary>

```json
{
  "action": "execute",
  "code": "df = ...",
  "handoff": "critic"
}
```

</details>

Then the runtime can validate the action before execution.

---

# 18. Error recovery is good but potentially creates loops

The current behavior is:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
execution error
    ↓
RecoveryStrategy.suggest()
    ↓
recovery hint
    ↓
LLM receives error
    ↓
generate corrected code
    ↓
execute again
```

</details>

<sup>[source]</sup>

This is a good agentic pattern.

But there is no explicit retry counter separate from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
role.max_cells
```

</details>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
bad code
bad code
bad code
bad code
...
```

</details>

can consume the entire cell budget.

That's not necessarily bad, but telemetry should distinguish:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
productive cells
recovery retries
```

</details>

---

# 19. A recovery loop can accidentally hide persistent failures

Imagine:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
1. NameError
2. NameError
3. NameError
4. NameError
...
```

</details>

The agent continues until `max_cells`.

Then:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
turn.summary = ...
```

</details>

and the session may simply continue to the next agent.

So a systemic failure doesn't necessarily terminate or mark the session as failed.

This is a major semantic question.

---

# 20. `SessionStatus.MAX_CELLS` is overloaded

At the beginning:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
status = SessionStatus.MAX_CELLS
```

</details>

<sup>[source]</sup>

Then that value remains unless:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
COMPLETE
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
INTERRUPTED
```

</details>

occurs.

Therefore `MAX_CELLS` effectively means:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
"did not complete and did not get interrupted"
```

</details>

It doesn't necessarily mean the cell limit was reached.

It could mean:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
LLM exception
kernel error
role failure
invalid role
zero turns
```

</details>

This is too broad.

---

# 21. There is no explicit `ERROR` session status path visible here

The loop should have something like:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
COMPLETE
MAX_TURNS
MAX_CELLS
CANCELLED
TIMEOUT
ERROR
KERNEL_FAILURE
```

</details>

Instead, exceptions from the LLM or infrastructure can escape `run()` altogether.

That means callers may receive:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
exception
```

</details>

rather than:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
SessionResult(status=ERROR)
```

</details>

The API is therefore inconsistent:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
expected failure → SessionResult
unexpected failure → exception
```

</details>

That's not inherently wrong, but it should be deliberate.

---

# 22. Cancellation is only checked between cells

The loop checks:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
cancel_token.is_set()
```

</details>

before starting another cell. <sup>[source]</sup>

However, during:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
code = role.llm(messages)
```

</details>

there is no cancellation mechanism visible.

So if the LLM call takes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
5 minutes
```

</details>

and cancellation occurs after 1 second:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
cancel
 ↓
LLM continues
 ↓
returns after 5 min
 ↓
kernel execution begins
```

</details>

The cancellation token doesn't automatically interrupt the LLM call.

This is a real end-to-end cancellation gap.

---

# 23. The kernel cancellation path is better

Once code reaches:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
kernel.execute(
    code,
    timeout=self.cell_timeout,
    cancel_event=self.cancel_token
)
```

</details>

the lower runtime can propagate cancellation into the Jupyter kernel.

That's good.

So cancellation currently looks like:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
LLM generation       ❌ not interruptible here
       ↓
Python execution     ✅ interruptible
       ↓
next cell            ✅ checked
       ↓
next turn             ✅ checked
```

</details>

The missing part is LLM generation cancellation.

---

# 24. Budgeting is conceptually good

The loop creates:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
BudgetTracker(self.budget)
```

</details>

per agent:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
analyst → tracker A
critic  → tracker B
narrator → tracker C
```

</details>

<sup>[source]</sup>

This avoids one greedy agent consuming another agent's budget.

That's a thoughtful design.

But the comment says:

> child agent cannot consume session's shared resources.

That statement is only true if `ExecutionBudget` itself represents the intended resource boundary.

If the actual kernel pool is shared, an agent can still consume:

- kernels,
- memory,
- wall-clock resources,
- CPU,

unless those are independently enforced.

So this is an **accounting isolation**, not complete resource isolation.

---

# 25. Another subtle issue: budget wrapper + export

In isolated mode:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
kernel
 ↓
BudgetedExecutor
 ↓
execute turn
```

</details>

Then `_export_turn()` calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
kernel.execute_silent(...)
```

</details>

through the same wrapper.

Therefore the export operation consumes the agent's budget too.

Likewise:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
seed code
```

</details>

also executes through the budget wrapper.

So an agent's declared budget may actually be consumed by:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
seed + agent cells + export
```

</details>

rather than just agent work.

That may be correct, but it should be explicit.

---

# 26. Namespace prompt leakage

`_build_system()` embeds:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
namespace = kernel.namespace
```

</details>

directly into the system prompt. <sup>[source]</sup>

That means potentially enormous data can enter the LLM context.

If the namespace contains:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
df = 1,000,000 rows
model = huge object
results = large JSON
```

</details>

the namespace representation could:

- explode prompt size,
- consume tokens,
- leak sensitive data,
- slow every turn.

This is a major scalability issue.

The agent should receive a **bounded namespace summary**, not the entire namespace.

---

# 27. Better:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
CURRENT KERNEL NAMESPACE

Variables:
  df_customers: DataFrame(124,381 × 18)
  model_churn: LogisticRegression
  results_auc: 0.842
  critique_flags: list[3]

Inspectable:
  df_customers
  model_churn
```

</details>

rather than serializing arbitrary object contents.

That would be dramatically more efficient.

---

# 28. The current `reads` field isn't enforced

`AgentRole` has:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
reads: list[str]
```

</details>

but the visible loop does not use it to restrict namespace access.

The role declares:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
reads = [...]
```

</details>

yet `_build_system()` gives the agent:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kernel.namespace
```

</details>

which potentially exposes everything.

So:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
writes = enforced
reads = apparently advisory
```

</details>

This is a major asymmetry.

If `reads` is intended as a capability boundary, it is not currently enforced here.

---

# 29. This is particularly important for isolated mode

In isolated mode, the agent receives:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
shared.seed_code()
```

</details>

which materializes all shared values.

Then the agent can inspect every seeded value, regardless of:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
role.reads
```

</details>

So the actual access policy is:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
all shared values are readable
```

</details>

not:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
role.reads
```

</details>

This is fine if intentional.

But then `reads` should either be removed or implemented.

---

# 30. Shared mode is explicitly trusted

The documentation says shared mode is:

> only for trusted roles. <sup>[source]</sup>

That's correct.

In shared mode:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
analyst
  ↓
same mutable namespace
  ↓
critic
  ↓
same namespace
```

</details>

There is no meaningful isolation.

Therefore `writes` isn't a true sandbox boundary in shared mode.

It's mostly governance/diagnostics.

That distinction should be prominent in public documentation.

---

# 31. `max_turns` is actually maximum loop iterations

Because:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
for turn_idx in range(self.max_turns)
```

</details>

`max_turns` means:

> maximum total agent turns across all roles.

It does **not** mean:

> maximum turns per agent.

That's probably correct, but worth documenting.

For:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
3 agents
max_turns = 6
```

</details>

you get:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
analyst
critic
narrator
analyst
critic
narrator
```

</details>

not six turns each.

---

# 32. Empty role list is not validated

This is a small but concrete bug.

If:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
roles = []
```

</details>

then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self.turn_order = []
```

</details>

and:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self.turn_order[turn_idx % len(self.turn_order)]
```

</details>

becomes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
ZeroDivisionError
```

</details>

The constructor should reject:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
roles == []
turn_order == []
```

</details>

immediately.

---

# 33. `turn_order` can reference nonexistent roles

The loop handles this:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
role = self.roles.get(agent_name)

if role is None:
    log.warning(...)
    continue
```

</details>

But silently skipping an invalid role means:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
turn 1 → valid
turn 2 → nonexistent
turn 3 → valid
```

</details>

and the session still proceeds.

For deterministic orchestration, invalid `turn_order` should be rejected during construction.

---

# 34. The most important architectural improvement

I would change the loop from:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
LLM
 ↓
string code
 ↓
execute
```

</details>

to:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

```text
LLM
 ↓
AgentAction
 ↓
policy validation
 ↓
budget check
 ↓
kernel execution
 ↓
ExecutionResult
 ↓
state transition
```

</details>

Specifically:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
AgentAction
├── action_id
├── agent
├── kind
├── code
├── handoff
└── requested_outputs
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

```text
ExecutionResult
├── action_id
├── status
├── output
├── error
├── duration
├── kernel_generation
└── cancellation
```

</details>

Now the entire system becomes traceable.

---

# 35. Target end-to-end state machine

The current implementation is roughly:

<details>
<summary><strong>💻 Code Block (text) — 17 lines</strong></summary>

```text
TURN
 │
 ▼
LLM
 │
 ▼
CODE
 │
 ▼
KERNEL
 │
 ├── error → recovery
 │
 └── success
       │
       ▼
   yield?
```

</details>

I'd make it:

<details>
<summary><strong>💻 Code Block (text) — 33 lines</strong></summary>

```text
TURN_CREATED
      │
      ▼
CHECK_CANCEL
      │
      ▼
CHECK_BUDGET
      │
      ▼
GENERATE_ACTION
      │
      ▼
VALIDATE_ACTION
      │
      ▼
EXECUTE
   ┌──┼───────────┐
   │  │           │
   ▼  ▼           ▼
OK ERROR      CANCELLED
   │  │           │
   │  ▼           ▼
   │ RECOVER    TERMINATE
   │  │
   │  └── retry
   ▼
OBSERVE
   │
   ▼
COMMIT
   │
   ▼
YIELD/HANDOFF?
```

</details>

This gives us an actual transaction boundary.

---

# 36. Revised verdict for the agent loop

| Area | Assessment |
|---|---|
| Multi-agent architecture | 🟢 Strong |
| Role model | 🟢 Strong |
| Agent identity | 🟢 Strong |
| Explicit shared memory | 🟢 Strong |
| Namespace write isolation | 🟢 Good |
| Isolated fresh kernels | 🟢 Strong concept |
| Per-agent budget trackers | 🟢 Good |
| Recovery loop | 🟢 Good foundation |
| Deterministic round-robin | 🟢 Good |
| Dynamic handoff | 🟠 Not actually implemented |
| Read permissions | 🔴 Not enforced |
| Cancellation during LLM generation | 🔴 Gap |
| Cancellation/export interaction | 🔴 Needs fix |
| Session error semantics | 🔴 Incomplete |
| Empty/invalid role validation | 🟠 Missing |
| Namespace prompt size | 🔴 Scalability/privacy concern |
| SharedMemory versioning | 🟠 Missing |
| Structured action protocol | 🟠 Needed |
| Turn transaction semantics | 🟠 Needs formalization |

---

# 37. Most important finding so far

The Kerno architecture has a surprisingly coherent progression:

<details>
<summary><strong>💻 Code Block (text) — 26 lines</strong></summary>

```text
                    Agent
                      │
              AgentAction needed
                      │
                      ▼
                MultiAgentLoop
                      │
               execution policy
                      │
                      ▼
                  KernelPool
                      │
                resource policy
                      │
                      ▼
                KernelRuntime
                      │
               execution policy
                      │
                      ▼
              OutputCollector
                      │
                protocol policy
                      │
                      ▼
                    IOPUB
```

</details>

The lower layers are already thinking in terms of **resource ownership, generations, cancellation, recovery, and isolation**.

The missing piece is a similarly rigorous **agent transaction model**.

That is where I'd focus next.

### Next audit target

The next file to inspect should be the execution-budget layer:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kerno/execution/budget.py
```

</details>

because the agent loop now depends critically on:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
BudgetTracker
BudgetedExecutor
ExecutionBudget
```

</details>

and we need to verify whether the claimed per-agent isolation is **actually enforced**, particularly across:

- kernel execution time,
- cell count,
- retries,
- cancellation,
- isolated seed/export operations,
- and shared versus isolated sessions.

That will determine whether Kerno's **budget boundary is real or merely accounting metadata**.

---

## [41] USER

Continue 

---

## [42] CHATGPT (gpt-5-6)

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
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"BudgetedExecutor","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"BudgetTracker ExecutionBudget","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/execution/budget.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

# Continue — deep audit of `kerno/execution/budget.py`

This file is important because it defines the resource contract used by the agent loop. The design is good in concept, but there is **one major architectural flaw** in the hierarchical-budget implementation and several important semantic issues.

[Open `budget.py` on the Kerno branch](https://github.com/Abdus2023/Kerno/blob/arena/01a0064f-kerno/kerno/execution/budget.py)

---

## 1. The basic budget model is clean

Kerno defines three resource dimensions:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
ExecutionBudget
├── max_executions
├── max_wall_time
└── max_output_bytes
```

</details>

<sup>[source]</sup>

This is a good minimal model.

It gives three distinct controls:

| Limit | Meaning |
|---|---|
| `max_executions` | Number of executions/cells |
| `max_wall_time` | Cumulative execution time |
| `max_output_bytes` | Cumulative stdout |

This is much better than having only a generic "timeout."

---

# 2. The enforcement model is intentionally non-preemptive

The implementation explicitly chooses:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
max_executions
    ↓
checked BEFORE execution

wall time
    ↓
measured AFTER execution

output
    ↓
measured AFTER execution
```

</details>

<sup>[source]</sup>

That means:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
budget = 10 seconds

execution #1 = 7 s
execution #2 = 7 s
```

</details>

is allowed to complete.

After execution #2:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
spent = 14 s
```

</details>

and the **next** execution is refused.

This is actually a good policy for notebook execution because abruptly killing a completed Python execution merely to enforce an aggregate budget can leave the kernel in an unpredictable state.

So the design choice itself is sound.

---

# 3. `max_executions` is genuinely enforced before touching the kernel

This is one of the strongest parts.

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._tracker.check_can_start()
```

</details>

runs before:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._executor.execute(...)
```

</details>

<sup>[source]</sup>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
budget exhausted
       ↓
BudgetExceeded
       ↓
underlying kernel NOT touched
```

</details>

That's exactly the invariant we want.

---

# 4. The wrapper turns budget exhaustion into an error cell

Instead of raising:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
BudgetExceeded
```

</details>

to the agent loop, `BudgetedExecutor.execute()` returns:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
CellOutput(
    error=CellError(
        ename="BudgetExceeded",
        ...
    )
)
```

</details>

<sup>[source]</sup>

This is an interesting choice because it makes budget exhaustion look like an ordinary failed execution.

And that exposes a problem.

---

# 5. Major issue: budget exhaustion is semantically NOT a normal execution error

The agent loop's recovery mechanism can potentially see:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
ename = BudgetExceeded
```

</details>

as:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Python execution failed
```

</details>

rather than:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
agent is permanently out of budget
```

</details>

So you can get:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
BudgetExceeded
      ↓
LLM receives error
      ↓
RecoveryStrategy
      ↓
LLM proposes another action
      ↓
BudgetedExecutor
      ↓
BudgetExceeded
```

</details>

The wrapper will continue refusing execution, but the agent may waste turns trying to recover from a condition that is not recoverable.

The budget layer should expose a machine-readable terminal condition.

For example:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
ExecutionResult.status =
    SUCCESS
    ERROR
    TIMEOUT
    CANCELLED
    BUDGET_EXCEEDED
```

</details>

rather than representing everything as a `CellOutput.error`.

---

# 6. The comment says "stops recovering" — but the code doesn't guarantee that

The docstring says:

> the agent loop sees a normal failed cell and stops recovering. <sup>[source]</sup>

But `BudgetedExecutor` itself does not stop recovery.

It merely returns:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
CellError(ename="BudgetExceeded")
```

</details>

Whether the loop stops depends entirely on the agent-loop/recovery implementation.

That means this statement is an **implicit cross-module contract**, not something enforced here.

I'd make it explicit in the execution result.

---

# 7. Sticky exhaustion is good

This is a strong design:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._exceeded = exc
```

</details>

Once wall-time/output budget is crossed:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

```text
id="9c6q8f"
execution completes
        ↓
budget becomes exceeded
        ↓
_exceeded = BudgetExceeded
        ↓
all future executions blocked
```

</details>

<sup>[source]</sup>

That prevents the agent from repeatedly trying to execute after the budget has been exhausted.

---

# 8. `max_executions=0` works correctly

Because:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._executions >= self.budget.max_executions
```

</details>

immediately evaluates:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
0 >= 0
```

</details>

the first execution is refused.

That's a nice edge-case behavior.

---

# 9. Negative limits are not validated

This is a concrete missing validation.

For example:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
ExecutionBudget(max_executions=-1)
```

</details>

will effectively mean:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
0 >= -1
```

</details>

and immediately reject execution.

Similarly:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
ExecutionBudget(max_wall_time=-5)
```

</details>

is nonsensical.

The constructor should validate:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
max_executions >= 0
max_wall_time >= 0
max_output_bytes >= 0
```

</details>

or reject `None`/invalid values explicitly.

---

# 10. Negative duration/output accounting isn't protected

`record()` accepts:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
duration_s: float
output_bytes: int
```

</details>

without validation.

A caller could theoretically do:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
record(-100, -500)
```

</details>

and reduce the accumulated budget.

The normal executor won't do that, but `BudgetTracker` is a public accounting primitive.

Defensive validation should reject negative measurements.

---

# 11. The output budget only counts stdout

The implementation does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
len(output.stdout)
```

</details>

<sup>[source]</sup>

Therefore `max_output_bytes` does not necessarily include:

- stderr,
- rich display data,
- images,
- HTML,
- JSON MIME payloads,
- traceback strings,
- metadata.

If Kerno calls this:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
max_output_bytes
```

</details>

that's potentially misleading.

A better definition would be:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
max_stdout_bytes
```

</details>

or aggregate all serialized output channels.

---

# 12. Output can therefore bypass the budget

Imagine:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
stdout = 1 KB
display_data = 100 MB
```

</details>

The budget sees:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
1 KB
```

</details>

even though the actual output produced by the execution may be enormous.

For a notebook/agent system this matters significantly.

An LLM-facing system should probably have:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
max_stdout_bytes
max_stderr_bytes
max_display_bytes
max_total_output_bytes
```

</details>

or at minimum:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
serialized_output_bytes
```

</details>

---

# 13. Wall-time is execution time, not total agent time

This is another important distinction.

The tracker measures:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
start = time.monotonic()
output = self._executor.execute(...)
duration_s = ...
```

</details>

<sup>[source]</sup>

Therefore the budget excludes:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
LLM generation
prompt construction
namespace processing
recovery reasoning
queue waiting
kernel acquisition
export
```

</details>

So:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
max_wall_time = 60 sec
```

</details>

does **not** mean:

> this agent may consume at most 60 seconds of wall-clock session time.

It means:

> underlying executor calls may cumulatively run for at most 60 seconds before future execution is blocked.

That's a valid policy, but the name/documentation should make this distinction explicit.

---

# 14. This confirms our previous agent-loop finding

We previously suspected that:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
BudgetTracker
```

</details>

was mostly execution accounting.

Now we can confirm it.

The budget does **not** directly control:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
LLM time
kernel acquisition
pool waiting
namespace operations
shared-memory operations
handoff
```

</details>

Therefore the actual agent resource boundary is:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
              Agent
                │
      ┌─────────┴─────────┐
      │                   │
  LLM generation      Executor
                          │
                    BudgetedExecutor
                          │
                    ExecutionBudget
```

</details>

Only the right-hand branch is budgeted.

---

# 15. The biggest flaw: `BudgetAllocator` does not track actual child consumption

This is the most important finding in this file.

The allocator does:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
Parent = 100 executions

allocate Child A = 30
allocate Child B = 40

remaining = 30
```

</details>

That's fine as **reservation accounting**.

But there is no connection between:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
BudgetTracker
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
BudgetAllocator
```

</details>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Parent budget = 100
Child A allocated = 30
Child A actually uses = 5
```

</details>

The allocator still considers:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
30 allocated
```

</details>

rather than:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
5 consumed
```

</details>

This is intentional reservation semantics perhaps, but the documentation calls it a parent budget.

We need to distinguish:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
allocated
reserved
consumed
remaining
```

</details>

---

# 16. More seriously: the parent budget isn't actually enforced by children

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
parent = 100 executions
child = allocate(30)
```

</details>

The child receives:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
ExecutionBudget(max_executions=30)
```

</details>

Good.

But the parent has no `BudgetTracker` reference.

So the child can consume:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
30
```

</details>

while the parent tracker, if one exists separately, doesn't automatically know that those 30 were consumed.

The hierarchy is therefore:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Parent allocation
        │
        └── creates child limit
```

</details>

not:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Parent resource counter
        │
        ├── Child A consumption
        ├── Child B consumption
        └── Child C consumption
```

</details>

That's a significant distinction.

---

# 17. `BudgetAllocator.allocate()` has a particularly dangerous `None` behavior

Suppose:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
parent = ExecutionBudget(max_executions=100)
allocator = BudgetAllocator(parent)
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
allocator.allocate()
```

</details>

does:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
remaining = 100
child.max_executions = 100
```

</details>

and then commits:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
allocated_exec += parent.max_executions
```

</details>

so:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
allocated = 100
remaining = 0
```

</details>

That's reasonable.

But if the parent is:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
ExecutionBudget(max_executions=None)
```

</details>

then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
allocate(executions=None)
```

</details>

creates:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
child.max_executions = None
```

</details>

which means unlimited.

That's also logically consistent.

---

# 18. But mixed finite/infinite dimensions require careful semantics

Example:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
parent:
    executions = 100
    wall_time = None
    output = 1 MB
```

</details>

Child:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
allocate(
    executions=50,
    output_bytes=None
)
```

</details>

gets:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
executions = 50
output = 1 MB remaining
```

</details>

Good.

But the allocator reserves the entire 1 MB.

Another child asking for:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
output_bytes=1
```

</details>

gets rejected.

Even if the first child actually outputs only:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
10 KB
```

</details>

So again:

> allocation ≠ consumption.

That should be explicit.

---

# 19. `name` isn't actually part of the child budget

`allocate(..., name="analyst")` stores:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._names[child_name] = child
```

</details>

but the returned `ExecutionBudget` doesn't contain:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
name
```

</details>

So the name is only an allocator-side lookup.

That's okay, but it means the budget object itself cannot identify its owner.

For observability, I'd add:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
BudgetAllocation
├── id
├── name
├── budget
├── tracker
└── parent
```

</details>

rather than returning a bare `ExecutionBudget`.

---

# 20. `_children` stores budgets but not trackers

The allocator maintains:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._children: list[ExecutionBudget]
```

</details>

<sup>[source]</sup>

That means it knows:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
what was allocated
```

</details>

but not:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
what was consumed
```

</details>

A stronger implementation would maintain:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
ChildAllocation
├── budget
├── tracker
├── allocated
└── consumed
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
remaining =
    parent_limit
    - sum(actual child consumption)
```

</details>

if the intended model is consumption-based.

---

# 21. Another subtle issue: allocation is not thread-safe

`BudgetTracker` has mutable fields:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
_executions
_wall_time
_output_bytes
_exceeded
```

</details>

and `BudgetAllocator` has:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
_allocated_exec
_allocated_time
_allocated_output
_children
```

</details>

with no locks.

If one budget can be shared across concurrent executions:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
Thread A → record()
Thread B → record()
```

</details>

updates can race.

If Kerno guarantees:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
one executor → one active execution
```

</details>

then that's fine.

But the allocator may eventually be used for multiple agents.

Then synchronization becomes necessary.

---

# 22. This connects to the KernelPool invariant

Earlier we identified:

> one `PooledKernel` should have one active execution.

If that invariant holds, then a per-agent `BudgetTracker` may also be single-writer.

That's a good reason to preserve:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
one task
   ↓
one kernel
   ↓
one execution at a time
   ↓
one BudgetTracker writer
```

</details>

If Kerno later introduces concurrent execution within an agent, this budget implementation will need synchronization.

---

# 23. `execute_silent()` still consumes output budget

This is important for the agent-loop isolated mode.

`execute_silent()` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
output = self.execute(... silent=True ...)
```

</details>

and then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
return output.stdout.strip()
```

</details>

<sup>[source]</sup>

So seed/export operations that are executed silently still count:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
execution count
wall time
stdout bytes
```

</details>

As noted earlier, this means the effective budget includes infrastructure operations.

That can produce surprising behavior:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
max_executions = 10

seed = 1
agent work = 9
export = 1

→ budget exhausted
```

</details>

The agent technically got only 9 work executions.

---

# 24. That may be the wrong abstraction

I'd separate:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
AgentBudget
```

</details>

from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
InfrastructureBudget
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Agent budget:
    user-visible executions = 10

Infrastructure:
    seed/export do not consume agent quota
```

</details>

or explicitly count them separately:

<details>
<summary><strong>💻 Code Block (json) — 5 lines</strong></summary>

```json
{
  "agent_executions": 9,
  "infrastructure_executions": 2,
  "total_executions": 11
}
```

</details>

This makes diagnostics much easier.

---

# 25. The `raw_kernel` escape hatch is powerful but dangerous

The wrapper exposes:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
@property
def raw_kernel(self):
```

</details>

<sup>[source]</sup>

and deliberately calls it:

> for trusted infrastructure.

That's reasonable.

But it creates a budget bypass:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
BudgetedExecutor
       │
       ├── execute() → budget enforced
       │
       └── raw_kernel.execute() → potentially bypasses budget
```

</details>

Any code that receives the wrapper can potentially access the raw kernel.

Therefore:

> `raw_kernel` must never be exposed to untrusted agent/tool code.

This should be a hard architectural rule, not merely a docstring warning.

---

# 26. The `records` passthrough is similarly important

The wrapper exposes:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
return getattr(self._executor, "records", ())
```

</details>

That's good for observability.

But if records contain:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
source code
stdout
stderr
exceptions
metadata
```

</details>

then agent-facing code may gain access to information outside its declared `reads`.

Again:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
trusted infrastructure → okay
agent/plugin code → potentially dangerous
```

</details>

---

# 27. BudgetExceeded should be a first-class execution status

I would change the result contract to:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
ExecutionResult
├── status
├── output
├── error
├── duration
├── budget
└── metadata
```

</details>

with:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
status =
    SUCCESS
    ERROR
    TIMEOUT
    CANCELLED
    BUDGET_EXCEEDED
```

</details>

Then the loop can do:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
BUDGET_EXCEEDED
      ↓
terminate agent
```

</details>

instead of:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
CellError
      ↓
maybe recovery
      ↓
LLM
```

</details>

---

# 28. Recommended hierarchical budget model

The clean architecture would be:

<details>
<summary><strong>💻 Code Block (text) — 14 lines</strong></summary>

```text
SessionBudget
      │
      ▼
BudgetAllocator
      │
      ├──────────────┐
      ▼              ▼
AgentAllocation A   AgentAllocation B
      │              │
      ▼              ▼
BudgetTracker A     BudgetTracker B
      │              │
      ▼              ▼
Executor A          Executor B
```

</details>

And consumption should flow upward:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
execution
   ↓
AgentTracker
   ↓
SessionTracker
```

</details>

Then the invariant becomes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
sum(child consumption) <= parent consumption/limit
```

</details>

depending on whether the parent is reservation-based or consumption-based.

---

# 29. Better data model

I'd replace the current conceptual split with:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
BudgetAllocation:
    name
    limit
    tracker
    parent
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
BudgetAllocation
       │
       ├── limit
       │     ├── executions
       │     ├── wall_time
       │     └── output
       │
       └── usage
             ├── executions
             ├── wall_time
             └── output
```

</details>

This eliminates the ambiguity between:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
allocated
spent
remaining
```

</details>

---

# 30. Current severity

| Finding | Severity |
|---|---|
| Child allocation not connected to parent consumption | 🔴 P1 |
| BudgetExceeded represented as ordinary cell error | 🔴 P1 |
| `raw_kernel` can bypass budget | 🔴 P1 security boundary |
| Output budget counts stdout only | 🟠 P1 |
| Budget excludes LLM/session wall time | 🟠 P1 semantic |
| Seed/export consume agent budget | 🟠 P1 |
| Negative limits not validated | 🟡 P2 |
| Negative accounting values accepted | 🟡 P2 |
| Allocator not thread-safe | 🟡 P2 |
| Allocation/name model weak | 🟡 P2 |

---

# 31. Overall verdict

The basic execution budget is **good and usable**:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
preflight execution limit
+
sticky wall/output exhaustion
+
post-execution accounting
+
observability snapshot
```

</details>

That's a solid foundation.

The hierarchical allocator, however, is currently closer to a:

> **budget reservation calculator**

than a true hierarchical resource controller.

That's the distinction I'd fix before calling the multi-agent budget architecture complete.

---

## The next critical layer

We have now established:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
MultiAgentLoop
      │
      ▼
BudgetedExecutor
      │
      ▼
ExecutionBudget
      │
      ▼
KernelRuntime
```

</details>

The next thing to audit is the **actual execution engine / output contract**, because we need to answer one final critical question:

> When `BudgetedExecutor.execute()` returns `CellOutput`, does that object reliably distinguish **Python error, timeout, cancellation, kernel death, and successful execution**?

That determines whether the entire chain:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Agent
 → Budget
 → Runtime
 → IOPUB
 → Result
```

</details>

can preserve failure semantics without losing information.

---

## [43] USER

Continue 

---

## [44] CHATGPT (gpt-5-6)

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
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"class ExecutionEngine","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"ExecutionEngine execute CellOutput","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/execution","ref":"arena/01a0064f-kerno"}}
```

</details>

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"CellOutput(","topn":50}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/kernel/output.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/types.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>💭 Thinking Process</strong></summary>

> Fetched the types file

</details>



---

## [45] CHATGPT (gpt-5-6)

# Continue — `kerno/kernel/output.py` + `kerno/types.py`

This is the next critical layer, and the result is actually encouraging: **Kerno has a reasonably good structured execution-result model**, but there is a serious mismatch between what the types can represent and what the output collector actually records.

The two relevant files are `kerno/kernel/output.py` and `kerno/types.py`. <sup>[source]</sup>

---

## 1. `CellOutput` is the correct abstraction

The central type is:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
CellOutput
├── stdout
├── stderr
├── result
├── displays
├── images
├── error
├── duration
└── execution_id
```

</details>

<sup>[source]</sup>

This is exactly what an agent-oriented notebook runtime needs.

It avoids forcing every caller to understand raw Jupyter/ZeroMQ messages.

The intended pipeline is:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
ZMQ / IOPub
     ↓
OutputCollector
     ↓
CellOutput
     ↓
Agent / Budget / Session
```

</details>

That's a strong boundary.

---

# 2. `CellError` is also nicely minimal

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
CellError
├── ename
├── evalue
└── traceback
```

</details>

<sup>[source]</sup>

This preserves the three things an LLM generally needs:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
what failed
why it failed
where it failed
```

</details>

And `OutputCollector` strips ANSI escape sequences from tracebacks, which is good for machine-readable error processing. <sup>[source]</sup>

---

# 3. Python exceptions are captured correctly

When IOPub sends:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
msg_type = "error"
```

</details>

the collector produces:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
CellError(
    ename=...,
    evalue=...,
    traceback=...
)
```

</details>

<sup>[source]</sup>

So:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
raise ValueError("bad data")
```

</details>

becomes something like:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
CellOutput.error.ename
    = ValueError

CellOutput.error.evalue
    = bad data
```

</details>

That's correct.

---

# 4. Timeout is represented as a kernel-level error

When the deadline expires:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
TimeoutError
```

</details>

is placed into `CellOutput.error`. <sup>[source]</sup>

Likewise cancellation becomes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
KernelInterrupted
```

</details>

This means the output layer already has enough information for the agent loop to distinguish:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Python error
Timeout
Cancellation
```

</details>

**provided the caller examines `error.ename`.**

---

# 5. But this reveals the budget problem we identified

Budget exhaustion also becomes:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
CellError(
    ename="BudgetExceeded"
)
```

</details>

So the system currently has several fundamentally different conditions represented using the same mechanism:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
CellOutput.error
├── ValueError
├── SyntaxError
├── TimeoutError
├── KernelInterrupted
└── BudgetExceeded
```

</details>

This works, but it's semantically weak.

The better model is:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
ExecutionStatus
├── SUCCESS
├── PYTHON_ERROR
├── TIMEOUT
├── CANCELLED
├── BUDGET_EXCEEDED
└── KERNEL_DIED
```

</details>

with `CellError` carrying the detailed exception only when applicable.

---

# 6. There is already a `SessionStatus.KERNEL_DIED`

This is interesting.

`SessionStatus` includes:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
RUNNING
COMPLETE
MAX_CELLS
INTERRUPTED
KERNEL_DIED
ERROR_UNHANDLED
```

</details>

<sup>[source]</sup>

So the project already recognizes kernel death as a **session-level semantic event**.

But `CellOutput` itself doesn't have:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
KERNEL_DIED
```

</details>

as an explicit status.

That creates an abstraction gap:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Cell layer:
    error / no error

Session layer:
    KERNEL_DIED
```

</details>

The intermediate execution layer has to infer kernel death.

---

# 7. `is_empty` is useful but slightly misleading

<details>
<summary><strong>💻 Code Block (python) — 8 lines</strong></summary>

```python
return (
    not stdout
    and not stderr
    and result is None
    and not displays
    and not images
    and not has_error
)
```

</details>

<sup>[source]</sup>

So a successful:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
x = 1
```

</details>

can produce:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
CellOutput(
    stdout="",
    stderr="",
    result=None
)
```

</details>

and be considered:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
is_empty = True
```

</details>

But:

> empty output does not mean empty execution.

It means:

> execution produced no captured user-visible output.

I'd rename it:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
has_visible_output
```

</details>

and perhaps retain `is_empty` only as a compatibility convenience.

---

# 8. `as_text()` is very useful for LLM consumption

The method prioritizes:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
ERROR
stdout
result
images
displays
```

</details>

<sup>[source]</sup>

That's exactly the right direction.

For an agent, this:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
[ERROR] NameError: df is not defined
...
```

</details>

is much more useful than dumping raw IOPub JSON.

---

# 9. But `as_text(max_chars)` doesn't bound every component

This is a subtle but important scalability issue.

`stdout` is bounded.

But:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
self.error.traceback
```

</details>

is only reduced to the last 5 lines.

Those five lines can theoretically be huge.

Likewise:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
HTML
```

</details>

is reduced to 500 characters, which is good.

But:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
result
```

</details>

is sliced to 500.

Images are represented only by count.

Overall it's reasonably bounded, but the method doesn't enforce a strict **global character budget**.

For LLM context safety, that's preferable:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
as_text(max_chars=3000)
```

</details>

should guarantee:

<details>
<summary><strong>💻 Code Block (text) — 0 lines</strong></summary>

```text

```

</details>

Currently it does not necessarily do so.

---

# 10. The output collector has a strong single-reader design

This comment is important:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
IOPub has ONE consumer
```

</details>

and Kerno introduces:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
IOPUB_LOCK = threading.RLock()
```

</details>

<sup>[source]</sup>

This is a good response to a real Jupyter architecture constraint.

Without it:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
collector thread ──┐
                   ├── IOPub socket
KernoComm thread ──┘
```

</details>

could steal messages from each other.

Particularly:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
status: idle
```

</details>

could be consumed by the wrong reader, leaving the execution waiting forever.

The lock prevents that.

---

# 11. But the global `IOPUB_LOCK` is a scalability bottleneck

The lock is global:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
IOPUB_LOCK = threading.RLock()
```

</details>

<sup>[source]</sup>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Kernel A collecting
        │
        ▼
   global lock
        │
        X
Kernel B collecting
```

</details>

If Kerno supports multiple kernels simultaneously—which `KernelPool` clearly intends to—this means output collection for independent kernels can serialize.

That's unnecessary.

The correct granularity is likely:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Kernel A → IOPub lock A
Kernel B → IOPub lock B
Kernel C → IOPub lock C
```

</details>

rather than:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
all kernels → one global lock
```

</details>

---

# 12. This could become a serious throughput limitation

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
8 agents
8 kernels
```

</details>

and each is executing long-running work.

With a global lock:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Agent A collects
Agent B waits
Agent C waits
Agent D waits
...
```

</details>

Even though the kernels are completely independent.

The lock only needs to protect:

> readers of the same IOPub socket.

It does not need to protect all IOPub sockets globally.

---

# 13. `comm_msg` handling is architecturally clever

Instead of a competing reader:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
KernoComm thread → get_iopub_msg()
```

</details>

the collector handles:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
case "comm_msg":
    handler(msg)
```

</details>

<sup>[source]</sup>

This is a good design.

The data path becomes:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

```text
IOPub
 │
 ▼
OutputCollector
 ├── stream
 ├── error
 ├── display
 ├── status
 └── comm_msg
       │
       ▼
   KernoComm
```

</details>

rather than two competing consumers.

That's exactly the correct architectural direction.

---

# 14. But `_comm_handler` is global too

The handler is stored as:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
_comm_handler
```

</details>

<sup>[source]</sup>

This means there is only one global comm handler for the entire process.

If you have:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
Kernel A → comm messages
Kernel B → comm messages
```

</details>

the same handler receives both.

The handler therefore needs to distinguish:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
which kernel/session produced this message?
```

</details>

If that context isn't attached or derivable from `msg`, cross-kernel event routing becomes ambiguous.

A per-kernel dispatcher would be cleaner.

---

# 15. The collector doesn't verify `msg_id`

This is an important protocol observation.

The function receives:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
collect(kc, msg_id, ...)
```

</details>

but the code processes every IOPub message arriving on the socket.

It doesn't appear to filter messages by:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
parent_header.msg_id == msg_id
```

</details>

Instead it waits for:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
status == idle
```

</details>

This is usually workable if the kernel has exactly one outstanding execution.

But it becomes fragile if:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
multiple execute requests
```

</details>

are in flight.

---

# 16. This reinforces the one-execution invariant

The architecture should explicitly guarantee:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
KernelRuntime
    ↓
one outstanding execute_request
    ↓
one collector
```

</details>

If that is enforced, the collector's design is safe enough.

If concurrent requests are ever supported, this collector needs a proper demultiplexer keyed by:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
parent_header.msg_id
```

</details>

---

# 17. Another problem: timeout returns without proving the kernel is idle

On timeout:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
output.error = TimeoutError
break
```

</details>

<sup>[source]</sup>

It calls:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
on_timeout()
```

</details>

which presumably interrupts the kernel.

But the collector does **not** wait for:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
status: idle
```

</details>

after interrupting.

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
collector returns
       ↓
kernel may still be executing
```

</details>

This is a critical lifecycle boundary.

The runtime must ensure that the kernel is actually quiescent before allowing the same kernel to be reused.

---

# 18. Cancellation has the same issue

Cancellation:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
cancel_event.set()
```

</details>

causes:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
on_timeout()
output.error = KernelInterrupted
break
```

</details>

and returns.

Again:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
return to caller
       ↓
kernel may still be stopping
```

</details>

If the pool immediately does:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
release()
reset()
available.put()
```

</details>

we could have:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
old execution still unwinding
          +
new task starts
```

</details>

That would be catastrophic.

---

# 19. This is one of the most important end-to-end findings

We can now connect three layers:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
OutputCollector
    ↓
returns after interrupt request

KernelRuntime
    ↓
may still be waiting for actual idle

KernelPool
    ↓
may eventually recycle kernel
```

</details>

Therefore we need a hard invariant:

> **A timeout/cancellation is not complete until the kernel has reached a known quiescent state or has been declared dead and retired.**

This should be enforced in `KernelRuntime`, not left to the agent loop.

---

# 20. `SessionStatus.KERNEL_DIED` needs a reliable source

We now see how kernel death might be detected:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
IOPub stops responding
       ↓
timeout
       ↓
interrupt attempt
       ↓
kernel still unavailable
       ↓
kernel dead
```

</details>

But `OutputCollector` itself only produces:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
TimeoutError
```

</details>

So the runtime must perform the second-stage classification.

That is appropriate.

The final chain should be:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

```text
Timeout
  ↓
interrupt
  ↓
wait for idle
  ↓
success → TIMEOUT
failure → KERNEL_DIED
```

</details>

---

# 21. `CellOutput.duration` isn't populated by `collect()`

This is a concrete implementation gap.

`CellOutput` contains:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
duration: float = 0.0
```

</details>

<sup>[source]</sup>

But `collect()` itself records:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
deadline
```

</details>

rather than assigning:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
output.duration
```

</details>

So the field must be populated by a higher layer, if at all.

This creates another hidden contract.

Better for the collector to do:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
started = monotonic()
...
output.duration = monotonic() - started
```

</details>

Then every caller receives consistent execution timing.

---

# 22. `execution_id` is present but not generated here

`CellOutput` contains:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
execution_id
```

</details>

<sup>[source]</sup>

The comment says it is a universal correlation key.

But `OutputCollector.collect()` receives:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
msg_id
```

</details>

and does not visibly assign:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
output.execution_id = msg_id
```

</details>

That seems like a missed opportunity.

The collector has the natural correlation identifier available.

It should probably preserve it.

---

# 23. This matters enormously for observability

The ideal trace should be:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
session_id
    ↓
agent_id
    ↓
turn_id
    ↓
execution_id
    ↓
Jupyter msg_id
    ↓
IOPub messages
```

</details>

Then you can answer:

> Which agent caused this Python exception?

without reconstructing the entire event history.

Kerno is already very close to this.

---

# 24. `CellOutput` should probably include status

I'd minimally add:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
ExecutionStatus
```

</details>

to the model.

For example:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
SUCCESS
PYTHON_ERROR
TIMEOUT
CANCELLED
BUDGET_EXCEEDED
KERNEL_DIED
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
error
```

</details>

can remain the detailed exception payload.

This eliminates all the string-based inference currently required.

---

# 25. The session model should derive its status from execution status

Currently:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
SessionStatus
```

</details>

contains:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
MAX_CELLS
INTERRUPTED
KERNEL_DIED
ERROR_UNHANDLED
```

</details>

But no:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
BUDGET_EXCEEDED
TIMEOUT
```

</details>

So the session layer will likely need to infer them from cell errors.

I'd change this to something like:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
SessionStatus
├── RUNNING
├── COMPLETE
├── BUDGET_EXCEEDED
├── MAX_CELLS
├── INTERRUPTED
├── TIMEOUT
├── KERNEL_DIED
└── ERROR_UNHANDLED
```

</details>

---

# 26. There is an interesting positive feature: recovery is measurable

`SessionResult.recovery_count` detects:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
error cell
   ↓
next cell succeeds
```

</details>

<sup>[source]</sup>

That's a useful metric.

For agent evaluation, you can eventually measure:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
recovery rate
error rate
mean recovery attempts
```

</details>

But the heuristic is simplistic.

For example:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
error
error
success
```

</details>

counts only one recovery.

It might actually represent:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
two failed repair attempts
one successful repair
```

</details>

A richer execution ledger would record explicit parent/child relationships:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
execution #4
    caused_by = execution #3
    reason = recovery
```

</details>

---

# 27. Recommended execution record

Kerno would benefit enormously from:

<details>
<summary><strong>💻 Code Block (text) — 19 lines</strong></summary>

```text
ExecutionRecord
├── execution_id
├── session_id
├── agent_id
├── turn_id
├── kernel_id
├── kernel_generation
├── code
├── status
├── started_at
├── ended_at
├── duration
├── stdout_bytes
├── stderr_bytes
├── output_bytes
├── error_class
├── error
├── retry_of
└── budget_snapshot
```

</details>

Then `CellOutput` remains the user-facing result while the ledger carries operational metadata.

---

# 28. Final assessment of this layer

### Strong

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
✓ structured CellOutput
✓ structured CellError
✓ IOPub single-reader protection
✓ comm integration without competing reader
✓ timeout detection
✓ cancellation detection
✓ ANSI cleanup
✓ output normalization
✓ LLM-friendly as_text()
✓ correlation field exists
```

</details>

### Needs correction

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

```text
⚠ global IOPUB lock
⚠ global comm handler
⚠ no explicit msg_id demultiplexing
⚠ timeout/cancel returns before confirmed idle
⚠ duration not populated here
⚠ execution_id not propagated here
⚠ budget/error/status semantics mixed
⚠ output-byte accounting incomplete
```

</details>

---

# 29. Most important invariant discovered

At this point, the entire Kerno execution architecture should enforce:

<details>
<summary><strong>💻 Code Block (text) — 26 lines</strong></summary>

```text
EXECUTION START
      │
      ▼
execution_id assigned
      │
      ▼
one kernel owns request
      │
      ▼
IOPub collected exclusively
      │
      ├── SUCCESS
      ├── PYTHON_ERROR
      ├── TIMEOUT
      ├── CANCELLED
      ├── BUDGET_EXCEEDED
      └── KERNEL_DIED
      │
      ▼
kernel reaches IDLE
      │
      ▼
execution finalized
      │
      ▼
CellOutput / ExecutionRecord
```

</details>

The critical missing guarantee is the middle one:

> **TIMEOUT/CANCELLED → kernel definitely quiescent before reuse.**

That is the next thing I would verify in `kerno/kernel/runtime.py`, because it determines whether the pool can safely recycle a kernel after a failed or interrupted execution.

[Kerno — requested branch `arena/01a0064f-kerno`](https://github.com/Abdus2023/Kerno/tree/arena%2F01a0064f-kerno)

---

## [46] USER

Continue 

---

## [47] CHATGPT (gpt-5-6)

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
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"kernel runtime interrupt shutdown reset execute","topn":50}}
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
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/kernel/runtime.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

# Continue — `kerno/kernel/runtime.py` audit

This file confirms the concern from the previous stage: **Kerno has a sophisticated timeout-escalation design, but its state machine currently has a dangerous semantic gap around interrupt completion and kernel reuse.**

[Open `runtime.py` on the Kerno branch](https://github.com/Abdus2023/Kerno/blob/arena/01a0064f-kerno/kerno/kernel/runtime.py)

---

## 1. The intended execution lifecycle is good

The runtime currently follows:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
START
  ↓
READY
  ↓
execute()
  ↓
BUSY
  ↓
collect()
  ↓
READY
```

</details>

And timeout escalation is:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
execute
  ↓
collect timeout
  ↓
interrupt()
  ↓
optional grace period
  ↓
kill
  ↓
restart
```

</details>

That's a sensible architecture.

The problem is that the implementation sometimes **declares the kernel READY before proving that it is actually ready**. <sup>[source]</sup>

---

# 2. Critical finding: `interrupt()` immediately changes state back to READY

The implementation is:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
self._state = KernelRuntimeState.INTERRUPTING
self._km.interrupt_kernel()
self._state = KernelRuntimeState.READY
```

</details>

<sup>[source]</sup>

This is the single most important issue in this file.

`interrupt_kernel()` means approximately:

> send an interrupt request to the kernel process.

It does **not** prove:

> the Python code has stopped executing and the kernel is idle.

So this:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
INTERRUPTING
    ↓
SIGINT
    ↓
READY
```

</details>

should actually be:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
INTERRUPTING
    ↓
SIGINT
    ↓
wait for confirmed idle
    ↓
READY
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
INTERRUPTING
    ↓
SIGINT
    ↓
failed to become idle
    ↓
DEAD / RESTARTING
```

</details>

---

# 3. This creates a possible double-execution race

Consider:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
Agent A
   │
   ├── execute("while True: ...")
   │
   └── timeout
          ↓
      interrupt()
          ↓
      state = READY
```

</details>

Before the interrupted Python execution has actually finished:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Agent A
   ↓
execute("print('next')")
```

</details>

could theoretically occur.

Then:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
old execution
     +
new execution
     ↓
same kernel
```

</details>

That's precisely what the previous collector analysis warned about.

---

# 4. `collect()` also returns immediately after timeout/cancellation

The runtime calls:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
collect(
    ...,
    on_timeout=self.interrupt,
    cancel_event=cancel_event,
)
```

</details>

and then the `finally` block does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._state = KernelRuntimeState.READY
```

</details>

<sup>[source]</sup>

So there are **two independent paths** that can incorrectly produce READY:

<details>
<summary><strong>💻 Code Block (text) — 15 lines</strong></summary>

```text
timeout
  ↓
interrupt()
  ↓
READY

OR

cancel
  ↓
interrupt()
  ↓
collect returns
  ↓
READY
```

</details>

Neither path waits for an authoritative kernel-idle event.

---

# 5. The timeout escalation policy is actually quite good

There is a strong idea here:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
soft interrupt
    ↓
grace period
    ↓
hard kill
    ↓
restart
```

</details>

The implementation documents this as an escalation ladder. <sup>[source]</sup>

Conceptually:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
T0
 │
 ├── SIGINT
 │
 │   grace = 2s
 │
 ├── SIGKILL
 │
 │   wait = 5s
 │
 └── restart
```

</details>

That's much more robust than simply calling `restart_kernel()` immediately.

---

# 6. But `_escalate_timeout()` has a serious semantic issue

The code says:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if not self.is_alive:
    return
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
proc.kill()
proc.wait(...)
```

</details>

and:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self.restart()
```

</details>

<sup>[source]</sup>

The documentation says:

> if the kernel died on its own, leave it dead and let recovery handle restart.

That's a reasonable policy.

But there is an inconsistency with the `state` property.

If the process dies:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
is_alive = False
```

</details>

then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
state
```

</details>

eventually becomes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
DEAD
```

</details>

Good.

But `execute()` has:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
finally:
    self._state = READY
```

</details>

So the execution path can overwrite the dead state with:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
READY
```

</details>

before anyone asks `state`.

---

# 7. Fortunately, `state` has sticky death detection

This part is good:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if self._km is None or not self._km.is_alive():
    self._state = KernelRuntimeState.DEAD
```

</details>

<sup>[source]</sup>

So:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
process dies
    ↓
_state may temporarily say READY
    ↓
state property queried
    ↓
is_alive = False
    ↓
DEAD
```

</details>

This partially protects the system.

But it is still better to **never write READY after a failed execution until health has been verified**.

---

# 8. `_assert_running()` has a related weakness

It checks:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if not self.is_alive:
    raise RuntimeError(...)
```

</details>

rather than:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if self.state != READY:
    ...
```

</details>

<sup>[source]</sup>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
_state = INTERRUPTING
is_alive = True
```

</details>

would still allow:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
execute()
```

</details>

because the process is technically alive.

The lifecycle contract should be:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
execute allowed only when:
    state == READY
    AND process alive
```

</details>

not merely:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
process alive
```

</details>

---

# 9. Recommended state machine

I'd formalize it as:

<details>
<summary><strong>💻 Code Block (text) — 28 lines</strong></summary>

```text
CLOSED
  │
  ▼
STARTING
  │
  ▼
READY
  │
  ▼
BUSY
  │
  ├───────────────┐
  │               │
  ▼               ▼
SUCCESS         INTERRUPTING
  │               │
  ▼               ▼
READY          WAIT_IDLE
                  │
          ┌───────┴────────┐
          ▼                ▼
        READY             DEAD
                            │
                            ▼
                        RESTARTING
                            │
                            ▼
                          READY
```

</details>

Current code effectively has:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
INTERRUPTING → READY
```

</details>

without the `WAIT_IDLE` state.

---

# 10. `restart()` is stronger because it waits for readiness

This part is correct:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
self._km.restart_kernel()
self._kc.wait_for_ready(timeout=self.startup_timeout)
```

</details>

<sup>[source]</sup>

So restart provides a genuine readiness boundary.

That gives us a useful principle:

> `wait_for_ready()` is an authoritative readiness signal; `is_alive` alone is not.

---

# 11. `shutdown()` correctly distinguishes `now`

This is also good:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._km.shutdown_kernel(now=now)
```

</details>

The API allows graceful versus immediate shutdown.

But after shutdown:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_state = CLOSED
```

</details>

is set **before** the underlying kernel is actually stopped.

For most callers that's fine because CLOSED is a logical lifecycle state.

The more important issue is consistency: don't use `READY` as a logical state unless the kernel is genuinely ready.

---

# 12. `stream_execute()` has the same lifecycle weakness

It does:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
self._state = BUSY
yield from stream(...)
finally:
    self._state = READY
```

</details>

<sup>[source]</sup>

Therefore timeout/cancellation during streaming can also lead to:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
BUSY
 ↓
interrupt
 ↓
stream returns
 ↓
READY
```

</details>

without confirmation that the kernel has reached idle.

So this isn't just a normal `execute()` bug.

It is a **runtime-wide lifecycle problem**.

---

# 13. Another important finding: `stream_execute()` increments cells before success

It does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._cell_count += 1
```

</details>

immediately after sending the request. <sup>[source]</sup>

Whereas normal `execute()` increments only after collection and only for non-silent execution.

So:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
execute()
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
stream_execute()
```

</details>

have different cell-count semantics.

Example:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
stream request
   ↓
kernel dies
   ↓
cells_executed += 1
```

</details>

The metric means:

> execute requests issued

rather than:

> cells successfully executed.

The API should choose one definition and use it consistently.

---

# 14. Silent execution doesn't count toward `_cell_count`

Normal execution:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if not silent:
    self._cell_count += 1
```

</details>

<sup>[source]</sup>

This means:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
execute_silent()
```

</details>

doesn't increment the runtime's visible cell count.

That's probably intentional for infrastructure operations.

But `BudgetTracker` **does** count the execution, as we found earlier.

So there are now two different notions:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
KernelRuntime.cells_executed
    ≠
BudgetTracker.executions
```

</details>

This should be documented explicitly.

---

# 15. `memory_mb` is actually an execution

This is easy to overlook.

The property:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
memory_mb
```

</details>

calls:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
execute_silent(
    "import psutil, os; print(...)"
)
```

</details>

<sup>[source]</sup>

Therefore a memory inspection causes:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Python execution
+
wall time
+
stdout
```

</details>

and potentially consumes the agent's execution budget.

This is another example of infrastructure activity leaking into the execution quota.

---

# 16. `reset_namespace()` is also a budget-consuming execution

It calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self.execute("%reset -f", silent=True, timeout=10)
```

</details>

So resetting state consumes:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
BudgetTracker execution
BudgetTracker wall time
BudgetTracker output
```

</details>

even though the agent didn't ask to execute user code.

This strongly supports separating:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
user execution budget
```

</details>

from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
runtime maintenance budget
```

</details>

---

# 17. Kernel generation is an excellent design

The runtime has:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._generation = 1
```

</details>

and increments on restart. <sup>[source]</sup>

This is valuable because:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
kernel_id = "abc"
generation = 3
```

</details>

means something very different from:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
kernel_id = "abc"
generation = 1
```

</details>

A restarted kernel is logically a new execution environment.

This should be propagated into every `CellOutput` / execution record.

---

# 18. The tracer already records generation

The runtime sends:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
kernel.id
kernel.generation
cell.num
cell.code_preview
cell.silent
```

</details>

into telemetry. <sup>[source]</sup>

That's excellent observability.

But the returned `CellOutput` should carry the same identifiers.

Otherwise:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
telemetry
```

</details>

knows:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kernel.generation = 4
```

</details>

while:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
CellOutput
```

</details>

doesn't necessarily know it.

---

# 19. Security concern: telemetry includes code preview

The tracer receives:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
"cell.code_preview": code[:80]
```

</details>

<sup>[source]</sup>

This is useful for debugging, but it means source code is entering telemetry.

If users execute:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
token = "secret..."
```

</details>

the first 80 characters could potentially be logged.

Even a short preview can expose:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
API keys
tokens
passwords
PII
SQL
internal URLs
```

</details>

I'd make code-preview telemetry:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
disabled by default
```

</details>

or redact obvious secrets.

---

# 20. Error telemetry has the same concern

The runtime records:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
output.error.evalue[:200]
```

</details>

<sup>[source]</sup>

Exceptions can contain sensitive information:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
FileNotFoundError('/home/user/private/project/...')

requests.exceptions...
    Authorization: Bearer ...

DatabaseError(...)
```

</details>

So telemetry needs a privacy policy.

---

# 21. `cell.output_bytes` is incomplete

Runtime telemetry records:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
len(output.stdout)
```

</details>

not:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
stdout + stderr + result + displays + images
```

</details>

This duplicates the budget-layer limitation.

You effectively have:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Budget output bytes
        ↓
stdout only

Telemetry output bytes
        ↓
stdout only
```

</details>

That should become a common `OutputMetrics` calculation.

---

# 22. `execute()` doesn't validate the timeout

There is no obvious validation for:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
timeout < 0
timeout = NaN
timeout = infinity
```

</details>

`collect()` ultimately receives the value.

The runtime API should normalize:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
timeout > 0
```

</details>

or explicitly define:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
timeout=None → unlimited
```

</details>

rather than leaving behavior to downstream code.

---

# 23. The timeout escalation policy is currently only applied to `TimeoutError`

This condition:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
output.error.ename == "TimeoutError"
```

</details>

triggers escalation. <sup>[source]</sup>

But cancellation creates:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
KernelInterrupted
```

</details>

So cancellation does not automatically enter the escalation ladder.

That might be intentional:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
user cancellation → interrupt only
timeout → interrupt → kill if necessary
```

</details>

and I think that's a reasonable distinction.

But it should be explicit in the contract.

---

# 24. The strongest architecture would centralize "quiescence"

Introduce:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
_wait_until_idle(...)
```

</details>

with semantics:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
wait for kernel idle
    ↓
confirmed → READY
timeout → DEAD/RESTARTING
```

</details>

Then both:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
interrupt()
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
cancel()
```

</details>

can use it.

For example:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
execute
  ↓
timeout
  ↓
request interrupt
  ↓
wait_until_idle
  ├── idle → return TimeoutError
  └── no idle → kill/restart
```

</details>

This gives the runtime one authoritative lifecycle transition.

---

# 25. Proposed corrected execution lifecycle

I'd make it:

<details>
<summary><strong>💻 Code Block (text) — 35 lines</strong></summary>

```text
READY
  │
  ▼
execute request
  │
  ▼
BUSY
  │
  ├── normal completion ───────────► READY
  │
  ├── Python error ────────────────► READY
  │
  ├── cancellation
  │      ↓
  │   INTERRUPTING
  │      ↓
  │   WAIT_IDLE
  │      ├── idle ────────────────► READY
  │      └── timeout ─────────────► DEAD
  │
  └── timeout
         ↓
      INTERRUPTING
         ↓
      WAIT_IDLE
         ├── idle ────────────────► READY
         └── timeout
                ↓
              KILL
                ↓
            RESTARTING
                ↓
          wait_for_ready()
                ↓
              READY
```

</details>

That would make kernel reuse substantially safer.

---

# 26. Current audit status

After the runtime layer, I'd classify the findings like this:

| Area | Status |
|---|---|
| Kernel startup | 🟢 Good |
| Graceful shutdown | 🟢 Good |
| Restart/readiness | 🟢 Good |
| Generation tracking | 🟢 Excellent |
| Telemetry | 🟢 Good foundation |
| Timeout escalation | 🟢 Good concept |
| Sticky DEAD state | 🟢 Good |
| Interrupt lifecycle | 🔴 Needs correction |
| Cancellation lifecycle | 🔴 Needs correction |
| Kernel reuse after interruption | 🔴 Must harden |
| Stream execution lifecycle | 🟠 Needs same fix |
| Cell counting semantics | 🟠 Inconsistent |
| Infrastructure budget accounting | 🟠 Architectural issue |
| Telemetry secret exposure | 🟠 Needs policy |

---

# 27. The architectural conclusion so far

We now have three connected findings:

<details>
<summary><strong>💻 Code Block (text) — 15 lines</strong></summary>

```text
                 Kerno
                   │
       ┌───────────┴───────────┐
       │                       │
   Budget layer           Kernel layer
       │                       │
       ▼                       ▼
 BudgetExceeded          Timeout/Cancel
       │                       │
       └───────────┬───────────┘
                   ▼
              CellOutput
                   │
                   ▼
              Agent Loop
```

</details>

The **resource accounting** is mostly sound.

The **structured output** is mostly sound.

The **kernel lifecycle boundary** is the part that needs hardening.

Most importantly:

> **"process is alive" is not equivalent to "kernel is ready for another execution."**

That distinction should become a first-class invariant throughout Kerno.

---

## Next audit target: `kerno/kernel/pool.py`

The next layer is particularly important because `KernelPool` decides whether a kernel is:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
available
leased
released
reused
retired
restarted
```

</details>

That's where we can determine whether the runtime's premature `READY` state can actually cause **cross-agent/kernel contamination**, and whether dead or interrupted kernels are correctly removed rather than returned to the pool.

[Kerno `kernel/pool.py` on the requested branch](https://github.com/Abdus2023/Kerno/blob/arena/01a0064f-kerno/kerno/kernel/pool.py)

---

## [48] USER

Continue 

---

## [49] CHATGPT (gpt-5-6)

<details>
<summary><strong>🛠️ api_tool.list_resources</strong></summary>

**Input:**

```json
{"paths":["GitHub"],"query":"fetch_file"}
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

# Continue — `kerno/kernel/pool.py` audit

This confirms the previous runtime concern and adds **several pool-level correctness bugs**. The pool architecture is understandable, but the current implementation should **not yet be treated as a reliable isolation boundary**.

[Open `pool.py` on the Kerno branch](https://github.com/Abdus2023/Kerno/blob/arena/01a0064f-kerno/kerno/kernel/pool.py)

---

## 1. The intended pool model is good

The pool defines:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
KernelPool
├── WARMING
├── AVAILABLE
├── ACQUIRED
├── RESETTING
└── DEAD
```

</details>

and maintains:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
_available
_active
_all
```

</details>

<sup>[source]</sup>

Conceptually:

<details>
<summary><strong>💻 Code Block (text) — 19 lines</strong></summary>

```text
                    KernelPool
                        │
          ┌─────────────┴─────────────┐
          │                           │
      AVAILABLE                    ACQUIRED
          │                           │
       acquire                     task
          │                           │
          └───────────┬───────────────┘
                      ▼
                    release
                      │
              ┌───────┴───────┐
              ▼               ▼
          soft reset       hard reset
              │               │
              └───────┬───────┘
                      ▼
                  AVAILABLE
```

</details>

That's the right overall architecture.

---

# 2. 🔴 Major bug: release is asynchronous

This is probably the most important pool-level issue.

For a normal completion:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
threading.Thread(
    target=self._soft_reset,
    args=(pk,),
    daemon=True
).start()
```

</details>

For an error/timeout:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
threading.Thread(
    target=self._hard_reset,
    args=(pk,),
    daemon=True
).start()
```

</details>

<sup>[source]</sup>

So:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
task finishes
    ↓
release()
    ↓
remove from _active
    ↓
start reset thread
    ↓
release() RETURNS
```

</details>

The pool hasn't actually finished sanitizing the kernel.

That is acceptable **only because the kernel isn't immediately placed back into `_available`**.

So this part is not an immediate contamination bug.

But it creates another issue.

---

# 3. A released kernel is temporarily invisible

After:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
release(task)
```

</details>

and before:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_soft_reset()
```

</details>

the kernel is:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
state = RESETTING
```

</details>

but:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
not _active
not _available
```

</details>

Therefore pool statistics temporarily report:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
available = 0
active = 0
total = 1
```

</details>

even though one kernel exists.

That's not necessarily wrong, but it means:

> `total != active + available`

can occur legitimately.

Your stats API therefore needs to include:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
resetting
warming
dead
```

</details>

otherwise operators may think the pool has lost capacity.

---

# 4. 🔴 `acquire()` can create more than `max_overflow`

This line is dangerous:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if self.overflow and len(self._active) < self.max_overflow:
    pk = self._create_kernel()
```

</details>

<sup>[source]</sup>

It checks only:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
active < max_overflow
```

</details>

It does **not** account for:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
available
resetting
warming
newly-created overflow kernels
```

</details>

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
size = 3
max_overflow = 10
```

</details>

and all 3 warm kernels are unavailable.

Several concurrent `acquire()` calls can all observe:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
active < 10
```

</details>

and create additional kernels.

The actual total could therefore exceed the intended:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
size + max_overflow
```

</details>

because `max_overflow` is being treated as an active-task limit rather than a pool-capacity limit.

---

# 5. Even worse: overflow semantics are ambiguous

The constructor says:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
max_overflow = 10
```

</details>

which strongly suggests:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
base pool = 3
maximum extra kernels = 10
maximum total = 13
```

</details>

But the code implements approximately:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
maximum active tasks = 10
```

</details>

That is not the same thing.

If 3 base kernels are active:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
len(_active) = 3
```

</details>

then the pool can create another kernel.

But whether that is "overflow #1" isn't tracked.

There should be:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
base_capacity
overflow_capacity
total_capacity
```

</details>

explicitly.

---

# 6. 🔴 `_create_kernel()` doesn't reserve capacity atomically

The sequence is:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
check capacity
    ↓
create KernelRuntime
    ↓
append _all
```

</details>

Multiple threads can race.

For example:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Thread A: sees capacity
Thread B: sees capacity
Thread C: sees capacity
```

</details>

all create kernels.

The `_kernel_seq` increment itself is protected, but **capacity reservation isn't**.

The pool needs an atomic reservation mechanism around creation.

---

# 7. `start()` has a race with `_running`

`start()` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._running = True
```

</details>

then creates several threads.

There's no guard against:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
start()
start()
```

</details>

being called twice.

The second call can:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
spawn another N kernels
spawn another monitor
```

</details>

and duplicate the pool.

The lifecycle should be:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
STOPPED → STARTING → RUNNING → STOPPING → STOPPED
```

</details>

with `start()` idempotence or an explicit error.

---

# 8. `shutdown()` doesn't join the monitor

It does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._running = False
```

</details>

but does not:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
join(_monitor)
```

</details>

<sup>[source]</sup>

The monitor may still be inside:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
time.sleep(30)
```

</details>

for up to 30 seconds.

That's usually okay for a daemon thread, but it means shutdown is not a clean lifecycle barrier.

---

# 9. 🔴 Shutdown races with reset threads

This is more important.

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
task finishes
   ↓
release()
   ↓
_soft_reset thread starts
   ↓
pool.shutdown()
```

</details>

Shutdown does:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
runtime.shutdown()
```

</details>

while the reset thread may simultaneously do:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
runtime.reset_namespace()
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
runtime.restart()
```

</details>

Now two lifecycle operations can race on the same kernel.

That is a genuine concurrency bug.

---

# 10. The pool has no per-kernel lifecycle lock

This is the missing primitive.

Every `PooledKernel` should probably have:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
lifecycle_lock: threading.RLock
```

</details>

so operations become serialized:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
acquire
release
reset
restart
interrupt
retire
shutdown
```

</details>

for a particular kernel.

Currently the pool has:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._lock
```

</details>

but that protects pool dictionaries/lists, not the lifecycle of the underlying kernel.

---

# 11. 🔴 `interrupt()` + `release()` can race

Consider:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Task A
  ↓
pool.interrupt("A")
  ↓
runtime.interrupt()
```

</details>

At nearly the same time:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Task A completes
  ↓
pool.release("A")
  ↓
hard reset thread
```

</details>

You can get:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
runtime.interrupt()
+
runtime.restart()
```

</details>

concurrently.

That is unsafe.

A per-kernel lifecycle lock would solve this.

---

# 12. `restart(task_id)` has the same problem

It retrieves the kernel under the pool lock:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk = self._active.get(task_id)
```

</details>

then releases the pool lock and does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk.runtime.restart()
```

</details>

<sup>[source]</sup>

So another thread can simultaneously:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
release(task_id)
```

</details>

and start:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_hard_reset(pk)
```

</details>

while `restart()` is already running.

Again:

> pool-level locking ≠ kernel lifecycle locking.

---

# 13. 🔴 The pool can hand out a runtime whose state isn't actually READY

`acquire()` gets:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk = self._available.get(...)
```

</details>

Then checks:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
if not pk.is_healthy:
```

</details>

where:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
is_healthy =
    runtime.is_alive
    AND not expired
```

</details>

<sup>[source]</sup>

But it does **not** verify:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
runtime.state == READY
```

</details>

This directly connects to our previous runtime finding.

A process can be alive while:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
runtime.state = BUSY
INTERRUPTING
RESETTING
```

</details>

So:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
alive != ready
```

</details>

must be reflected in `is_healthy`.

---

# 14. `is_healthy` should be stricter

Currently:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
return self.runtime.is_alive and not self.is_expired
```

</details>

It should conceptually be:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
runtime.is_alive
AND runtime.state == READY
AND pool state == AVAILABLE
AND not expired
AND not retired
```

</details>

Otherwise the pool's health model is weaker than its acquisition contract.

---

# 15. 🔴 Soft reset itself consumes execution budget

This is especially important now that we've seen all three layers.

`_soft_reset()` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk.runtime.reset_namespace()
```

</details>

and `_bootstrap()` can execute Python.

So:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
task
 ↓
release
 ↓
soft reset
 ↓
reset_namespace()
 ↓
BudgetTracker
```

</details>

if the runtime is wrapped by a budgeted executor.

The pool is therefore performing infrastructure executions after the task has technically ended.

This reinforces the earlier need for separate budgets.

---

# 16. Soft reset may not be sufficient for isolation

The comment says:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Soft reset: clear namespace, reload skills
```

</details>

But `%reset -f` only clears Python namespace state.

It doesn't necessarily eliminate:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
background threads
subprocesses
open sockets
file handles
native library state
global C state
environment mutations
cwd changes
signal handlers
atexit handlers
installed monkey patches
```

</details>

So a "clean namespace" isn't necessarily:

> clean kernel.

For untrusted or adversarial workloads, only process replacement gives a strong isolation boundary.

---

# 17. This is crucial for Kerno's threat model

There are really three isolation levels:

### Level 1 — namespace reset

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
same process
new Python namespace
```

</details>

Fast, weak.

### Level 2 — kernel restart

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
new Jupyter kernel process
```

</details>

Much stronger.

### Level 3 — OS/container isolation

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
new process/container
resource limits
filesystem/network policy
```

</details>

Strongest.

Kerno's pool currently operates primarily at levels 1 and 2.

That's fine for cooperative notebook workloads.

It should **not** be described as a security sandbox unless additional OS-level isolation exists.

---

# 18. 🔴 `_retire()` has a race with `_all`

It does:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if pk in self._all:
    self._all.remove(pk)
```

</details>

under the lock.

Good.

But it shuts down the runtime **before** acquiring the lock:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
shutdown
↓
lock
↓
remove
```

</details>

Another thread could inspect the pool between those events and see:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
pk still in _all
state maybe AVAILABLE
runtime already shutting down
```

</details>

The state should transition to `DEAD`/`RETIRING` before the shutdown begins.

---

# 19. Retiring an available kernel leaves a stale queue entry

This is an important bug.

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_available contains pk
```

</details>

Monitor sees:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
pk.is_expired
```

</details>

and calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
_retire(pk)
```

</details>

The kernel is removed from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_all
```

</details>

but the code does not remove `pk` from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_available
```

</details>

because Python's `Queue` doesn't support convenient arbitrary removal.

So the queue can still contain:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
dead pk
```

</details>

Later:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
acquire()
 ↓
_available.get()
 ↓
dead pk
```

</details>

The health check catches it and replaces it.

So this may self-heal, but the queue contains stale entries and pool capacity accounting becomes inaccurate.

---

# 20. This can cause an availability illusion

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
_all = []
_available queue = [dead kernel]
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
stats()
```

</details>

can report:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
available = 1
total = 0
```

</details>

That is clearly inconsistent.

A robust pool should use one source of truth for membership and derive availability from it.

---

# 21. 🔴 `acquire()` can accidentally create an extra replacement

If a stale/dead kernel is pulled:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
if not pk.is_healthy:
    pk.runtime.shutdown(now=True)
    pk.state = DEAD
    pk = self._create_kernel()
```

</details>

<sup>[source]</sup>

But the stale kernel remains in:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_all
```

</details>

unless `_create_kernel()` or something else removes it.

So:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
dead kernel
+
new kernel
```

</details>

can coexist in `_all`.

The pool's `total` count therefore becomes wrong.

---

# 22. `is_expired` has an expensive side effect

The property:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
memory = self._safe_memory()
```

</details>

calls:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
runtime.memory_mb
```

</details>

which, as we saw, executes Python inside the kernel.

So merely asking:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk.is_expired
```

</details>

can itself execute code in the kernel.

This happens in:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
acquire()
release()
monitor
health checks
```

</details>

That's a major architectural smell.

A health check should not itself mutate or consume the workload.

---

# 23. This creates a recursive resource-accounting problem

We now have:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
check pool health
      ↓
is_expired
      ↓
memory_mb
      ↓
execute_silent()
      ↓
budget consumption
```

</details>

Therefore:

> checking whether the kernel is healthy can consume the very budget you're trying to measure.

That's a serious design flaw.

Memory should be measured externally where possible:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Kernel process PID
      ↓
psutil.Process(pid).memory_info()
```

</details>

rather than executing Python inside the kernel.

---

# 24. Memory measurement also fails open

`_safe_memory()`:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
try:
    return self.runtime.memory_mb
except Exception:
    return 0.0
```

</details>

<sup>[source]</sup>

If memory measurement fails, Kerno assumes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
memory = 0 MB
```

</details>

That's dangerous.

If the kernel is actually consuming:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
8192 MB
```

</details>

but the measurement failed, the pool treats it as healthy.

Better:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
measurement failure
    ↓
unknown
    ↓
do not declare healthy
```

</details>

or at least:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
health = DEGRADED
```

</details>

---

# 25. Memory limit is not an enforcement mechanism

Even when:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
memory > 4096 MB
```

</details>

the pool only marks the kernel:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
expired
```

</details>

and eventually retires it.

That's **post-hoc detection**, not memory enforcement.

The process can exceed the limit before the monitor notices it.

Because the monitor runs every:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
30 seconds
```

</details>

the kernel may remain above the limit for a substantial period.

For real memory enforcement, OS-level resource limits are needed.

---

# 26. `MAX_LIFETIME` is measured from kernel creation, not restart

This is subtle.

`created_at` is set when:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
PooledKernel(...)
```

</details>

is created.

When:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
runtime.restart()
```

</details>

occurs:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
created_at
```

</details>

does not reset.

That's actually a reasonable choice if:

> lifetime means pool object lifetime.

But if the intention is:

> maximum age of current kernel process,

then restart should update the generation timestamp.

I'd rename it:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
MAX_POOL_LIFETIME
```

</details>

or introduce:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
process_started_at
generation_started_at
```

</details>

---

# 27. `tasks_served` survives kernel restart

That is probably correct.

It measures:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
number of tasks served by this pooled object
```

</details>

rather than:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
number served by this kernel generation
```

</details>

Again, generation-specific metrics would help:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
tasks_served_total
tasks_served_generation
```

</details>

---

# 28. The monitor detects runaway tasks but doesn't act

This code:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if ... > 3600:
    warnings.warn(...)
```

</details>

only warns.

So:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
task stuck for > 1 hour
```

</details>

does not automatically trigger:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
interrupt
timeout
retirement
```

</details>

That's fine if intentionally advisory.

But the pool constructor doesn't expose a `max_task_duration`, so the `MAX_LIFETIME` concept can be misleading.

Kernel lifetime and task duration are separate concepts.

---

# 29. `release()` silently ignores unknown task IDs

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
pk = self._active.pop(task_id, None)

if pk is None:
    return
```

</details>

<sup>[source]</sup>

This is convenient, but dangerous for debugging.

Suppose a caller accidentally does:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
release("wrong-task")
```

</details>

Nothing happens.

The real kernel remains acquired forever.

I'd prefer:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
release unknown task
    ↓
KeyError / PoolOwnershipError
```

</details>

or an explicit:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
strict=False
```

</details>

mode.

---

# 30. Task ownership is otherwise a good idea

The pool maps:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
task_id → PooledKernel
```

</details>

This is strong.

It enables:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
interrupt(task_id)
restart(task_id)
release(task_id)
```

</details>

without exposing pool internals.

The missing piece is stronger ownership enforcement.

A task should ideally receive:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
KernelLease
```

</details>

instead of a raw `KernelRuntime`.

---

# 31. Why a `KernelLease` is better

Currently:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
runtime = pool.acquire("task-123")
```

</details>

returns a raw runtime.

The caller can retain it indefinitely:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
pool.release("task-123")
↓
runtime reference still exists
```

</details>

The pool then assumes ownership has ended.

A lease object could enforce:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
KernelLease
├── task_id
├── runtime
├── generation
├── released
└── context-manager lifecycle
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
with pool.acquire("task-123") as kernel:
    ...
```

</details>

would naturally enforce ownership.

---

# 32. Generation fencing should be added to leases

This is especially useful after restart.

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
task gets kernel generation 4
```

</details>

then kernel restarts:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
generation 5
```

</details>

The old lease should know:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
my generation = 4
current generation = 5
```

</details>

and reject stale assumptions.

This prevents an old task/result from accidentally being associated with the new kernel state.

---

# 33. Recommended pool state machine

I'd formalize each pooled kernel as:

<details>
<summary><strong>💻 Code Block (text) — 21 lines</strong></summary>

```text
WARMING
   ↓
AVAILABLE
   ↓
ACQUIRED
   │
   ├── complete → RESETTING
   │                ↓
   │             AVAILABLE
   │
   ├── error → RESETTING
   │             ↓
   │          AVAILABLE
   │
   ├── timeout → INTERRUPTING
   │                ↓
   │             IDLE?
   │             ├── yes → RESETTING
   │             └── no → DEAD
   │
   └── OOM → DEAD
```

</details>

Current implementation compresses too many transitions into asynchronous helper threads.

---

# 34. The biggest pool-level invariant

The pool needs to guarantee:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

```text
∀ kernel:
    kernel ∈ AVAILABLE
    ⇒
        runtime.is_alive
        AND runtime.state == READY
        AND kernel.state == AVAILABLE
        AND kernel has no active task
        AND kernel is not resetting
```

</details>

And:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
kernel ∈ ACQUIRED
    ⇒
        exactly one task owns it
```

</details>

And:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
kernel ∈ RESETTING
    ⇒
        it cannot be acquired
```

</details>

And:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
kernel ∈ DEAD
    ⇒
        it cannot be acquired
```

</details>

These should be tested directly.

---

# 35. Priority findings from this file

| Finding | Priority |
|---|---:|
| Reset/shutdown/restart race | 🔴 P0 |
| Runtime READY doesn't guarantee idle | 🔴 P0 |
| Stale kernels can remain in `_available` | 🔴 P1 |
| Dead kernels can remain in `_all` | 🔴 P1 |
| Overflow capacity is incorrectly defined | 🔴 P1 |
| No per-kernel lifecycle lock | 🔴 P1 |
| Health check executes code in kernel | 🔴 P1 |
| Memory measurement fails open | 🟠 P1 |
| Soft reset isn't strong isolation | 🟠 P1 |
| Raw runtime returned instead of lease | 🟠 P2 |
| Stats omit resetting/warming/dead | 🟡 P2 |
| Unknown release silently ignored | 🟡 P2 |
| `start()` not idempotent | 🟡 P2 |
| Monitor shutdown not joined | 🟡 P2 |
| Telemetry/resource semantics | 🟡 P2 |

---

# 36. Overall Kerno execution architecture — current verdict

After auditing:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
budget.py
output.py
types.py
runtime.py
pool.py
```

</details>

the architecture looks like:

<details>
<summary><strong>💻 Code Block (text) — 15 lines</strong></summary>

```text
                     KERNO
                       │
             ┌─────────┴─────────┐
             │                   │
         Agent Layer         Kernel Pool
                                 │
                         ┌───────┴───────┐
                         │               │
                     Runtime          Lifecycle
                         │               │
                    IOPub/Comm       Reset/Restart
                         │
                    CellOutput
                         │
                    Budgeting
```

</details>

### The good news

The project has **real architectural structure**, not just a collection of notebook helpers.

It has:

- lifecycle states,
- kernel pooling,
- generation tracking,
- structured outputs,
- timeout escalation,
- resource budgets,
- reset strategies,
- tracing,
- task ownership,
- overflow handling.

### The problem

Several components currently assume:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
alive == ready
interrupt == stopped
reset == isolated
health check == observation
budget allocation == consumption
```

</details>

Those equivalences are **not generally true**.

That's where the next engineering work should concentrate.

---

# 37. Recommended correction order

I would **not** start by adding more features.

I'd harden the existing substrate in this order:

### P0 — Kernel lifecycle correctness

Implement one authoritative:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
wait_until_idle()
```

</details>

and prohibit:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
READY
```

</details>

until it succeeds.

### P0 — Per-kernel synchronization

Add:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
PooledKernel.lifecycle_lock
```

</details>

and serialize:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
execute
interrupt
restart
reset
retire
shutdown
```

</details>

### P1 — Queue membership correctness

Replace stale `Queue` entries with a design where:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
AVAILABLE
```

</details>

is authoritative.

### P1 — Health without kernel execution

Measure kernel RSS externally.

Do **not** use:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
memory_mb → execute_silent()
```

</details>

for pool health.

### P1 — Explicit execution status

Introduce:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
SUCCESS
PYTHON_ERROR
TIMEOUT
CANCELLED
BUDGET_EXCEEDED
KERNEL_DIED
```

</details>

### P1 — Hierarchical budget accounting

Separate:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
allocated
consumed
remaining
```

</details>

and connect child consumption to the parent.

### P2 — Kernel leases

Return:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
KernelLease
```

</details>

instead of a bare runtime.

---

## Next layer: agent orchestration

The next audit should move **above the kernel infrastructure** into the actual Kerno agent/session orchestration:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

```text
Agent
 ↓
Plan
 ↓
Action
 ↓
Executor
 ↓
Recovery
 ↓
Budget
 ↓
SessionResult
```

</details>

That is where we can determine whether the low-level problems above actually propagate into **agent behavior**—especially whether `TimeoutError`, `BudgetExceeded`, kernel death, retries, and recovery can produce loops, incorrect success states, or accidental execution after a terminal condition.

[Kerno repository — branch `arena/01a0064f-kerno`](https://github.com/Abdus2023/Kerno/tree/arena/01a0064f-kerno)

---

---
[← Previous section](./08-kernel-output-and-execution-design.md) | [Back to index](./README.md) | [Next section →](./10-prompt-error-persistence.md)

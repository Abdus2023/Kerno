# 09 — Agent Loop And Orchestration

## next audit layer: `MultiAgentLoop`

We should now move from **kernel/resource correctness** into **agent execution semantics**.

One correction first: I don't currently have the contents of `kerno/agent/loop.py` in the visible tool results, so I won't invent findings about that file. The previous audit established the exact contract that this layer must satisfy.

### The contract going upward

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

The critical question is:

> **Does one agent turn correspond to one well-defined transaction whose success/failure/cancellation is reflected consistently in agent state, budgets, and kernel state?**

---

## 1. What we need to verify

A correct loop should behave approximately like:

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

The dangerous implementation is:

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

because then the agent's logical state can diverge from the actual execution state.

---

## 2. Cancellation must be checked at multiple boundaries

From the lower layers we already know that kernel cancellation can propagate into an actual Jupyter interrupt.

The agent loop should therefore have at least three cancellation checkpoints:

```text
before turn
    ↓
before tool/kernel call
    ↓
after execution / before committing state
```

Why the third one matters:

```text
kernel finishes
      ↓
cancel arrives
      ↓
agent commits observation
```

Without a post-execution cancellation check, a cancelled turn may still mutate the agent's durable state.

---

## 3. Budget enforcement must be transactional

Suppose the loop has:

```text
max_turns = 10
```

and is currently at:

```text
turn = 10
```

The loop must not do:

```text
turn 10
   ↓
start execution
   ↓
discover budget exhausted
```

Instead:

```text
budget check
    ↓
allowed?
 ┌──┴──┐
NO    YES
│      │
stop   execute
```

The same applies to:

- token budget,
- wall-clock budget,
- tool-call budget,
- kernel execution budget.

A budget should be treated as a **precondition**, not merely a counter reported after the fact.

---

## 4. Turn accounting needs a precise definition

The runtime already has a subtle distinction between:

```text
submitted
completed
failed
silent
```

The agent loop should similarly distinguish:

```text
turn_started
turn_completed
turn_failed
turn_cancelled
turn_timed_out
```

Otherwise a metric like:

```text
turn_count = 5
```

is ambiguous.

For agent orchestration, I'd strongly prefer:

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

---

## 5. Kernel failure must not automatically mean agent failure

There are at least four distinct situations:

```text
Kernel execution failed
Kernel timed out
Kernel was interrupted
Kernel died
```

These should not necessarily produce the same agent-level result.

For example:

```text
Python exception
    ↓
recoverable tool failure
    ↓
agent can reason about error
```

whereas:

```text
kernel process died
    ↓
resource failure
    ↓
pool restart
    ↓
agent may retry
```

and:

```text
budget exceeded
    ↓
agent must stop
```

These are semantically different.

---

## 6. The pool/runtime architecture already supports recovery

This is important.

We have:

```text
KernelPool
    │
    ├── restart(task)
    ├── interrupt(task)
    ├── release(task)
    └── health_check()
```

and:

```text
KernelRuntime
    │
    ├── execute()
    ├── interrupt()
    ├── restart()
    └── timeout escalation
```

So the agent loop shouldn't implement its own kernel recovery logic.

It should delegate:

```text
AgentLoop
    ↓
KernelPool
    ↓
KernelRuntime
```

Otherwise we'd get duplicated recovery policies.

---

## 7. Resource ownership should surround the entire tool execution

The ideal pattern is:

```text
acquire(task)
    │
    ├── execute
    ├── collect
    ├── process output
    └── release(task)
```

with release guaranteed even when:

```text
execute → exception
execute → timeout
execute → cancellation
agent → exception
```

Conceptually:

```python
kernel = pool.acquire(task_id)
try:
    ...
finally:
    pool.release(task_id, reason=...)
```

The `finally` equivalent is essential.

Without it:

```text
exception
   ↓
release skipped
   ↓
kernel remains ACQUIRED
   ↓
pool capacity leaks
```

---

## 8. This connects directly to the P0 pool finding

We identified:

```text
release(reason="unknown")
```

can orphan a kernel.

Therefore the agent loop must **never manufacture arbitrary release reasons**.

The contract should use an enum:

```text
COMPLETE
ERROR
TIMEOUT
CANCELLED
OOM
KERNEL_DEAD
```

rather than free-form strings.

That lets the type system enforce the lifecycle.

---

## 9. Agent state should only commit after successful observation

Consider:

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

The state transition should be:

```text
PLANNED
   ↓
EXECUTING
   ↓
OBSERVED
   ↓
STATE_COMMITTED
```

not:

```text
PLANNED
   ↓
STATE_COMMITTED
   ↓
execute
```

This gives you a clean transactional boundary.

---

## 10. Failed observations should be represented, not erased

A robust agent state model should retain:

```text
observation:
    status = error
    error_type = ...
    message = ...
```

rather than simply returning:

```text
None
```

Otherwise the next agent turn cannot distinguish:

```text
no observation
```

from:

```text
execution failed
```

That's particularly important for autonomous retry behavior.

---

## 11. Retry policy belongs above the kernel

The kernel runtime can say:

```text
TIMEOUT
```

The pool can say:

```text
kernel restarted
```

But the agent loop should decide:

```text
retry?
```

For example:

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

This separation keeps infrastructure deterministic.

---

## 12. The agent loop should have an explicit terminal state

A clean state machine is:

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

With budget exhaustion:

```text
RUNNING
   ↓
BUDGET_EXCEEDED
   ↓
TERMINATED
```

This is better than relying on:

```text
for turn in range(...)
```

alone.

---

## 13. Why this matters for Kerno specifically

Kerno is not just a notebook executor.

The architecture we've seen is aiming toward:

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

Therefore correctness isn't merely:

> "Did Python execute?"

It's:

> **"Did the agent's causal state advance exactly once in response to the correct execution result?"**

That is a much stronger requirement.

---

## 14. The ideal causal chain

I'd make this invariant explicit:

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

Never:

```text
Decision #N
   ├── Execution A
   ├── Execution B
   └── State transition
```

unless parallel execution is explicitly part of the agent model.

---

## 15. The next thing to inspect in the repository

The most useful files now are:

```text
kerno/agent/loop.py
kerno/agent/agent.py
kerno/agent/state.py
kerno/agent/budget.py
```

and whichever module defines the tool/execution interface.

The purpose isn't just to read them individually.

We need to construct one **end-to-end causal trace**:

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

Then test the four exceptional paths:

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

That will give us the first genuinely **end-to-end correctness audit** of this Kerno branch rather than another isolated file review.

---

## deep audit of `kerno/loop/multi_agent.py`

We now have the actual implementation, and this changes the assessment substantially. The loop contains several thoughtful security/isolation features, but there are also **real lifecycle bugs** at the agent-loop boundary.

The file is `kerno/loop/multi_agent.py` on the requested `arena/01a0064f-kerno` branch. <sup>[source]</sup>

---

## 1. Architecture: genuinely interesting

Kerno supports two fundamentally different execution models:

```text
SHARED
──────
Agent A ──┐
          ├── same KernelRuntime
Agent B ──┤
Agent C ──┘
```

and:

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

The isolated model is particularly interesting because it explicitly rejects implicit mutable kernel sharing.

The code documents the intended invariant:

> only explicitly shared state crosses an agent boundary. <sup>[source]</sup>

That is a strong design decision.

---

## 2. Agent identity is treated as a security principal

This is one of the best aspects.

`AgentRole` contains:

```python
name
llm
system
max_cells
reads
writes
```

and the kernel factory can receive:

```python
kernel_factory(agent)
```

rather than merely:

```python
kernel_factory()
```

<sup>[source]</sup>

That means the architecture can eventually implement:

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

This is much more powerful than merely having different prompts.

---

## 3. `NamespacePartition` reinforces that model

The isolation layer registers:

```text
analyst → results_, model_, df_, analysis_
critic  → critique_
narrator → narrative_, key_findings
```

<sup>[source]</sup>

Then the namespace is checked after a turn.

The underlying implementation explicitly treats undeclared keys as violations unless they were intentionally shared. <sup>[source]</sup>

That's a good security boundary.

---

## 4. But there is an important conceptual limitation

The namespace partition is **detective**, not preventive.

The sequence is:

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

So:

> An isolated agent can still mutate its own temporary kernel arbitrarily during execution.

The system only prevents that state from crossing the boundary.

That's actually a reasonable design.

But the documentation should say:

**"write isolation across turns"**

rather than implying:

**"agents cannot write undeclared variables."**

---

## 5. Shared memory implementation is clean

`SharedValue` contains:

```text
key
value
producer
timestamp
```

<sup>[source]</sup>

This is exactly the metadata we want for cross-agent state:

```text
results_summary
    producer = analyst
    timestamp = ...
```

rather than an anonymous dictionary.

That gives us provenance.

---

## 6. But `SharedMemory` isn't actually immutable

The docstring says shared values are:

> immutable JSON copies. <sup>[source]</sup>

The **cross-boundary copy** is immutable from the originating kernel's perspective, which is good.

But on the host side:

```python
self._values[key] = sv
```

allows the whole `SharedMemory` object to be overwritten.

And `SharedValue.value` is typed as:

```python
Any
```

so nested Python structures aren't deeply immutable.

For correctness, I'd treat the host store as:

```text
append-only versioned values
```

or use deep-copy/frozen structures.

---

## 7. A more serious issue: shared values can be overwritten silently

This:

```python
self._values[key] = sv
```

means:

```text
analyst:
results_summary = A

later:

critic:
results_summary = B
```

simply replaces A.

The original producer disappears from the current mapping.

The `timestamp` and producer tell you who produced the **current** value, but not the history.

For multi-agent reasoning, versioning would be much stronger:

```text
results_summary@1 → analyst
results_summary@2 → critic
```

or:

```text
SharedValue
├── version
├── producer
├── previous_version
└── timestamp
```

---

## 8. Major bug: `finally` can mask the actual exception

This is the first concrete P0/P1 issue in `run()`.

The code does:

```python
try:
    ...
    turn = self._run_turn(...)
finally:
    if self.isolation == "isolated":
        self._export_turn(role, turn_kernel, next_agent)
        self._shutdown_turn_kernel(turn_kernel)
```

<sup>[source]</sup>

If `_run_turn()` raises before assigning:

```python
turn = ...
```

then the `finally` block runs, which is fine.

But afterward Python re-raises the original exception.

However, `_export_turn()` itself can execute another kernel operation during failure handling.

That creates a dangerous sequence:

```text
LLM/kernel execution fails
       ↓
finally
       ↓
execute export code
       ↓
export also fails
```

Although `_export_turn()` catches its own exception, it can still perform additional kernel execution after a failed turn.

That is questionable transactional semantics.

---

## 9. Worse: cancellation triggers export

This is more important.

Suppose:

```text
cancel_token.set()
```

during an isolated agent execution.

`kernel.execute()` can react to the cancellation.

Then:

```text
_run_turn()
    ↓
exception / termination
    ↓
finally
    ↓
_export_turn()
```

So a cancelled agent can still execute:

```text
export_code(...)
```

after cancellation.

That violates a strong cancellation invariant:

> After cancellation, no new agent work should begin.

The export is not merely bookkeeping—it executes Python inside the kernel.

I would change the logic to:

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

---

## 10. The isolated kernel is shut down correctly in principle

The finalizer calls:

```text
raw_kernel.shutdown()
```

or:

```text
kernel.shutdown()
```

<sup>[source]</sup>

That is good.

The lifecycle is therefore:

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

This strongly enforces isolation.

---

## 11. But isolated kernel creation has no startup cleanup guarantee

If:

```python
kernel = self.kernel_factory(agent)
```

succeeds partially and then:

```python
shared.seed_code()
```

fails,

the `finally` block still attempts shutdown.

Good.

But if `kernel_factory()` itself starts a kernel and throws after partial creation, Kerno has no object to put into the `finally`.

That resource leak is owned by the factory contract.

I'd document:

> `kernel_factory` must be transactional: either return a fully initialized executor or clean up all resources before raising.

---

## 12. `TypeError` fallback is dangerous

This is subtle:

```python
try:
    kernel = self.kernel_factory(agent)
except TypeError:
    kernel = self.kernel_factory()
```

<sup>[source]</sup>

Suppose the factory correctly accepts `agent`, but its internal implementation contains:

```python
def factory(agent):
    something_that_raises_TypeError()
```

Kerno interprets that as:

> factory doesn't accept an argument.

Then it calls:

```python
factory()
```

and produces a second, misleading error.

This is a classic exception-swallowing problem.

Better inspect the callable signature once, or require one canonical interface:

```python
Callable[[str], KernelRuntime]
```

---

## 13. Turn ordering is deterministic, which is good

The loop uses:

```python
self.turn_order[turn_idx % len(self.turn_order)]
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

This is deterministic.

That's good for reproducibility.

But it isn't really "multi-agent planning."

It's a **round-robin coordinator** with optional handoff signals.

That's an important architectural distinction.

---

## 14. `next_agent` is calculated but not actually used for scheduling

The code computes:

```python
next_agent = ...
```

and passes it to:

```python
_export_turn(...)
```

which uses it for message routing. <sup>[source]</sup>

But it does not change the next scheduled role.

So if analyst sends:

```text
HANDOFF: narrator
```

the loop doesn't actually route execution to narrator.

It still uses:

```text
turn_order[(turn_idx + 1) % len(turn_order)]
```

This means **handoff is communication metadata, not control flow**.

If the design intends actual dynamic delegation, this is incomplete.

---

## 15. `HANDOFF_SIGNAL` is therefore currently advisory

The code extracts:

```text
## HANDOFF:
```

into:

```python
turn.handoff_context
```

but nothing in the visible scheduling logic consumes that context to choose the next agent.

So:

```text
Agent A:
    # HANDOFF: critic
```

doesn't mean:

```text
next = critic
```

unless critic was already next in `turn_order`.

That's a functional limitation worth documenting.

---

## 16. The biggest semantic weakness: LLM output becomes executable code directly

This line is the heart of the loop:

```python
code = role.llm(messages)
```

followed by:

```python
output = kernel.execute(code, ...)
```

<sup>[source]</sup>

There is no visible intermediate:

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

The architecture assumes:

> the LLM callable returns valid executable Python.

That's simple, but fragile.

A malformed response:

```text
Here is what I would do:
1. load pandas
2. inspect data
```

becomes a Python execution attempt.

---

## 17. A structured agent action protocol would be much stronger

Instead of:

```python
code = role.llm(messages)
```

I'd eventually want:

```text
AgentAction
├── kind = EXECUTE
├── code
├── reasoning_summary
├── requested_outputs
└── handoff
```

or:

```json
{
  "action": "execute",
  "code": "df = ...",
  "handoff": "critic"
}
```

Then the runtime can validate the action before execution.

---

## 18. Error recovery is good but potentially creates loops

The current behavior is:

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

<sup>[source]</sup>

This is a good agentic pattern.

But there is no explicit retry counter separate from:

```text
role.max_cells
```

Therefore:

```text
bad code
bad code
bad code
bad code
...
```

can consume the entire cell budget.

That's not necessarily bad, but telemetry should distinguish:

```text
productive cells
recovery retries
```

---

## 19. A recovery loop can accidentally hide persistent failures

Imagine:

```text
1. NameError
2. NameError
3. NameError
4. NameError
...
```

The agent continues until `max_cells`.

Then:

```text
turn.summary = ...
```

and the session may simply continue to the next agent.

So a systemic failure doesn't necessarily terminate or mark the session as failed.

This is a major semantic question.

---

## 20. `SessionStatus.MAX_CELLS` is overloaded

At the beginning:

```python
status = SessionStatus.MAX_CELLS
```

<sup>[source]</sup>

Then that value remains unless:

```text
COMPLETE
```

or:

```text
INTERRUPTED
```

occurs.

Therefore `MAX_CELLS` effectively means:

```text
"did not complete and did not get interrupted"
```

It doesn't necessarily mean the cell limit was reached.

It could mean:

```text
LLM exception
kernel error
role failure
invalid role
zero turns
```

This is too broad.

---

## 21. There is no explicit `ERROR` session status path visible here

The loop should have something like:

```text
COMPLETE
MAX_TURNS
MAX_CELLS
CANCELLED
TIMEOUT
ERROR
KERNEL_FAILURE
```

Instead, exceptions from the LLM or infrastructure can escape `run()` altogether.

That means callers may receive:

```text
exception
```

rather than:

```text
SessionResult(status=ERROR)
```

The API is therefore inconsistent:

```text
expected failure → SessionResult
unexpected failure → exception
```

That's not inherently wrong, but it should be deliberate.

---

## 22. Cancellation is only checked between cells

The loop checks:

```python
cancel_token.is_set()
```

before starting another cell. <sup>[source]</sup>

However, during:

```python
code = role.llm(messages)
```

there is no cancellation mechanism visible.

So if the LLM call takes:

```text
5 minutes
```

and cancellation occurs after 1 second:

```text
cancel
 ↓
LLM continues
 ↓
returns after 5 min
 ↓
kernel execution begins
```

The cancellation token doesn't automatically interrupt the LLM call.

This is a real end-to-end cancellation gap.

---

## 23. The kernel cancellation path is better

Once code reaches:

```python
kernel.execute(
    code,
    timeout=self.cell_timeout,
    cancel_event=self.cancel_token
)
```

the lower runtime can propagate cancellation into the Jupyter kernel.

That's good.

So cancellation currently looks like:

```text
LLM generation       ❌ not interruptible here
       ↓
Python execution     ✅ interruptible
       ↓
next cell            ✅ checked
       ↓
next turn             ✅ checked
```

The missing part is LLM generation cancellation.

---

## 24. Budgeting is conceptually good

The loop creates:

```python
BudgetTracker(self.budget)
```

per agent:

```text
analyst → tracker A
critic  → tracker B
narrator → tracker C
```

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

## 25. Another subtle issue: budget wrapper + export

In isolated mode:

```text
kernel
 ↓
BudgetedExecutor
 ↓
execute turn
```

Then `_export_turn()` calls:

```python
kernel.execute_silent(...)
```

through the same wrapper.

Therefore the export operation consumes the agent's budget too.

Likewise:

```text
seed code
```

also executes through the budget wrapper.

So an agent's declared budget may actually be consumed by:

```text
seed + agent cells + export
```

rather than just agent work.

That may be correct, but it should be explicit.

---

## 26. Namespace prompt leakage

`_build_system()` embeds:

```python
namespace = kernel.namespace
```

directly into the system prompt. <sup>[source]</sup>

That means potentially enormous data can enter the LLM context.

If the namespace contains:

```text
df = 1,000,000 rows
model = huge object
results = large JSON
```

the namespace representation could:

- explode prompt size,
- consume tokens,
- leak sensitive data,
- slow every turn.

This is a major scalability issue.

The agent should receive a **bounded namespace summary**, not the entire namespace.

---

## 27. Better:

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

rather than serializing arbitrary object contents.

That would be dramatically more efficient.

---

## 28. The current `reads` field isn't enforced

`AgentRole` has:

```python
reads: list[str]
```

but the visible loop does not use it to restrict namespace access.

The role declares:

```text
reads = [...]
```

yet `_build_system()` gives the agent:

```text
kernel.namespace
```

which potentially exposes everything.

So:

```text
writes = enforced
reads = apparently advisory
```

This is a major asymmetry.

If `reads` is intended as a capability boundary, it is not currently enforced here.

---

## 29. This is particularly important for isolated mode

In isolated mode, the agent receives:

```text
shared.seed_code()
```

which materializes all shared values.

Then the agent can inspect every seeded value, regardless of:

```text
role.reads
```

So the actual access policy is:

```text
all shared values are readable
```

not:

```text
role.reads
```

This is fine if intentional.

But then `reads` should either be removed or implemented.

---

## 30. Shared mode is explicitly trusted

The documentation says shared mode is:

> only for trusted roles. <sup>[source]</sup>

That's correct.

In shared mode:

```text
analyst
  ↓
same mutable namespace
  ↓
critic
  ↓
same namespace
```

There is no meaningful isolation.

Therefore `writes` isn't a true sandbox boundary in shared mode.

It's mostly governance/diagnostics.

That distinction should be prominent in public documentation.

---

## 31. `max_turns` is actually maximum loop iterations

Because:

```python
for turn_idx in range(self.max_turns)
```

`max_turns` means:

> maximum total agent turns across all roles.

It does **not** mean:

> maximum turns per agent.

That's probably correct, but worth documenting.

For:

```text
3 agents
max_turns = 6
```

you get:

```text
analyst
critic
narrator
analyst
critic
narrator
```

not six turns each.

---

## 32. Empty role list is not validated

This is a small but concrete bug.

If:

```python
roles = []
```

then:

```python
self.turn_order = []
```

and:

```python
self.turn_order[turn_idx % len(self.turn_order)]
```

becomes:

```text
ZeroDivisionError
```

The constructor should reject:

```text
roles == []
turn_order == []
```

immediately.

---

## 33. `turn_order` can reference nonexistent roles

The loop handles this:

```python
role = self.roles.get(agent_name)

if role is None:
    log.warning(...)
    continue
```

But silently skipping an invalid role means:

```text
turn 1 → valid
turn 2 → nonexistent
turn 3 → valid
```

and the session still proceeds.

For deterministic orchestration, invalid `turn_order` should be rejected during construction.

---

## 34. The most important architectural improvement

I would change the loop from:

```text
LLM
 ↓
string code
 ↓
execute
```

to:

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

Specifically:

```text
AgentAction
├── action_id
├── agent
├── kind
├── code
├── handoff
└── requested_outputs
```

and:

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

Now the entire system becomes traceable.

---

## 35. Target end-to-end state machine

The current implementation is roughly:

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

I'd make it:

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

This gives us an actual transaction boundary.

---

## 36. Revised verdict for the agent loop

| Area | Assessment |
|---|---|
| Multi-agent architecture |  Strong |
| Role model |  Strong |
| Agent identity |  Strong |
| Explicit shared memory |  Strong |
| Namespace write isolation |  Good |
| Isolated fresh kernels |  Strong concept |
| Per-agent budget trackers |  Good |
| Recovery loop |  Good foundation |
| Deterministic round-robin |  Good |
| Dynamic handoff |  Not actually implemented |
| Read permissions |  Not enforced |
| Cancellation during LLM generation |  Gap |
| Cancellation/export interaction |  Needs fix |
| Session error semantics |  Incomplete |
| Empty/invalid role validation |  Missing |
| Namespace prompt size |  Scalability/privacy concern |
| SharedMemory versioning |  Missing |
| Structured action protocol |  Needed |
| Turn transaction semantics |  Needs formalization |

---

## 37. Most important finding so far

The Kerno architecture has a surprisingly coherent progression:

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

The lower layers are already thinking in terms of **resource ownership, generations, cancellation, recovery, and isolation**.

The missing piece is a similarly rigorous **agent transaction model**.

That is where I'd focus next.

### Next audit target

The next file to inspect should be the execution-budget layer:

```text
kerno/execution/budget.py
```

because the agent loop now depends critically on:

```text
BudgetTracker
BudgetedExecutor
ExecutionBudget
```

and we need to verify whether the claimed per-agent isolation is **actually enforced**, particularly across:

- kernel execution time,
- cell count,
- retries,
- cancellation,
- isolated seed/export operations,
- and shared versus isolated sessions.

That will determine whether Kerno's **budget boundary is real or merely accounting metadata**.

---

## deep audit of `kerno/execution/budget.py`

This file is important because it defines the resource contract used by the agent loop. The design is good in concept, but there is **one major architectural flaw** in the hierarchical-budget implementation and several important semantic issues.

[Open `budget.py` on the Kerno branch](https://github.com/Abdus2023/Kerno/blob/arena/01a0064f-kerno/kerno/execution/budget.py)

---

## 1. The basic budget model is clean

Kerno defines three resource dimensions:

```text
ExecutionBudget
├── max_executions
├── max_wall_time
└── max_output_bytes
```

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

## 2. The enforcement model is intentionally non-preemptive

The implementation explicitly chooses:

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

<sup>[source]</sup>

That means:

```text
budget = 10 seconds

execution #1 = 7 s
execution #2 = 7 s
```

is allowed to complete.

After execution #2:

```text
spent = 14 s
```

and the **next** execution is refused.

This is actually a good policy for notebook execution because abruptly killing a completed Python execution merely to enforce an aggregate budget can leave the kernel in an unpredictable state.

So the design choice itself is sound.

---

## 3. `max_executions` is genuinely enforced before touching the kernel

This is one of the strongest parts.

```python
self._tracker.check_can_start()
```

runs before:

```python
self._executor.execute(...)
```

<sup>[source]</sup>

Therefore:

```text
budget exhausted
       ↓
BudgetExceeded
       ↓
underlying kernel NOT touched
```

That's exactly the invariant we want.

---

## 4. The wrapper turns budget exhaustion into an error cell

Instead of raising:

```python
BudgetExceeded
```

to the agent loop, `BudgetedExecutor.execute()` returns:

```text
CellOutput(
    error=CellError(
        ename="BudgetExceeded",
        ...
    )
)
```

<sup>[source]</sup>

This is an interesting choice because it makes budget exhaustion look like an ordinary failed execution.

And that exposes a problem.

---

## 5. Major issue: budget exhaustion is semantically NOT a normal execution error

The agent loop's recovery mechanism can potentially see:

```text
ename = BudgetExceeded
```

as:

```text
Python execution failed
```

rather than:

```text
agent is permanently out of budget
```

So you can get:

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

The wrapper will continue refusing execution, but the agent may waste turns trying to recover from a condition that is not recoverable.

The budget layer should expose a machine-readable terminal condition.

For example:

```text
ExecutionResult.status =
    SUCCESS
    ERROR
    TIMEOUT
    CANCELLED
    BUDGET_EXCEEDED
```

rather than representing everything as a `CellOutput.error`.

---

## 6. The comment says "stops recovering" — but the code doesn't guarantee that

The docstring says:

> the agent loop sees a normal failed cell and stops recovering. <sup>[source]</sup>

But `BudgetedExecutor` itself does not stop recovery.

It merely returns:

```text
CellError(ename="BudgetExceeded")
```

Whether the loop stops depends entirely on the agent-loop/recovery implementation.

That means this statement is an **implicit cross-module contract**, not something enforced here.

I'd make it explicit in the execution result.

---

## 7. Sticky exhaustion is good

This is a strong design:

```python
self._exceeded = exc
```

Once wall-time/output budget is crossed:

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

<sup>[source]</sup>

That prevents the agent from repeatedly trying to execute after the budget has been exhausted.

---

## 8. `max_executions=0` works correctly

Because:

```python
self._executions >= self.budget.max_executions
```

immediately evaluates:

```text
0 >= 0
```

the first execution is refused.

That's a nice edge-case behavior.

---

## 9. Negative limits are not validated

This is a concrete missing validation.

For example:

```python
ExecutionBudget(max_executions=-1)
```

will effectively mean:

```text
0 >= -1
```

and immediately reject execution.

Similarly:

```python
ExecutionBudget(max_wall_time=-5)
```

is nonsensical.

The constructor should validate:

```text
max_executions >= 0
max_wall_time >= 0
max_output_bytes >= 0
```

or reject `None`/invalid values explicitly.

---

## 10. Negative duration/output accounting isn't protected

`record()` accepts:

```python
duration_s: float
output_bytes: int
```

without validation.

A caller could theoretically do:

```text
record(-100, -500)
```

and reduce the accumulated budget.

The normal executor won't do that, but `BudgetTracker` is a public accounting primitive.

Defensive validation should reject negative measurements.

---

## 11. The output budget only counts stdout

The implementation does:

```python
len(output.stdout)
```

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

```text
max_output_bytes
```

that's potentially misleading.

A better definition would be:

```text
max_stdout_bytes
```

or aggregate all serialized output channels.

---

## 12. Output can therefore bypass the budget

Imagine:

```text
stdout = 1 KB
display_data = 100 MB
```

The budget sees:

```text
1 KB
```

even though the actual output produced by the execution may be enormous.

For a notebook/agent system this matters significantly.

An LLM-facing system should probably have:

```text
max_stdout_bytes
max_stderr_bytes
max_display_bytes
max_total_output_bytes
```

or at minimum:

```text
serialized_output_bytes
```

---

## 13. Wall-time is execution time, not total agent time

This is another important distinction.

The tracker measures:

```python
start = time.monotonic()
output = self._executor.execute(...)
duration_s = ...
```

<sup>[source]</sup>

Therefore the budget excludes:

```text
LLM generation
prompt construction
namespace processing
recovery reasoning
queue waiting
kernel acquisition
export
```

So:

```text
max_wall_time = 60 sec
```

does **not** mean:

> this agent may consume at most 60 seconds of wall-clock session time.

It means:

> underlying executor calls may cumulatively run for at most 60 seconds before future execution is blocked.

That's a valid policy, but the name/documentation should make this distinction explicit.

---

## 14. This confirms our previous agent-loop finding

We previously suspected that:

```text
BudgetTracker
```

was mostly execution accounting.

Now we can confirm it.

The budget does **not** directly control:

```text
LLM time
kernel acquisition
pool waiting
namespace operations
shared-memory operations
handoff
```

Therefore the actual agent resource boundary is:

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

Only the right-hand branch is budgeted.

---

## 15. The biggest flaw: `BudgetAllocator` does not track actual child consumption

This is the most important finding in this file.

The allocator does:

```text
Parent = 100 executions

allocate Child A = 30
allocate Child B = 40

remaining = 30
```

That's fine as **reservation accounting**.

But there is no connection between:

```text
BudgetTracker
```

and:

```text
BudgetAllocator
```

Therefore:

```text
Parent budget = 100
Child A allocated = 30
Child A actually uses = 5
```

The allocator still considers:

```text
30 allocated
```

rather than:

```text
5 consumed
```

This is intentional reservation semantics perhaps, but the documentation calls it a parent budget.

We need to distinguish:

```text
allocated
reserved
consumed
remaining
```

---

## 16. More seriously: the parent budget isn't actually enforced by children

Suppose:

```text
parent = 100 executions
child = allocate(30)
```

The child receives:

```text
ExecutionBudget(max_executions=30)
```

Good.

But the parent has no `BudgetTracker` reference.

So the child can consume:

```text
30
```

while the parent tracker, if one exists separately, doesn't automatically know that those 30 were consumed.

The hierarchy is therefore:

```text
Parent allocation
        │
        └── creates child limit
```

not:

```text
Parent resource counter
        │
        ├── Child A consumption
        ├── Child B consumption
        └── Child C consumption
```

That's a significant distinction.

---

## 17. `BudgetAllocator.allocate()` has a particularly dangerous `None` behavior

Suppose:

```python
parent = ExecutionBudget(max_executions=100)
allocator = BudgetAllocator(parent)
```

Then:

```python
allocator.allocate()
```

does:

```text
remaining = 100
child.max_executions = 100
```

and then commits:

```text
allocated_exec += parent.max_executions
```

so:

```text
allocated = 100
remaining = 0
```

That's reasonable.

But if the parent is:

```python
ExecutionBudget(max_executions=None)
```

then:

```python
allocate(executions=None)
```

creates:

```text
child.max_executions = None
```

which means unlimited.

That's also logically consistent.

---

## 18. But mixed finite/infinite dimensions require careful semantics

Example:

```text
parent:
    executions = 100
    wall_time = None
    output = 1 MB
```

Child:

```text
allocate(
    executions=50,
    output_bytes=None
)
```

gets:

```text
executions = 50
output = 1 MB remaining
```

Good.

But the allocator reserves the entire 1 MB.

Another child asking for:

```text
output_bytes=1
```

gets rejected.

Even if the first child actually outputs only:

```text
10 KB
```

So again:

> allocation ≠ consumption.

That should be explicit.

---

## 19. `name` isn't actually part of the child budget

`allocate(..., name="analyst")` stores:

```python
self._names[child_name] = child
```

but the returned `ExecutionBudget` doesn't contain:

```text
name
```

So the name is only an allocator-side lookup.

That's okay, but it means the budget object itself cannot identify its owner.

For observability, I'd add:

```text
BudgetAllocation
├── id
├── name
├── budget
├── tracker
└── parent
```

rather than returning a bare `ExecutionBudget`.

---

## 20. `_children` stores budgets but not trackers

The allocator maintains:

```python
self._children: list[ExecutionBudget]
```

<sup>[source]</sup>

That means it knows:

```text
what was allocated
```

but not:

```text
what was consumed
```

A stronger implementation would maintain:

```text
ChildAllocation
├── budget
├── tracker
├── allocated
└── consumed
```

Then:

```text
remaining =
    parent_limit
    - sum(actual child consumption)
```

if the intended model is consumption-based.

---

## 21. Another subtle issue: allocation is not thread-safe

`BudgetTracker` has mutable fields:

```text
_executions
_wall_time
_output_bytes
_exceeded
```

and `BudgetAllocator` has:

```text
_allocated_exec
_allocated_time
_allocated_output
_children
```

with no locks.

If one budget can be shared across concurrent executions:

```text
Thread A → record()
Thread B → record()
```

updates can race.

If Kerno guarantees:

```text
one executor → one active execution
```

then that's fine.

But the allocator may eventually be used for multiple agents.

Then synchronization becomes necessary.

---

## 22. This connects to the KernelPool invariant

Earlier we identified:

> one `PooledKernel` should have one active execution.

If that invariant holds, then a per-agent `BudgetTracker` may also be single-writer.

That's a good reason to preserve:

```text
one task
   ↓
one kernel
   ↓
one execution at a time
   ↓
one BudgetTracker writer
```

If Kerno later introduces concurrent execution within an agent, this budget implementation will need synchronization.

---

## 23. `execute_silent()` still consumes output budget

This is important for the agent-loop isolated mode.

`execute_silent()` does:

```python
output = self.execute(... silent=True ...)
```

and then:

```python
return output.stdout.strip()
```

<sup>[source]</sup>

So seed/export operations that are executed silently still count:

```text
execution count
wall time
stdout bytes
```

As noted earlier, this means the effective budget includes infrastructure operations.

That can produce surprising behavior:

```text
max_executions = 10

seed = 1
agent work = 9
export = 1

→ budget exhausted
```

The agent technically got only 9 work executions.

---

## 24. That may be the wrong abstraction

I'd separate:

```text
AgentBudget
```

from:

```text
InfrastructureBudget
```

For example:

```text
Agent budget:
    user-visible executions = 10

Infrastructure:
    seed/export do not consume agent quota
```

or explicitly count them separately:

```json
{
  "agent_executions": 9,
  "infrastructure_executions": 2,
  "total_executions": 11
}
```

This makes diagnostics much easier.

---

## 25. The `raw_kernel` escape hatch is powerful but dangerous

The wrapper exposes:

```python
@property
def raw_kernel(self):
```

<sup>[source]</sup>

and deliberately calls it:

> for trusted infrastructure.

That's reasonable.

But it creates a budget bypass:

```text
BudgetedExecutor
       │
       ├── execute() → budget enforced
       │
       └── raw_kernel.execute() → potentially bypasses budget
```

Any code that receives the wrapper can potentially access the raw kernel.

Therefore:

> `raw_kernel` must never be exposed to untrusted agent/tool code.

This should be a hard architectural rule, not merely a docstring warning.

---

## 26. The `records` passthrough is similarly important

The wrapper exposes:

```python
return getattr(self._executor, "records", ())
```

That's good for observability.

But if records contain:

```text
source code
stdout
stderr
exceptions
metadata
```

then agent-facing code may gain access to information outside its declared `reads`.

Again:

```text
trusted infrastructure → okay
agent/plugin code → potentially dangerous
```

---

## 27. BudgetExceeded should be a first-class execution status

I would change the result contract to:

```text
ExecutionResult
├── status
├── output
├── error
├── duration
├── budget
└── metadata
```

with:

```text
status =
    SUCCESS
    ERROR
    TIMEOUT
    CANCELLED
    BUDGET_EXCEEDED
```

Then the loop can do:

```text
BUDGET_EXCEEDED
      ↓
terminate agent
```

instead of:

```text
CellError
      ↓
maybe recovery
      ↓
LLM
```

---

## 28. Recommended hierarchical budget model

The clean architecture would be:

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

And consumption should flow upward:

```text
execution
   ↓
AgentTracker
   ↓
SessionTracker
```

Then the invariant becomes:

```text
sum(child consumption) <= parent consumption/limit
```

depending on whether the parent is reservation-based or consumption-based.

---

## 29. Better data model

I'd replace the current conceptual split with:

```python
BudgetAllocation:
    name
    limit
    tracker
    parent
```

Then:

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

This eliminates the ambiguity between:

```text
allocated
spent
remaining
```

---

## 30. Current severity

| Finding | Severity |
|---|---|
| Child allocation not connected to parent consumption |  P1 |
| BudgetExceeded represented as ordinary cell error |  P1 |
| `raw_kernel` can bypass budget |  P1 security boundary |
| Output budget counts stdout only |  P1 |
| Budget excludes LLM/session wall time |  P1 semantic |
| Seed/export consume agent budget |  P1 |
| Negative limits not validated |  P2 |
| Negative accounting values accepted |  P2 |
| Allocator not thread-safe |  P2 |
| Allocation/name model weak |  P2 |

---

## 31. Overall verdict

The basic execution budget is **good and usable**:

```text
preflight execution limit
+
sticky wall/output exhaustion
+
post-execution accounting
+
observability snapshot
```

That's a solid foundation.

The hierarchical allocator, however, is currently closer to a:

> **budget reservation calculator**

than a true hierarchical resource controller.

That's the distinction I'd fix before calling the multi-agent budget architecture complete.

---

## The next critical layer

We have now established:

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

The next thing to audit is the **actual execution engine / output contract**, because we need to answer one final critical question:

> When `BudgetedExecutor.execute()` returns `CellOutput`, does that object reliably distinguish **Python error, timeout, cancellation, kernel death, and successful execution**?

That determines whether the entire chain:

```text
Agent
 → Budget
 → Runtime
 → IOPUB
 → Result
```

can preserve failure semantics without losing information.

---

## `kerno/kernel/output.py` + `kerno/types.py`

This is the next critical layer, and the result is actually encouraging: **Kerno has a reasonably good structured execution-result model**, but there is a serious mismatch between what the types can represent and what the output collector actually records.

The two relevant files are `kerno/kernel/output.py` and `kerno/types.py`. <sup>[source]</sup>

---

## 1. `CellOutput` is the correct abstraction

The central type is:

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

<sup>[source]</sup>

This is exactly what an agent-oriented notebook runtime needs.

It avoids forcing every caller to understand raw Jupyter/ZeroMQ messages.

The intended pipeline is:

```text
ZMQ / IOPub
     ↓
OutputCollector
     ↓
CellOutput
     ↓
Agent / Budget / Session
```

That's a strong boundary.

---

## 2. `CellError` is also nicely minimal

```text
CellError
├── ename
├── evalue
└── traceback
```

<sup>[source]</sup>

This preserves the three things an LLM generally needs:

```text
what failed
why it failed
where it failed
```

And `OutputCollector` strips ANSI escape sequences from tracebacks, which is good for machine-readable error processing. <sup>[source]</sup>

---

## 3. Python exceptions are captured correctly

When IOPub sends:

```text
msg_type = "error"
```

the collector produces:

```python
CellError(
    ename=...,
    evalue=...,
    traceback=...
)
```

<sup>[source]</sup>

So:

```python
raise ValueError("bad data")
```

becomes something like:

```text
CellOutput.error.ename
    = ValueError

CellOutput.error.evalue
    = bad data
```

That's correct.

---

## 4. Timeout is represented as a kernel-level error

When the deadline expires:

```text
TimeoutError
```

is placed into `CellOutput.error`. <sup>[source]</sup>

Likewise cancellation becomes:

```text
KernelInterrupted
```

This means the output layer already has enough information for the agent loop to distinguish:

```text
Python error
Timeout
Cancellation
```

**provided the caller examines `error.ename`.**

---

## 5. But this reveals the budget problem we identified

Budget exhaustion also becomes:

```text
CellError(
    ename="BudgetExceeded"
)
```

So the system currently has several fundamentally different conditions represented using the same mechanism:

```text
CellOutput.error
├── ValueError
├── SyntaxError
├── TimeoutError
├── KernelInterrupted
└── BudgetExceeded
```

This works, but it's semantically weak.

The better model is:

```text
ExecutionStatus
├── SUCCESS
├── PYTHON_ERROR
├── TIMEOUT
├── CANCELLED
├── BUDGET_EXCEEDED
└── KERNEL_DIED
```

with `CellError` carrying the detailed exception only when applicable.

---

## 6. There is already a `SessionStatus.KERNEL_DIED`

This is interesting.

`SessionStatus` includes:

```text
RUNNING
COMPLETE
MAX_CELLS
INTERRUPTED
KERNEL_DIED
ERROR_UNHANDLED
```

<sup>[source]</sup>

So the project already recognizes kernel death as a **session-level semantic event**.

But `CellOutput` itself doesn't have:

```text
KERNEL_DIED
```

as an explicit status.

That creates an abstraction gap:

```text
Cell layer:
    error / no error

Session layer:
    KERNEL_DIED
```

The intermediate execution layer has to infer kernel death.

---

## 7. `is_empty` is useful but slightly misleading

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

<sup>[source]</sup>

So a successful:

```python
x = 1
```

can produce:

```text
CellOutput(
    stdout="",
    stderr="",
    result=None
)
```

and be considered:

```text
is_empty = True
```

But:

> empty output does not mean empty execution.

It means:

> execution produced no captured user-visible output.

I'd rename it:

```text
has_visible_output
```

and perhaps retain `is_empty` only as a compatibility convenience.

---

## 8. `as_text()` is very useful for LLM consumption

The method prioritizes:

```text
ERROR
stdout
result
images
displays
```

<sup>[source]</sup>

That's exactly the right direction.

For an agent, this:

```text
[ERROR] NameError: df is not defined
...
```

is much more useful than dumping raw IOPub JSON.

---

## 9. But `as_text(max_chars)` doesn't bound every component

This is a subtle but important scalability issue.

`stdout` is bounded.

But:

```text
self.error.traceback
```

is only reduced to the last 5 lines.

Those five lines can theoretically be huge.

Likewise:

```text
HTML
```

is reduced to 500 characters, which is good.

But:

```text
result
```

is sliced to 500.

Images are represented only by count.

Overall it's reasonably bounded, but the method doesn't enforce a strict **global character budget**.

For LLM context safety, that's preferable:

```text
as_text(max_chars=3000)
```

should guarantee:

```text

```

Currently it does not necessarily do so.

---

## 10. The output collector has a strong single-reader design

This comment is important:

```text
IOPub has ONE consumer
```

and Kerno introduces:

```python
IOPUB_LOCK = threading.RLock()
```

<sup>[source]</sup>

This is a good response to a real Jupyter architecture constraint.

Without it:

```text
collector thread ──┐
                   ├── IOPub socket
KernoComm thread ──┘
```

could steal messages from each other.

Particularly:

```text
status: idle
```

could be consumed by the wrong reader, leaving the execution waiting forever.

The lock prevents that.

---

## 11. But the global `IOPUB_LOCK` is a scalability bottleneck

The lock is global:

```python
IOPUB_LOCK = threading.RLock()
```

<sup>[source]</sup>

Therefore:

```text
Kernel A collecting
        │
        ▼
   global lock
        │
        X
Kernel B collecting
```

If Kerno supports multiple kernels simultaneously—which `KernelPool` clearly intends to—this means output collection for independent kernels can serialize.

That's unnecessary.

The correct granularity is likely:

```text
Kernel A → IOPub lock A
Kernel B → IOPub lock B
Kernel C → IOPub lock C
```

rather than:

```text
all kernels → one global lock
```

---

## 12. This could become a serious throughput limitation

Suppose:

```text
8 agents
8 kernels
```

and each is executing long-running work.

With a global lock:

```text
Agent A collects
Agent B waits
Agent C waits
Agent D waits
...
```

Even though the kernels are completely independent.

The lock only needs to protect:

> readers of the same IOPub socket.

It does not need to protect all IOPub sockets globally.

---

## 13. `comm_msg` handling is architecturally clever

Instead of a competing reader:

```text
KernoComm thread → get_iopub_msg()
```

the collector handles:

```text
case "comm_msg":
    handler(msg)
```

<sup>[source]</sup>

This is a good design.

The data path becomes:

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

rather than two competing consumers.

That's exactly the correct architectural direction.

---

## 14. But `_comm_handler` is global too

The handler is stored as:

```python
_comm_handler
```

<sup>[source]</sup>

This means there is only one global comm handler for the entire process.

If you have:

```text
Kernel A → comm messages
Kernel B → comm messages
```

the same handler receives both.

The handler therefore needs to distinguish:

```text
which kernel/session produced this message?
```

If that context isn't attached or derivable from `msg`, cross-kernel event routing becomes ambiguous.

A per-kernel dispatcher would be cleaner.

---

## 15. The collector doesn't verify `msg_id`

This is an important protocol observation.

The function receives:

```python
collect(kc, msg_id, ...)
```

but the code processes every IOPub message arriving on the socket.

It doesn't appear to filter messages by:

```text
parent_header.msg_id == msg_id
```

Instead it waits for:

```text
status == idle
```

This is usually workable if the kernel has exactly one outstanding execution.

But it becomes fragile if:

```text
multiple execute requests
```

are in flight.

---

## 16. This reinforces the one-execution invariant

The architecture should explicitly guarantee:

```text
KernelRuntime
    ↓
one outstanding execute_request
    ↓
one collector
```

If that is enforced, the collector's design is safe enough.

If concurrent requests are ever supported, this collector needs a proper demultiplexer keyed by:

```text
parent_header.msg_id
```

---

## 17. Another problem: timeout returns without proving the kernel is idle

On timeout:

```text
output.error = TimeoutError
break
```

<sup>[source]</sup>

It calls:

```text
on_timeout()
```

which presumably interrupts the kernel.

But the collector does **not** wait for:

```text
status: idle
```

after interrupting.

Therefore:

```text
collector returns
       ↓
kernel may still be executing
```

This is a critical lifecycle boundary.

The runtime must ensure that the kernel is actually quiescent before allowing the same kernel to be reused.

---

## 18. Cancellation has the same issue

Cancellation:

```text
cancel_event.set()
```

causes:

```text
on_timeout()
output.error = KernelInterrupted
break
```

and returns.

Again:

```text
return to caller
       ↓
kernel may still be stopping
```

If the pool immediately does:

```text
release()
reset()
available.put()
```

we could have:

```text
old execution still unwinding
          +
new task starts
```

That would be catastrophic.

---

## 19. This is one of the most important end-to-end findings

We can now connect three layers:

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

Therefore we need a hard invariant:

> **A timeout/cancellation is not complete until the kernel has reached a known quiescent state or has been declared dead and retired.**

This should be enforced in `KernelRuntime`, not left to the agent loop.

---

## 20. `SessionStatus.KERNEL_DIED` needs a reliable source

We now see how kernel death might be detected:

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

But `OutputCollector` itself only produces:

```text
TimeoutError
```

So the runtime must perform the second-stage classification.

That is appropriate.

The final chain should be:

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

---

## 21. `CellOutput.duration` isn't populated by `collect()`

This is a concrete implementation gap.

`CellOutput` contains:

```python
duration: float = 0.0
```

<sup>[source]</sup>

But `collect()` itself records:

```text
deadline
```

rather than assigning:

```text
output.duration
```

So the field must be populated by a higher layer, if at all.

This creates another hidden contract.

Better for the collector to do:

```text
started = monotonic()
...
output.duration = monotonic() - started
```

Then every caller receives consistent execution timing.

---

## 22. `execution_id` is present but not generated here

`CellOutput` contains:

```text
execution_id
```

<sup>[source]</sup>

The comment says it is a universal correlation key.

But `OutputCollector.collect()` receives:

```text
msg_id
```

and does not visibly assign:

```text
output.execution_id = msg_id
```

That seems like a missed opportunity.

The collector has the natural correlation identifier available.

It should probably preserve it.

---

## 23. This matters enormously for observability

The ideal trace should be:

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

Then you can answer:

> Which agent caused this Python exception?

without reconstructing the entire event history.

Kerno is already very close to this.

---

## 24. `CellOutput` should probably include status

I'd minimally add:

```text
ExecutionStatus
```

to the model.

For example:

```text
SUCCESS
PYTHON_ERROR
TIMEOUT
CANCELLED
BUDGET_EXCEEDED
KERNEL_DIED
```

Then:

```text
error
```

can remain the detailed exception payload.

This eliminates all the string-based inference currently required.

---

## 25. The session model should derive its status from execution status

Currently:

```text
SessionStatus
```

contains:

```text
MAX_CELLS
INTERRUPTED
KERNEL_DIED
ERROR_UNHANDLED
```

But no:

```text
BUDGET_EXCEEDED
TIMEOUT
```

So the session layer will likely need to infer them from cell errors.

I'd change this to something like:

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

---

## 26. There is an interesting positive feature: recovery is measurable

`SessionResult.recovery_count` detects:

```text
error cell
   ↓
next cell succeeds
```

<sup>[source]</sup>

That's a useful metric.

For agent evaluation, you can eventually measure:

```text
recovery rate
error rate
mean recovery attempts
```

But the heuristic is simplistic.

For example:

```text
error
error
success
```

counts only one recovery.

It might actually represent:

```text
two failed repair attempts
one successful repair
```

A richer execution ledger would record explicit parent/child relationships:

```text
execution #4
    caused_by = execution #3
    reason = recovery
```

---

## 27. Recommended execution record

Kerno would benefit enormously from:

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

Then `CellOutput` remains the user-facing result while the ledger carries operational metadata.

---

## 28. Final assessment of this layer

### Strong

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

### Needs correction

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

---

## 29. Most important invariant discovered

At this point, the entire Kerno execution architecture should enforce:

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

The critical missing guarantee is the middle one:

> **TIMEOUT/CANCELLED → kernel definitely quiescent before reuse.**

That is the next thing I would verify in `kerno/kernel/runtime.py`, because it determines whether the pool can safely recycle a kernel after a failed or interrupted execution.

[Kerno — requested branch `arena/01a0064f-kerno`](https://github.com/Abdus2023/Kerno/tree/arena%2F01a0064f-kerno)

---

## `kerno/kernel/runtime.py` audit

This file confirms the concern from the previous stage: **Kerno has a sophisticated timeout-escalation design, but its state machine currently has a dangerous semantic gap around interrupt completion and kernel reuse.**

[Open `runtime.py` on the Kerno branch](https://github.com/Abdus2023/Kerno/blob/arena/01a0064f-kerno/kerno/kernel/runtime.py)

---

## 1. The intended execution lifecycle is good

The runtime currently follows:

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

And timeout escalation is:

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

That's a sensible architecture.

The problem is that the implementation sometimes **declares the kernel READY before proving that it is actually ready**. <sup>[source]</sup>

---

## 2. Critical finding: `interrupt()` immediately changes state back to READY

The implementation is:

```python
self._state = KernelRuntimeState.INTERRUPTING
self._km.interrupt_kernel()
self._state = KernelRuntimeState.READY
```

<sup>[source]</sup>

This is the single most important issue in this file.

`interrupt_kernel()` means approximately:

> send an interrupt request to the kernel process.

It does **not** prove:

> the Python code has stopped executing and the kernel is idle.

So this:

```text
INTERRUPTING
    ↓
SIGINT
    ↓
READY
```

should actually be:

```text
INTERRUPTING
    ↓
SIGINT
    ↓
wait for confirmed idle
    ↓
READY
```

or:

```text
INTERRUPTING
    ↓
SIGINT
    ↓
failed to become idle
    ↓
DEAD / RESTARTING
```

---

## 3. This creates a possible double-execution race

Consider:

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

Before the interrupted Python execution has actually finished:

```text
Agent A
   ↓
execute("print('next')")
```

could theoretically occur.

Then:

```text
old execution
     +
new execution
     ↓
same kernel
```

That's precisely what the previous collector analysis warned about.

---

## 4. `collect()` also returns immediately after timeout/cancellation

The runtime calls:

```python
collect(
    ...,
    on_timeout=self.interrupt,
    cancel_event=cancel_event,
)
```

and then the `finally` block does:

```python
self._state = KernelRuntimeState.READY
```

<sup>[source]</sup>

So there are **two independent paths** that can incorrectly produce READY:

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

Neither path waits for an authoritative kernel-idle event.

---

## 5. The timeout escalation policy is actually quite good

There is a strong idea here:

```text
soft interrupt
    ↓
grace period
    ↓
hard kill
    ↓
restart
```

The implementation documents this as an escalation ladder. <sup>[source]</sup>

Conceptually:

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

That's much more robust than simply calling `restart_kernel()` immediately.

---

## 6. But `_escalate_timeout()` has a serious semantic issue

The code says:

```python
if not self.is_alive:
    return
```

Then:

```python
proc.kill()
proc.wait(...)
```

and:

```python
self.restart()
```

<sup>[source]</sup>

The documentation says:

> if the kernel died on its own, leave it dead and let recovery handle restart.

That's a reasonable policy.

But there is an inconsistency with the `state` property.

If the process dies:

```text
is_alive = False
```

then:

```python
state
```

eventually becomes:

```text
DEAD
```

Good.

But `execute()` has:

```python
finally:
    self._state = READY
```

So the execution path can overwrite the dead state with:

```text
READY
```

before anyone asks `state`.

---

## 7. Fortunately, `state` has sticky death detection

This part is good:

```python
if self._km is None or not self._km.is_alive():
    self._state = KernelRuntimeState.DEAD
```

<sup>[source]</sup>

So:

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

This partially protects the system.

But it is still better to **never write READY after a failed execution until health has been verified**.

---

## 8. `_assert_running()` has a related weakness

It checks:

```python
if not self.is_alive:
    raise RuntimeError(...)
```

rather than:

```python
if self.state != READY:
    ...
```

<sup>[source]</sup>

Therefore:

```text
_state = INTERRUPTING
is_alive = True
```

would still allow:

```text
execute()
```

because the process is technically alive.

The lifecycle contract should be:

```text
execute allowed only when:
    state == READY
    AND process alive
```

not merely:

```text
process alive
```

---

## 9. Recommended state machine

I'd formalize it as:

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

Current code effectively has:

```text
INTERRUPTING → READY
```

without the `WAIT_IDLE` state.

---

## 10. `restart()` is stronger because it waits for readiness

This part is correct:

```python
self._km.restart_kernel()
self._kc.wait_for_ready(timeout=self.startup_timeout)
```

<sup>[source]</sup>

So restart provides a genuine readiness boundary.

That gives us a useful principle:

> `wait_for_ready()` is an authoritative readiness signal; `is_alive` alone is not.

---

## 11. `shutdown()` correctly distinguishes `now`

This is also good:

```python
self._km.shutdown_kernel(now=now)
```

The API allows graceful versus immediate shutdown.

But after shutdown:

```text
_state = CLOSED
```

is set **before** the underlying kernel is actually stopped.

For most callers that's fine because CLOSED is a logical lifecycle state.

The more important issue is consistency: don't use `READY` as a logical state unless the kernel is genuinely ready.

---

## 12. `stream_execute()` has the same lifecycle weakness

It does:

```python
self._state = BUSY
yield from stream(...)
finally:
    self._state = READY
```

<sup>[source]</sup>

Therefore timeout/cancellation during streaming can also lead to:

```text
BUSY
 ↓
interrupt
 ↓
stream returns
 ↓
READY
```

without confirmation that the kernel has reached idle.

So this isn't just a normal `execute()` bug.

It is a **runtime-wide lifecycle problem**.

---

## 13. Another important finding: `stream_execute()` increments cells before success

It does:

```python
self._cell_count += 1
```

immediately after sending the request. <sup>[source]</sup>

Whereas normal `execute()` increments only after collection and only for non-silent execution.

So:

```text
execute()
```

and:

```text
stream_execute()
```

have different cell-count semantics.

Example:

```text
stream request
   ↓
kernel dies
   ↓
cells_executed += 1
```

The metric means:

> execute requests issued

rather than:

> cells successfully executed.

The API should choose one definition and use it consistently.

---

## 14. Silent execution doesn't count toward `_cell_count`

Normal execution:

```python
if not silent:
    self._cell_count += 1
```

<sup>[source]</sup>

This means:

```text
execute_silent()
```

doesn't increment the runtime's visible cell count.

That's probably intentional for infrastructure operations.

But `BudgetTracker` **does** count the execution, as we found earlier.

So there are now two different notions:

```text
KernelRuntime.cells_executed
    ≠
BudgetTracker.executions
```

This should be documented explicitly.

---

## 15. `memory_mb` is actually an execution

This is easy to overlook.

The property:

```python
memory_mb
```

calls:

```python
execute_silent(
    "import psutil, os; print(...)"
)
```

<sup>[source]</sup>

Therefore a memory inspection causes:

```text
Python execution
+
wall time
+
stdout
```

and potentially consumes the agent's execution budget.

This is another example of infrastructure activity leaking into the execution quota.

---

## 16. `reset_namespace()` is also a budget-consuming execution

It calls:

```python
self.execute("%reset -f", silent=True, timeout=10)
```

So resetting state consumes:

```text
BudgetTracker execution
BudgetTracker wall time
BudgetTracker output
```

even though the agent didn't ask to execute user code.

This strongly supports separating:

```text
user execution budget
```

from:

```text
runtime maintenance budget
```

---

## 17. Kernel generation is an excellent design

The runtime has:

```python
self._generation = 1
```

and increments on restart. <sup>[source]</sup>

This is valuable because:

```text
kernel_id = "abc"
generation = 3
```

means something very different from:

```text
kernel_id = "abc"
generation = 1
```

A restarted kernel is logically a new execution environment.

This should be propagated into every `CellOutput` / execution record.

---

## 18. The tracer already records generation

The runtime sends:

```text
kernel.id
kernel.generation
cell.num
cell.code_preview
cell.silent
```

into telemetry. <sup>[source]</sup>

That's excellent observability.

But the returned `CellOutput` should carry the same identifiers.

Otherwise:

```text
telemetry
```

knows:

```text
kernel.generation = 4
```

while:

```text
CellOutput
```

doesn't necessarily know it.

---

## 19. Security concern: telemetry includes code preview

The tracer receives:

```python
"cell.code_preview": code[:80]
```

<sup>[source]</sup>

This is useful for debugging, but it means source code is entering telemetry.

If users execute:

```python
token = "secret..."
```

the first 80 characters could potentially be logged.

Even a short preview can expose:

```text
API keys
tokens
passwords
PII
SQL
internal URLs
```

I'd make code-preview telemetry:

```text
disabled by default
```

or redact obvious secrets.

---

## 20. Error telemetry has the same concern

The runtime records:

```python
output.error.evalue[:200]
```

<sup>[source]</sup>

Exceptions can contain sensitive information:

```text
FileNotFoundError('/home/user/private/project/...')

requests.exceptions...
    Authorization: Bearer ...

DatabaseError(...)
```

So telemetry needs a privacy policy.

---

## 21. `cell.output_bytes` is incomplete

Runtime telemetry records:

```python
len(output.stdout)
```

not:

```text
stdout + stderr + result + displays + images
```

This duplicates the budget-layer limitation.

You effectively have:

```text
Budget output bytes
        ↓
stdout only

Telemetry output bytes
        ↓
stdout only
```

That should become a common `OutputMetrics` calculation.

---

## 22. `execute()` doesn't validate the timeout

There is no obvious validation for:

```text
timeout < 0
timeout = NaN
timeout = infinity
```

`collect()` ultimately receives the value.

The runtime API should normalize:

```text
timeout > 0
```

or explicitly define:

```text
timeout=None → unlimited
```

rather than leaving behavior to downstream code.

---

## 23. The timeout escalation policy is currently only applied to `TimeoutError`

This condition:

```python
output.error.ename == "TimeoutError"
```

triggers escalation. <sup>[source]</sup>

But cancellation creates:

```text
KernelInterrupted
```

So cancellation does not automatically enter the escalation ladder.

That might be intentional:

```text
user cancellation → interrupt only
timeout → interrupt → kill if necessary
```

and I think that's a reasonable distinction.

But it should be explicit in the contract.

---

## 24. The strongest architecture would centralize "quiescence"

Introduce:

```python
_wait_until_idle(...)
```

with semantics:

```text
wait for kernel idle
    ↓
confirmed → READY
timeout → DEAD/RESTARTING
```

Then both:

```text
interrupt()
```

and:

```text
cancel()
```

can use it.

For example:

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

This gives the runtime one authoritative lifecycle transition.

---

## 25. Proposed corrected execution lifecycle

I'd make it:

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

That would make kernel reuse substantially safer.

---

## 26. Current audit status

After the runtime layer, I'd classify the findings like this:

| Area | Status |
|---|---|
| Kernel startup |  Good |
| Graceful shutdown |  Good |
| Restart/readiness |  Good |
| Generation tracking |  Excellent |
| Telemetry |  Good foundation |
| Timeout escalation |  Good concept |
| Sticky DEAD state |  Good |
| Interrupt lifecycle |  Needs correction |
| Cancellation lifecycle |  Needs correction |
| Kernel reuse after interruption |  Must harden |
| Stream execution lifecycle |  Needs same fix |
| Cell counting semantics |  Inconsistent |
| Infrastructure budget accounting |  Architectural issue |
| Telemetry secret exposure |  Needs policy |

---

## 27. The architectural conclusion so far

We now have three connected findings:

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

The **resource accounting** is mostly sound.

The **structured output** is mostly sound.

The **kernel lifecycle boundary** is the part that needs hardening.

Most importantly:

> **"process is alive" is not equivalent to "kernel is ready for another execution."**

That distinction should become a first-class invariant throughout Kerno.

---

## Next audit target: `kerno/kernel/pool.py`

The next layer is particularly important because `KernelPool` decides whether a kernel is:

```text
available
leased
released
reused
retired
restarted
```

That's where we can determine whether the runtime's premature `READY` state can actually cause **cross-agent/kernel contamination**, and whether dead or interrupted kernels are correctly removed rather than returned to the pool.

[Kerno `kernel/pool.py` on the requested branch](https://github.com/Abdus2023/Kerno/blob/arena/01a0064f-kerno/kerno/kernel/pool.py)

---

## `kerno/kernel/pool.py` audit

This confirms the previous runtime concern and adds **several pool-level correctness bugs**. The pool architecture is understandable, but the current implementation should **not yet be treated as a reliable isolation boundary**.

[Open `pool.py` on the Kerno branch](https://github.com/Abdus2023/Kerno/blob/arena/01a0064f-kerno/kerno/kernel/pool.py)

---

## 1. The intended pool model is good

The pool defines:

```text
KernelPool
├── WARMING
├── AVAILABLE
├── ACQUIRED
├── RESETTING
└── DEAD
```

and maintains:

```text
_available
_active
_all
```

<sup>[source]</sup>

Conceptually:

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

That's the right overall architecture.

---

## 2.  Major bug: release is asynchronous

This is probably the most important pool-level issue.

For a normal completion:

```python
threading.Thread(
    target=self._soft_reset,
    args=(pk,),
    daemon=True
).start()
```

For an error/timeout:

```python
threading.Thread(
    target=self._hard_reset,
    args=(pk,),
    daemon=True
).start()
```

<sup>[source]</sup>

So:

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

The pool hasn't actually finished sanitizing the kernel.

That is acceptable **only because the kernel isn't immediately placed back into `_available`**.

So this part is not an immediate contamination bug.

But it creates another issue.

---

## 3. A released kernel is temporarily invisible

After:

```text
release(task)
```

and before:

```text
_soft_reset()
```

the kernel is:

```text
state = RESETTING
```

but:

```text
not _active
not _available
```

Therefore pool statistics temporarily report:

```text
available = 0
active = 0
total = 1
```

even though one kernel exists.

That's not necessarily wrong, but it means:

> `total != active + available`

can occur legitimately.

Your stats API therefore needs to include:

```text
resetting
warming
dead
```

otherwise operators may think the pool has lost capacity.

---

## 4.  `acquire()` can create more than `max_overflow`

This line is dangerous:

```python
if self.overflow and len(self._active) < self.max_overflow:
    pk = self._create_kernel()
```

<sup>[source]</sup>

It checks only:

```text
active < max_overflow
```

It does **not** account for:

```text
available
resetting
warming
newly-created overflow kernels
```

Suppose:

```text
size = 3
max_overflow = 10
```

and all 3 warm kernels are unavailable.

Several concurrent `acquire()` calls can all observe:

```text
active < 10
```

and create additional kernels.

The actual total could therefore exceed the intended:

```text
size + max_overflow
```

because `max_overflow` is being treated as an active-task limit rather than a pool-capacity limit.

---

## 5. Even worse: overflow semantics are ambiguous

The constructor says:

```python
max_overflow = 10
```

which strongly suggests:

```text
base pool = 3
maximum extra kernels = 10
maximum total = 13
```

But the code implements approximately:

```text
maximum active tasks = 10
```

That is not the same thing.

If 3 base kernels are active:

```text
len(_active) = 3
```

then the pool can create another kernel.

But whether that is "overflow #1" isn't tracked.

There should be:

```text
base_capacity
overflow_capacity
total_capacity
```

explicitly.

---

## 6.  `_create_kernel()` doesn't reserve capacity atomically

The sequence is:

```text
check capacity
    ↓
create KernelRuntime
    ↓
append _all
```

Multiple threads can race.

For example:

```text
Thread A: sees capacity
Thread B: sees capacity
Thread C: sees capacity
```

all create kernels.

The `_kernel_seq` increment itself is protected, but **capacity reservation isn't**.

The pool needs an atomic reservation mechanism around creation.

---

## 7. `start()` has a race with `_running`

`start()` does:

```python
self._running = True
```

then creates several threads.

There's no guard against:

```text
start()
start()
```

being called twice.

The second call can:

```text
spawn another N kernels
spawn another monitor
```

and duplicate the pool.

The lifecycle should be:

```text
STOPPED → STARTING → RUNNING → STOPPING → STOPPED
```

with `start()` idempotence or an explicit error.

---

## 8. `shutdown()` doesn't join the monitor

It does:

```python
self._running = False
```

but does not:

```text
join(_monitor)
```

<sup>[source]</sup>

The monitor may still be inside:

```python
time.sleep(30)
```

for up to 30 seconds.

That's usually okay for a daemon thread, but it means shutdown is not a clean lifecycle barrier.

---

## 9.  Shutdown races with reset threads

This is more important.

Suppose:

```text
task finishes
   ↓
release()
   ↓
_soft_reset thread starts
   ↓
pool.shutdown()
```

Shutdown does:

```text
runtime.shutdown()
```

while the reset thread may simultaneously do:

```text
runtime.reset_namespace()
```

or:

```text
runtime.restart()
```

Now two lifecycle operations can race on the same kernel.

That is a genuine concurrency bug.

---

## 10. The pool has no per-kernel lifecycle lock

This is the missing primitive.

Every `PooledKernel` should probably have:

```python
lifecycle_lock: threading.RLock
```

so operations become serialized:

```text
acquire
release
reset
restart
interrupt
retire
shutdown
```

for a particular kernel.

Currently the pool has:

```python
self._lock
```

but that protects pool dictionaries/lists, not the lifecycle of the underlying kernel.

---

## 11.  `interrupt()` + `release()` can race

Consider:

```text
Task A
  ↓
pool.interrupt("A")
  ↓
runtime.interrupt()
```

At nearly the same time:

```text
Task A completes
  ↓
pool.release("A")
  ↓
hard reset thread
```

You can get:

```text
runtime.interrupt()
+
runtime.restart()
```

concurrently.

That is unsafe.

A per-kernel lifecycle lock would solve this.

---

## 12. `restart(task_id)` has the same problem

It retrieves the kernel under the pool lock:

```python
pk = self._active.get(task_id)
```

then releases the pool lock and does:

```python
pk.runtime.restart()
```

<sup>[source]</sup>

So another thread can simultaneously:

```text
release(task_id)
```

and start:

```text
_hard_reset(pk)
```

while `restart()` is already running.

Again:

> pool-level locking ≠ kernel lifecycle locking.

---

## 13.  The pool can hand out a runtime whose state isn't actually READY

`acquire()` gets:

```python
pk = self._available.get(...)
```

Then checks:

```python
if not pk.is_healthy:
```

where:

```text
is_healthy =
    runtime.is_alive
    AND not expired
```

<sup>[source]</sup>

But it does **not** verify:

```text
runtime.state == READY
```

This directly connects to our previous runtime finding.

A process can be alive while:

```text
runtime.state = BUSY
INTERRUPTING
RESETTING
```

So:

```text
alive != ready
```

must be reflected in `is_healthy`.

---

## 14. `is_healthy` should be stricter

Currently:

```python
return self.runtime.is_alive and not self.is_expired
```

It should conceptually be:

```text
runtime.is_alive
AND runtime.state == READY
AND pool state == AVAILABLE
AND not expired
AND not retired
```

Otherwise the pool's health model is weaker than its acquisition contract.

---

## 15.  Soft reset itself consumes execution budget

This is especially important now that we've seen all three layers.

`_soft_reset()` does:

```python
pk.runtime.reset_namespace()
```

and `_bootstrap()` can execute Python.

So:

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

if the runtime is wrapped by a budgeted executor.

The pool is therefore performing infrastructure executions after the task has technically ended.

This reinforces the earlier need for separate budgets.

---

## 16. Soft reset may not be sufficient for isolation

The comment says:

```text
Soft reset: clear namespace, reload skills
```

But `%reset -f` only clears Python namespace state.

It doesn't necessarily eliminate:

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

So a "clean namespace" isn't necessarily:

> clean kernel.

For untrusted or adversarial workloads, only process replacement gives a strong isolation boundary.

---

## 17. This is crucial for Kerno's threat model

There are really three isolation levels:

### Level 1 — namespace reset

```text
same process
new Python namespace
```

Fast, weak.

### Level 2 — kernel restart

```text
new Jupyter kernel process
```

Much stronger.

### Level 3 — OS/container isolation

```text
new process/container
resource limits
filesystem/network policy
```

Strongest.

Kerno's pool currently operates primarily at levels 1 and 2.

That's fine for cooperative notebook workloads.

It should **not** be described as a security sandbox unless additional OS-level isolation exists.

---

## 18.  `_retire()` has a race with `_all`

It does:

```python
if pk in self._all:
    self._all.remove(pk)
```

under the lock.

Good.

But it shuts down the runtime **before** acquiring the lock:

```text
shutdown
↓
lock
↓
remove
```

Another thread could inspect the pool between those events and see:

```text
pk still in _all
state maybe AVAILABLE
runtime already shutting down
```

The state should transition to `DEAD`/`RETIRING` before the shutdown begins.

---

## 19. Retiring an available kernel leaves a stale queue entry

This is an important bug.

Suppose:

```text
_available contains pk
```

Monitor sees:

```text
pk.is_expired
```

and calls:

```python
_retire(pk)
```

The kernel is removed from:

```text
_all
```

but the code does not remove `pk` from:

```text
_available
```

because Python's `Queue` doesn't support convenient arbitrary removal.

So the queue can still contain:

```text
dead pk
```

Later:

```text
acquire()
 ↓
_available.get()
 ↓
dead pk
```

The health check catches it and replaces it.

So this may self-heal, but the queue contains stale entries and pool capacity accounting becomes inaccurate.

---

## 20. This can cause an availability illusion

Suppose:

```text
_all = []
_available queue = [dead kernel]
```

Then:

```text
stats()
```

can report:

```text
available = 1
total = 0
```

That is clearly inconsistent.

A robust pool should use one source of truth for membership and derive availability from it.

---

## 21.  `acquire()` can accidentally create an extra replacement

If a stale/dead kernel is pulled:

```python
if not pk.is_healthy:
    pk.runtime.shutdown(now=True)
    pk.state = DEAD
    pk = self._create_kernel()
```

<sup>[source]</sup>

But the stale kernel remains in:

```text
_all
```

unless `_create_kernel()` or something else removes it.

So:

```text
dead kernel
+
new kernel
```

can coexist in `_all`.

The pool's `total` count therefore becomes wrong.

---

## 22. `is_expired` has an expensive side effect

The property:

```python
memory = self._safe_memory()
```

calls:

```text
runtime.memory_mb
```

which, as we saw, executes Python inside the kernel.

So merely asking:

```python
pk.is_expired
```

can itself execute code in the kernel.

This happens in:

```text
acquire()
release()
monitor
health checks
```

That's a major architectural smell.

A health check should not itself mutate or consume the workload.

---

## 23. This creates a recursive resource-accounting problem

We now have:

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

Therefore:

> checking whether the kernel is healthy can consume the very budget you're trying to measure.

That's a serious design flaw.

Memory should be measured externally where possible:

```text
Kernel process PID
      ↓
psutil.Process(pid).memory_info()
```

rather than executing Python inside the kernel.

---

## 24. Memory measurement also fails open

`_safe_memory()`:

```python
try:
    return self.runtime.memory_mb
except Exception:
    return 0.0
```

<sup>[source]</sup>

If memory measurement fails, Kerno assumes:

```text
memory = 0 MB
```

That's dangerous.

If the kernel is actually consuming:

```text
8192 MB
```

but the measurement failed, the pool treats it as healthy.

Better:

```text
measurement failure
    ↓
unknown
    ↓
do not declare healthy
```

or at least:

```text
health = DEGRADED
```

---

## 25. Memory limit is not an enforcement mechanism

Even when:

```text
memory > 4096 MB
```

the pool only marks the kernel:

```text
expired
```

and eventually retires it.

That's **post-hoc detection**, not memory enforcement.

The process can exceed the limit before the monitor notices it.

Because the monitor runs every:

```text
30 seconds
```

the kernel may remain above the limit for a substantial period.

For real memory enforcement, OS-level resource limits are needed.

---

## 26. `MAX_LIFETIME` is measured from kernel creation, not restart

This is subtle.

`created_at` is set when:

```text
PooledKernel(...)
```

is created.

When:

```text
runtime.restart()
```

occurs:

```text
created_at
```

does not reset.

That's actually a reasonable choice if:

> lifetime means pool object lifetime.

But if the intention is:

> maximum age of current kernel process,

then restart should update the generation timestamp.

I'd rename it:

```text
MAX_POOL_LIFETIME
```

or introduce:

```text
process_started_at
generation_started_at
```

---

## 27. `tasks_served` survives kernel restart

That is probably correct.

It measures:

```text
number of tasks served by this pooled object
```

rather than:

```text
number served by this kernel generation
```

Again, generation-specific metrics would help:

```text
tasks_served_total
tasks_served_generation
```

---

## 28. The monitor detects runaway tasks but doesn't act

This code:

```python
if ... > 3600:
    warnings.warn(...)
```

only warns.

So:

```text
task stuck for > 1 hour
```

does not automatically trigger:

```text
interrupt
timeout
retirement
```

That's fine if intentionally advisory.

But the pool constructor doesn't expose a `max_task_duration`, so the `MAX_LIFETIME` concept can be misleading.

Kernel lifetime and task duration are separate concepts.

---

## 29. `release()` silently ignores unknown task IDs

```python
pk = self._active.pop(task_id, None)

if pk is None:
    return
```

<sup>[source]</sup>

This is convenient, but dangerous for debugging.

Suppose a caller accidentally does:

```text
release("wrong-task")
```

Nothing happens.

The real kernel remains acquired forever.

I'd prefer:

```text
release unknown task
    ↓
KeyError / PoolOwnershipError
```

or an explicit:

```text
strict=False
```

mode.

---

## 30. Task ownership is otherwise a good idea

The pool maps:

```text
task_id → PooledKernel
```

This is strong.

It enables:

```text
interrupt(task_id)
restart(task_id)
release(task_id)
```

without exposing pool internals.

The missing piece is stronger ownership enforcement.

A task should ideally receive:

```text
KernelLease
```

instead of a raw `KernelRuntime`.

---

## 31. Why a `KernelLease` is better

Currently:

```python
runtime = pool.acquire("task-123")
```

returns a raw runtime.

The caller can retain it indefinitely:

```text
pool.release("task-123")
↓
runtime reference still exists
```

The pool then assumes ownership has ended.

A lease object could enforce:

```text
KernelLease
├── task_id
├── runtime
├── generation
├── released
└── context-manager lifecycle
```

Then:

```python
with pool.acquire("task-123") as kernel:
    ...
```

would naturally enforce ownership.

---

## 32. Generation fencing should be added to leases

This is especially useful after restart.

Suppose:

```text
task gets kernel generation 4
```

then kernel restarts:

```text
generation 5
```

The old lease should know:

```text
my generation = 4
current generation = 5
```

and reject stale assumptions.

This prevents an old task/result from accidentally being associated with the new kernel state.

---

## 33. Recommended pool state machine

I'd formalize each pooled kernel as:

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

Current implementation compresses too many transitions into asynchronous helper threads.

---

## 34. The biggest pool-level invariant

The pool needs to guarantee:

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

And:

```text
kernel ∈ ACQUIRED
    ⇒
        exactly one task owns it
```

And:

```text
kernel ∈ RESETTING
    ⇒
        it cannot be acquired
```

And:

```text
kernel ∈ DEAD
    ⇒
        it cannot be acquired
```

These should be tested directly.

---

## 35. Priority findings from this file

| Finding | Priority |
|---|---:|
| Reset/shutdown/restart race |  P0 |
| Runtime READY doesn't guarantee idle |  P0 |
| Stale kernels can remain in `_available` |  P1 |
| Dead kernels can remain in `_all` |  P1 |
| Overflow capacity is incorrectly defined |  P1 |
| No per-kernel lifecycle lock |  P1 |
| Health check executes code in kernel |  P1 |
| Memory measurement fails open |  P1 |
| Soft reset isn't strong isolation |  P1 |
| Raw runtime returned instead of lease |  P2 |
| Stats omit resetting/warming/dead |  P2 |
| Unknown release silently ignored |  P2 |
| `start()` not idempotent |  P2 |
| Monitor shutdown not joined |  P2 |
| Telemetry/resource semantics |  P2 |

---

## 36. Overall Kerno execution architecture — current verdict

After auditing:

```text
budget.py
output.py
types.py
runtime.py
pool.py
```

the architecture looks like:

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

```text
alive == ready
interrupt == stopped
reset == isolated
health check == observation
budget allocation == consumption
```

Those equivalences are **not generally true**.

That's where the next engineering work should concentrate.

---

## 37. Recommended correction order

I would **not** start by adding more features.

I'd harden the existing substrate in this order:

### P0 — Kernel lifecycle correctness

Implement one authoritative:

```text
wait_until_idle()
```

and prohibit:

```text
READY
```

until it succeeds.

### P0 — Per-kernel synchronization

Add:

```text
PooledKernel.lifecycle_lock
```

and serialize:

```text
execute
interrupt
restart
reset
retire
shutdown
```

### P1 — Queue membership correctness

Replace stale `Queue` entries with a design where:

```text
AVAILABLE
```

is authoritative.

### P1 — Health without kernel execution

Measure kernel RSS externally.

Do **not** use:

```text
memory_mb → execute_silent()
```

for pool health.

### P1 — Explicit execution status

Introduce:

```text
SUCCESS
PYTHON_ERROR
TIMEOUT
CANCELLED
BUDGET_EXCEEDED
KERNEL_DIED
```

### P1 — Hierarchical budget accounting

Separate:

```text
allocated
consumed
remaining
```

and connect child consumption to the parent.

### P2 — Kernel leases

Return:

```text
KernelLease
```

instead of a bare runtime.

---

## Next layer: agent orchestration

The next audit should move **above the kernel infrastructure** into the actual Kerno agent/session orchestration:

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

That is where we can determine whether the low-level problems above actually propagate into **agent behavior**—especially whether `TimeoutError`, `BudgetExceeded`, kernel death, retries, and recovery can produce loops, incorrect success states, or accidental execution after a terminal condition.

[Kerno repository — branch `arena/01a0064f-kerno`](https://github.com/Abdus2023/Kerno/tree/arena/01a0064f-kerno)

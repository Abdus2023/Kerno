# 08 — Kernel Output And Execution Design

## The next audit target

The next file I would inspect is **`kerno/kernel/output.py`**.

That's now the critical junction:

```text
Jupyter IOPUB
     │
     ▼
output.py
     │
 ┌───┴────┐
 ▼        ▼
stdout   comm_msg
 │        │
 ▼        ▼
cell     KernoComm
result
```

If `output.py` gets the single-reader, buffering, timeout, `idle`, `comm_msg`, and error semantics right, then the whole **KernelRuntime → KernelPool → KernoComm** stack has a solid foundation.

If it doesn't, the communication correctness problems propagate upward into every agent loop.

---

## `kerno/kernel/output.py`

This file is actually **better than the previous communication audit suggested**. The earlier concern about cancellation only being checked between agent turns is no longer applicable at the cell-output layer: `OutputCollector.collect()` explicitly propagates cancellation **mid-cell** by invoking the interrupt callback. <sup>[source]</sup>

That is an important strength.

---

## 1. `output.py` is the sensory boundary

The file's architecture is very clear:

```text
Jupyter kernel
     │
     │ ZMQ / IOPUB
     ▼
OutputCollector
     │
     ├── stdout
     ├── stderr
     ├── result
     ├── images
     ├── HTML
     ├── JSON
     ├── errors
     └── comm_msg
            │
            ▼
        KernoComm
```

The docstring calls this the **"sensory layer"**: everything the kernel says is collected here. <sup>[source]</sup>

That's a good architectural boundary.

---

## 2. The single-reader solution is correct

The most important design decision is:

```python
IOPUB_LOCK = threading.RLock()
```

and both `collect()` and `stream()` hold it while consuming IOPUB. <sup>[source]</sup>

This addresses the classic failure mode:

```text
             IOPUB
               │
       ┌───────┴────────┐
       ▼                ▼
 output collector   comm listener
       │                │
       └───────┬────────┘
               ▼
          messages stolen
```

particularly the dangerous case where the communication listener consumes:

```text
status: idle
```

before the cell collector sees it.

The resulting symptom would be:

```text
cell actually finished
       │
       ▼
idle consumed elsewhere
       │
       ▼
collector waits
       │
       ▼
timeout
```

The current architecture explicitly prevents that. <sup>[source]</sup>

**This is one of the strongest parts of the current Kerno implementation.**

---

## 3. The `RLock` choice is sensible

Using:

```python
threading.RLock()
```

rather than a normal `Lock` gives re-entrant behavior.

That matters if future layers call output/communication routines from within code that already holds the IOPUB coordination lock.

It also makes the lock less brittle during refactoring.

---

## 4. Cancellation is genuinely propagated into the kernel

This is important.

Inside the collection loop:

```text
cancel_event.is_set()
        │
        ▼
     on_timeout()
        │
        ▼
 kernel interrupt
        │
        ▼
 KernelInterrupted
```

<sup>[source]</sup>

So cancellation isn't merely:

```text
"stop waiting for the result"
```

It is:

```text
"interrupt the actual running kernel execution"
```

That's the correct semantic behavior.

---

## 5. Timeout has the same interrupt path

The timeout path does:

```text
deadline exceeded
       │
       ▼
on_timeout()
       │
       ▼
interrupt kernel
       │
       ▼
TimeoutError
```

<sup>[source]</sup>

That's also correct.

A common bad implementation is:

```text
timeout
  ↓
return TimeoutError
  ↓
kernel continues running
```

which creates an orphaned computation.

Kerno is attempting to avoid that.

---

## 6. But there is still a subtle timeout race

Consider:

```text
t = 9.99s
cell finishes
       │
       ▼
kernel sends idle
```

while:

```text
deadline = 10.00s
```

The collector receives messages sequentially.

The implementation uses:

```python
remaining = deadline - time.monotonic()
```

before calling:

```python
kc.get_iopub_msg(...)
```

<sup>[source]</sup>

This is reasonable.

However, a timeout can still occur immediately around the boundary where the kernel has actually finished but the host's wall clock reaches the deadline first.

That's unavoidable in a wall-clock timeout design, but the runtime should make the resulting semantics explicit:

> **Timeout means the collector did not observe terminal completion before the deadline, not necessarily that the kernel computation itself had not completed.**

That distinction matters for diagnostics.

---

## 7. `idle` is correctly treated as the terminal event

The collector terminates only when:

```text
status.execution_state == "idle"
```

<sup>[source]</sup>

That's the correct Jupyter execution lifecycle concept.

The resulting state machine is approximately:

```text
busy
 │
 ├── stream
 ├── display
 ├── execute_result
 ├── error
 ├── comm_msg
 └── ...
 │
 ▼
idle
 │
 ▼
complete
```

Good.

---

## 8. Error handling is well structured

The code converts Jupyter errors into:

```text
CellError
├── ename
├── evalue
└── traceback
```

and strips ANSI escape sequences from the traceback. <sup>[source]</sup>

That is useful because raw terminal formatting can otherwise pollute logs/UI.

For example:

```text
\x1b[31mError\x1b[0m
```

becomes:

```text
Error
```

This is exactly the sort of normalization an execution substrate should perform.

---

## 9. Display handling is intentionally selective

The collector recognizes:

```text
image/png
text/html
application/json
text/plain
```

<sup>[source]</sup>

and maps them to structured `CellOutput` fields.

That's a good start.

The model is:

```text
Jupyter MIME bundle
       │
       ├── image/png → images
       ├── text/html → displays
       ├── application/json → displays
       └── text/plain → result
```

---

## 10. But MIME handling is incomplete

There are many legitimate Jupyter MIME types:

```text
image/jpeg
image/svg+xml
text/markdown
application/javascript
application/vnd.vega.v5+json
application/vnd.plotly.v1+json
application/pdf
```

Kerno currently ignores them.

That's not a correctness bug if the intended scope is narrow, but it means:

> `CellOutput` is currently a normalized subset of Jupyter output, not a complete representation of the Jupyter display protocol.

For an analytics platform, I'd expect at least:

```text
image/png
image/jpeg
image/svg+xml
text/html
text/markdown
text/plain
application/json
```

---

## 11. There is a potential data-loss issue with `text/plain`

The code only sets:

```python
output.result = data["text/plain"]
```

when:

```text
msg_type == "execute_result"
```

<sup>[source]</sup>

That's reasonable for the final expression result.

But `display_data` with `text/plain` is ignored.

For example:

```python
display("important diagnostic")
```

may produce display data whose text representation isn't retained.

Whether that's desirable depends on Kerno's output contract.

I'd probably preserve generic display MIME data rather than discard it.

---

## 12. `clear_output` is explicitly unsupported

The comment says:

```text
clear_output, etc. — ignored for now
```

<sup>[source]</sup>

This means interactive notebook behavior isn't faithfully reproduced.

For an execution engine, that's acceptable.

For a notebook-compatible environment, eventually you need:

```text
clear_output(wait=True)
```

semantics.

Otherwise a cell that progressively updates a display can produce a very different result in Kerno.

---

## 13. The communication integration is clean

This is important in light of the previous audit.

`output.py` handles:

```text
comm_msg
```

inline:

```text
IOPUB
 │
 ▼
collect()
 │
 ├── normal output
 │
 └── comm_msg
       │
       ▼
   _comm_handler
```

<sup>[source]</sup>

Therefore the architecture really does implement the single-reader pattern we wanted.

This means my previous P0 concern should be refined:

> The **IOPUB reader race is solved inside the collector**.

The remaining issue is the **global handler ownership model**, not competing IOPUB readers.

---

## 14. But `_comm_handler` is still global

We have:

```python
_comm_handler: Optional["callable"] = None
```

and:

```python
set_comm_handler(handler)
```

<sup>[source]</sup>

This remains a real concurrency concern.

Imagine:

```text
Kernel A
   │
   └── collector → global handler A

Kernel B
   │
   └── collector → global handler B
```

The second:

```python
set_comm_handler(handler_B)
```

replaces the first.

Then:

```text
Kernel A comm_msg
      │
      ▼
handler B
```

could occur.

The lock prevents simultaneous IOPUB reads, but **does not provide handler isolation between kernels**.

---

## 15. The correct solution is to make the handler per collector/client

Instead of:

```python
collect(kc, msg_id, ...)
```

with a global:

```text
_comm_handler
```

I'd prefer:

```python
collect(
    kc,
    msg_id,
    ...,
    comm_handler=handler,
)
```

Then:

```text
Kernel A
  │
  ▼
collect(...)
  │
  └── handler_A

Kernel B
  │
  ▼
collect(...)
  │
  └── handler_B
```

No global mutable state.

That is a much safer design.

---

## 16. The same applies to `stream()`

`stream()` also reads:

```text
IOPUB
```

under the same global lock.

Good.

But it uses the same global:

```text
_comm_handler
```

So it has the same identity problem.

The clean API should be:

```python
stream(..., comm_handler=handler)
```

---

## 17. The collector currently doesn't verify message ownership

This is a major Jupyter protocol question.

The function receives:

```python
msg_id
```

but doesn't visibly filter incoming IOPUB messages by the execution request's parent message ID.

It simply processes:

```python
msg = kc.get_iopub_msg(...)
```

and waits for an `idle`.

That means the collector assumes the associated kernel connection is sufficiently isolated.

If multiple executions are in flight on the same kernel client, messages could potentially become ambiguous.

The safer invariant is:

```text
parent_header.msg_id == requested_msg_id
```

for execution-associated messages.

---

## 18. This matters enormously for concurrency

Suppose:

```text
execute A
execute B
```

are submitted before A completes.

IOPUB can contain:

```text
A output
B output
A output
B output
A idle
B idle
```

A collector that only looks for:

```text
idle
```

could terminate at the wrong idle.

Kerno therefore needs an explicit invariant:

> **One active execution per kernel**, or message correlation by parent ID.

If the runtime guarantees one cell at a time, that's fine.

If it doesn't, this becomes a P0 correctness issue.

---

## 19. The likely intended model is one active cell per kernel

Given the kernel pool architecture, this is probably the intended model:

```text
Kernel instance
     │
     └── one active execution
```

rather than:

```text
Kernel instance
     │
     ├── cell A
     ├── cell B
     └── cell C
```

If that's the design invariant, it should be explicitly documented and enforced.

For example:

```text
KernelRuntime
    execution_lock
         │
         ▼
    execute(cell)
         │
         ▼
       idle
         │
         ▼
    release lock
```

That would make the output collector's assumptions formally safe.

---

## 20. `stream()` is useful but has a subtle semantic difference

`collect()` accumulates:

```text
stdout
stderr
images
displays
result
error
```

while:

```python
stream()
```

yields:

```text
stdout
stderr
error
done
```

<sup>[source]</sup>

So `stream()` isn't a streaming version of `CellOutput`.

It's a **streaming text/error event interface**.

That's okay, but the naming/documentation should make that explicit.

---

## 21. `stream()` also ignores display messages

The `stream()` match handles:

```text
stream
error
comm_msg
status
```

but not:

```text
display_data
execute_result
```

<sup>[source]</sup>

So:

```python
stream(...)
```

will not expose images/HTML/results.

Again, that's a design choice, but it should be stated.

---

## 22. A stronger output event model would unify both APIs

Instead of two separate semantic models:

```text
collect → CellOutput
stream  → tuple[str, str]
```

I'd introduce:

```text
OutputEvent
├── type
├── execution_id
├── timestamp
├── payload
└── final
```

For example:

```text
STREAM stdout
DISPLAY image
RESULT value
ERROR exception
COMM event
STATUS idle
```

Then:

```text
stream()
    │
    ▼
OutputEvent sequence
```

and:

```text
collect()
    │
    ▼
reduce(OutputEvent[])
    │
    ▼
CellOutput
```

That would eliminate duplicated protocol parsing.

---

## 23. The resulting architecture becomes much cleaner

```text
                 Jupyter IOPUB
                       │
                       ▼
                OutputCollector
                       │
                       ▼
                  OutputEvent
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   CellOutput       KernoComm      Stream API
        │              │              │
        ▼              ▼              ▼
    agent loop     telemetry/UI    live client
```

This is probably the architectural refactor I'd prioritize before adding more features.

---

## 24. Revised audit status

###  Strong

- Single IOPUB reader coordination.
- Mid-cell cancellation.
- Kernel interruption on timeout.
- Correct `idle` terminal condition.
- Structured error conversion.
- ANSI traceback cleanup.
- Inline communication dispatch.
- Separate `collect()` and `stream()` APIs.
- Handler exceptions don't kill collection.

###  Needs hardening

- Global `_comm_handler`.
- No explicit parent-message correlation visible.
- Limited MIME support.
- `clear_output` ignored.
- `stream()` doesn't represent display/result messages.
- Generic display text can be lost.
- Output event model is duplicated.

###  Verify before claiming concurrent-kernel safety

The most important question now is:

> **Does Kerno enforce one active execution per kernel, or can a single kernel have multiple outstanding `execute()` requests?**

If **one execution per kernel is guaranteed**, the current collector architecture is substantially safer.

If **multiple executions are possible**, the collector needs parent-message correlation before we can consider it correct.

---

## Next: `KernelRuntime`

We now have enough evidence to go one level higher.

The next audit should trace the complete execution path:

```text
Agent
  ↓
MultiAgentLoop
  ↓
KernelRuntime.execute()
  ↓
KernelClient.execute()
  ↓
OutputCollector.collect()
  ↓
IOPUB
  ↓
CellOutput
  ↓
Budget / timeout / cancellation
```

That will let us answer the most important question for the whole repository:

> **Is a Kerno cell execution actually a well-defined, cancellable, budgeted transaction from submission through kernel termination and result collection?**

That is the next architectural gate.

---

## `kerno/kernel/runtime.py`

This is the critical layer. After inspecting the actual branch implementation, the execution path is:

```text
Agent / Loop
    ↓
KernelRuntime.execute()
    ↓
Jupyter KernelClient.execute()
    ↓
OutputCollector.collect()
    ↓
IOPUB
    ↓
CellOutput
    ↓
timeout / cancellation / recovery
```

The implementation is **substantially mature**, especially around timeout escalation, kernel generations, health state, and telemetry. But there are several important concurrency and lifecycle issues that should be resolved before calling this a production-grade execution primitive. <sup>[source]</sup>

---

## 1. The basic execution transaction is well designed

`execute()` does:

```text
assert kernel alive
      ↓
create telemetry span
      ↓
submit code
      ↓
state = BUSY
      ↓
collect output
      ↓
state = READY
      ↓
record duration/errors/metrics
      ↓
return CellOutput
```

That is the right high-level abstraction.

The kernel runtime therefore exposes a clean contract:

```python
output = runtime.execute(code)
```

rather than forcing callers to understand:

- Jupyter `KernelClient`
- IOPUB
- message IDs
- idle messages
- timeout interrupts
- output parsing.

That's exactly what a runtime abstraction should do.

---

## 2. Startup lifecycle is straightforward

`start()` transitions:

```text
CLOSED
  ↓
STARTING
  ↓
KernelManager
  ↓
KernelClient
  ↓
start_channels()
  ↓
wait_for_ready()
  ↓
READY
```

<sup>[source]</sup>

This is good because the runtime doesn't advertise itself as ready until the kernel has passed `wait_for_ready()`.

The startup timeout is configurable:

```python
startup_timeout: float = 30.0
```

which is sensible.

---

## 3. But startup failure leaves lifecycle cleanup questionable

Suppose:

```text
start_kernel()
    succeeds

start_channels()
    succeeds

wait_for_ready()
    FAILS
```

The method raises, but the code doesn't visibly perform:

```text
stop_channels()
shutdown_kernel()
```

in a failure cleanup path.

That can leave a partially initialized `KernelManager`/process around.

A safer implementation is:

```text
STARTING
   │
   ├── success → READY
   │
   └── exception
         ↓
      cleanup
         ↓
       DEAD/CLOSED
```

This is a relatively small but important lifecycle hardening.

---

## 4. `shutdown()` is appropriately explicit

The method:

```python
self._state = KernelRuntimeState.CLOSED
```

then:

```text
stop_channels()
     ↓
shutdown_kernel()
```

<sup>[source]</sup>

The `now` argument is useful:

```python
shutdown(now=False)
```

because callers can choose graceful versus immediate shutdown.

One improvement:

> Set `CLOSED` only after cleanup succeeds, or distinguish `CLOSING` from `CLOSED`.

Currently the runtime declares itself closed before the underlying process/channel cleanup completes.

That's usually acceptable, but a richer state machine would make lifecycle races easier to diagnose.

---

## 5. `interrupt()` is intentionally soft

```text
interrupt()
   ↓
INTERRUPTING
   ↓
interrupt_kernel()
   ↓
READY
```

<sup>[source]</sup>

The good part is that the implementation already has the concept of a timeout escalation ladder.

But there's a subtle correctness problem:

## `interrupt()` immediately says `READY`

After:

```python
self._km.interrupt_kernel()
```

the code immediately executes:

```python
self._state = KernelRuntimeState.READY
```

That doesn't prove the kernel has actually returned to `idle`.

The real sequence is:

```text
interrupt request
      ≠
execution finished
```

A more accurate state machine is:

```text
BUSY
 ↓
INTERRUPTING
 ↓
WAITING_FOR_IDLE
 ↓
READY
```

This matters if another execution is submitted immediately after an interrupt.

---

## 6. The timeout escalation ladder is a strong feature

This is one of the best parts of the implementation.

The documented strategy is:

```text
timeout
   ↓
soft interrupt
   ↓
grace period
   ↓
hard process termination
   ↓
restart
```

<sup>[source]</sup>

That is much better than:

```text
timeout → return error → leave kernel running
```

The latter creates orphaned computation.

Kerno is clearly trying to enforce:

> A timed-out execution cannot silently continue forever.

That's a strong runtime invariant.

---

## 7. But `_escalate_timeout()` blocks the caller

The escalation function does:

```python
time.sleep(grace_s)
```

with the default:

```text
2 seconds
```

then potentially waits another:

```text
5 seconds
```

for process termination. <sup>[source]</sup>

Therefore:

```text
120 s execution timeout
       +
2 s grace
       +
up to 5 s kill wait
```

means the caller may not get its final `CellOutput` until considerably after the nominal timeout.

That's not necessarily wrong.

But Kerno should distinguish:

```text
execution timeout
```

from:

```text
recovery duration
```

in telemetry.

For example:

```text
execution_timeout = 120s
interrupt_grace = 2s
kill_wait = 5s
total_recovery = 7s
```

---

## 8. The biggest issue: restart happens after hard kill

The code does:

```text
proc.kill()
proc.wait()
restart()
```

<sup>[source]</sup>

Conceptually correct.

But `KernelManager.restart_kernel()` behavior depends on the underlying Jupyter client/provisioner state.

After manually killing the process, the runtime should ensure that the manager's state and channels are still valid before invoking restart.

This deserves an integration test:

```text
execute(infinite_loop)
        ↓
timeout
        ↓
SIGINT
        ↓
SIGKILL
        ↓
restart
        ↓
wait_for_ready
        ↓
execute("1 + 1")
        ↓
2
```

That is a **must-have recovery test**.

---

## 9. Generation tracking is excellent

This is a particularly good design:

```python
self._generation += 1
```

on restart. <sup>[source]</sup>

So:

```text
kernel_id = A
generation = 1
```

becomes:

```text
kernel_id = A
generation = 2
```

after restart.

This solves a subtle observability problem.

Without generation:

```text
kernel-42
```

could represent:

```text
process #1
process #2
process #3
```

with no way to distinguish them.

With generation:

```text
kernel-42 / generation-1
kernel-42 / generation-2
kernel-42 / generation-3
```

execution traces become much more reliable.

---

## 10. Sticky `DEAD` is also a strong improvement

The `state` property deliberately makes `DEAD` sticky:

```text
process dies
    ↓
state = DEAD
    ↓
future state reads
    ↓
still DEAD
```

until an explicit restart.

<sup>[source]</sup>

That's good.

Otherwise a race could produce:

```text
process killed
      ↓
poll() hasn't updated yet
      ↓
state says READY
```

which is dangerous for a kernel pool.

This is exactly the kind of defensive state management an execution runtime needs.

---

## 11. However, `is_alive` and `state` have different semantics

`is_alive`:

```python
return bool(self._km and self._km.is_alive())
```

while `state` has sticky lifecycle semantics.

Therefore it's possible to observe:

```text
state == DEAD
is_alive == True
```

briefly if the underlying process hasn't been observed dead yet.

That's intentional for sticky death, but callers need to know which property is authoritative.

I'd document:

> `state` is the runtime's logical lifecycle state; `is_alive` is the underlying process liveness observation.

---

## 12. The most important concurrency issue: `execute()` has no execution lock

This is the biggest finding in this file.

There is no visible:

```python
threading.Lock()
```

around:

```python
self._kc.execute(...)
collect(...)
```

Therefore two threads could theoretically do:

```text
Thread A
  ↓
execute(A)

Thread B
  ↓
execute(B)
```

against the same `KernelRuntime`.

Then:

```text
Kernel
 │
 ├── execute A
 └── execute B
```

could overlap.

This directly connects to the concern from `output.py`.

If Kerno's architectural invariant is:

> **one active execution per kernel**

then that invariant needs to be enforced here.

Not merely assumed.

---

## 13. The correct fix is an execution lock

Conceptually:

```python
with self._execution_lock:
    msg_id = self._kc.execute(...)
    output = collect(...)
```

Then:

```text
KernelRuntime
     │
 execution_lock
     │
 ┌───┴────┐
 │        │
 A waits  B waits
 │
 ▼
execute A
 │
 ▼
idle
 │
 ▼
release
 │
 ▼
execute B
```

That makes the output collector's current assumptions safe.

---

## 14. `stream_execute()` has the same issue

`stream_execute()` does:

```python
msg_id = self._kc.execute(code)
...
yield from stream(...)
```

<sup>[source]</sup>

It also has no execution lock.

This is actually trickier because the generator holds the execution open across multiple `yield`s.

The lock must therefore remain held for the lifetime of the generator:

```text
stream_execute()
      │
      ▼
 acquire
      │
      ▼
 execute
      │
      ▼
 yield events
      │
      ▼
 done/error/cancel
      │
      ▼
 release
```

A normal `with` surrounding only the `execute()` call wouldn't be enough.

---

## 15. `_cell_count` is not concurrency-safe either

`execute()` records:

```python
self._cell_count + 1
```

then later increments:

```python
self._cell_count += 1
```

<sup>[source]</sup>

With concurrent calls:

```text
A reads 7
B reads 7
```

both could report:

```text
cell.num = 8
```

So the execution lock also solves cell numbering.

---

## 16. `stream_execute()` increments the counter before completion

There's another semantic difference.

Normal:

```text
execute()
   ↓
collect
   ↓
if not silent:
    cell_count += 1
```

Streaming:

```text
stream_execute()
   ↓
cell_count += 1
   ↓
stream
```

So a failed/cancelled streaming execution still increments the count.

Maybe that's intentional:

> "number of submitted cells"

rather than:

> "number of completed cells."

But then the property should be named accordingly.

I'd separate:

```text
cells_submitted
cells_completed
cells_failed
cells_cancelled
```

if telemetry matters.

---

## 17. `silent` affects telemetry semantics

This code:

```python
if not silent:
    self._cell_count += 1
    self._metrics.record_cell(...)
```

means silent executions aren't counted.

But `execute_silent()` is used internally by:

```text
memory_mb
```

and potentially other infrastructure.

That's sensible if the metric is intended to represent user-facing cell execution.

However:

```text
cells_executed
```

currently doesn't mean literally every execution.

It means roughly:

> non-silent executions counted by this runtime.

That naming should be clarified.

---

## 18. `memory_mb` is a clever but expensive implementation

It runs:

```python
import psutil, os
print(psutil.Process(os.getpid()).memory_info().rss / 1e6)
```

inside the kernel. <sup>[source]</sup>

This gives memory usage of the **kernel process**, which is exactly what you want.

But it means every call to:

```python
runtime.memory_mb
```

is itself a kernel execution.

So:

```text
memory_mb
   ↓
execute_silent()
   ↓
Jupyter execute
   ↓
IOPUB
   ↓
collect
```

That's relatively expensive.

For periodic telemetry, the runtime should eventually expose process metrics from the host side instead.

---

## 19. `memory_mb` also depends on `psutil`

If `psutil` isn't installed inside the kernel environment:

```text
memory_mb
   ↓
ImportError
   ↓
CellError
   ↓
execute_silent()
   ↓
""
   ↓
0.0
```

The method eventually returns:

```text
0.0
```

That conflates:

```text
actual memory = 0
```

with:

```text
measurement failed
```

A better API would be:

```text
Optional[float]
```

or raise a dedicated telemetry error.

---

## 20. `execute_silent()` hides kernel errors

It does:

```python
output = self.execute(...)
return output.stdout.strip()
```

If the execution fails, it returns the stdout regardless.

So:

```text
execute_silent("bad code")
```

doesn't necessarily raise.

That can be useful for internal probes, but dangerous for callers expecting:

```python
result = runtime.execute_silent(...)
```

to mean successful execution.

I'd define explicit semantics:

```text
execute_silent()
    = execute but don't display/count output

execute_checked()
    = execute and raise on CellError
```

or make `execute_silent()` raise on `output.has_error`.

---

## 21. `reset_namespace()` relies on IPython `%reset`

```python
self.execute("%reset -f", ...)
```

<sup>[source]</sup>

That's fine for the default Python/IPython kernel.

But `KernelRuntime` accepts:

```python
kernel_name="..."
```

which suggests other Jupyter kernels may be supported.

Then `%reset -f` is not necessarily portable.

Therefore:

> `KernelRuntime` is currently more Python/IPython-specific than its generic Jupyter abstraction suggests.

This should either be documented or abstracted.

---

## 22. `namespace` also assumes Python-specific semantics

It calls:

```python
get_snapshot(self._kc)
```

and `inspect()` calls:

```python
get_object_detail(...)
```

Those are presumably Python-oriented introspection facilities.

So the runtime should probably distinguish:

```text
Jupyter kernel transport
```

from:

```text
Python kernel capabilities
```

Architecture:

```text
KernelRuntime
├── generic Jupyter execution
│
└── PythonKernelFeatures
    ├── namespace
    ├── inspect
    ├── reset
    └── memory
```

That would make the abstraction cleaner.

---

## 23. Telemetry integration is strong

Every execution gets:

```text
kernel.id
kernel.generation
cell.num
cell.code_preview
cell.silent
```

<sup>[source]</sup>

and then:

```text
cell.duration_ms
cell.had_error
cell.output_bytes
cell.n_images
```

This is exactly what an agent runtime needs for observability.

The generation field is particularly valuable after restarts.

---

## 24. But `code_preview` is potentially sensitive

The tracer stores:

```python
code[:80].replace("\n", " ")
```

<sup>[source]</sup>

That means source code is being placed into telemetry.

For generic infrastructure this can leak:

```text
API keys
passwords
tokens
PII
SQL
private prompts
```

even within the first 80 characters.

I would change this to an opt-in feature:

```text
trace_code_preview = false
```

and otherwise record:

```text
code_length
code_hash
```

For example:

```text
cell.code_bytes = 482
cell.code_sha256 = ...
```

Much safer.

---

## 25. Error telemetry has a similar privacy concern

The runtime records:

```python
span.set("error.evalue", output.error.evalue[:200])
```

<sup>[source]</sup>

Exception messages can contain:

```text
file paths
database URLs
user data
credentials
query fragments
```

So telemetry should eventually support redaction.

---

## 26. The execution transaction is not fully atomic

Consider:

```text
execute()
   │
   ├── kernel executes
   │
   ├── output collection
   │
   ├── timeout
   │
   ├── interrupt
   │
   └── restart
```

The runtime returns a `CellOutput`, but it doesn't appear to expose a unified execution lifecycle record such as:

```text
Execution
├── execution_id
├── kernel_id
├── generation
├── submitted_at
├── started_at
├── completed_at
├── status
├── timeout
├── cancellation
├── restart
└── output
```

That would make the runtime much easier to reason about.

---

## 27. This is the abstraction I recommend

Introduce:

```text
ExecutionRecord
```

with:

```text
execution_id
kernel_id
generation
cell_number
status
started_at
completed_at
duration
timeout
cancelled
interrupted
restarted
output
error
```

Then:

```text
KernelRuntime.execute()
        │
        ▼
ExecutionRecord
        │
 ┌──────┼─────────┐
 ▼      ▼         ▼
metrics trace    loop
```

This would unify the runtime's lifecycle and observability.

---

## 28. Final runtime state machine

The current implementation is roughly:

```text
                    ┌───────────────┐
                    │               │
                    ▼               │
CLOSED → STARTING → READY → BUSY ───┘
                      │       │
                      │       ▼
                      │  INTERRUPTING
                      │       │
                      │       ▼
                      │     READY
                      │
                      ▼
                    DEAD
```

I'd make the target state machine:

```text
                    ┌──────────────┐
                    │              │
                    ▼              │
CLOSED → STARTING → READY → BUSY ──┘
                      │       │
                      │       ▼
                      │ INTERRUPTING
                      │       │
                      │       ▼
                      │ WAITING_IDLE
                      │       │
                      │       ▼
                      │     READY
                      │
                      ▼
                    DEAD
                      │
                      ▼
                  RESTARTING
                      │
                      ▼
                    READY
```

And enforce:

```text
ONE ACTIVE EXECUTION PER KERNEL
```

with an execution lock.

---

## 29. Current verdict

| Area | Verdict |
|---|---|
| Kernel startup |  Good |
| Kernel shutdown |  Good |
| Timeout handling |  Strong |
| Hard timeout escalation |  Strong concept |
| Restart generation |  Excellent |
| Sticky DEAD state |  Excellent |
| Telemetry |  Strong |
| Cancellation |  Strong |
| Output integration |  Strong |
| Execution concurrency |  Needs explicit lock |
| Interrupt state |  Too optimistic |
| Startup cleanup |  Needs hardening |
| Generic Jupyter support |  Actually Python/IPython-oriented |
| Telemetry privacy |  Needs redaction/configuration |
| Execution lifecycle model |  Should be formalized |

---

## 30. The key architectural conclusion

After inspecting:

```text
runtime.py
output.py
channel.py
isolation.py
```

the architecture is now much clearer:

```text
                         KERNO
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
         Runtime        Isolation    Communication
             │             │             │
             ▼             ▼             ▼
         Jupyter        SharedMemory    IOPUB Comm
         Kernel             │             │
             │              │             │
             └──────────────┼─────────────┘
                            ▼
                       Agent Loop
```

This is a **real execution substrate**, not merely a package of convenience functions.

The remaining work is primarily about making its implicit invariants explicit:

> **one execution per kernel, correlated messages, transactional state, bounded communication, and formal execution lifecycle.**

Those are the things that turn a good prototype into a robust runtime.

### Next audit target: `kerno/kernel/pool.py`

That is now the logical next layer:

```text
KernelRuntime
      ↓
KernelPool
      ↓
MultiAgentLoop
```

The pool will tell us whether the runtime's new `DEAD`/`generation`/restart semantics are actually handled correctly when kernels are **allocated, released, reused, expired, killed, and recovered**. <sup>[source]</sup>

---

## `kerno/kernel/pool.py`

This file exposes the **resource-management layer** above `KernelRuntime`. The overall design is good, but the audit finds several important lifecycle/concurrency bugs that are more serious than the issues in `runtime.py`.

The intended architecture is:

```text
                    KernelPool
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   AVAILABLE        ACQUIRED         RESETTING
        │               │               │
        ▼               ▼               ▼
     task A           task B          cleanup
        │
        ▼
   KernelRuntime
```

The pool is responsible for:

- prewarming,
- acquisition,
- release,
- reset,
- retirement,
- replacement,
- overflow,
- health monitoring,
- task-to-kernel ownership.

That separation is exactly right. <sup>[source]</sup>

---

## 1. The core state model is good

The pool defines:

```text
WARMING
AVAILABLE
ACQUIRED
RESETTING
DEAD
```

<sup>[source]</sup>

That's a sensible state machine.

The important distinction is:

```text
KernelRuntime state
        ≠
Pool ownership state
```

For example:

```text
Pool:     ACQUIRED
Runtime:  READY
```

means:

> The kernel is owned by a task and currently ready to execute.

Whereas:

```text
Pool:     RESETTING
Runtime:  READY
```

means:

> The kernel is not available to users because pool cleanup is in progress.

That is a strong abstraction.

---

## 2. `PooledKernel` correctly adds pool-level lifecycle limits

Each kernel has:

```text
MAX_CELLS    = 200
MAX_LIFETIME = 3600 s
MAX_MEMORY   = 4096 MB
```

and `is_expired` checks all three. <sup>[source]</sup>

Conceptually:

```text
             kernel
                │
       ┌────────┼────────┐
       ▼        ▼        ▼
     cells     age     memory
       │        │        │
       └────────┼────────┘
                ▼
             expired
```

This is exactly the kind of containment mechanism needed for long-running agent systems.

---

## 3. But the memory limit has a semantic problem

`is_expired` calls:

```python
memory = self._safe_memory()
```

and `_safe_memory()` returns:

```python
0.0
```

when measurement fails. <sup>[source]</sup>

That means:

```text
memory measurement failed
        ↓
0 MB
        ↓
kernel considered healthy
```

This is unsafe.

If the monitoring mechanism fails, the system should not silently conclude:

> memory usage is zero.

Better:

```text
memory = UNKNOWN
```

and then choose an explicit policy:

```text
UNKNOWN → don't expire
```

or, for safety:

```text
UNKNOWN → mark health degraded
```

but never pretend it is `0`.

---

## 4. The first major bug: acquisition can create duplicate replacement kernels

Look at:

```python
pk = self._available.get(...)
```

Then:

```python
if not pk.is_healthy:
    pk.runtime.shutdown(now=True)
    pk.state = DEAD
    pk = self._create_kernel()
```

<sup>[source]</sup>

The dead kernel remains inside:

```text
self._all
```

because acquisition doesn't call `_retire()`.

So:

```text
_all:
  k-0001 DEAD
  k-0002 AVAILABLE
```

and the dead kernel is still counted in pool inventory.

Eventually you can accumulate stale `PooledKernel` objects in `_all`.

This should instead be:

```text
unhealthy available kernel
       ↓
_retire(pk, replace=False)
       ↓
create replacement
```

or otherwise remove it from `_all`.

---

## 5. More serious: `acquire()` can exceed `max_overflow`

The overflow condition is:

```python
if self.overflow and len(self._active) < self.max_overflow:
    pk = self._create_kernel()
```

<sup>[source]</sup>

But `max_overflow` is compared against:

```text
active kernels
```

rather than:

```text
overflow kernels
```

Suppose:

```text
size = 3
max_overflow = 10
```

You could have:

```text
3 base kernels
+ 10 active overflow kernels
```

which is already 13 total.

But the condition is not actually expressing:

> maximum of 10 overflow kernels.

It's expressing:

> permit creation while fewer than 10 kernels are active.

Those are very different policies.

---

## 6. Worse: overflow kernels are not tracked as overflow

`PooledKernel` doesn't contain:

```text
is_overflow
```

or:

```text
capacity_origin
```

Therefore after:

```text
size = 3
overflow = true
```

the pool cannot distinguish:

```text
base kernel
```

from:

```text
overflow kernel
```

That makes controlled overflow retirement difficult.

I'd add:

```python
is_overflow: bool = False
```

or better:

```text
pool_class = BASE | OVERFLOW
```

---

## 7. The pool can create an unbounded number of replacement threads

`_retire()` does:

```python
threading.Thread(
    target=self._warm_one,
    daemon=True
).start()
```

<sup>[source]</sup>

And `_warm_one()` creates a kernel.

The monitor can retire multiple kernels in one pass:

```text
k1 expired → replacement thread
k2 expired → replacement thread
k3 expired → replacement thread
...
```

Meanwhile other failure paths can also call `_retire()`.

There's no central capacity controller.

A robust pool should maintain:

```text
desired_capacity
current_capacity
pending_creations
```

and ensure:

```text
current + pending <= target
```

---

## 8. The second major bug: release/reset race

This is probably the most important pool-level issue.

`release()` removes the kernel from `_active`:

```python
pk = self._active.pop(task_id, None)
```

then starts:

```python
threading.Thread(
    target=self._soft_reset,
    args=(pk,),
    daemon=True
).start()
```

<sup>[source]</sup>

The reset happens asynchronously.

That's fine **if the kernel remains inaccessible until reset finishes**.

And currently it isn't placed back into `_available` until `_soft_reset()` finishes.

So far, good.

But now consider:

```text
release(task A)
      ↓
soft-reset thread starts
      ↓
pool.shutdown()
```

The shutdown operation can race with the reset thread.

The reset thread might then execute:

```text
reset_namespace()
bootstrap()
_available.put(pk)
```

after shutdown has supposedly completed.

That could resurrect a supposedly closed pool.

---

## 9. `shutdown()` doesn't join reset/creation/monitor threads

`shutdown()` does:

```python
self._running = False
```

and shuts down the kernels currently in `_all`. <sup>[source]</sup>

But background threads include:

```text
_monitor
_warm_one
_soft_reset
_hard_reset
```

None are tracked comprehensively or joined.

Therefore:

```text
shutdown()
   │
   ├── returns
   │
   └── background reset still running
```

is possible.

This violates a desirable shutdown invariant:

> After `KernelPool.shutdown()` returns, no pool-managed work should be able to create, reset, enqueue, or replace kernels.

---

## 10. `_running` is not sufficient synchronization

The monitor checks:

```python
while self._running:
```

but `_soft_reset()` and `_hard_reset()` don't check `_running` before putting kernels into `_available`.

So:

```text
shutdown()
   ↓
_running = False
```

doesn't stop:

```text
soft_reset
   ↓
_available.put(pk)
```

This is a concrete shutdown race.

Every background mutation should either:

```text
check pool active state
```

or be serialized through a pool lifecycle controller.

---

## 11. Another major issue: `release()` doesn't handle unknown reasons

The documented reasons are:

```text
complete
error
timeout
oom
```

<sup>[source]</sup>

But there is no:

```python
case _:
    raise ValueError(...)
```

So:

```python
pool.release(task_id, reason="banana")
```

will:

1. remove the kernel from active,
2. increment `tasks_served`,
3. clear ownership,
4. do nothing else.

The kernel becomes orphaned:

```text
not active
not available
not resetting
not dead
```

That's a real state corruption bug.

Add:

```python
case _:
    raise ValueError(...)
```

before mutating ownership, or validate `reason` first.

---

## 12. `release()` has another problem with failed reset

For:

```text
complete
```

the pool launches `_soft_reset()`.

If it fails:

```python
except Exception:
    self._hard_reset(pk)
```

Good.

But `_hard_reset()` can also fail:

```python
except Exception:
    self._retire(pk)
```

which starts a replacement thread.

This produces:

```text
release
  ↓
soft reset
  ↓
failure
  ↓
hard reset
  ↓
failure
  ↓
retire
  ↓
replacement thread
```

That's a reasonable recovery strategy.

The problem is that **the task caller gets no indication whatsoever that release triggered a replacement**.

That should at least be reflected in pool telemetry.

---

## 13. `restart(task_id)` is actually a strong API

This is one of the better parts:

```python
pk.runtime.restart()
```

while keeping:

```text
same PooledKernel
same KernelRuntime object
same task ownership
```

and only incrementing runtime generation. <sup>[source]</sup>

That's useful for agents.

For example:

```text
Agent
 │
 ├── has runtime reference R
 │
 ├── kernel becomes corrupted
 │
 ├── pool.restart(task)
 │
 └── R remains valid
```

That's much better than replacing the Python object behind the task's back.

---

## 14. But `restart()` doesn't reset pool lifecycle metadata

After restart:

```text
created_at
tasks_served
```

remain unchanged.

That's potentially correct if these represent the **physical pooled kernel lifetime**.

But then:

```text
runtime.generation
```

represents process lifetime while:

```text
PooledKernel.created_at
```

represents pool-object lifetime.

These should be explicitly documented.

Otherwise an agent could restart a kernel repeatedly while:

```text
created_at → 59 minutes
```

and then immediately hit:

```text
MAX_LIFETIME
```

even though the underlying process was freshly restarted.

That may actually be desirable for resource churn prevention—but it should be intentional.

---

## 15. `interrupt()` correctly preserves task ownership

This API:

```python
pool.interrupt(task_id)
```

finds the active pooled kernel and calls:

```python
pk.runtime.interrupt()
```

<sup>[source]</sup>

This is exactly the right layering:

```text
Agent cancellation
       ↓
KernelPool.interrupt(task_id)
       ↓
KernelRuntime.interrupt()
       ↓
Jupyter interrupt
```

The important missing piece is what happens **after** the interrupt.

The pool still considers:

```text
state = ACQUIRED
```

and the runtime may optimistically report `READY`.

This is another reason the runtime needs the stronger:

```text
WAITING_FOR_IDLE
```

state proposed earlier.

---

## 16. `health_check()` is excellent for observability

The returned information:

```text
state
alive
generation
cells
uptime
task_id
tasks_served
```

<sup>[source]</sup>

is exactly what an operator needs.

Example:

```json
{
  "k-0002": {
    "state": "ACQUIRED",
    "alive": true,
    "generation": 4,
    "cells": 71,
    "uptime": 1820.2,
    "task_id": "analysis-42",
    "tasks_served": 18
  }
}
```

This is a strong foundation for a future dashboard.

---

## 17. But `stats` is too weak for capacity management

Currently:

```text
available
active
total
active_tasks
```

<sup>[source]</sup>

Missing:

```text
warming
resetting
dead
overflow
pending_creation
expired
unhealthy
```

For a resource pool, I'd want:

```json
{
  "capacity": 3,
  "available": 2,
  "active": 1,
  "warming": 0,
  "resetting": 0,
  "overflow": 0,
  "pending": 0,
  "dead": 0
}
```

This would make pool behavior much easier to diagnose.

---

## 18. `_monitor_loop()` has a hidden policy problem

It checks every 30 seconds:

```text
AVAILABLE + expired → retire
ACQUIRED + >1 hour → warning
```

<sup>[source]</sup>

But an acquired kernel that exceeds:

```text
MAX_LIFETIME
```

is **not retired**.

It is only warned about.

So the lifecycle policy is inconsistent:

```text
AVAILABLE:
    lifetime hard limit

ACQUIRED:
    lifetime soft warning
```

That may be intentional because killing an active task is dangerous.

If so, define two separate limits:

```text
MAX_IDLE_LIFETIME
MAX_TASK_LIFETIME
```

rather than using one `MAX_LIFETIME` for both.

---

## 19. The monitor also doesn't enforce memory/cell limits on acquired kernels

The same issue applies to:

```text
MAX_MEMORY
MAX_CELLS
```

An active task can exceed:

```text
4096 MB
```

and the monitor only checks:

```text
acquired for > 1 hour
```

It doesn't actually enforce memory/cell limits while acquired.

This means:

> lifecycle limits are primarily **between-task retirement policies**, not hard runtime limits.

That distinction should be made explicit.

---

## 20. `is_expired` uses `cells_executed`

From the previous runtime audit, `cells_executed` is not necessarily literally every execution because silent executions aren't counted.

Therefore:

```text
MAX_CELLS = 200
```

may not mean:

> kernel has executed 200 cells.

It means closer to:

> kernel has executed 200 counted/non-silent cells.

That creates an accounting mismatch.

I'd fix this at the runtime layer by maintaining:

```text
executions_submitted
executions_completed
executions_failed
```

and have pool retirement use the explicit metric.

---

## 21. Bootstrap failure is deliberately nonfatal

`_bootstrap()` does:

```python
output = runtime.execute(...)
```

and if there's an error:

```python
warnings.warn(...)
```

rather than failing the kernel. <sup>[source]</sup>

This is questionable.

If `skills_path` contains mandatory capabilities:

```text
kernel starts
   ↓
skills fail
   ↓
kernel marked AVAILABLE
```

then the pool hands out a kernel that does not satisfy its declared configuration.

For optional skills, that's fine.

For required skills, it should be:

```text
bootstrap failure
      ↓
kernel DEAD
      ↓
replacement
```

I would introduce:

```text
skills_required = True/False
```

---

## 22. Bootstrap reads the entire file synchronously

```python
code = path.read_text()
```

then sends it as one cell.

For a large skill file:

```text
100 KB+
```

the entire file becomes one execution.

That can interact badly with:

- startup timeout,
- output collection,
- timeout recovery,
- cell limits.

Better eventually:

```text
bootstrap manifest
     ↓
load modules
     ↓
verify
     ↓
ready
```

rather than one giant cell.

---

## 23. The biggest architectural issue: queue ownership is not fully atomic

The pool has:

```text
_available Queue
_active dict
_all list
```

with `_lock` around the dictionaries/list.

But the transition:

```text
AVAILABLE
   ↓
Queue.get()
   ↓
ACQUIRED
   ↓
_active[task] = pk
```

is split between queue synchronization and pool locking.

This creates a small but important failure window:

```text
queue.get()
    ↓
process crashes / exception
    ↓
kernel removed from queue
    ↓
never inserted into active
```

The pool loses track of it.

Likewise:

```text
_active.pop()
    ↓
background reset starts
    ↓
thread fails before requeue
```

can lose the kernel.

A stronger design uses a single state transition coordinator.

---

## 24. The pool needs an explicit invariant

The most important invariant should be:

```text
Every PooledKernel is in exactly ONE ownership state:
```

```text
AVAILABLE
ACQUIRED
RESETTING
WARMING
DEAD
```

and:

```text
AVAILABLE  ↔ _available
ACQUIRED   ↔ _active
RESETTING  ↔ reset worker
WARMING    ↔ creation worker
DEAD       ↔ removed
```

Currently `_all` can contain objects that don't correspond cleanly to those ownership structures.

That is the area I'd formalize.

---

## 25. Recommended pool architecture

I'd introduce a central lifecycle controller:

```text
                         KernelPool
                            │
                     PoolController
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
      AVAILABLE          ACQUIRED          RESETTING
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                            ▼
                       PooledKernel
                            │
                            ▼
                      KernelRuntime
```

Every transition goes through:

```text
_transition(pk, FROM, TO)
```

so you can enforce:

```text
AVAILABLE → ACQUIRED
ACQUIRED → RESETTING
RESETTING → AVAILABLE
RESETTING → DEAD
WARMING → AVAILABLE
WARMING → DEAD
```

and reject invalid transitions.

---

## 26. Recommended capacity controller

Instead of spawning replacement threads freely:

```text
_retire()
  ↓
thread(_warm_one)
```

use:

```text
desired_capacity
current_capacity
pending_creations
```

with:

```text
reconcile()
```

conceptually:

```text
if current + pending < desired:
    create

if current > desired:
    retire idle kernels
```

This gives deterministic pool capacity.

---

## 27. Revised severity table

| Finding | Severity |
|---|---|
| Unknown `release(reason)` silently orphaning kernel |  P0 |
| Shutdown races with background reset/replacement |  P0 |
| No explicit one-kernel/one-execution enforcement |  P0 |
| Dead acquired kernel can remain in `_all` |  P1 |
| Overflow accounting incorrect |  P1 |
| Replacement creation not capacity-controlled |  P1 |
| Runtime interrupt state too optimistic |  P1 |
| Bootstrap failure may expose unconfigured kernel |  P1 |
| Memory measurement failure → `0.0` |  P1 |
| Weak pool statistics |  P2 |
| Lifecycle semantics of `created_at` vs generation unclear |  P2 |

---

## 28. The four-layer model is now becoming very clear

We have now audited:

```text
                 MultiAgentLoop
                       │
                       ▼
                  KernelPool
                       │
              ┌────────┴────────┐
              ▼                 ▼
        KernelRuntime       ownership
              │
              ▼
        OutputCollector
              │
              ▼
             IOPUB
              │
              ▼
          KernoComm
```

Each layer has a distinct responsibility:

| Layer | Responsibility |
|---|---|
| `MultiAgentLoop` | agent orchestration |
| `KernelPool` | resource ownership/lifecycle |
| `KernelRuntime` | one kernel execution |
| `OutputCollector` | IOPUB protocol/output |
| `KernoComm` | structured live events |

That's a **very good architectural decomposition**.

The problem isn't the overall architecture.

The problem is that the boundaries aren't yet enforcing all of their invariants.

---

## 29. The most important invariant to establish next

Before continuing into higher-level agent logic, I would lock down this contract:

```text
ONE TASK
   │
   ▼
ONE PooledKernel
   │
   ▼
ONE ACTIVE EXECUTION
   │
   ▼
ONE CORRELATED IOPUB EXECUTION
   │
   ▼
ONE TERMINAL RESULT
   │
   ▼
RESET / RETIRE
   │
   ▼
AVAILABLE
```

If this invariant holds, the rest of Kerno becomes dramatically easier to reason about.

If it doesn't, bugs can cross all four layers.

---

## Next: `kerno/agent/loop.py`

The next audit should move above the infrastructure:

```text
KernelPool
    ↓
MultiAgentLoop
    ↓
Agent
    ↓
turn / tool / observation / decision
```

That is where we'll determine whether Kerno's **actual agent semantics** match the infrastructure underneath it—especially:

- turn boundaries,
- cancellation propagation,
- budget enforcement,
- shared memory,
- agent-to-agent communication,
- failure recovery,
- and whether a failed kernel execution can incorrectly advance an agent's state.

That is the next major architectural gate.

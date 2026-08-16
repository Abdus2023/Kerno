[← Back to index](./README.md) | [Next section →](./09-agent-loop-and-orchestration.md)

## The next audit target

The next file I would inspect is **`kerno/kernel/output.py`**.

That's now the critical junction:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

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

</details>

If `output.py` gets the single-reader, buffering, timeout, `idle`, `comm_msg`, and error semantics right, then the whole **KernelRuntime → KernelPool → KernoComm** stack has a solid foundation.

If it doesn't, the communication correctness problems propagate upward into every agent loop.

---

## [29] USER

Continue 

---

## [30] CHATGPT (gpt-5-6)

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
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/kernel/output.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

## Continue — `kerno/kernel/output.py`

This file is actually **better than the previous communication audit suggested**. The earlier concern about cancellation only being checked between agent turns is no longer applicable at the cell-output layer: `OutputCollector.collect()` explicitly propagates cancellation **mid-cell** by invoking the interrupt callback. <sup>[source]</sup>

That is an important strength.

---

# 1. `output.py` is the sensory boundary

The file's architecture is very clear:

<details>
<summary><strong>💻 Code Block (text) — 17 lines</strong></summary>

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

</details>

The docstring calls this the **"sensory layer"**: everything the kernel says is collected here. <sup>[source]</sup>

That's a good architectural boundary.

---

# 2. The single-reader solution is correct

The most important design decision is:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
IOPUB_LOCK = threading.RLock()
```

</details>

and both `collect()` and `stream()` hold it while consuming IOPUB. <sup>[source]</sup>

This addresses the classic failure mode:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

particularly the dangerous case where the communication listener consumes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
status: idle
```

</details>

before the cell collector sees it.

The resulting symptom would be:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

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

</details>

The current architecture explicitly prevents that. <sup>[source]</sup>

**This is one of the strongest parts of the current Kerno implementation.**

---

# 3. The `RLock` choice is sensible

Using:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
threading.RLock()
```

</details>

rather than a normal `Lock` gives re-entrant behavior.

That matters if future layers call output/communication routines from within code that already holds the IOPUB coordination lock.

It also makes the lock less brittle during refactoring.

---

# 4. Cancellation is genuinely propagated into the kernel

This is important.

Inside the collection loop:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

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

</details>

<sup>[source]</sup>

So cancellation isn't merely:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
"stop waiting for the result"
```

</details>

It is:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
"interrupt the actual running kernel execution"
```

</details>

That's the correct semantic behavior.

---

# 5. Timeout has the same interrupt path

The timeout path does:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

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

</details>

<sup>[source]</sup>

That's also correct.

A common bad implementation is:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
timeout
  ↓
return TimeoutError
  ↓
kernel continues running
```

</details>

which creates an orphaned computation.

Kerno is attempting to avoid that.

---

# 6. But there is still a subtle timeout race

Consider:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
t = 9.99s
cell finishes
       │
       ▼
kernel sends idle
```

</details>

while:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
deadline = 10.00s
```

</details>

The collector receives messages sequentially.

The implementation uses:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
remaining = deadline - time.monotonic()
```

</details>

before calling:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
kc.get_iopub_msg(...)
```

</details>

<sup>[source]</sup>

This is reasonable.

However, a timeout can still occur immediately around the boundary where the kernel has actually finished but the host's wall clock reaches the deadline first.

That's unavoidable in a wall-clock timeout design, but the runtime should make the resulting semantics explicit:

> **Timeout means the collector did not observe terminal completion before the deadline, not necessarily that the kernel computation itself had not completed.**

That distinction matters for diagnostics.

---

# 7. `idle` is correctly treated as the terminal event

The collector terminates only when:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
status.execution_state == "idle"
```

</details>

<sup>[source]</sup>

That's the correct Jupyter execution lifecycle concept.

The resulting state machine is approximately:

<details>
<summary><strong>💻 Code Block (text) — 14 lines</strong></summary>

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

</details>

Good.

---

# 8. Error handling is well structured

The code converts Jupyter errors into:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
CellError
├── ename
├── evalue
└── traceback
```

</details>

and strips ANSI escape sequences from the traceback. <sup>[source]</sup>

That is useful because raw terminal formatting can otherwise pollute logs/UI.

For example:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
\x1b[31mError\x1b[0m
```

</details>

becomes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Error
```

</details>

This is exactly the sort of normalization an execution substrate should perform.

---

# 9. Display handling is intentionally selective

The collector recognizes:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
image/png
text/html
application/json
text/plain
```

</details>

<sup>[source]</sup>

and maps them to structured `CellOutput` fields.

That's a good start.

The model is:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
Jupyter MIME bundle
       │
       ├── image/png → images
       ├── text/html → displays
       ├── application/json → displays
       └── text/plain → result
```

</details>

---

# 10. But MIME handling is incomplete

There are many legitimate Jupyter MIME types:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
image/jpeg
image/svg+xml
text/markdown
application/javascript
application/vnd.vega.v5+json
application/vnd.plotly.v1+json
application/pdf
```

</details>

Kerno currently ignores them.

That's not a correctness bug if the intended scope is narrow, but it means:

> `CellOutput` is currently a normalized subset of Jupyter output, not a complete representation of the Jupyter display protocol.

For an analytics platform, I'd expect at least:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
image/png
image/jpeg
image/svg+xml
text/html
text/markdown
text/plain
application/json
```

</details>

---

# 11. There is a potential data-loss issue with `text/plain`

The code only sets:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
output.result = data["text/plain"]
```

</details>

when:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
msg_type == "execute_result"
```

</details>

<sup>[source]</sup>

That's reasonable for the final expression result.

But `display_data` with `text/plain` is ignored.

For example:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
display("important diagnostic")
```

</details>

may produce display data whose text representation isn't retained.

Whether that's desirable depends on Kerno's output contract.

I'd probably preserve generic display MIME data rather than discard it.

---

# 12. `clear_output` is explicitly unsupported

The comment says:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
clear_output, etc. — ignored for now
```

</details>

<sup>[source]</sup>

This means interactive notebook behavior isn't faithfully reproduced.

For an execution engine, that's acceptable.

For a notebook-compatible environment, eventually you need:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
clear_output(wait=True)
```

</details>

semantics.

Otherwise a cell that progressively updates a display can produce a very different result in Kerno.

---

# 13. The communication integration is clean

This is important in light of the previous audit.

`output.py` handles:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
comm_msg
```

</details>

inline:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

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

</details>

<sup>[source]</sup>

Therefore the architecture really does implement the single-reader pattern we wanted.

This means my previous P0 concern should be refined:

> The **IOPUB reader race is solved inside the collector**.

The remaining issue is the **global handler ownership model**, not competing IOPUB readers.

---

# 14. But `_comm_handler` is still global

We have:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
_comm_handler: Optional["callable"] = None
```

</details>

and:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
set_comm_handler(handler)
```

</details>

<sup>[source]</sup>

This remains a real concurrency concern.

Imagine:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Kernel A
   │
   └── collector → global handler A

Kernel B
   │
   └── collector → global handler B
```

</details>

The second:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
set_comm_handler(handler_B)
```

</details>

replaces the first.

Then:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
Kernel A comm_msg
      │
      ▼
handler B
```

</details>

could occur.

The lock prevents simultaneous IOPUB reads, but **does not provide handler isolation between kernels**.

---

# 15. The correct solution is to make the handler per collector/client

Instead of:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
collect(kc, msg_id, ...)
```

</details>

with a global:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_comm_handler
```

</details>

I'd prefer:

<details>
<summary><strong>💻 Code Block (python) — 6 lines</strong></summary>

```python
collect(
    kc,
    msg_id,
    ...,
    comm_handler=handler,
)
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

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

</details>

No global mutable state.

That is a much safer design.

---

# 16. The same applies to `stream()`

`stream()` also reads:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
IOPUB
```

</details>

under the same global lock.

Good.

But it uses the same global:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_comm_handler
```

</details>

So it has the same identity problem.

The clean API should be:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
stream(..., comm_handler=handler)
```

</details>

---

# 17. The collector currently doesn't verify message ownership

This is a major Jupyter protocol question.

The function receives:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
msg_id
```

</details>

but doesn't visibly filter incoming IOPUB messages by the execution request's parent message ID.

It simply processes:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
msg = kc.get_iopub_msg(...)
```

</details>

and waits for an `idle`.

That means the collector assumes the associated kernel connection is sufficiently isolated.

If multiple executions are in flight on the same kernel client, messages could potentially become ambiguous.

The safer invariant is:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
parent_header.msg_id == requested_msg_id
```

</details>

for execution-associated messages.

---

# 18. This matters enormously for concurrency

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
execute A
execute B
```

</details>

are submitted before A completes.

IOPUB can contain:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
A output
B output
A output
B output
A idle
B idle
```

</details>

A collector that only looks for:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
idle
```

</details>

could terminate at the wrong idle.

Kerno therefore needs an explicit invariant:

> **One active execution per kernel**, or message correlation by parent ID.

If the runtime guarantees one cell at a time, that's fine.

If it doesn't, this becomes a P0 correctness issue.

---

# 19. The likely intended model is one active cell per kernel

Given the kernel pool architecture, this is probably the intended model:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Kernel instance
     │
     └── one active execution
```

</details>

rather than:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Kernel instance
     │
     ├── cell A
     ├── cell B
     └── cell C
```

</details>

If that's the design invariant, it should be explicitly documented and enforced.

For example:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

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

</details>

That would make the output collector's assumptions formally safe.

---

# 20. `stream()` is useful but has a subtle semantic difference

`collect()` accumulates:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
stdout
stderr
images
displays
result
error
```

</details>

while:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
stream()
```

</details>

yields:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
stdout
stderr
error
done
```

</details>

<sup>[source]</sup>

So `stream()` isn't a streaming version of `CellOutput`.

It's a **streaming text/error event interface**.

That's okay, but the naming/documentation should make that explicit.

---

# 21. `stream()` also ignores display messages

The `stream()` match handles:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
stream
error
comm_msg
status
```

</details>

but not:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
display_data
execute_result
```

</details>

<sup>[source]</sup>

So:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
stream(...)
```

</details>

will not expose images/HTML/results.

Again, that's a design choice, but it should be stated.

---

# 22. A stronger output event model would unify both APIs

Instead of two separate semantic models:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
collect → CellOutput
stream  → tuple[str, str]
```

</details>

I'd introduce:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
OutputEvent
├── type
├── execution_id
├── timestamp
├── payload
└── final
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
STREAM stdout
DISPLAY image
RESULT value
ERROR exception
COMM event
STATUS idle
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
stream()
    │
    ▼
OutputEvent sequence
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
collect()
    │
    ▼
reduce(OutputEvent[])
    │
    ▼
CellOutput
```

</details>

That would eliminate duplicated protocol parsing.

---

# 23. The resulting architecture becomes much cleaner

<details>
<summary><strong>💻 Code Block (text) — 14 lines</strong></summary>

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

</details>

This is probably the architectural refactor I'd prioritize before adding more features.

---

# 24. Revised audit status

### 🟢 Strong

- Single IOPUB reader coordination.
- Mid-cell cancellation.
- Kernel interruption on timeout.
- Correct `idle` terminal condition.
- Structured error conversion.
- ANSI traceback cleanup.
- Inline communication dispatch.
- Separate `collect()` and `stream()` APIs.
- Handler exceptions don't kill collection.

### 🟠 Needs hardening

- Global `_comm_handler`.
- No explicit parent-message correlation visible.
- Limited MIME support.
- `clear_output` ignored.
- `stream()` doesn't represent display/result messages.
- Generic display text can be lost.
- Output event model is duplicated.

### 🔴 Verify before claiming concurrent-kernel safety

The most important question now is:

> **Does Kerno enforce one active execution per kernel, or can a single kernel have multiple outstanding `execute()` requests?**

If **one execution per kernel is guaranteed**, the current collector architecture is substantially safer.

If **multiple executions are possible**, the collector needs parent-message correlation before we can consider it correct.

---

# Next: `KernelRuntime`

We now have enough evidence to go one level higher.

The next audit should trace the complete execution path:

<details>
<summary><strong>💻 Code Block (text) — 15 lines</strong></summary>

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

</details>

That will let us answer the most important question for the whole repository:

> **Is a Kerno cell execution actually a well-defined, cancellable, budgeted transaction from submission through kernel termination and result collection?**

That is the next architectural gate.

---

## [31] USER

Continue 

---

## [32] CHATGPT (gpt-5-6)

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
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"class KernelRuntime","topn":20}}
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
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/kernel/runtime.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

# Continue — `kerno/kernel/runtime.py`

This is the critical layer. After inspecting the actual branch implementation, the execution path is:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

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

</details>

The implementation is **substantially mature**, especially around timeout escalation, kernel generations, health state, and telemetry. But there are several important concurrency and lifecycle issues that should be resolved before calling this a production-grade execution primitive. <sup>[source]</sup>

---

## 1. The basic execution transaction is well designed

`execute()` does:

<details>
<summary><strong>💻 Code Block (text) — 15 lines</strong></summary>

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

</details>

That is the right high-level abstraction.

The kernel runtime therefore exposes a clean contract:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
output = runtime.execute(code)
```

</details>

rather than forcing callers to understand:

- Jupyter `KernelClient`
- IOPUB
- message IDs
- idle messages
- timeout interrupts
- output parsing.

That's exactly what a runtime abstraction should do.

---

# 2. Startup lifecycle is straightforward

`start()` transitions:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

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

</details>

<sup>[source]</sup>

This is good because the runtime doesn't advertise itself as ready until the kernel has passed `wait_for_ready()`.

The startup timeout is configurable:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
startup_timeout: float = 30.0
```

</details>

which is sensible.

---

# 3. But startup failure leaves lifecycle cleanup questionable

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

```text
start_kernel()
    succeeds

start_channels()
    succeeds

wait_for_ready()
    FAILS
```

</details>

The method raises, but the code doesn't visibly perform:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
stop_channels()
shutdown_kernel()
```

</details>

in a failure cleanup path.

That can leave a partially initialized `KernelManager`/process around.

A safer implementation is:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

This is a relatively small but important lifecycle hardening.

---

# 4. `shutdown()` is appropriately explicit

The method:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._state = KernelRuntimeState.CLOSED
```

</details>

then:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
stop_channels()
     ↓
shutdown_kernel()
```

</details>

<sup>[source]</sup>

The `now` argument is useful:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
shutdown(now=False)
```

</details>

because callers can choose graceful versus immediate shutdown.

One improvement:

> Set `CLOSED` only after cleanup succeeds, or distinguish `CLOSING` from `CLOSED`.

Currently the runtime declares itself closed before the underlying process/channel cleanup completes.

That's usually acceptable, but a richer state machine would make lifecycle races easier to diagnose.

---

# 5. `interrupt()` is intentionally soft

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
interrupt()
   ↓
INTERRUPTING
   ↓
interrupt_kernel()
   ↓
READY
```

</details>

<sup>[source]</sup>

The good part is that the implementation already has the concept of a timeout escalation ladder.

But there's a subtle correctness problem:

## `interrupt()` immediately says `READY`

After:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._km.interrupt_kernel()
```

</details>

the code immediately executes:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._state = KernelRuntimeState.READY
```

</details>

That doesn't prove the kernel has actually returned to `idle`.

The real sequence is:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
interrupt request
      ≠
execution finished
```

</details>

A more accurate state machine is:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
BUSY
 ↓
INTERRUPTING
 ↓
WAITING_FOR_IDLE
 ↓
READY
```

</details>

This matters if another execution is submitted immediately after an interrupt.

---

# 6. The timeout escalation ladder is a strong feature

This is one of the best parts of the implementation.

The documented strategy is:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

<sup>[source]</sup>

That is much better than:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
timeout → return error → leave kernel running
```

</details>

The latter creates orphaned computation.

Kerno is clearly trying to enforce:

> A timed-out execution cannot silently continue forever.

That's a strong runtime invariant.

---

# 7. But `_escalate_timeout()` blocks the caller

The escalation function does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
time.sleep(grace_s)
```

</details>

with the default:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
2 seconds
```

</details>

then potentially waits another:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
5 seconds
```

</details>

for process termination. <sup>[source]</sup>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
120 s execution timeout
       +
2 s grace
       +
up to 5 s kill wait
```

</details>

means the caller may not get its final `CellOutput` until considerably after the nominal timeout.

That's not necessarily wrong.

But Kerno should distinguish:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
execution timeout
```

</details>

from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
recovery duration
```

</details>

in telemetry.

For example:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
execution_timeout = 120s
interrupt_grace = 2s
kill_wait = 5s
total_recovery = 7s
```

</details>

---

# 8. The biggest issue: restart happens after hard kill

The code does:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
proc.kill()
proc.wait()
restart()
```

</details>

<sup>[source]</sup>

Conceptually correct.

But `KernelManager.restart_kernel()` behavior depends on the underlying Jupyter client/provisioner state.

After manually killing the process, the runtime should ensure that the manager's state and channels are still valid before invoking restart.

This deserves an integration test:

<details>
<summary><strong>💻 Code Block (text) — 15 lines</strong></summary>

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

</details>

That is a **must-have recovery test**.

---

# 9. Generation tracking is excellent

This is a particularly good design:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._generation += 1
```

</details>

on restart. <sup>[source]</sup>

So:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
kernel_id = A
generation = 1
```

</details>

becomes:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
kernel_id = A
generation = 2
```

</details>

after restart.

This solves a subtle observability problem.

Without generation:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kernel-42
```

</details>

could represent:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
process #1
process #2
process #3
```

</details>

with no way to distinguish them.

With generation:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
kernel-42 / generation-1
kernel-42 / generation-2
kernel-42 / generation-3
```

</details>

execution traces become much more reliable.

---

# 10. Sticky `DEAD` is also a strong improvement

The `state` property deliberately makes `DEAD` sticky:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
process dies
    ↓
state = DEAD
    ↓
future state reads
    ↓
still DEAD
```

</details>

until an explicit restart.

<sup>[source]</sup>

That's good.

Otherwise a race could produce:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
process killed
      ↓
poll() hasn't updated yet
      ↓
state says READY
```

</details>

which is dangerous for a kernel pool.

This is exactly the kind of defensive state management an execution runtime needs.

---

# 11. However, `is_alive` and `state` have different semantics

`is_alive`:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
return bool(self._km and self._km.is_alive())
```

</details>

while `state` has sticky lifecycle semantics.

Therefore it's possible to observe:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
state == DEAD
is_alive == True
```

</details>

briefly if the underlying process hasn't been observed dead yet.

That's intentional for sticky death, but callers need to know which property is authoritative.

I'd document:

> `state` is the runtime's logical lifecycle state; `is_alive` is the underlying process liveness observation.

---

# 12. The most important concurrency issue: `execute()` has no execution lock

This is the biggest finding in this file.

There is no visible:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
threading.Lock()
```

</details>

around:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
self._kc.execute(...)
collect(...)
```

</details>

Therefore two threads could theoretically do:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Thread A
  ↓
execute(A)

Thread B
  ↓
execute(B)
```

</details>

against the same `KernelRuntime`.

Then:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
Kernel
 │
 ├── execute A
 └── execute B
```

</details>

could overlap.

This directly connects to the concern from `output.py`.

If Kerno's architectural invariant is:

> **one active execution per kernel**

then that invariant needs to be enforced here.

Not merely assumed.

---

# 13. The correct fix is an execution lock

Conceptually:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
with self._execution_lock:
    msg_id = self._kc.execute(...)
    output = collect(...)
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 19 lines</strong></summary>

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

</details>

That makes the output collector's current assumptions safe.

---

# 14. `stream_execute()` has the same issue

`stream_execute()` does:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
msg_id = self._kc.execute(code)
...
yield from stream(...)
```

</details>

<sup>[source]</sup>

It also has no execution lock.

This is actually trickier because the generator holds the execution open across multiple `yield`s.

The lock must therefore remain held for the lifetime of the generator:

<details>
<summary><strong>💻 Code Block (text) — 16 lines</strong></summary>

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

</details>

A normal `with` surrounding only the `execute()` call wouldn't be enough.

---

# 15. `_cell_count` is not concurrency-safe either

`execute()` records:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._cell_count + 1
```

</details>

then later increments:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._cell_count += 1
```

</details>

<sup>[source]</sup>

With concurrent calls:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
A reads 7
B reads 7
```

</details>

both could report:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
cell.num = 8
```

</details>

So the execution lock also solves cell numbering.

---

# 16. `stream_execute()` increments the counter before completion

There's another semantic difference.

Normal:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
execute()
   ↓
collect
   ↓
if not silent:
    cell_count += 1
```

</details>

Streaming:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
stream_execute()
   ↓
cell_count += 1
   ↓
stream
```

</details>

So a failed/cancelled streaming execution still increments the count.

Maybe that's intentional:

> "number of submitted cells"

rather than:

> "number of completed cells."

But then the property should be named accordingly.

I'd separate:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
cells_submitted
cells_completed
cells_failed
cells_cancelled
```

</details>

if telemetry matters.

---

# 17. `silent` affects telemetry semantics

This code:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
if not silent:
    self._cell_count += 1
    self._metrics.record_cell(...)
```

</details>

means silent executions aren't counted.

But `execute_silent()` is used internally by:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
memory_mb
```

</details>

and potentially other infrastructure.

That's sensible if the metric is intended to represent user-facing cell execution.

However:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
cells_executed
```

</details>

currently doesn't mean literally every execution.

It means roughly:

> non-silent executions counted by this runtime.

That naming should be clarified.

---

# 18. `memory_mb` is a clever but expensive implementation

It runs:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
import psutil, os
print(psutil.Process(os.getpid()).memory_info().rss / 1e6)
```

</details>

inside the kernel. <sup>[source]</sup>

This gives memory usage of the **kernel process**, which is exactly what you want.

But it means every call to:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
runtime.memory_mb
```

</details>

is itself a kernel execution.

So:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

That's relatively expensive.

For periodic telemetry, the runtime should eventually expose process metrics from the host side instead.

---

# 19. `memory_mb` also depends on `psutil`

If `psutil` isn't installed inside the kernel environment:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

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

</details>

The method eventually returns:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
0.0
```

</details>

That conflates:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
actual memory = 0
```

</details>

with:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
measurement failed
```

</details>

A better API would be:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Optional[float]
```

</details>

or raise a dedicated telemetry error.

---

# 20. `execute_silent()` hides kernel errors

It does:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
output = self.execute(...)
return output.stdout.strip()
```

</details>

If the execution fails, it returns the stdout regardless.

So:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
execute_silent("bad code")
```

</details>

doesn't necessarily raise.

That can be useful for internal probes, but dangerous for callers expecting:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
result = runtime.execute_silent(...)
```

</details>

to mean successful execution.

I'd define explicit semantics:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
execute_silent()
    = execute but don't display/count output

execute_checked()
    = execute and raise on CellError
```

</details>

or make `execute_silent()` raise on `output.has_error`.

---

# 21. `reset_namespace()` relies on IPython `%reset`

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self.execute("%reset -f", ...)
```

</details>

<sup>[source]</sup>

That's fine for the default Python/IPython kernel.

But `KernelRuntime` accepts:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
kernel_name="..."
```

</details>

which suggests other Jupyter kernels may be supported.

Then `%reset -f` is not necessarily portable.

Therefore:

> `KernelRuntime` is currently more Python/IPython-specific than its generic Jupyter abstraction suggests.

This should either be documented or abstracted.

---

# 22. `namespace` also assumes Python-specific semantics

It calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
get_snapshot(self._kc)
```

</details>

and `inspect()` calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
get_object_detail(...)
```

</details>

Those are presumably Python-oriented introspection facilities.

So the runtime should probably distinguish:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Jupyter kernel transport
```

</details>

from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Python kernel capabilities
```

</details>

Architecture:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

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

</details>

That would make the abstraction cleaner.

---

# 23. Telemetry integration is strong

Every execution gets:

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

<sup>[source]</sup>

and then:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
cell.duration_ms
cell.had_error
cell.output_bytes
cell.n_images
```

</details>

This is exactly what an agent runtime needs for observability.

The generation field is particularly valuable after restarts.

---

# 24. But `code_preview` is potentially sensitive

The tracer stores:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
code[:80].replace("\n", " ")
```

</details>

<sup>[source]</sup>

That means source code is being placed into telemetry.

For generic infrastructure this can leak:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
API keys
passwords
tokens
PII
SQL
private prompts
```

</details>

even within the first 80 characters.

I would change this to an opt-in feature:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
trace_code_preview = false
```

</details>

and otherwise record:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
code_length
code_hash
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
cell.code_bytes = 482
cell.code_sha256 = ...
```

</details>

Much safer.

---

# 25. Error telemetry has a similar privacy concern

The runtime records:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
span.set("error.evalue", output.error.evalue[:200])
```

</details>

<sup>[source]</sup>

Exception messages can contain:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
file paths
database URLs
user data
credentials
query fragments
```

</details>

So telemetry should eventually support redaction.

---

# 26. The execution transaction is not fully atomic

Consider:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

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

</details>

The runtime returns a `CellOutput`, but it doesn't appear to expose a unified execution lifecycle record such as:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

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

</details>

That would make the runtime much easier to reason about.

---

# 27. This is the abstraction I recommend

Introduce:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
ExecutionRecord
```

</details>

with:

<details>
<summary><strong>💻 Code Block (text) — 14 lines</strong></summary>

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

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

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

</details>

This would unify the runtime's lifecycle and observability.

---

# 28. Final runtime state machine

The current implementation is roughly:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

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

</details>

I'd make the target state machine:

<details>
<summary><strong>💻 Code Block (text) — 22 lines</strong></summary>

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

</details>

And enforce:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
ONE ACTIVE EXECUTION PER KERNEL
```

</details>

with an execution lock.

---

# 29. Current verdict

| Area | Verdict |
|---|---|
| Kernel startup | 🟢 Good |
| Kernel shutdown | 🟢 Good |
| Timeout handling | 🟢 Strong |
| Hard timeout escalation | 🟢 Strong concept |
| Restart generation | 🟢 Excellent |
| Sticky DEAD state | 🟢 Excellent |
| Telemetry | 🟢 Strong |
| Cancellation | 🟢 Strong |
| Output integration | 🟢 Strong |
| Execution concurrency | 🔴 Needs explicit lock |
| Interrupt state | 🟠 Too optimistic |
| Startup cleanup | 🟠 Needs hardening |
| Generic Jupyter support | 🟠 Actually Python/IPython-oriented |
| Telemetry privacy | 🟠 Needs redaction/configuration |
| Execution lifecycle model | 🟠 Should be formalized |

---

# 30. The key architectural conclusion

After inspecting:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
runtime.py
output.py
channel.py
isolation.py
```

</details>

the architecture is now much clearer:

<details>
<summary><strong>💻 Code Block (text) — 14 lines</strong></summary>

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

</details>

This is a **real execution substrate**, not merely a package of convenience functions.

The remaining work is primarily about making its implicit invariants explicit:

> **one execution per kernel, correlated messages, transactional state, bounded communication, and formal execution lifecycle.**

Those are the things that turn a good prototype into a robust runtime.

### Next audit target: `kerno/kernel/pool.py`

That is now the logical next layer:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
KernelRuntime
      ↓
KernelPool
      ↓
MultiAgentLoop
```

</details>

The pool will tell us whether the runtime's new `DEAD`/`generation`/restart semantics are actually handled correctly when kernels are **allocated, released, reused, expired, killed, and recovered**. <sup>[source]</sup>

---

## [33] USER

Continue 

---

## [34] CHATGPT (gpt-5-6)

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

## [35] CHATGPT (gpt-5-6)

# Continue — `kerno/kernel/pool.py`

This file exposes the **resource-management layer** above `KernelRuntime`. The overall design is good, but the audit finds several important lifecycle/concurrency bugs that are more serious than the issues in `runtime.py`.

The intended architecture is:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

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

</details>

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

# 1. The core state model is good

The pool defines:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
WARMING
AVAILABLE
ACQUIRED
RESETTING
DEAD
```

</details>

<sup>[source]</sup>

That's a sensible state machine.

The important distinction is:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
KernelRuntime state
        ≠
Pool ownership state
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
Pool:     ACQUIRED
Runtime:  READY
```

</details>

means:

> The kernel is owned by a task and currently ready to execute.

Whereas:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
Pool:     RESETTING
Runtime:  READY
```

</details>

means:

> The kernel is not available to users because pool cleanup is in progress.

That is a strong abstraction.

---

# 2. `PooledKernel` correctly adds pool-level lifecycle limits

Each kernel has:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
MAX_CELLS    = 200
MAX_LIFETIME = 3600 s
MAX_MEMORY   = 4096 MB
```

</details>

and `is_expired` checks all three. <sup>[source]</sup>

Conceptually:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

This is exactly the kind of containment mechanism needed for long-running agent systems.

---

# 3. But the memory limit has a semantic problem

`is_expired` calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
memory = self._safe_memory()
```

</details>

and `_safe_memory()` returns:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
0.0
```

</details>

when measurement fails. <sup>[source]</sup>

That means:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
memory measurement failed
        ↓
0 MB
        ↓
kernel considered healthy
```

</details>

This is unsafe.

If the monitoring mechanism fails, the system should not silently conclude:

> memory usage is zero.

Better:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
memory = UNKNOWN
```

</details>

and then choose an explicit policy:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
UNKNOWN → don't expire
```

</details>

or, for safety:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
UNKNOWN → mark health degraded
```

</details>

but never pretend it is `0`.

---

# 4. The first major bug: acquisition can create duplicate replacement kernels

Look at:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk = self._available.get(...)
```

</details>

Then:

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

The dead kernel remains inside:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
self._all
```

</details>

because acquisition doesn't call `_retire()`.

So:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
_all:
  k-0001 DEAD
  k-0002 AVAILABLE
```

</details>

and the dead kernel is still counted in pool inventory.

Eventually you can accumulate stale `PooledKernel` objects in `_all`.

This should instead be:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
unhealthy available kernel
       ↓
_retire(pk, replace=False)
       ↓
create replacement
```

</details>

or otherwise remove it from `_all`.

---

# 5. More serious: `acquire()` can exceed `max_overflow`

The overflow condition is:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
if self.overflow and len(self._active) < self.max_overflow:
    pk = self._create_kernel()
```

</details>

<sup>[source]</sup>

But `max_overflow` is compared against:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
active kernels
```

</details>

rather than:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
overflow kernels
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

You could have:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
3 base kernels
+ 10 active overflow kernels
```

</details>

which is already 13 total.

But the condition is not actually expressing:

> maximum of 10 overflow kernels.

It's expressing:

> permit creation while fewer than 10 kernels are active.

Those are very different policies.

---

# 6. Worse: overflow kernels are not tracked as overflow

`PooledKernel` doesn't contain:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
is_overflow
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
capacity_origin
```

</details>

Therefore after:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
size = 3
overflow = true
```

</details>

the pool cannot distinguish:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
base kernel
```

</details>

from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
overflow kernel
```

</details>

That makes controlled overflow retirement difficult.

I'd add:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
is_overflow: bool = False
```

</details>

or better:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
pool_class = BASE | OVERFLOW
```

</details>

---

# 7. The pool can create an unbounded number of replacement threads

`_retire()` does:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
threading.Thread(
    target=self._warm_one,
    daemon=True
).start()
```

</details>

<sup>[source]</sup>

And `_warm_one()` creates a kernel.

The monitor can retire multiple kernels in one pass:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
k1 expired → replacement thread
k2 expired → replacement thread
k3 expired → replacement thread
...
```

</details>

Meanwhile other failure paths can also call `_retire()`.

There's no central capacity controller.

A robust pool should maintain:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
desired_capacity
current_capacity
pending_creations
```

</details>

and ensure:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
current + pending <= target
```

</details>

---

# 8. The second major bug: release/reset race

This is probably the most important pool-level issue.

`release()` removes the kernel from `_active`:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk = self._active.pop(task_id, None)
```

</details>

then starts:

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

<sup>[source]</sup>

The reset happens asynchronously.

That's fine **if the kernel remains inaccessible until reset finishes**.

And currently it isn't placed back into `_available` until `_soft_reset()` finishes.

So far, good.

But now consider:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
release(task A)
      ↓
soft-reset thread starts
      ↓
pool.shutdown()
```

</details>

The shutdown operation can race with the reset thread.

The reset thread might then execute:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
reset_namespace()
bootstrap()
_available.put(pk)
```

</details>

after shutdown has supposedly completed.

That could resurrect a supposedly closed pool.

---

# 9. `shutdown()` doesn't join reset/creation/monitor threads

`shutdown()` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._running = False
```

</details>

and shuts down the kernels currently in `_all`. <sup>[source]</sup>

But background threads include:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
_monitor
_warm_one
_soft_reset
_hard_reset
```

</details>

None are tracked comprehensively or joined.

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
shutdown()
   │
   ├── returns
   │
   └── background reset still running
```

</details>

is possible.

This violates a desirable shutdown invariant:

> After `KernelPool.shutdown()` returns, no pool-managed work should be able to create, reset, enqueue, or replace kernels.

---

# 10. `_running` is not sufficient synchronization

The monitor checks:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
while self._running:
```

</details>

but `_soft_reset()` and `_hard_reset()` don't check `_running` before putting kernels into `_available`.

So:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
shutdown()
   ↓
_running = False
```

</details>

doesn't stop:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
soft_reset
   ↓
_available.put(pk)
```

</details>

This is a concrete shutdown race.

Every background mutation should either:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
check pool active state
```

</details>

or be serialized through a pool lifecycle controller.

---

# 11. Another major issue: `release()` doesn't handle unknown reasons

The documented reasons are:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
complete
error
timeout
oom
```

</details>

<sup>[source]</sup>

But there is no:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
case _:
    raise ValueError(...)
```

</details>

So:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pool.release(task_id, reason="banana")
```

</details>

will:

1. remove the kernel from active,
2. increment `tasks_served`,
3. clear ownership,
4. do nothing else.

The kernel becomes orphaned:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
not active
not available
not resetting
not dead
```

</details>

That's a real state corruption bug.

Add:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
case _:
    raise ValueError(...)
```

</details>

before mutating ownership, or validate `reason` first.

---

# 12. `release()` has another problem with failed reset

For:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
complete
```

</details>

the pool launches `_soft_reset()`.

If it fails:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
except Exception:
    self._hard_reset(pk)
```

</details>

Good.

But `_hard_reset()` can also fail:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
except Exception:
    self._retire(pk)
```

</details>

which starts a replacement thread.

This produces:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

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

</details>

That's a reasonable recovery strategy.

The problem is that **the task caller gets no indication whatsoever that release triggered a replacement**.

That should at least be reflected in pool telemetry.

---

# 13. `restart(task_id)` is actually a strong API

This is one of the better parts:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk.runtime.restart()
```

</details>

while keeping:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
same PooledKernel
same KernelRuntime object
same task ownership
```

</details>

and only incrementing runtime generation. <sup>[source]</sup>

That's useful for agents.

For example:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

That's much better than replacing the Python object behind the task's back.

---

# 14. But `restart()` doesn't reset pool lifecycle metadata

After restart:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
created_at
tasks_served
```

</details>

remain unchanged.

That's potentially correct if these represent the **physical pooled kernel lifetime**.

But then:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
runtime.generation
```

</details>

represents process lifetime while:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
PooledKernel.created_at
```

</details>

represents pool-object lifetime.

These should be explicitly documented.

Otherwise an agent could restart a kernel repeatedly while:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
created_at → 59 minutes
```

</details>

and then immediately hit:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
MAX_LIFETIME
```

</details>

even though the underlying process was freshly restarted.

That may actually be desirable for resource churn prevention—but it should be intentional.

---

# 15. `interrupt()` correctly preserves task ownership

This API:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pool.interrupt(task_id)
```

</details>

finds the active pooled kernel and calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pk.runtime.interrupt()
```

</details>

<sup>[source]</sup>

This is exactly the right layering:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Agent cancellation
       ↓
KernelPool.interrupt(task_id)
       ↓
KernelRuntime.interrupt()
       ↓
Jupyter interrupt
```

</details>

The important missing piece is what happens **after** the interrupt.

The pool still considers:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
state = ACQUIRED
```

</details>

and the runtime may optimistically report `READY`.

This is another reason the runtime needs the stronger:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
WAITING_FOR_IDLE
```

</details>

state proposed earlier.

---

# 16. `health_check()` is excellent for observability

The returned information:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
state
alive
generation
cells
uptime
task_id
tasks_served
```

</details>

<sup>[source]</sup>

is exactly what an operator needs.

Example:

<details>
<summary><strong>💻 Code Block (json) — 11 lines</strong></summary>

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

</details>

This is a strong foundation for a future dashboard.

---

# 17. But `stats` is too weak for capacity management

Currently:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
available
active
total
active_tasks
```

</details>

<sup>[source]</sup>

Missing:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
warming
resetting
dead
overflow
pending_creation
expired
unhealthy
```

</details>

For a resource pool, I'd want:

<details>
<summary><strong>💻 Code Block (json) — 10 lines</strong></summary>

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

</details>

This would make pool behavior much easier to diagnose.

---

# 18. `_monitor_loop()` has a hidden policy problem

It checks every 30 seconds:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
AVAILABLE + expired → retire
ACQUIRED + >1 hour → warning
```

</details>

<sup>[source]</sup>

But an acquired kernel that exceeds:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
MAX_LIFETIME
```

</details>

is **not retired**.

It is only warned about.

So the lifecycle policy is inconsistent:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
AVAILABLE:
    lifetime hard limit

ACQUIRED:
    lifetime soft warning
```

</details>

That may be intentional because killing an active task is dangerous.

If so, define two separate limits:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
MAX_IDLE_LIFETIME
MAX_TASK_LIFETIME
```

</details>

rather than using one `MAX_LIFETIME` for both.

---

# 19. The monitor also doesn't enforce memory/cell limits on acquired kernels

The same issue applies to:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
MAX_MEMORY
MAX_CELLS
```

</details>

An active task can exceed:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
4096 MB
```

</details>

and the monitor only checks:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
acquired for > 1 hour
```

</details>

It doesn't actually enforce memory/cell limits while acquired.

This means:

> lifecycle limits are primarily **between-task retirement policies**, not hard runtime limits.

That distinction should be made explicit.

---

# 20. `is_expired` uses `cells_executed`

From the previous runtime audit, `cells_executed` is not necessarily literally every execution because silent executions aren't counted.

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
MAX_CELLS = 200
```

</details>

may not mean:

> kernel has executed 200 cells.

It means closer to:

> kernel has executed 200 counted/non-silent cells.

That creates an accounting mismatch.

I'd fix this at the runtime layer by maintaining:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
executions_submitted
executions_completed
executions_failed
```

</details>

and have pool retirement use the explicit metric.

---

# 21. Bootstrap failure is deliberately nonfatal

`_bootstrap()` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
output = runtime.execute(...)
```

</details>

and if there's an error:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
warnings.warn(...)
```

</details>

rather than failing the kernel. <sup>[source]</sup>

This is questionable.

If `skills_path` contains mandatory capabilities:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
kernel starts
   ↓
skills fail
   ↓
kernel marked AVAILABLE
```

</details>

then the pool hands out a kernel that does not satisfy its declared configuration.

For optional skills, that's fine.

For required skills, it should be:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
bootstrap failure
      ↓
kernel DEAD
      ↓
replacement
```

</details>

I would introduce:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
skills_required = True/False
```

</details>

---

# 22. Bootstrap reads the entire file synchronously

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
code = path.read_text()
```

</details>

then sends it as one cell.

For a large skill file:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
100 KB+
```

</details>

the entire file becomes one execution.

That can interact badly with:

- startup timeout,
- output collection,
- timeout recovery,
- cell limits.

Better eventually:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
bootstrap manifest
     ↓
load modules
     ↓
verify
     ↓
ready
```

</details>

rather than one giant cell.

---

# 23. The biggest architectural issue: queue ownership is not fully atomic

The pool has:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
_available Queue
_active dict
_all list
```

</details>

with `_lock` around the dictionaries/list.

But the transition:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
AVAILABLE
   ↓
Queue.get()
   ↓
ACQUIRED
   ↓
_active[task] = pk
```

</details>

is split between queue synchronization and pool locking.

This creates a small but important failure window:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
queue.get()
    ↓
process crashes / exception
    ↓
kernel removed from queue
    ↓
never inserted into active
```

</details>

The pool loses track of it.

Likewise:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
_active.pop()
    ↓
background reset starts
    ↓
thread fails before requeue
```

</details>

can lose the kernel.

A stronger design uses a single state transition coordinator.

---

# 24. The pool needs an explicit invariant

The most important invariant should be:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
Every PooledKernel is in exactly ONE ownership state:
```

</details>

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
AVAILABLE
ACQUIRED
RESETTING
WARMING
DEAD
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
AVAILABLE  ↔ _available
ACQUIRED   ↔ _active
RESETTING  ↔ reset worker
WARMING    ↔ creation worker
DEAD       ↔ removed
```

</details>

Currently `_all` can contain objects that don't correspond cleanly to those ownership structures.

That is the area I'd formalize.

---

# 25. Recommended pool architecture

I'd introduce a central lifecycle controller:

<details>
<summary><strong>💻 Code Block (text) — 15 lines</strong></summary>

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

</details>

Every transition goes through:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
_transition(pk, FROM, TO)
```

</details>

so you can enforce:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
AVAILABLE → ACQUIRED
ACQUIRED → RESETTING
RESETTING → AVAILABLE
RESETTING → DEAD
WARMING → AVAILABLE
WARMING → DEAD
```

</details>

and reject invalid transitions.

---

# 26. Recommended capacity controller

Instead of spawning replacement threads freely:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
_retire()
  ↓
thread(_warm_one)
```

</details>

use:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
desired_capacity
current_capacity
pending_creations
```

</details>

with:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
reconcile()
```

</details>

conceptually:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
if current + pending < desired:
    create

if current > desired:
    retire idle kernels
```

</details>

This gives deterministic pool capacity.

---

# 27. Revised severity table

| Finding | Severity |
|---|---|
| Unknown `release(reason)` silently orphaning kernel | 🔴 P0 |
| Shutdown races with background reset/replacement | 🔴 P0 |
| No explicit one-kernel/one-execution enforcement | 🔴 P0 |
| Dead acquired kernel can remain in `_all` | 🔴 P1 |
| Overflow accounting incorrect | 🔴 P1 |
| Replacement creation not capacity-controlled | 🟠 P1 |
| Runtime interrupt state too optimistic | 🟠 P1 |
| Bootstrap failure may expose unconfigured kernel | 🟠 P1 |
| Memory measurement failure → `0.0` | 🟠 P1 |
| Weak pool statistics | 🟡 P2 |
| Lifecycle semantics of `created_at` vs generation unclear | 🟡 P2 |

---

# 28. The four-layer model is now becoming very clear

We have now audited:

<details>
<summary><strong>💻 Code Block (text) — 17 lines</strong></summary>

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

</details>

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

# 29. The most important invariant to establish next

Before continuing into higher-level agent logic, I would lock down this contract:

<details>
<summary><strong>💻 Code Block (text) — 19 lines</strong></summary>

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

</details>

If this invariant holds, the rest of Kerno becomes dramatically easier to reason about.

If it doesn't, bugs can cross all four layers.

---

## Next: `kerno/agent/loop.py`

The next audit should move above the infrastructure:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
KernelPool
    ↓
MultiAgentLoop
    ↓
Agent
    ↓
turn / tool / observation / decision
```

</details>

That is where we'll determine whether Kerno's **actual agent semantics** match the infrastructure underneath it—especially:

- turn boundaries,
- cancellation propagation,
- budget enforcement,
- shared memory,
- agent-to-agent communication,
- failure recovery,
- and whether a failed kernel execution can incorrectly advance an agent's state.

That is the next major architectural gate.

---

---
[← Previous section](./07-isolation-and-communication.md) | [Back to index](./README.md) | [Next section →](./09-agent-loop-and-orchestration.md)

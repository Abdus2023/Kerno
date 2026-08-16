# 07 — Isolation And Communication

## `kerno/isolation.py` audit

I checked the actual isolation implementation on your `arena/01a0064f-kerno` branch. This confirms the architecture is **conceptually good but not yet as strong as its documentation claims**. <sup>[source]</sup>

The important distinction is:

> **The receiving kernel gets a copy, but `SharedMemory` itself does not protect its stored value from mutation.**

That changes the isolation verdict.

---

## 1. The intended model

Kerno defines two mechanisms:

```text
SharedMemory
    =
explicit cross-agent data

NamespacePartition
    =
allowed namespace writes
```

The intended boundary is:

```text
Agent A
   │
   │ declared export
   ▼
SharedMemory
   │
   │ JSON serialization
   ▼
Agent B's kernel
```

This is a good model. <sup>[source]</sup>

---

## 2. The first important bug: `SharedValue` is frozen, but `value` is not immutable

This is subtle.

The code uses:

```python
@dataclass(frozen=True)
class SharedValue:
    value: Any
```

<sup>[source]</sup>

`frozen=True` prevents:

```python
sv.value = something_else
```

but it does **not** prevent:

```python
sv.value["secret"] = "modified"
```

if `value` is a dictionary.

Likewise:

```python
sv.value.append(...)
```

works if `value` is a list.

So:

```text
frozen dataclass
       ≠
immutable value
```

This is an important correctness distinction.

---

## 3. Example of the problem

Suppose Agent A does:

```python
data = {
    "result": 42,
    "items": [1, 2, 3]
}
```

Then:

```python
shared.put("data", data, "analyst")
```

Now the host-side `SharedMemory` contains a reference to `data`.

If the original kernel-side object is somehow retained/reused, or if host code receives and mutates the same object:

```python
data["items"].append(999)
```

the supposedly shared value can change.

The `SharedValue` object itself remains frozen, but:

```text
SharedValue
    │
    └── value ─────► mutable dict
```

is still mutable.

---

## 4. The good part: `seed_code()` really does create a copy

This part is much stronger.

The code generates:

```python
sv_key = _json.loads(...)
```

rather than directly injecting the original Python object. <sup>[source]</sup>

So the receiving kernel gets:

```text
SharedMemory
     │
     │ json.dumps()
     ▼
serialized data
     │
     │ json.loads()
     ▼
new Python object
```

Therefore:

```text
Agent A's object
       │
       X
       │
Agent B's object
```

There is no Python object identity crossing the boundary.

That is genuinely good isolation.

---

## 5. But "immutable" is still technically incorrect

The receiving agent can do:

```python
data["items"].append(999)
```

and mutate its **local copy**.

That's perfectly fine.

The important property is:

```text
Agent B mutation
      │
      X
      │
SharedMemory
```

doesn't propagate back.

So the correct terminology should be:

> **defensive serialized copies**

rather than:

> immutable JSON copies.

That wording matters for a security/architecture document.

---

## 6. Bigger problem: `SharedMemory.put()` doesn't serialize at insertion

Current:

```python
def put(self, key, value, producer):
    sv = SharedValue(
        key=key,
        value=value,
        producer=producer,
    )
    self._values[key] = sv
```

<sup>[source]</sup>

A stronger implementation would validate/copy immediately:

```text
put()
 │
 ├── validate JSON serializable
 │
 ├── serialize
 │
 ├── deserialize
 │
 └── store defensive copy
```

That would establish the invariant:

> Once inserted, SharedMemory owns its own copy of the value.

That is much safer.

---

## 7. There is also a key-collision problem

`SharedMemory` is:

```python
self._values: dict[str, SharedValue]
```

and:

```python
self._values[key] = sv
```

<sup>[source]</sup>

Therefore:

```text
Agent A:
results_summary = A

Agent B:
results_summary = B
```

produces:

```text
results_summary → B
```

Agent A's value disappears.

There is no:

```text
version
revision
conflict
CAS
sequence
```

mechanism.

This becomes significant in parallel multi-agent execution.

---

## 8. Current model assumes sequential turns

The multi-agent loop we examined is sequential:

```text
A
↓
B
↓
C
```

So key collisions are deterministic.

But if Kerno evolves toward:

```text
A ─────┐
       ├── SharedMemory
B ─────┘
```

then:

```text
A writes key X
B writes key X
```

becomes a race.

The data model should eventually support:

```text
key
version
producer
turn_id
timestamp
```

at minimum.

---

## 9. Namespace isolation is only write detection

This is another important distinction.

`NamespacePartition` does:

```python
allows(agent, key)
```

and:

```python
violations(...)
```

<sup>[source]</sup>

This controls:

> what the agent is **allowed to export/write**

It does **not** control:

> what Python code can read from the kernel.

In an isolated kernel, this is okay because each agent gets a separate process.

But in `shared` mode:

```text
Agent A
   │
   ▼
same Python namespace
   ▲
   │
Agent B
```

`NamespacePartition` cannot prevent:

```python
secret_from_agent_b
```

from being read.

So K-009 should be explicitly described as:

> **namespace/write-policy enforcement**

rather than general information-flow security.

---

## 10. `violations()` has a particularly interesting property

The code allows a key if:

```python
key in shared_keys
```

even if the current agent didn't declare that key. <sup>[source]</sup>

That's intentional:

```text
shared state
   ↓
readable
```

But it means:

```text
shared key
```

is effectively a capability to expose data to every isolated agent.

Therefore the security model is:

```text
private
   ↓
explicitly export
   ↓
public-to-agent-set
```

not:

```text
private
   ↓
shared with specific recipient
```

This is an important limitation.

---

## 11. `isolate_seed_code()` confirms broadcast semantics

It simply calls:

```python
return shared.seed_code()
```

<sup>[source]</sup>

There is no recipient parameter.

So:

```text
Agent A exports X
        │
        ▼
SharedMemory
        │
   ┌────┼────┐
   ▼    ▼    ▼
  B     C    D
```

all receive X.

That is fine for a cooperative pipeline.

But it prevents more sophisticated confidentiality policies such as:

```text
analyst → critic
analyst → narrator
analyst ✕ auditor
```

---

## 12. `seed_code()` has a serious identifier-safety issue

This is probably the most concrete bug in this file.

The key is directly inserted into Python:

```python
f"{sv.key} = _json.loads(...)"
```

<sup>[source]</sup>

So if a shared key is:

```text
foo
```

you get:

```python
foo = ...
```

Fine.

But if a key is malicious or invalid:

```text
foo; os.system("...")
```

the generated source becomes dangerous.

Even if current agents only generate trusted names, this is an unsafe code-generation boundary.

---

## 13. The same problem exists with the export prefixes

`export_code()` generates Python source containing:

```python
{prefixes!r}
```

which is safer because it is represented as a Python literal.

But the shared key is inserted as an actual assignment target.

The solution is simple:

### Validate keys as identifiers

Require:

```python
key.isidentifier()
```

or impose a stricter Kerno namespace:

```text
[a-zA-Z_][a-zA-Z0-9_]*
```

before inserting it into generated code.

Even better:

```text
__kerno_shared__ = {
    "key": value
}
```

instead of dynamically generating variable names.

---

## 14. Better design: don't generate assignment statements

Instead of:

```python
results_summary = ...
```

generate:

```python
__kerno_shared__ = _json.loads(...)
```

Then the kernel gets:

```python
__kerno_shared__["results_summary"]
```

This provides three benefits:

1. No identifier injection.
2. Clear shared/private distinction.
3. Easy namespace auditing.

Architecture:

```text
Kernel namespace
│
├── agent variables
│
├── Python/IPython internals
│
└── __kerno_shared__
      ├── results_summary
      ├── model_metrics
      └── key_findings
```

This is considerably cleaner.

---

## 15. Exporting is also vulnerable to output contamination

`export_code()` does:

```python
print(_json.dumps(_out))
```

<sup>[source]</sup>

It assumes the stdout returned by the kernel is exactly the JSON object.

But the execution environment may produce other output.

For example:

```python
print("debug")
```

during execution could cause:

```text
debug
{"results": 42}
```

Then:

```python
json.loads(stdout)
```

fails.

The code handles this by returning `{}`:

```python
except ...:
    return {}
```

<sup>[source]</sup>

So a legitimate export can silently disappear.

---

## 16. Export protocol should use a unique framing marker

Instead of relying on raw stdout:

```text
{"results":42}
```

use:

```text
__KERNO_EXPORT_BEGIN__
{"results":42}
__KERNO_EXPORT_END__
```

Then the host extracts the framed payload.

Even better, use a dedicated Jupyter MIME/display channel if available.

That would eliminate accidental stdout interference.

---

## 17. JSON-only export is deliberately restrictive

The export code accepts:

```text
str
int
float
bool
None
list
dict
```

and JSON serializability. <sup>[source]</sup>

That means these won't cross:

```text
DataFrame
numpy.ndarray
torch.Tensor
sklearn model
file handle
socket
generator
custom class
```

This is actually **good for isolation**.

It forces agents to convert complex objects into explicit representations.

For example:

```python
model_metrics = {
    "accuracy": 0.94,
    "f1": 0.91
}
```

instead of attempting:

```python
model = trained_model
```

This keeps the inter-agent protocol language-neutral and serializable.

---

## 18. But NaN/Infinity need consideration

Python's `json.dumps()` by default permits:

```python
float("nan")
float("inf")
```

using non-standard JSON representations.

That can create interoperability issues.

A strict protocol should use:

```python
json.dumps(value, allow_nan=False)
```

and reject invalid JSON values.

Then Kerno's state protocol is genuinely JSON-compatible.

---

## 19. There is no size limit on SharedMemory values

An agent could potentially export:

```python
huge_result = [...]
```

containing hundreds of MB.

Then:

```text
kernel
 ↓
json.dumps
 ↓
SharedMemory
 ↓
seed_code
 ↓
json.loads
```

can consume enormous memory.

This connects directly to the earlier pool resource-limit issue.

Kerno needs:

```text
MAX_SHARED_VALUE_BYTES
```

and preferably:

```text
MAX_TOTAL_SHARED_MEMORY_BYTES
```

For example:

```text
per value
  ≤ 1 MB

total session
  ≤ 32 MB
```

depending on the intended workload.

---

## 20. SharedMemory also needs lifecycle semantics

Currently:

```text
SharedMemory
    │
    └── values remain
```

There is no visible concept of:

```text
session
turn
version
expiration
checkpoint
rollback
```

This is the missing piece we predicted.

Consider:

```text
Turn 1:
analyst → results = valid

Turn 2:
analyst → results = invalid
```

The second `put()` simply replaces the first.

There's no history.

For an agent runtime, I'd strongly prefer:

```text
SharedValue
├── key
├── value
├── producer
├── session_id
├── turn_id
├── revision
├── timestamp
└── status
```

---

## 21. This enables transactional state

Then the architecture becomes:

```text
                 Agent Turn
                     │
                     ▼
              staging memory
                     │
          ┌──────────┴──────────┐
          │                     │
       success                failure
          │                     │
          ▼                     ▼
       COMMIT                 DISCARD
          │
          ▼
     SharedMemory
```

That would solve the earlier problem where `_export_turn()` runs from `finally`.

The exported state can become atomic:

```text
turn 7:
  analyst
  status = COMMITTED
```

or:

```text
turn 7:
  analyst
  status = FAILED
```

---

## 22. Revised isolation verdict

After inspecting the real implementation:

###  Actually strong

- Separate kernel per isolated agent.
- Cross-agent state is explicitly exported.
- Export is limited to declared prefixes.
- Receiving kernel gets JSON-deserialized copies.
- Producer attribution exists.
- Mutable Python object identity does not cross the kernel boundary.
- Complex non-JSON objects are naturally excluded.

###  Needs hardening

- `SharedMemory` stores mutable references.
- No defensive copy at `put()`.
- No versioning.
- No conflict detection.
- No per-recipient sharing.
- No size limits.
- No strict JSON validation.
- Export relies on stdout parsing.
- Shared keys are inserted into generated Python source.
- Failed turns can potentially export partial state.

###  Important architectural limitations

- `shared` mode is cooperative, not isolated.
- `NamespacePartition` is not a read-security mechanism.
- Shared values are broadcast rather than capability-scoped.
- There is no transaction/commit/rollback model.

---

## 23. The recommended K-009 architecture

I'd evolve it to:

```text
                       Agent A
                          │
                     local kernel
                          │
                     declared writes
                          │
                          ▼
                    Export Validator
                          │
             ┌────────────┴────────────┐
             │                         │
       JSON/schema check          size limit
             │                         │
             └────────────┬────────────┘
                          ▼
                    Turn Staging
                          │
                       COMMIT
                          │
                          ▼
                 Versioned SharedMemory
                          │
               ┌──────────┼──────────┐
               ▼          ▼          ▼
              Agent B    Agent C    Agent D
               │          │          │
           JSON copy   JSON copy   JSON copy
```

And the state object:

```text
SharedValue
├── key
├── value
├── producer
├── session_id
├── turn_id
├── revision
├── created_at
└── committed_at
```

---

## 24. One particularly important correction to the previous audit

Earlier I said we needed to verify whether the receiving agent receives a true copy.

**That part is now confirmed.**

`seed_code()` serializes the value and reconstructs it with `json.loads()`, so the receiving kernel does receive a separate Python object. <sup>[source]</sup>

The remaining problem is **host-side ownership of the stored value**, not cross-kernel object identity.

So the accurate statement is:

> **Kerno has real cross-kernel value copying, but SharedMemory itself is not yet defensively immutable/versioned.**

That's a much more precise assessment.

---

## Next gate: `kerno/communication.py`

The next subsystem should be the communication layer.

We now have:

```text
KernelRuntime
      ↓
KernelPool
      ↓
MultiAgentLoop
      ↓
Isolation / SharedMemory
      ↓
??? Communication
```

That layer determines whether `AgentBus` is merely a convenience wrapper or a genuine **agent protocol** with ordering, delivery, correlation, broadcast, failure handling, and backpressure.

That is the next place where we can determine whether Kerno is becoming a real **agent-native execution platform** rather than simply a Python/Jupyter orchestration library.

---

## `kerno/comms/channel.py`

This file changes the picture significantly. Kerno isn't relying only on `SharedMemory` for communication; it has a **second, real-time machine communication channel built on Jupyter/IPython Comm messages over IOPUB**. <sup>[source]</sup>

The distinction is important:

```text
SharedMemory
    = state transfer

KernoComm
    = live event/telemetry channel
```

That is a good architectural separation.

---

## 1. The communication architecture

The current design is:

```text
                    Kerno
                      │
               ┌──────┴──────┐
               │             │
               ▼             ▼
         SharedMemory     KernoComm
               │             │
         state/data       events
               │             │
               ▼             ▼
          Agent B        Orchestrator
```

`KernoComm` deliberately keeps structured machine messages out of stdout/stderr. <sup>[source]</sup>

That is exactly what you want.

---

## 2. Why the IOPUB design is important

The kernel emits:

```text
comm_msg
```

through Jupyter's IOPUB channel.

The orchestrator receives those messages while the normal output collector is already reading IOPUB.

The source explicitly explains that this avoids a competing reader consuming execution messages such as the terminal `idle` message. <sup>[source]</sup>

This is a **very important correctness fix**.

The bad architecture would be:

```text
                 IOPUB
                   │
          ┌────────┴────────┐
          ▼                 ▼
   output collector    comm thread
          │                 │
          └──────┬──────────┘
                 ▼
             race condition
```

The current design instead does:

```text
                 IOPUB
                   │
                   ▼
             Output Collector
                   │
          ┌────────┴────────┐
          ▼                 ▼
      cell output       comm_msg
                            │
                            ▼
                       KernoComm
```

That single-reader discipline is the right approach.

---

## 3. `CommMessage` is deliberately simple

The protocol currently contains:

```text
kind
payload
agent_name
session_id
timestamp
```

<sup>[source]</sup>

And predefined kinds include:

```text
progress
anomaly
decision
result
custom
```

This gives Kerno a useful event vocabulary without making the protocol unnecessarily complicated.

---

## 4. Progress messages

An agent can emit:

```python
progress("loading data", 0.1)
```

or:

```python
progress("model trained", 0.8, accuracy=0.92)
```

which becomes:

```text
progress
├── step
├── pct
└── details
```

<sup>[source]</sup>

This is useful for:

- UI progress bars
- CLI progress
- telemetry
- dashboards
- orchestration decisions
- human monitoring

---

## 5. Anomaly messages are more important than they look

The kernel can emit:

```python
signal_anomaly(
    "Negative revenue values detected",
    "warning",
    count=42
)
```

This creates an explicit machine-readable signal.

So instead of parsing:

```text
stdout:
"WARNING: 42 negative values..."
```

the orchestrator receives:

```text
{
    "kind": "anomaly",
    "payload": {
        "description": "...",
        "severity": "warning",
        "count": 42
    }
}
```

That's much more reliable.

---

## 6. Decision messages are especially interesting

The agent can say:

```python
signal_decision(
    "Found 3 outlier clusters. Should I investigate all?",
    ["investigate_all", "top_only", "skip"]
)
```

<sup>[source]</sup>

This is potentially the beginning of a **human-in-the-loop protocol**:

```text
Agent
  │
  ▼
decision_required
  │
  ▼
Orchestrator
  │
  ├── automatic policy
  │
  └── human
          │
          ▼
       decision
          │
          ▼
       Agent
```

However, there is a major limitation.

---

## 7. `decision_required()` does NOT actually pause execution

The source explicitly says:

> "Execution continues without blocking." <sup>[source]</sup>

So currently:

```text
Agent
  │
  ▼
decision signal
  │
  ├──────────────► orchestrator
  │
  ▼
continues executing
```

rather than:

```text
Agent
  │
  ▼
decision signal
  │
  ▼
WAITING
  │
  ▼
decision
  │
  ▼
RESUME
```

That means the current API is really:

> **decision notification**

not:

> **decision synchronization primitive**.

That's fine, but the documentation should make this distinction explicit.

---

## 8. Intermediate results are streaming, not state

`emit_result()` serializes the value and sends:

```text
result
├── name
├── value
└── description
```

<sup>[source]</sup>

This is different from:

```text
SharedMemory.put()
```

and that's good.

We now have three distinct semantic categories:

```text
┌──────────────────────────────────────┐
│              KERNO                   │
├──────────────────────────────────────┤
│ SharedMemory                         │
│   durable workflow state             │
├──────────────────────────────────────┤
│ AgentBus / messages                  │
│   agent-to-agent communication       │
├──────────────────────────────────────┤
│ KernoComm                            │
│   live kernel → orchestrator events  │
└──────────────────────────────────────┘
```

That separation should become an explicit architectural principle.

---

## 9. Major issue: `emit_result()` truncates the serialized payload

This line is significant:

```python
serialized = json.dumps(value, default=str)[:10_000]
```

<sup>[source]</sup>

So if the JSON representation is:

```text
50 KB
```

the transmitted message becomes:

```text
first 10 KB
```

This is **not valid JSON anymore** if truncation occurs in the middle.

For example:

```json
{"records":[{"name":"...
```

can simply be cut off.

Therefore the consumer cannot reliably parse `value` as JSON.

This is the first concrete protocol correctness issue I'd fix.

---

## 10. The fallback makes it worse

If serialization fails:

```python
serialized = str(value)[:1000]
```

So the receiver gets a string that may look like:

```text
"<some object representation>"
```

instead of structured data.

That's acceptable as an emergency diagnostic path, but not as a result protocol.

I'd change the protocol to:

```text
result
├── encoding = "json"
├── value = {...}
└── truncated = false
```

or:

```text
result
├── encoding = "text"
├── value = "..."
└── truncated = true
```

Never silently change the semantic type.

---

## 11. Large results need chunking

The docstring says:

> "Intermediate result streaming (large results sent in chunks)." <sup>[source]</sup>

But the implementation shown doesn't actually implement chunking.

It does:

```text
large result
     │
     ▼
json.dumps()
     │
     ▼
[:10_000]
     │
     ▼
truncated
```

That's not chunking.

A real protocol needs:

```text
result_start
    │
    ├── chunk 0
    ├── chunk 1
    ├── chunk 2
    └── chunk N
    │
    ▼
result_end
```

with something like:

```text
stream_id
sequence
total_chunks
payload
checksum
```

---

## 12. `CommMessage` lacks a message ID

Currently:

```text
kind
payload
agent_name
session_id
timestamp
```

There is no:

```text
message_id
```

That makes correlation difficult.

Suppose:

```text
decision
decision
decision
```

arrive quickly.

The orchestrator should be able to identify:

```text
message_id = msg-001
```

and later:

```text
response_to = msg-001
```

This becomes essential if decisions become asynchronous.

---

## 13. No correlation ID

Similarly, a message needs something like:

```text
correlation_id
```

For example:

```text
Agent:
  decision_required
      message_id = M42
      correlation_id = T7

Orchestrator:
  decision_response
      response_to = M42
      correlation_id = T7
```

Now Kerno can connect:

```text
task
  ↓
turn
  ↓
message
  ↓
response
```

without relying on timestamps.

---

## 14. Timestamp alone isn't enough for ordering

The current timestamp is:

```python
time.time()
```

<sup>[source]</sup>

This is useful for observability but not sufficient as a message ordering guarantee.

Two messages can have very close timestamps.

The protocol should include:

```text
sequence_no
```

per session/kernel.

Then:

```text
M1 seq=1
M2 seq=2
M3 seq=3
```

gives deterministic ordering.

---

## 15. The handler model is synchronous

This is another architectural issue.

`_dispatch()` does:

```text
for handler:
    handler(msg)
```

<sup>[source]</sup>

So if a handler takes:

```text
5 seconds
```

then the IOPUB processing path is potentially blocked for 5 seconds.

That's dangerous because the communication path is intentionally integrated with output collection.

A handler should ideally be:

```text
receive
  │
  ▼
append/enqueue
  │
  ▼
return immediately
  │
  ▼
worker dispatches handler
```

instead of:

```text
receive
  │
  ▼
handler
  │
  ▼
slow external operation
  │
  ▼
return
```

---

## 16. Handler exceptions are contained — good

The implementation catches handler failures:

```text
handler error
   │
   ├── log warning
   └── continue
```

<sup>[source]</sup>

That's correct.

A telemetry/UI callback should never crash kernel execution.

---

## 17. The global `set_comm_handler()` is a major architectural concern

`start()` does:

```python
set_comm_handler(self._on_comm_msg)
```

and `stop()` does:

```python
set_comm_handler(None)
```

<sup>[source]</sup>

This appears to be a **global dispatcher**.

That means if two `KernoComm` objects exist:

```text
Comm A.start()
Comm B.start()
```

B can overwrite A's handler.

Then:

```text
kernel A → global handler B
```

That's dangerous.

If Kerno is ever expected to support multiple kernels/sessions concurrently, the handler must be scoped to the kernel/session.

---

## 18. This connects directly to `KernelPool`

Remember the pool can contain:

```text
Kernel 1
Kernel 2
Kernel 3
...
```

If `KernoComm` uses a global handler:

```text
Kernel 1 ──┐
Kernel 2 ──┼──► ONE global handler
Kernel 3 ──┘
```

the communication architecture must somehow identify the source kernel.

But `_on_comm_msg()` constructs:

```python
CommMessage(
    kind=...,
    payload=...
)
```

without populating:

```text
agent_name
session_id
```

from the actual kernel context. <sup>[source]</sup>

So source attribution is currently weaker than the dataclass suggests.

---

## 19. This is a critical concurrency gate

The system currently wants:

```text
                KernelPool
       ┌──────────┼──────────┐
       ▼          ▼          ▼
    Kernel A   Kernel B   Kernel C
       │          │          │
       ▼          ▼          ▼
     Comm       Comm       Comm
       │          │          │
       └──────────┼──────────┘
                  ▼
             orchestrator
```

The protocol needs:

```text
session_id
kernel_id
agent_id
turn_id
message_id
sequence
```

otherwise messages can become ambiguous.

---

## 20. `agent_name` and `session_id` exist but aren't populated

This is particularly revealing.

The dataclass defines:

```text
agent_name
session_id
```

but `_on_comm_msg()` creates:

```text
kind
payload
```

only. <sup>[source]</sup>

So the metadata fields currently default to:

```text
agent_name = ""
session_id = ""
```

unless some later layer modifies the message.

This means the protocol schema is ahead of its actual implementation.

---

## 21. The kernel itself also doesn't send identity metadata

The emitted message is:

```python
{
    "kind": kind,
    "payload": payload,
    "ts": time.time()
}
```

<sup>[source]</sup>

No:

```text
kernel_id
agent_id
session_id
turn_id
```

So the orchestrator has to infer the source from the connection/context.

That is fragile once multiple kernels are active.

The kernel-side setup should know its identity:

```python
_kerno_comm = Comm(...)
_kerno_context = {
    "session_id": "...",
    "agent_id": "...",
    "kernel_id": "...",
}
```

and include it in every message.

---

## 22. Security: `Comm` is a capability surface

The kernel exposes:

```text
progress()
signal_anomaly()
signal_decision()
emit_result()
```

These are useful APIs.

But an agent can call them arbitrarily.

For example:

```python
for i in range(1_000_000):
    progress("spam", i / 1_000_000)
```

This could flood the orchestrator.

So KernoComm needs:

```text
max_messages/sec
max_payload_bytes
max_result_streams
```

and perhaps coalescing:

```text
progress
progress
progress
progress
```

→ only emit the latest progress state at a controlled rate.

---

## 23. The communication architecture needs backpressure

Right now the conceptual flow is:

```text
kernel
  │
  ▼
IOPUB
  │
  ▼
collector
  │
  ▼
handler
```

A robust system needs:

```text
kernel
  │
  ▼
IOPUB
  │
  ▼
collector
  │
  ▼
bounded queue
  │
  ├── normal
  ├── backpressure
  └── overflow policy
          │
          ▼
       dispatcher
```

Otherwise a fast agent can produce messages faster than the orchestrator can process them.

---

## 24. Recommended protocol v2

I'd evolve `CommMessage` to:

```text
CommMessage
├── message_id
├── session_id
├── kernel_id
├── agent_id
├── turn_id
├── sequence
├── kind
├── timestamp
├── correlation_id
├── payload
├── encoding
└── final
```

For example:

```json
{
  "message_id": "msg_0192",
  "session_id": "sess_01",
  "kernel_id": "kernel_04",
  "agent_id": "analyst",
  "turn_id": 7,
  "sequence": 18,
  "kind": "progress",
  "timestamp": 1786860000.12,
  "correlation_id": "turn_7",
  "payload": {
    "step": "training",
    "pct": 0.72
  }
}
```

Now the message is independently traceable.

---

## 25. Communication should become event-sourced

This is where Kerno could become substantially more powerful.

Instead of thinking:

```text
CommMessage = notification
```

think:

```text
CommMessage = event
```

Then:

```text
Agent
  │
  ▼
Event
  │
  ├── UI
  ├── telemetry
  ├── audit log
  ├── orchestrator
  ├── checkpoint
  └── replay
```

A session could produce:

```text
001 TURN_STARTED
002 PROGRESS
003 PROGRESS
004 ANOMALY
005 RESULT
006 TURN_COMPLETED
```

That gives you a natural execution trace.

---

## 26. And now the architecture converges

We have now inspected:

```text
KernelRuntime
      │
      ▼
KernelPool
      │
      ▼
MultiAgentLoop
      │
      ▼
Isolation
      │
      ▼
KernoComm
```

The resulting model is:

```text
                       KERNO SESSION
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
          execution        state        events
              │             │             │
              ▼             ▼             ▼
        KernelRuntime   SharedMemory   KernoComm
              │             │             │
              ▼             ▼             ▼
          KernelPool    agent state    event stream
              │
              ▼
          agent turn
              │
              ▼
       MultiAgentLoop
```

This is no longer just a "Jupyter helper."

It is developing into an **agent execution substrate around Jupyter kernels**.

---

##  Current priority findings

### P0 — fix before calling communication production-grade

1. **Global `set_comm_handler()` is unsafe for concurrent kernels.**
2. **Messages lack reliable kernel/agent/session/turn identity.**
3. **`emit_result()` truncates JSON rather than implementing chunking.**
4. **No message ID / correlation ID / sequence number.**
5. **Synchronous handlers can block the IOPUB collection path.**

### P1

6. Add bounded queues/backpressure.
7. Add message/payload rate limits.
8. Implement actual result chunking.
9. Make decision requests optionally blocking.
10. Add explicit message lifecycle (`START/CHUNK/END`).
11. Strictly validate payload encoding.
12. Add per-kernel communication ownership.

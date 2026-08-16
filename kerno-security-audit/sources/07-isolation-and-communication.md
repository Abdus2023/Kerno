[← Back to index](./README.md) | [Next section →](./08-kernel-output-and-execution-design.md)

## [25] USER

Continue

---

## [26] CHATGPT (gpt-5-6)

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
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/isolation.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

## Continue — `kerno/isolation.py` audit

I checked the actual isolation implementation on your `arena/01a0064f-kerno` branch. This confirms the architecture is **conceptually good but not yet as strong as its documentation claims**. <sup>[source]</sup>

The important distinction is:

> **The receiving kernel gets a copy, but `SharedMemory` itself does not protect its stored value from mutation.**

That changes the isolation verdict.

---

# 1. The intended model

Kerno defines two mechanisms:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
SharedMemory
    =
explicit cross-agent data

NamespacePartition
    =
allowed namespace writes
```

</details>

The intended boundary is:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

This is a good model. <sup>[source]</sup>

---

# 2. The first important bug: `SharedValue` is frozen, but `value` is not immutable

This is subtle.

The code uses:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
@dataclass(frozen=True)
class SharedValue:
    value: Any
```

</details>

<sup>[source]</sup>

`frozen=True` prevents:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
sv.value = something_else
```

</details>

but it does **not** prevent:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
sv.value["secret"] = "modified"
```

</details>

if `value` is a dictionary.

Likewise:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
sv.value.append(...)
```

</details>

works if `value` is a list.

So:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
frozen dataclass
       ≠
immutable value
```

</details>

This is an important correctness distinction.

---

# 3. Example of the problem

Suppose Agent A does:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
data = {
    "result": 42,
    "items": [1, 2, 3]
}
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
shared.put("data", data, "analyst")
```

</details>

Now the host-side `SharedMemory` contains a reference to `data`.

If the original kernel-side object is somehow retained/reused, or if host code receives and mutates the same object:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
data["items"].append(999)
```

</details>

the supposedly shared value can change.

The `SharedValue` object itself remains frozen, but:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
SharedValue
    │
    └── value ─────► mutable dict
```

</details>

is still mutable.

---

# 4. The good part: `seed_code()` really does create a copy

This part is much stronger.

The code generates:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
sv_key = _json.loads(...)
```

</details>

rather than directly injecting the original Python object. <sup>[source]</sup>

So the receiving kernel gets:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Agent A's object
       │
       X
       │
Agent B's object
```

</details>

There is no Python object identity crossing the boundary.

That is genuinely good isolation.

---

# 5. But "immutable" is still technically incorrect

The receiving agent can do:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
data["items"].append(999)
```

</details>

and mutate its **local copy**.

That's perfectly fine.

The important property is:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Agent B mutation
      │
      X
      │
SharedMemory
```

</details>

doesn't propagate back.

So the correct terminology should be:

> **defensive serialized copies**

rather than:

> immutable JSON copies.

That wording matters for a security/architecture document.

---

# 6. Bigger problem: `SharedMemory.put()` doesn't serialize at insertion

Current:

<details>
<summary><strong>💻 Code Block (python) — 7 lines</strong></summary>

```python
def put(self, key, value, producer):
    sv = SharedValue(
        key=key,
        value=value,
        producer=producer,
    )
    self._values[key] = sv
```

</details>

<sup>[source]</sup>

A stronger implementation would validate/copy immediately:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

That would establish the invariant:

> Once inserted, SharedMemory owns its own copy of the value.

That is much safer.

---

# 7. There is also a key-collision problem

`SharedMemory` is:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._values: dict[str, SharedValue]
```

</details>

and:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
self._values[key] = sv
```

</details>

<sup>[source]</sup>

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Agent A:
results_summary = A

Agent B:
results_summary = B
```

</details>

produces:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
results_summary → B
```

</details>

Agent A's value disappears.

There is no:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
version
revision
conflict
CAS
sequence
```

</details>

mechanism.

This becomes significant in parallel multi-agent execution.

---

# 8. Current model assumes sequential turns

The multi-agent loop we examined is sequential:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
A
↓
B
↓
C
```

</details>

So key collisions are deterministic.

But if Kerno evolves toward:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
A ─────┐
       ├── SharedMemory
B ─────┘
```

</details>

then:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
A writes key X
B writes key X
```

</details>

becomes a race.

The data model should eventually support:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
key
version
producer
turn_id
timestamp
```

</details>

at minimum.

---

# 9. Namespace isolation is only write detection

This is another important distinction.

`NamespacePartition` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
allows(agent, key)
```

</details>

and:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
violations(...)
```

</details>

<sup>[source]</sup>

This controls:

> what the agent is **allowed to export/write**

It does **not** control:

> what Python code can read from the kernel.

In an isolated kernel, this is okay because each agent gets a separate process.

But in `shared` mode:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Agent A
   │
   ▼
same Python namespace
   ▲
   │
Agent B
```

</details>

`NamespacePartition` cannot prevent:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
secret_from_agent_b
```

</details>

from being read.

So K-009 should be explicitly described as:

> **namespace/write-policy enforcement**

rather than general information-flow security.

---

# 10. `violations()` has a particularly interesting property

The code allows a key if:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
key in shared_keys
```

</details>

even if the current agent didn't declare that key. <sup>[source]</sup>

That's intentional:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
shared state
   ↓
readable
```

</details>

But it means:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
shared key
```

</details>

is effectively a capability to expose data to every isolated agent.

Therefore the security model is:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
private
   ↓
explicitly export
   ↓
public-to-agent-set
```

</details>

not:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
private
   ↓
shared with specific recipient
```

</details>

This is an important limitation.

---

# 11. `isolate_seed_code()` confirms broadcast semantics

It simply calls:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
return shared.seed_code()
```

</details>

<sup>[source]</sup>

There is no recipient parameter.

So:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

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

</details>

all receive X.

That is fine for a cooperative pipeline.

But it prevents more sophisticated confidentiality policies such as:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
analyst → critic
analyst → narrator
analyst ✕ auditor
```

</details>

---

# 12. `seed_code()` has a serious identifier-safety issue

This is probably the most concrete bug in this file.

The key is directly inserted into Python:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
f"{sv.key} = _json.loads(...)"
```

</details>

<sup>[source]</sup>

So if a shared key is:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
foo
```

</details>

you get:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
foo = ...
```

</details>

Fine.

But if a key is malicious or invalid:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
foo; os.system("...")
```

</details>

the generated source becomes dangerous.

Even if current agents only generate trusted names, this is an unsafe code-generation boundary.

---

# 13. The same problem exists with the export prefixes

`export_code()` generates Python source containing:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
{prefixes!r}
```

</details>

which is safer because it is represented as a Python literal.

But the shared key is inserted as an actual assignment target.

The solution is simple:

### Validate keys as identifiers

Require:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
key.isidentifier()
```

</details>

or impose a stricter Kerno namespace:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
[a-zA-Z_][a-zA-Z0-9_]*
```

</details>

before inserting it into generated code.

Even better:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
__kerno_shared__ = {
    "key": value
}
```

</details>

instead of dynamically generating variable names.

---

# 14. Better design: don't generate assignment statements

Instead of:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
results_summary = ...
```

</details>

generate:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
__kerno_shared__ = _json.loads(...)
```

</details>

Then the kernel gets:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
__kerno_shared__["results_summary"]
```

</details>

This provides three benefits:

1. No identifier injection.
2. Clear shared/private distinction.
3. Easy namespace auditing.

Architecture:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

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

</details>

This is considerably cleaner.

---

# 15. Exporting is also vulnerable to output contamination

`export_code()` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
print(_json.dumps(_out))
```

</details>

<sup>[source]</sup>

It assumes the stdout returned by the kernel is exactly the JSON object.

But the execution environment may produce other output.

For example:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
print("debug")
```

</details>

during execution could cause:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
debug
{"results": 42}
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
json.loads(stdout)
```

</details>

fails.

The code handles this by returning `{}`:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
except ...:
    return {}
```

</details>

<sup>[source]</sup>

So a legitimate export can silently disappear.

---

# 16. Export protocol should use a unique framing marker

Instead of relying on raw stdout:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
{"results":42}
```

</details>

use:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
__KERNO_EXPORT_BEGIN__
{"results":42}
__KERNO_EXPORT_END__
```

</details>

Then the host extracts the framed payload.

Even better, use a dedicated Jupyter MIME/display channel if available.

That would eliminate accidental stdout interference.

---

# 17. JSON-only export is deliberately restrictive

The export code accepts:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
str
int
float
bool
None
list
dict
```

</details>

and JSON serializability. <sup>[source]</sup>

That means these won't cross:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

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

</details>

This is actually **good for isolation**.

It forces agents to convert complex objects into explicit representations.

For example:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
model_metrics = {
    "accuracy": 0.94,
    "f1": 0.91
}
```

</details>

instead of attempting:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
model = trained_model
```

</details>

This keeps the inter-agent protocol language-neutral and serializable.

---

# 18. But NaN/Infinity need consideration

Python's `json.dumps()` by default permits:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
float("nan")
float("inf")
```

</details>

using non-standard JSON representations.

That can create interoperability issues.

A strict protocol should use:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
json.dumps(value, allow_nan=False)
```

</details>

and reject invalid JSON values.

Then Kerno's state protocol is genuinely JSON-compatible.

---

# 19. There is no size limit on SharedMemory values

An agent could potentially export:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
huge_result = [...]
```

</details>

containing hundreds of MB.

Then:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

can consume enormous memory.

This connects directly to the earlier pool resource-limit issue.

Kerno needs:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
MAX_SHARED_VALUE_BYTES
```

</details>

and preferably:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
MAX_TOTAL_SHARED_MEMORY_BYTES
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
per value
  ≤ 1 MB

total session
  ≤ 32 MB
```

</details>

depending on the intended workload.

---

# 20. SharedMemory also needs lifecycle semantics

Currently:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
SharedMemory
    │
    └── values remain
```

</details>

There is no visible concept of:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
session
turn
version
expiration
checkpoint
rollback
```

</details>

This is the missing piece we predicted.

Consider:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Turn 1:
analyst → results = valid

Turn 2:
analyst → results = invalid
```

</details>

The second `put()` simply replaces the first.

There's no history.

For an agent runtime, I'd strongly prefer:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

---

# 21. This enables transactional state

Then the architecture becomes:

<details>
<summary><strong>💻 Code Block (text) — 14 lines</strong></summary>

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

</details>

That would solve the earlier problem where `_export_turn()` runs from `finally`.

The exported state can become atomic:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
turn 7:
  analyst
  status = COMMITTED
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
turn 7:
  analyst
  status = FAILED
```

</details>

---

# 22. Revised isolation verdict

After inspecting the real implementation:

### 🟢 Actually strong

- Separate kernel per isolated agent.
- Cross-agent state is explicitly exported.
- Export is limited to declared prefixes.
- Receiving kernel gets JSON-deserialized copies.
- Producer attribution exists.
- Mutable Python object identity does not cross the kernel boundary.
- Complex non-JSON objects are naturally excluded.

### 🟠 Needs hardening

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

### 🔴 Important architectural limitations

- `shared` mode is cooperative, not isolated.
- `NamespacePartition` is not a read-security mechanism.
- Shared values are broadcast rather than capability-scoped.
- There is no transaction/commit/rollback model.

---

# 23. The recommended K-009 architecture

I'd evolve it to:

<details>
<summary><strong>💻 Code Block (text) — 27 lines</strong></summary>

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

</details>

And the state object:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

---

# 24. One particularly important correction to the previous audit

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

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

That layer determines whether `AgentBus` is merely a convenience wrapper or a genuine **agent protocol** with ordering, delivery, correlation, broadcast, failure handling, and backpressure.

That is the next place where we can determine whether Kerno is becoming a real **agent-native execution platform** rather than simply a Python/Jupyter orchestration library.

---

## [27] USER

Continue 

---

## [28] CHATGPT (gpt-5-6)

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
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"AgentBus","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"AgentMessage","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"communication","topn":30}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/comms/channel.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

## Continue — `kerno/comms/channel.py`

This file changes the picture significantly. Kerno isn't relying only on `SharedMemory` for communication; it has a **second, real-time machine communication channel built on Jupyter/IPython Comm messages over IOPUB**. <sup>[source]</sup>

The distinction is important:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
SharedMemory
    = state transfer

KernoComm
    = live event/telemetry channel
```

</details>

That is a good architectural separation.

---

# 1. The communication architecture

The current design is:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

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

</details>

`KernoComm` deliberately keeps structured machine messages out of stdout/stderr. <sup>[source]</sup>

That is exactly what you want.

---

# 2. Why the IOPUB design is important

The kernel emits:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
comm_msg
```

</details>

through Jupyter's IOPUB channel.

The orchestrator receives those messages while the normal output collector is already reading IOPUB.

The source explicitly explains that this avoids a competing reader consuming execution messages such as the terminal `idle` message. <sup>[source]</sup>

This is a **very important correctness fix**.

The bad architecture would be:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

The current design instead does:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

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

</details>

That single-reader discipline is the right approach.

---

# 3. `CommMessage` is deliberately simple

The protocol currently contains:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
kind
payload
agent_name
session_id
timestamp
```

</details>

<sup>[source]</sup>

And predefined kinds include:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
progress
anomaly
decision
result
custom
```

</details>

This gives Kerno a useful event vocabulary without making the protocol unnecessarily complicated.

---

# 4. Progress messages

An agent can emit:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
progress("loading data", 0.1)
```

</details>

or:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
progress("model trained", 0.8, accuracy=0.92)
```

</details>

which becomes:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
progress
├── step
├── pct
└── details
```

</details>

<sup>[source]</sup>

This is useful for:

- UI progress bars
- CLI progress
- telemetry
- dashboards
- orchestration decisions
- human monitoring

---

# 5. Anomaly messages are more important than they look

The kernel can emit:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
signal_anomaly(
    "Negative revenue values detected",
    "warning",
    count=42
)
```

</details>

This creates an explicit machine-readable signal.

So instead of parsing:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
stdout:
"WARNING: 42 negative values..."
```

</details>

the orchestrator receives:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

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

</details>

That's much more reliable.

---

# 6. Decision messages are especially interesting

The agent can say:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
signal_decision(
    "Found 3 outlier clusters. Should I investigate all?",
    ["investigate_all", "top_only", "skip"]
)
```

</details>

<sup>[source]</sup>

This is potentially the beginning of a **human-in-the-loop protocol**:

<details>
<summary><strong>💻 Code Block (text) — 17 lines</strong></summary>

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

</details>

However, there is a major limitation.

---

# 7. `decision_required()` does NOT actually pause execution

The source explicitly says:

> "Execution continues without blocking." <sup>[source]</sup>

So currently:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

rather than:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

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

</details>

That means the current API is really:

> **decision notification**

not:

> **decision synchronization primitive**.

That's fine, but the documentation should make this distinction explicit.

---

# 8. Intermediate results are streaming, not state

`emit_result()` serializes the value and sends:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
result
├── name
├── value
└── description
```

</details>

<sup>[source]</sup>

This is different from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
SharedMemory.put()
```

</details>

and that's good.

We now have three distinct semantic categories:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

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

</details>

That separation should become an explicit architectural principle.

---

# 9. Major issue: `emit_result()` truncates the serialized payload

This line is significant:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
serialized = json.dumps(value, default=str)[:10_000]
```

</details>

<sup>[source]</sup>

So if the JSON representation is:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
50 KB
```

</details>

the transmitted message becomes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
first 10 KB
```

</details>

This is **not valid JSON anymore** if truncation occurs in the middle.

For example:

<details>
<summary><strong>💻 Code Block (json) — 1 lines</strong></summary>

```json
{"records":[{"name":"...
```

</details>

can simply be cut off.

Therefore the consumer cannot reliably parse `value` as JSON.

This is the first concrete protocol correctness issue I'd fix.

---

# 10. The fallback makes it worse

If serialization fails:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
serialized = str(value)[:1000]
```

</details>

So the receiver gets a string that may look like:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
"<some object representation>"
```

</details>

instead of structured data.

That's acceptable as an emergency diagnostic path, but not as a result protocol.

I'd change the protocol to:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
result
├── encoding = "json"
├── value = {...}
└── truncated = false
```

</details>

or:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
result
├── encoding = "text"
├── value = "..."
└── truncated = true
```

</details>

Never silently change the semantic type.

---

# 11. Large results need chunking

The docstring says:

> "Intermediate result streaming (large results sent in chunks)." <sup>[source]</sup>

But the implementation shown doesn't actually implement chunking.

It does:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

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

</details>

That's not chunking.

A real protocol needs:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

with something like:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
stream_id
sequence
total_chunks
payload
checksum
```

</details>

---

# 12. `CommMessage` lacks a message ID

Currently:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
kind
payload
agent_name
session_id
timestamp
```

</details>

There is no:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
message_id
```

</details>

That makes correlation difficult.

Suppose:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
decision
decision
decision
```

</details>

arrive quickly.

The orchestrator should be able to identify:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
message_id = msg-001
```

</details>

and later:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
response_to = msg-001
```

</details>

This becomes essential if decisions become asynchronous.

---

# 13. No correlation ID

Similarly, a message needs something like:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
correlation_id
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

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

</details>

Now Kerno can connect:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
task
  ↓
turn
  ↓
message
  ↓
response
```

</details>

without relying on timestamps.

---

# 14. Timestamp alone isn't enough for ordering

The current timestamp is:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
time.time()
```

</details>

<sup>[source]</sup>

This is useful for observability but not sufficient as a message ordering guarantee.

Two messages can have very close timestamps.

The protocol should include:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
sequence_no
```

</details>

per session/kernel.

Then:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
M1 seq=1
M2 seq=2
M3 seq=3
```

</details>

gives deterministic ordering.

---

# 15. The handler model is synchronous

This is another architectural issue.

`_dispatch()` does:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
for handler:
    handler(msg)
```

</details>

<sup>[source]</sup>

So if a handler takes:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
5 seconds
```

</details>

then the IOPUB processing path is potentially blocked for 5 seconds.

That's dangerous because the communication path is intentionally integrated with output collection.

A handler should ideally be:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

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

</details>

instead of:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

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

</details>

---

# 16. Handler exceptions are contained — good

The implementation catches handler failures:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
handler error
   │
   ├── log warning
   └── continue
```

</details>

<sup>[source]</sup>

That's correct.

A telemetry/UI callback should never crash kernel execution.

---

# 17. The global `set_comm_handler()` is a major architectural concern

`start()` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
set_comm_handler(self._on_comm_msg)
```

</details>

and `stop()` does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
set_comm_handler(None)
```

</details>

<sup>[source]</sup>

This appears to be a **global dispatcher**.

That means if two `KernoComm` objects exist:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
Comm A.start()
Comm B.start()
```

</details>

B can overwrite A's handler.

Then:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kernel A → global handler B
```

</details>

That's dangerous.

If Kerno is ever expected to support multiple kernels/sessions concurrently, the handler must be scoped to the kernel/session.

---

# 18. This connects directly to `KernelPool`

Remember the pool can contain:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
Kernel 1
Kernel 2
Kernel 3
...
```

</details>

If `KernoComm` uses a global handler:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
Kernel 1 ──┐
Kernel 2 ──┼──► ONE global handler
Kernel 3 ──┘
```

</details>

the communication architecture must somehow identify the source kernel.

But `_on_comm_msg()` constructs:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
CommMessage(
    kind=...,
    payload=...
)
```

</details>

without populating:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
agent_name
session_id
```

</details>

from the actual kernel context. <sup>[source]</sup>

So source attribution is currently weaker than the dataclass suggests.

---

# 19. This is a critical concurrency gate

The system currently wants:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

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

</details>

The protocol needs:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
session_id
kernel_id
agent_id
turn_id
message_id
sequence
```

</details>

otherwise messages can become ambiguous.

---

# 20. `agent_name` and `session_id` exist but aren't populated

This is particularly revealing.

The dataclass defines:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
agent_name
session_id
```

</details>

but `_on_comm_msg()` creates:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
kind
payload
```

</details>

only. <sup>[source]</sup>

So the metadata fields currently default to:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
agent_name = ""
session_id = ""
```

</details>

unless some later layer modifies the message.

This means the protocol schema is ahead of its actual implementation.

---

# 21. The kernel itself also doesn't send identity metadata

The emitted message is:

<details>
<summary><strong>💻 Code Block (python) — 5 lines</strong></summary>

```python
{
    "kind": kind,
    "payload": payload,
    "ts": time.time()
}
```

</details>

<sup>[source]</sup>

No:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
kernel_id
agent_id
session_id
turn_id
```

</details>

So the orchestrator has to infer the source from the connection/context.

That is fragile once multiple kernels are active.

The kernel-side setup should know its identity:

<details>
<summary><strong>💻 Code Block (python) — 6 lines</strong></summary>

```python
_kerno_comm = Comm(...)
_kerno_context = {
    "session_id": "...",
    "agent_id": "...",
    "kernel_id": "...",
}
```

</details>

and include it in every message.

---

# 22. Security: `Comm` is a capability surface

The kernel exposes:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
progress()
signal_anomaly()
signal_decision()
emit_result()
```

</details>

These are useful APIs.

But an agent can call them arbitrarily.

For example:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
for i in range(1_000_000):
    progress("spam", i / 1_000_000)
```

</details>

This could flood the orchestrator.

So KernoComm needs:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
max_messages/sec
max_payload_bytes
max_result_streams
```

</details>

and perhaps coalescing:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
progress
progress
progress
progress
```

</details>

→ only emit the latest progress state at a controlled rate.

---

# 23. The communication architecture needs backpressure

Right now the conceptual flow is:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

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

</details>

A robust system needs:

<details>
<summary><strong>💻 Code Block (text) — 17 lines</strong></summary>

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

</details>

Otherwise a fast agent can produce messages faster than the orchestrator can process them.

---

# 24. Recommended protocol v2

I'd evolve `CommMessage` to:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

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

</details>

For example:

<details>
<summary><strong>💻 Code Block (json) — 15 lines</strong></summary>

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

</details>

Now the message is independently traceable.

---

# 25. Communication should become event-sourced

This is where Kerno could become substantially more powerful.

Instead of thinking:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
CommMessage = notification
```

</details>

think:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
CommMessage = event
```

</details>

Then:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

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

</details>

A session could produce:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
001 TURN_STARTED
002 PROGRESS
003 PROGRESS
004 ANOMALY
005 RESULT
006 TURN_COMPLETED
```

</details>

That gives you a natural execution trace.

---

# 26. And now the architecture converges

We have now inspected:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

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

</details>

The resulting model is:

<details>
<summary><strong>💻 Code Block (text) — 17 lines</strong></summary>

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

</details>

This is no longer just a "Jupyter helper."

It is developing into an **agent execution substrate around Jupyter kernels**.

---

# 🔴 Current priority findings

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

---

---
[← Previous section](./06-kernel-pool-and-concurrency.md) | [Back to index](./README.md) | [Next section →](./08-kernel-output-and-execution-design.md)

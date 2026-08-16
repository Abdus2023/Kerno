# Kerno Deep Audit

> Repository-level audit of [`Abdus2023/Kerno`](https://github.com/Abdus2023/Kerno) at the current `main` branch.
> Date: 2026-08-15 · Head commit: `563f65c` — "Enrich skill library and improve kernel reliability (#2)"

Kerno describes itself as:

> **"A kernel-native agent runtime — a persistent execution environment where an LLM takes consecutive actions over time, building state, running arbitrary code, and producing reproducible artifacts."**

The conceptual progression that motivates this audit:

| Jupyter | Kerno |
|---|---|
| `Notebook → Kernel → Execute → State → Outputs` | `Agent → Kernel → Action → Persistent State → Artifacts` |

That is a substantially different abstraction from treating an LLM as a simple request/response API. It suggests a **persistent computational substrate for an agent** — much closer to the kernel-native/agent-runtime direction.

---

## Executive verdict

Kerno has a genuinely interesting architectural core, but it is not yet a security-grade agent runtime.

| Area | Assessment |
|---|---|
| Core concept | Strong |
| Jupyter/kernel integration | Strong |
| Agent-loop architecture | Good |
| Persistence / program-agent concept | Promising |
| Notebook reproducibility | Good direction |
| Observability | Good direction |
| Testing breadth | Strong structurally |
| Security boundary | Weak / unsafe for hostile input |
| Dependency discipline | Needs work |
| Lifecycle/error isolation | Needs work |
| Production readiness | Not yet |
| Research prototype value | High |

**The most important conclusion:**

> Kerno is better understood today as a sophisticated Python/Jupyter agent orchestration framework than as a hardened "kernel-native runtime."

That is not a criticism of the idea. In fact, the kernel-native idea is the strongest part of the project.

---

## Phase I — Repository audit

### 1. The architecture is conceptually right

The README makes the fundamental design explicit:

> "Connect a brain (LLM) to a body (Jupyter kernel)."

And the underlying mapping is sound:

```
              ┌──────────────┐
              │     LLM      │
              │ decision     │
              │ making       │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │    Loop      │
              │ reactive     │
              │ reflect      │
              │ plan         │
              │ debate       │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │    Kernel    │
              │  IPython     │
              │  namespace   │
              │  execution   │
              └──────┬───────┘
                     │
            ┌────────┼────────┐
            ▼        ▼        ▼
          state    output   artifacts
```

This is substantially more interesting than the usual `prompt → LLM → tool call → result → prompt`, because the computational state itself becomes persistent working memory.

The actual implementation confirms that this is not merely marketing: `KernelRuntime` uses `jupyter_client.KernelManager`, starts a kernel, establishes channels, waits for readiness, and executes code through the kernel client.

### 2. The kernel abstraction is real

`KernelRuntime` is one of the strongest components. It provides:

- kernel startup
- readiness waiting
- shutdown
- interrupt
- restart
- code execution
- streaming execution
- namespace inspection
- object inspection
- memory measurement
- execution metrics
- tracing

The basic lifecycle is:

```
KernelRuntime()
      │
      ▼
   start()
      │
      ▼
KernelManager
      │
      ▼
KernelClient
      │
      ▼
wait_for_ready()
      │
      ▼
execute()
```

That is a legitimate kernel runtime abstraction over Jupyter rather than a fake subprocess wrapper.

**Particularly good:** the runtime captures execution metadata:

```
kernel.id
cell.num
cell.code_preview
cell.duration_ms
cell.had_error
cell.output_bytes
cell.n_images
error.ename
error.evalue
```

This is exactly the sort of information needed for an agent execution trace.

### 3. Kerno's biggest architectural strength: the loop/kernel separation

The `BaseLoop` abstraction is clean conceptually. It owns:

```
Task
  ↓
Prompt construction
  ↓
LLM
  ↓
Generated cell
  ↓
Kernel
  ↓
CellOutput
  ↓
History
  ↓
Recovery
  ↓
next iteration
```

And specialized loops provide different policies:

- Reactive
- Reflect/revise
- Plan/execute
- Hierarchical
- Multi-agent
- Debate

The repository contains corresponding loop modules, while the public `run()` API selects the strategy.

This is a good separation:

- The LLM isn't responsible for kernel management.
- The kernel isn't responsible for planning.
- The loop isn't responsible for persistence.

That's the right direction.

### 4. The execution model is more sophisticated than the README initially suggests

The `BaseLoop` has:

- execution limits
- error counting
- recovery hints
- history compression
- memory retrieval
- plugin lifecycle hooks
- checkpoints
- telemetry
- completion signaling
- session results

For example, it detects repeated errors and injects a strategy-change message rather than endlessly repeating the same operation. This gives Kerno a real:

```
Observe
   ↓
Act
   ↓
Observe result
   ↓
Classify failure
   ↓
Recover
   ↓
Act differently
```

loop. That is an important distinction from a naive autonomous code executor.

### 5. But the "kernel-native" claim needs qualification

Kerno currently delegates the actual computational substrate to:

```
Jupyter
   ↓
jupyter_client
   ↓
IPython kernel
```

The dependency manifest explicitly includes `jupyter-client` and `ipykernel`. So architecturally:

```
Kerno
  └── agent runtime
       └── Jupyter kernel runtime
            └── IPython execution
```

rather than:

```
Kerno
  └── native computational kernel
```

That's perfectly reasonable. But it means Kerno's innovation is primarily agent orchestration around a persistent computational kernel, not replacement of the Jupyter kernel. And that's actually a strong niche.

### 6. The ProgramAgent layer is ambitious

`ProgramAgent` is considerably more ambitious than a simple session runner. It introduces:

- `AgentIdentity`
- `AgentProfile`
- `SessionContext`
- `KnowledgeEngine`
- `CapabilityRegistry`
- `SkillProposal`
- `SessionVault`
- `Provenance`

The design explicitly states that the agent isn't simply an LLM inside a loop; it is an architecture using an LLM loop as one component.

Conceptually:

```
ProgramAgent
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
   Identity        Knowledge      Capabilities
       │              │              │
       └──────────────┼──────────────┘
                      ▼
                SessionContext
                      │
                      ▼
                 LLM + Kernel
                      │
                      ▼
                 SessionResult
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
   Knowledge       Skills         Profile
```

This is approaching a persistent agent operating environment, rather than merely an agent library.

### 7. The skill system is powerful — but increases the attack surface

The repository has a large skill subsystem and many examples. The README advertises: data analysis, visualization, ML, statistics, NLP, time series, synthetic data, feature engineering, anomaly detection, reporting, documents, graphs, simulation, optimization, finance, experiments, APIs, web, filesystem, SQL, LLM tools.

This is excellent from a usability perspective. But security-wise it creates a fundamental equation:

```
More skills
    =
More available capabilities
    =
Larger attack surface
```

The skill system therefore needs to be treated as **capability security**, not merely convenience APIs.

### 8. Critical security finding: the AllowList is not a sandbox

This is the most important finding in the audit.

Kerno explicitly describes its security model as **static analysis + runtime import hooks**. That's useful defense-in-depth. But it is not sufficient to treat the kernel as hostile-code containment.

The static checker is regex-based. For example, it checks patterns such as `subprocess`, `requests`, `socket`, `open(..., "w")`, `os.remove`, `shutil`, `eval`, `exec`, `compile`, `__import__`, and import statements. Regex filtering is inherently brittle for Python code.

More importantly, there is an **architectural bypass**: in `_run.py`, the allowlist wrapper around `kernel.execute()` is installed only in the branch handling `reactive`, `reflect`, `plan`. The `hierarchical`, `multi_agent`, and `debate` branches construct their agents before that wrapping logic.

So the intended invariant — `allowlist → every generated cell → kernel` — is not globally enforced. The actual architecture can become:

```
allowlist
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
   reactive/reflect/plan   other loops
          │                   │
          ▼                   ▼
       guarded            potentially
       execute             unguarded
```

**Severity: HIGH.** This should be fixed before describing the security profiles as reliable enforcement boundaries.

### 9. Critical security finding: the allowlist itself is bypassable

Even in the guarded path, the security mechanism is not a true Python sandbox.

For example, `data_analysis()` permits `pathlib`, `os.path`, `IPython`, `matplotlib`, `pandas`, `numpy`, ... while trying to prohibit filesystem/network operations. But capability restrictions based on imports and regexes don't establish a security boundary.

Examples of problematic categories include:

- `Path.write_text()`
- `Path.write_bytes()`

when `pathlib` is allowed. Likewise, high-level libraries can initiate operations that aren't represented by obvious `open(...)` or `requests(...)` syntax — e.g., data libraries can support URL-backed loading.

The important distinction:

> Blocking syntax is not equivalent to blocking capability.

### 10. Runtime import hook is also not a sandbox

The generated kernel code replaces `builtins.__import__` with a restricted implementation. That can be useful as a policy layer. But the process is still a normal Python process. Therefore:

```
Python process
   │
   ├── native extensions
   ├── filesystem
   ├── environment
   ├── OS resources
   ├── network
   ├── signals
   └── process APIs
```

remain fundamentally part of the same trust domain.

**Recommendation:** rename the concept internally from "sandbox" to **execution policy / capability guard** — unless Kerno runs the kernel inside a genuinely isolated environment.

### 11. Docker exists — but isolation isn't automatically guaranteed

The repository contains `Dockerfile.kerno`, `docker-compose.yml`, `docker-compose.prod.yml`, and `nginx.conf`. That's good. But containerization should be made an explicit part of the security architecture rather than an optional deployment artifact.

For an agent that executes arbitrary Python generated by an LLM, the desired model should be:

```
Host
 │
 └── hardened container / VM
       │
       ├── Kerno
       │
       └── Jupyter kernel
```

not:

```
Host Python
    │
    └── Jupyter kernel
          │
          └── LLM-generated code
```

The latter should be considered trusted-code execution.

### 12. Another important lifecycle problem

`run()` starts the kernel with `with KernelRuntime(...) as kernel:` — which is good. But the communications subsystem is started separately:

```python
comm = KernoComm(kernel).start()
...
result = agent.run(task)
...
comm.stop()
```

There is no `finally` surrounding the agent execution in the shown implementation, so an exception inside the loop can potentially leave communication resources in an undesirable state. This should become:

```python
try:
    result = agent.run(task)
finally:
    comm.stop()
```

**Severity: Medium.** Not fundamental, but important for long-running agents.

### 13. Notebook persistence is one of Kerno's best ideas

The notebook layer is particularly interesting. The project can transform an agent session into a reproducible `.ipynb` artifact and resume from notebooks. This produces:

```
LLM reasoning/action
       ↓
kernel execution
       ↓
cell history
       ↓
Notebook
       ↓
reproducible artifact
```

That's powerful because the notebook becomes an **execution ledger**. It can preserve generated code, outputs, errors, execution sequence, and computational state representation. This is a natural bridge between AI agent execution and scientific/reproducible computing.

### 14. But notebook reproducibility is not identical to state reproducibility

This distinction matters. A notebook records code + outputs. It does not automatically guarantee:

- exact environment
- exact package versions
- exact external data
- exact random state
- exact filesystem
- exact network responses
- exact model response

Therefore Kerno should eventually distinguish:

- **Artifact reproducibility** — "Here is the generated notebook."
- **Execution reproducibility** — "This notebook can reproduce the same result under a declared environment and input snapshot."

That's a much higher bar.

### 15. Checkpointing has a hidden architectural problem

`BaseLoop._auto_checkpoint()` generates code inside the same kernel to scan globals and serialize DataFrames/models. That's clever. But it means the checkpoint mechanism itself becomes code executed in the agent's computational environment:

```
Agent
 ↓
Kernel
 ↓
checkpoint code
 ↓
filesystem
```

The runtime should ideally have a privileged host-side checkpoint service rather than relying on arbitrary Python executing inside the same namespace. Otherwise the checkpoint mechanism inherits the same security problems as agent-generated code.

### 16. Dependency design needs tightening

The core dependencies are surprisingly heavy: `jupyter-client`, `ipykernel`, `pandas`, `numpy`, `matplotlib`, `scikit-learn`, `scipy`, `requests`, `openpyxl`, ...

For a "kernel-native agent runtime," split into modules such as:

```
kerno-core
kerno-kernel
kerno-skills-data
kerno-skills-ml
kerno-skills-docs
kerno-skills-web
kerno-agent
kerno-cli
```

because otherwise a minimal Kerno installation becomes a large analytical environment. The README already conceptually has optional skill packs, but the base dependency list still contains much of the analytical stack.

### 17. Testing architecture is actually impressive

The test tree is broad. It includes `unit/`, `behavioral/`, `integration/`, `property/` — with tests covering runtime, loops, memory, security, plugins, notebook audit, program scale, skills, telemetry, composition, error classification, OpenAI compatibility, OpenRouter, multi-agent, debate, snapshots, and pipeline behavior.

This is much better than the typical early-stage agent project.

But: no `.github/workflows` directory was found through the repository contents endpoint. So we should not claim CI is currently validating the repository based solely on the existence of this test suite. **Tests existing ≠ tests running continuously on GitHub.**

### 18. The test suite appears to understand the right failure domains

The existence of `test_loop_pre_execution.py`, `test_plugin_pre_execution.py`, `test_security.py`, `test_pipeline.py`, `test_program_scale.py`, `test_notebook_audit.py` is encouraging — the architecture has already evolved beyond a simple happy-path prototype.

However, the next generation of tests should explicitly test **security invariants**, not just individual blocking rules. For example:

```
INVARIANT:
If security profile = X,
NO execution path may reach kernel.execute()
without passing through policy P.
```

That is much stronger than testing that `"subprocess"` is blocked.

### 19. The architecture currently has too many responsibilities in the public facade

`kerno/__init__.py` is ~18 KB, while `_run.py` itself is ~12.5 KB. The repository tree also contains many top-level modules and subsystems: kernel, loop, skills, memory, agent, plugins, telemetry, comms, security, notebook, configuration, composition, CLI, evolution, knowledge, vault, ...

This isn't necessarily bad, but it suggests the project is growing rapidly. The danger is architectural entropy. At this stage, explicit subsystem boundaries become critical.

### 20. The strongest architectural boundary should be redesigned around "Execution"

Make one abstraction central: **ExecutionEngine**. Everything that wants to execute code must go through it:

```
┌───────────────┐
│ Agent / Loop  │
└───────┬───────┘
        │
        ▼
┌─────────────────┐
│ ExecutionEngine │
├─────────────────┤
│ policy          │
│ authorization   │
│ timeout         │
│ tracing         │
│ audit           │
│ quota           │
└───────┬─────────┘
        │
        ▼
┌─────────────────┐
│ KernelRuntime   │
└─────────────────┘
```

Then there is one invariant:

> No agent, loop, plugin, skill, checkpoint, or subsystem may directly execute code except through ExecutionEngine.

That would eliminate several classes of bugs simultaneously.

### 21. Kerno needs a real capability model

The current model is essentially `regex + imports`. The next model should be:

```
Capability
   │
   ├── filesystem.read
   ├── filesystem.write
   ├── network.connect
   ├── process.spawn
   ├── package.import
   ├── notebook.write
   ├── artifact.create
   ├── secret.read
   └── kernel.execute
```

Then profiles become:

```
read_only:
    filesystem.read
    artifact.create

data_analysis:
    filesystem.read
    artifact.create
    dataframe.compute

research:
    filesystem.read
    network.connect
    artifact.create

trusted:
    ...
```

The LLM should never receive "Python powers." It should receive capabilities.

### 22. The biggest conceptual opportunity: Kerno could become an Agent Kernel

This is where the repository becomes especially interesting.

Jupyter's model is:

```
Frontend
   ↓
Kernel
   ↓
Language runtime
   ↓
State
```

Kerno currently does:

```
LLM
 ↓
Agent loop
 ↓
Jupyter kernel
 ↓
State
```

The next architectural evolution could be:

```
Agent Kernel
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
     Observe     Plan       Execute
        │          │          │
        └──────────┼──────────┘
                   ▼
               State
                   │
         ┌─────────┼─────────┐
         ▼         ▼         ▼
      Memory    Artifacts   Events
```

That would move Kerno from "LLM controlling a Jupyter kernel" toward "a persistent computational kernel whose primary client is an autonomous agent." That is much more distinctive.

### 23. Kerno vs Jupyter

| Jupyter | Kerno |
|---|---|
| Human-driven | Agent-driven |
| Notebook → kernel | Task → agent loop → kernel |
| Human decides next cell | LLM decides next cell |
| Kernel state | Kernel state |
| Rich outputs | Rich outputs |
| `.ipynb` | `.ipynb` execution artifact |
| REPL | Autonomous REPL |
| Human recovery | Agent recovery |
| Manual persistence | Agent/session persistence |
| Kernel protocol | Kernel protocol + agent orchestration |

Kerno is essentially exploring what happens when you put an autonomous decision loop above the Jupyter kernel abstraction.

### 24. Severity-ranked findings

| Severity | Finding |
|---|---|
| 🔴 P0 | **Security boundary** — AllowList is not a security boundary. It should not be advertised as protection against hostile/untrusted code until execution is isolated. |
| 🔴 P0 | **Policy bypass across loop types** — The allowlist enforcement in `_run.py` is installed only for the ordinary loop path, while hierarchical/multi-agent/debate paths are constructed outside that wrapper. Fix immediately. |
| 🔴 P0 | **Same-process arbitrary Python** — The kernel is a Python process with access to host resources. For untrusted agent workloads, use container/VM/process isolation with explicit OS-level restrictions. |
| 🟠 P1 | **Capability model** — Replace regex/import security with a capability-oriented policy system. |
| 🟠 P1 | **Execution choke point** — Introduce a single ExecutionEngine through which all code execution must pass. |
| 🟠 P1 | **Lifecycle cleanup** — Make communication/plugin/checkpoint resources exception-safe with try/finally. |
| 🟠 P1 | **Reproducibility** — Record Python version, package lock, kernel version, kernel spec, environment, input hashes, artifact hashes, LLM model, prompt/config hash, random seeds — alongside notebooks. |
| 🟡 P2 | **Dependency modularization** — Move the analytical ecosystem into optional packages/extras. |
| 🟡 P2 | **CI** — Establish explicit GitHub Actions gates and distinguish "tests exist" from "tests executed by CI". |

### 25. Recommended target architecture

```
┌──────────────────────┐
│       ProgramAgent   │
│ identity / knowledge │
│ capabilities / goals │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│     AgentRuntime     │
│ observe/plan/execute │
│ reflect/checkpoint   │
└──────────┬───────────┘
           │
┌──────────┼──────────┐
▼          ▼          ▼
Memory   Capability  Policy
Engine    Engine     Engine
   │          │          │
   └──────────┼──────────┘
              ▼
┌──────────────────────┐
│   ExecutionEngine    │
│                      │
│ authorize            │
│ audit                │
│ quota                │
│ timeout              │
│ trace                │
│ checkpoint           │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│    KernelRuntime     │
│   Jupyter/IPython    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ isolated environment │
│ container / VM       │
└──────────────────────┘
```

### Final assessment (Phase I)

Kerno is not a throwaway prototype. The repository already contains a substantial architecture: kernel lifecycle management, multiple agent-loop strategies, persistent agent profiles, memory/knowledge, capabilities, notebook auditing, plugins, telemetry, checkpoints, skills, parallel kernels, and a fairly broad test organization.

But there is a crucial distinction:

> **The computational architecture is substantially ahead of the security architecture.**

The kernel/agent design is good enough to justify serious further development. The security design is not yet strong enough to let an untrusted LLM or untrusted input control the kernel safely.

The most valuable next step is not adding more skills or more agent loops — it is to make this invariant true:

```
ONE EXECUTION CHOKE POINT

LLM
 │
Agent
 │
Loop
 │
Plugin
 │
Skill
 │
Checkpoint
 │
 └──────────────► ExecutionEngine
                       │
                ┌──────┼──────┐
                │      │      │
             Policy  Audit  Quota
                │      │      │
                └──────┼──────┘
                       ▼
                  KernelRuntime
                       ▼
                 Isolated Kernel
```

Once that exists, Kerno can legitimately start becoming an Agent Kernel rather than merely an agent framework built around Jupyter.

---

## Phase II — Deep architectural audit

Moving from "what Kerno contains" to "what Kerno should become."

### 26. The real Kerno abstraction is a persistent computational state machine

The most interesting property isn't actually "LLM + Jupyter." It is this:

```
                 ┌───────────────┐
                 │ Persistent    │
                 │ Agent State   │
                 └───────┬───────┘
                         │
                         ▼
                 ┌───────────────┐
                 │ Decision      │
                 │ / Planning    │
                 └───────┬───────┘
                         │
                         ▼
                 ┌───────────────┐
                 │ Code / Action │
                 └───────┬───────┘
                         │
                         ▼
                 ┌───────────────┐
                 │ Kernel        │
                 │ Execution     │
                 └───────┬───────┘
                         │
                         ▼
                 ┌───────────────┐
                 │ New State     │
                 └───────┬───────┘
                         │
                         └──────────────► next transition
```

That's essentially a **state machine whose transition function is partially generated by an LLM** — a much stronger theoretical foundation than "AI agent with tools."

### 27. Kerno should explicitly define its state model

Currently, state is distributed across several mechanisms:

```
kernel namespace
loop history
memory
knowledge
agent profile
session context
checkpoints
plugins
telemetry
notebook
```

The danger is that there is no single authoritative definition of **"What is the state of a Kerno agent?"**

Define `AgentState` as a first-class immutable/versioned object:

```
AgentState
├── identity
├── task
├── goals
├── kernel_state_ref
├── memory_state_ref
├── capability_state
├── execution_counter
├── checkpoint_id
├── artifact_refs
├── provenance
└── policy_state
```

Then every transition becomes:

```
Stateₙ    + Actionₙ    + Observationₙ
    ↓
Stateₙ₊₁
```

That gives Kerno a formal execution model.

### 28. Introduce an event log

Kerno already has telemetry and tracing, but the architecture would become much stronger with a canonical event stream:

```
AgentCreated
TaskStarted
PlanGenerated
ActionProposed
ActionAuthorized
CodeSubmitted
KernelExecutionStarted
KernelOutputProduced
KernelExecutionFailed
RecoveryTriggered
CheckpointCreated
ArtifactCreated
MemoryUpdated
TaskCompleted
TaskFailed
```

Then:

```
Agent
   │
   ▼
 Event Log
   │
   ├── telemetry
   ├── notebook
   ├── audit
   ├── replay
   ├── debugging
   └── persistence
```

One event stream can become the backbone for the entire system.

### 29. This also solves the observability problem

Instead of every subsystem independently producing telemetry (`loop → telemetry`, `kernel → telemetry`, `plugins → telemetry`, `memory → telemetry`), use:

```
                 EventBus
                     │
        ┌────────────┼─────────────┐
        ▼            ▼             ▼
    Telemetry      Audit        Recorder
        │            │             │
        ▼            ▼             ▼
     metrics       security      notebook
```

This reduces duplicated instrumentation.

### 30. Execution should have an explicit transaction lifecycle

The current execution model is roughly `generate code → execute → collect output`. A stronger model:

```
                 Action
                    │
                    ▼
               ┌─────────┐
               │ Prepare │
               └────┬────┘
                    ▼
              Authorization
                    │
               ┌────┴────┐
               │         │
             DENY       ALLOW
               │         │
               ▼         ▼
             reject    execute
                          │
                       observation
                          │
                        validate
                          │
                    ┌──────┴──────┐
                    ▼             ▼
                commit        rollback
```

This matters enormously once Kerno supports filesystem, network, databases, or external APIs.

### 31. "Code execution" and "capability execution" should be separate

Today a skill may effectively cause Python to perform an operation. Instead define:

```
Agent
  ↓
Capability Request
  ↓
Capability Broker
  ↓
Approved implementation
```

For example:

```json
{
  "capability": "filesystem.read",
  "path": "/workspace/data.csv"
}
```

The agent does **not** need to generate `open("/workspace/data.csv")` — the broker handles it. Then Python code can remain useful for computation:

```python
df = load_dataset("dataset:123")
```

while the capability broker controls how data is obtained.

### 32. This leads to a two-plane architecture

**Control plane:**

```
Agent
Loop
Policy
Memory
Capabilities
Scheduler
Identity
Audit
```

**Data plane:**

```
Kernel
Filesystem
Network
Database
GPU
Artifacts
External services
```

With a strict boundary:

```
CONTROL PLANE
       │
       │ authorized capability
       ▼
    BROKER
       │
       ▼
   DATA PLANE
```

This is much easier to secure than letting the LLM directly manipulate the data plane.

### 33. Multi-agent execution needs stronger isolation

There are two fundamentally different meanings of "multi-agent":

**Shared kernel** (easy but dangerous — agents can accidentally or intentionally modify each other's state):

```
Agent A ─┐
          ├── Kernel
Agent B ─┤
          │
Agent C ─┘
```

**Isolated kernels** (should be the default):

```
Agent A → Kernel A
Agent B → Kernel B
Agent C → Kernel C
```

Then explicit shared resources can be introduced:

```
Agent A ─┐
Agent B ─┼── Shared Artifact Store
Agent C ─┘
```

That provides much cleaner isolation.

### 34. Parallel kernels should become a first-class scheduler

The repository already has infrastructure around parallel kernels. The next step is to turn that into a `KernelPool`:

```
KernelPool
├── acquire()
├── release()
├── restart()
├── health_check()
├── quota()
├── isolate()
└── destroy()
```

Then the agent runtime doesn't care whether execution occurs in one kernel, a fresh kernel, a pooled kernel, a remote kernel, a container, or a VM — that becomes an implementation detail.

### 35. Kerno should separate "session" from "kernel"

A session is: `identity, task, memory, history, artifacts, policy, provenance`.

A kernel is: `Python process, namespace, execution state`.

They are not the same thing. Therefore:

```
Session
    │
    ├── Kernel A
    ├── Kernel B
    └── Kernel C
```

should be possible. For example, a session could survive a kernel restart:

```
Session
    │
    ├── checkpoint
    └── new Kernel
```

That's much more robust.

### 36. Kernel restart should not mean agent restart

This should become a hard invariant:

```
kernel crash ≠ agent crash
```

Instead:

```
Kernel failure
       │
       ▼
      detect
       │
       ▼
   checkpoint
       │
       ▼
  restart kernel
       │
       ▼
  restore state
       │
       ▼
    resume agent
```

This is one of the biggest advantages of treating Kerno as a runtime rather than a wrapper.

### 37. State restoration needs deterministic serialization

Simply serializing arbitrary Python globals is unreliable. Objects may contain open files, sockets, threads, native handles, database connections, generators, and external resources.

Therefore checkpointing should distinguish **Serializable State** from **Ephemeral Runtime State**:

```
Checkpoint
├── variables
├── artifacts
├── metadata
├── random seeds
├── package environment
└── provenance

NOT:
├── sockets
├── open file handles
├── threads
└── live network connections
```

### 38. Notebook should become a projection, not the database

Don't make `.ipynb` the canonical persistence format. Instead:

```
Canonical Event/State Store
           │
      ┌────┼────┐
      ▼    ▼    ▼
  Notebook  JSON  Audit
   JSON     API    Log
```

The notebook becomes one **projection** of the execution. That solves many reproducibility and versioning problems.

### 39. Kerno needs a provenance graph

Represent:

```
Task
  │
  ├── Action
  │     │
  │     └── Code
  │           │
  │           └── Execution
  │                 │
  │                 ├── Input
  │                 └── Output
  │
  └── Artifact
```

Then you can answer: *Where did this artifact come from?*

```
report.pdf
    ↑
analysis dataframe
    ↑
cell #27
    ↑
agent action #31
    ↑
task abc123
```

That's extremely valuable for scientific, industrial, and enterprise use.

### 40. This is where Kerno can differentiate from ordinary agent frameworks

Most agent frameworks optimize: `prompt, tools, memory, routing`.

Kerno can instead optimize: `persistent computation state, execution provenance, recovery, reproducibility`.

The tagline could eventually become something like:

> **Kerno — a persistent execution kernel for autonomous programs.**

rather than simply "agent runtime."

### 41. Proposed Kerno v2 architecture

```
kerno/
├── core/
│   ├── state.py
│   ├── event.py
│   ├── action.py
│   ├── observation.py
│   └── result.py
│
├── agent/
│   ├── agent.py
│   ├── identity.py
│   ├── session.py
│   └── lifecycle.py
│
├── execution/
│   ├── engine.py
│   ├── policy.py
│   ├── authorization.py
│   ├── quota.py
│   └── audit.py
│
├── kernel/
│   ├── runtime.py
│   ├── pool.py
│   ├── lifecycle.py
│   └── transport.py
│
├── capabilities/
│   ├── registry.py
│   ├── filesystem.py
│   ├── network.py
│   ├── process.py
│   └── artifacts.py
│
├── memory/
│   ├── working.py
│   ├── persistent.py
│   └── retrieval.py
│
├── provenance/
│   ├── graph.py
│   ├── recorder.py
│   └── replay.py
│
├── isolation/
│   ├── local.py
│   ├── docker.py
│   └── vm.py
│
├── notebook/
│   ├── exporter.py
│   ├── importer.py
│   └── projection.py
│
└── skills/
```

This isn't about reorganizing files for aesthetics — it establishes **security and lifecycle boundaries in the architecture itself**.

### 42. The critical invariants

- **K-001 — Single execution boundary:** Every executable agent action passes through `ExecutionEngine`.
- **K-002 — No direct privileged capability:** Kernel code cannot directly obtain privileged host capabilities.
- **K-003 — Kernel isolation:** Untrusted workloads execute in an OS-level isolation boundary.
- **K-004 — Session/kernel independence:** Kernel failure does not imply session failure.
- **K-005 — Event completeness:** Every externally meaningful execution transition emits an event.
- **K-006 — Provenance:** Every artifact is traceable to the execution that created it.
- **K-007 — Checkpoint consistency:** A checkpoint identifies exactly which state and event sequence it represents.
- **K-008 — Capability authorization:** Capabilities are granted explicitly, not inferred from Python syntax.
- **K-009 — Multi-agent isolation:** Agents do not share mutable kernel state unless explicitly configured.
- **K-010 — CI evidence:** Repository test presence is never treated as evidence that CI passed until CI actually executes.

### 43. Suggested development order

Do **not** implement dozens of new features first.

- **Phase A — Security:** `ExecutionEngine → CapabilityBroker → Isolation`
- **Phase B — State:** `AgentState, EventLog, Checkpoint, Provenance`
- **Phase C — Lifecycle:** `KernelPool, KernelRestart, SessionResume`
- **Phase D — Multi-agent:** `Agent isolation, Shared artifacts, Message passing`
- **Phase E — Reproducibility:** `Environment lock, Input hashes, Artifact hashes, Notebook projection, Replay`
- **Phase F — Advanced intelligence:** only then expand `planning, debate, reflection, skill evolution, multi-agent coordination`.

### 44. The deeper connection to the Jupyter question

```
IPython
    │
    ▼
Jupyter Kernel
    │
    ▼
Persistent computational state
    │
    ▼
Kerno KernelRuntime
    │
    ▼
Agent-controlled execution
    │
    ▼
Persistent autonomous program
```

Jupyter solved: **How can a human interact continuously with a computational kernel?**

Kerno is attempting to solve: **How can an autonomous program interact continuously with a computational kernel while retaining state, memory, capabilities, artifacts, and recovery?**

That is a legitimate next layer above Jupyter. The most important immediate work is not more intelligence — it is making **execution, state, capabilities, isolation, and provenance formally correct**.

---

## Phase III — Kerno audit: execution semantics, correctness, and runtime contracts

The previous phase established the central security issue. Now the deeper question: **Can Kerno provide a deterministic, well-defined execution model when an LLM is continuously modifying a persistent computational state?**

### 45. Define the execution contract first

Right now the conceptual operation is `LLM → generate Python → kernel.execute() → output`. A runtime needs a stronger contract:

```
ActionRequest
     │
     ├── session_id
     ├── agent_id
     ├── action_id
     ├── code
     ├── capabilities_requested
     ├── timeout
     ├── resource limits
     └── provenance
           │
           ▼
     Authorization
           │
           ▼
     Execution
           │
           ▼
     Observation
           │
           ▼
     ActionResult
```

The critical point: **code alone must not be the unit of execution** — the unit should be an `Action`.

### 46. Introduce an explicit Action model

```python
@dataclass(frozen=True)
class Action:
    id: str
    session_id: str
    agent_id: str
    kind: str
    payload: object
    capabilities: frozenset[str]
    timeout_ms: int
    created_at: datetime
```

Then:

```python
@dataclass(frozen=True)
class ActionResult:
    action_id: str
    status: ActionStatus
    stdout: str
    stderr: str
    outputs: tuple[ArtifactRef, ...]
    duration_ms: int
    error: Optional[ExecutionError]
```

This gives every execution a stable identity — essential for retries, audit, replay, provenance, debugging, distributed execution, billing/quota, and exactly-once/at-least-once semantics.

### 47. Separate Action from Code

Not every action should require Python:

```
Action
├── ExecuteCode
├── ReadArtifact
├── WriteArtifact
├── SearchMemory
├── InvokeCapability
├── SendMessage
├── CreateCheckpoint
├── SpawnAgent
└── RequestHumanApproval
```

Then the kernel is merely **one execution backend**, preventing Kerno from becoming "everything is Python":

```
                 Action
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
       Kernel    Capability   Service
       backend     broker     backend
```

### 48. The LLM should produce intent, not privileged execution

Current model: `LLM → Python`.

Target: `LLM → Action/Plan → Authorization → Execution`.

```json
{
  "kind": "ExecuteCode",
  "code": "df.groupby('category').mean()",
  "requires": ["kernel.compute"]
}
```

```json
{
  "kind": "ReadArtifact",
  "artifact": "dataset.csv"
}
```

The LLM is **requesting an operation**, rather than directly acquiring a capability.

### 49. Add an Action State Machine

Every action should have a lifecycle:

```
                CREATED
                    │
                    ▼
               VALIDATING
                    │
                    ▼
               AUTHORIZING
              /           \
           DENY             ALLOW
            │                │
            ▼                ▼
         REJECTED         QUEUED
                             │
                             ▼
                         RUNNING
                        /       \
                   SUCCESS     FAILURE
                     │            │
                     ▼            ▼
                 COMMITTED     RECOVERING
                                   │
                              ┌────┴────┐
                              ▼         ▼
                            RETRY    FAILED
```

This makes execution behavior observable and testable, and prevents ambiguous states such as "Did Kerno execute this action, partially execute it, or merely generate it?"

### 50. Retry semantics need to be explicit

LLM systems naturally retry, but retries are dangerous for side effects. Consider `charge_credit_card()` — if the kernel times out after the external service accepted the request, blindly retrying can perform the operation twice.

Every action should declare:

```
idempotency:
    SAFE
    IDEMPOTENT
    NON_IDEMPOTENT
    UNKNOWN
```

Recovery policy:

```
SAFE:            retry automatically
IDEMPOTENT:      retry with same idempotency key
NON_IDEMPOTENT:  require explicit policy
UNKNOWN:         don't automatically retry
```

### 51. Error handling needs a taxonomy

The repository already has error classification, which is a good foundation. Take it further into runtime-level categories:

```
ExecutionError
├── ValidationError
├── AuthorizationError
├── SyntaxError
├── RuntimeError
├── TimeoutError
├── ResourceLimitError
├── KernelCrashedError
├── DependencyError
├── CapabilityError
├── ExternalServiceError
├── SerializationError
└── ProvenanceError
```

Then recovery strategies become type-directed:

```
SyntaxError              → regenerate code
TimeoutError             → reduce workload / increase timeout
KernelCrashedError       → restart kernel
AuthorizationError       → request capability / stop
Non-idempotent external
failure                  → do NOT blindly retry
```

### 52. Distinguish logical failure from infrastructure failure

- **Agent failure:** the generated algorithm is wrong.
- **Kernel failure:** the Python process crashed.
- **Runtime failure:** the Kerno scheduler failed.
- **External failure:** the database/API is unavailable.

These have different recovery semantics. The architecture should preserve:

```
failure.domain
failure.phase
failure.retryability
failure.cause
```

rather than just an exception string.

### 53. The kernel needs health state

`KernelRuntime` should eventually expose:

```
KernelState
├── STARTING
├── READY
├── BUSY
├── DEGRADED
├── INTERRUPTING
├── RESTARTING
├── DEAD
└── CLOSED
```

Then the scheduler can reason about kernel health:

```
BUSY
   ↓ timeout
   ↓ INTERRUPTING
   ↓ if unsuccessful
   ↓ RESTARTING
   ↓ READY
```

rather than assuming `execute()` always returns normally.

### 54. Kernel identity needs to be persistent

Every kernel should have a stable runtime identity:

```
kernel_id
session_id
agent_id
generation
created_at
parent_kernel_id
```

A restart should produce `kernel_id = K1, generation = 2` — not make the restarted process look like an entirely unrelated kernel. This makes provenance much easier.

### 55. Execution sequence numbers

Every action should receive a monotonic sequence:

```
session S1
  action 0001
  action 0002
  action 0003
  ...
  action 0047
```

Then kernel execution can record:

```
session = S1
action = 0047
kernel_generation = 3
cell = 29
```

This gives a clean cross-reference between agent history, kernel cells, events, notebook cells, artifacts, and telemetry.

### 56. This solves notebook audit properly

Instead of treating notebook cells as the source of truth, each cell gets metadata:

```json
{
  "action_id": "act_0047",
  "session_id": "sess_001",
  "kernel_generation": 3,
  "event_start": "evt_812",
  "event_end": "evt_816",
  "code_hash": "...",
  "output_hash": "..."
}
```

Now the notebook becomes a **human-readable projection of the execution ledger** — significantly more powerful than ordinary Jupyter history.

### 57. Determinism should be explicit

LLM agents are inherently nondeterministic, but Kerno can still make execution **replayable**. Record:

```
model
model parameters
system prompt hash
task
tool/capability configuration
generated action
Python version
kernel version
package lock
random seeds
environment variables
input hashes
external resource versions
```

Then:

```
Original execution
        │
        ▼
Execution Record
        │
        ▼
Replay
```

Replay does not necessarily mean identical LLM reasoning. It can mean: **re-execute the already-recorded actions under the same declared environment.** That's a much more achievable and useful definition.

### 58. Add "replay without LLM"

This could become one of Kerno's strongest features. Suppose an agent generated `action 1 → action 2 → action 3 → action 4`. A replay mode should execute them without asking the LLM to regenerate them:

```
Agent run
    │
    ├── live mode
    └── replay mode
```

Extremely useful for debugging.

### 59. Add "fork from checkpoint"

Once state and events are formalized:

```
Checkpoint A
     │
     ├── Agent branch 1
     ├── Agent branch 2
     └── Agent branch 3
```

This enables experimentation:

```
same state
    │
    ├── GPT configuration A
    ├── GPT configuration B
    └── different planning strategy
```

Then compare outcomes. That turns Kerno into a computational experimentation platform.

### 60. This naturally creates a DAG

A session is no longer necessarily a linear sequence:

```
                 Checkpoint 10
                   /          \
                  /            \
           Experiment A      Experiment B
                │                 │
                ▼                 ▼
            Result A          Result B
```

So the state model should support `parent_state`, `branch_id`, `revision` — resembling Git conceptually (`commit → branch → merge`), but for computational state.

### 61. Kerno could eventually have "computational Git"

This is not literal Git integration — it's the same conceptual model:

```
State 0
   │
   ▼
State 1
   │
   ▼
State 2
   ├─────────────┐
   ▼             ▼
State 3A       State 3B
   │             │
   ▼             ▼
Result A      Result B
```

Then you can compare actions, outputs, artifacts, resource usage, and agent decisions between branches. That would be a genuinely novel feature for an agent runtime.

### 62. Memory should be divided into three layers

- **Working memory:** current task context (minutes / current execution).
- **Session memory:** persistent information for the current agent/session (hours / days).
- **Long-term knowledge:** reusable information (weeks / months).

```
Agent
  │
  ├── WorkingMemory
  ├── SessionMemory
  └── KnowledgeStore
```

Do not let all three collapse into one generic "memory."

### 63. Kernel state should not be memory

`df`, `model`, `temporary variable`, `imported module` are **computational state**. Whereas `"user prefers parquet"`, `"dataset contains 20M rows"`, `"previous experiment failed because X"` are **semantic memory**.

The kernel is excellent at the first; a memory subsystem should handle the second. That prevents the Jupyter namespace from becoming an accidental memory database.

### 64. Skill evolution needs provenance

The repository's skill-composition/evolution direction is ambitious. But if an agent creates or modifies a skill, record:

```
skill_id
parent_skill
author_agent
source_action
test_results
capabilities_required
version
approval
```

Then:

```
Skill v1
    │
    └── agent proposal
           │
           ▼
        validation
           │
           ▼
        Skill v2
```

A generated skill should never silently replace a trusted skill.

### 65. Generated skills need a trust level

```
UNTRUSTED
EXPERIMENTAL
VALIDATED
TRUSTED
SYSTEM
```

Execution policies can say:

```
production session:  SYSTEM, TRUSTED
research session:    + VALIDATED
sandbox:             + EXPERIMENTAL
never:               UNTRUSTED → privileged capabilities
```

This fits naturally with the capability architecture.

### 66. Plugins should obey the same boundary

A common mistake: `Python code = restricted`, `plugin = trusted`. That creates an escape hatch. Instead:

```
Agent
  │
  Plugin
  │
  CapabilityBroker
  │
  Policy
```

Plugins should declare **required capabilities** rather than automatically inheriting all runtime privileges.

### 67. Secrets require a dedicated mechanism

Do not expose environment variables wholesale to the kernel. Bad: `os.environ`. Better:

```
SecretBroker
     │
     ├── request(secret_id)
     ├── authorize()
     └── inject temporary credential
```

And preferably:

```
secret
  ↓
external service
  ↓
never stored in notebook
  ↓
never included in event payload
```

Otherwise Kerno's reproducibility/audit system can accidentally become a secret-exfiltration system.

### 68. Observability must have a redaction layer

Because Kerno records code, outputs, errors, notebook cells, telemetry, and provenance, it must assume outputs can contain secrets:

```
Execution
    ↓
Observation
    ↓
Redaction
    ↓
Event Store
```

not `Execution → Event Store`. Potential sensitive material includes: API keys, tokens, passwords, cookies, authorization headers, private data, environment variables.

### 69. Resource limits need to be OS-level eventually

Python-level timeout, memory measurement, and execution counters are useful, but production isolation needs:

```
CPU quota
memory limit
process limit
filesystem quota
network policy
disk quota
GPU quota
execution timeout
```

These belong outside the Python process:

```
Kernel container
├── CPU: 2 cores
├── RAM: 2 GB
├── disk: 5 GB
├── PIDs: 128
├── network: disabled
└── timeout: 60s
```

The runtime can then enforce policy at the OS boundary.

### 70. This gives Kerno a proper security hierarchy

```
                    Kerno
                       │
                  Policy Engine
                       │
               ┌───────┴───────┐
               ▼               ▼
        Application policy   OS policy
               │               │
               ▼               ▼
        Capability broker   Container/VM
               │               │
               └───────┬───────┘
                       ▼
                    Kernel
```

Defense in depth. The current regex/import AllowList can remain as an **additional layer**, but should no longer be the primary security boundary.

### 71. Testing should evolve into invariant testing

Instead of only testing features (`test_allowlist()`, `test_kernel()`, `test_memory()`), add invariant tests:

```
test_every_execution_passes_policy()
test_denied_capability_never_reaches_kernel()
test_kernel_restart_preserves_session()
test_action_ids_are_unique()
test_event_sequence_is_monotonic()
test_artifact_has_provenance()
test_replay_does_not_call_llm()
test_secret_never_enters_notebook()
test_agent_isolation()
```

These tests protect architecture rather than implementation details.

### 72. Add fault injection

A serious runtime needs deliberate failures. Test:

```
kill kernel
timeout execution
corrupt checkpoint
drop event
fail LLM request
fail artifact write
disconnect network
exhaust memory
exhaust disk
duplicate action
```

Then verify recovery semantics:

```
kill kernel
    ↓
detect
    ↓
checkpoint
    ↓
restart
    ↓
restore
    ↓
resume
```

This is where Kerno can move from "feature-rich framework" toward "runtime."

### 73. A proper CI matrix

```
               CI
                 │
      ┌──────────┼──────────┐
      ▼          ▼          ▼
    Static      Unit     Integration
      │          │          │
      ▼          ▼          ▼
   typing      tests     kernel tests
   lint        property   Docker
   security    tests      multi-agent
```

And separately:

```
Security CI
├── dependency audit
├── secret scanning
├── policy invariant tests
└── container hardening checks
```

The key principle remains: **don't label these gates PASS until the external CI actually executes them.**

### 74. Kerno's maturity model

- **K0 — Agent wrapper:** `LLM → Python → Jupyter`. Kerno is already beyond this.
- **K1 — Agent runtime:** `LLM → Loop → Persistent kernel → Memory/artifacts`. **Current Kerno is approximately here.**
- **K2 — Secure agent runtime:** `Agent → Policy → Capability broker → Isolated kernel`. This should be the immediate target.
- **K3 — Agent kernel:** `Persistent state + event log + replay + checkpoint/fork + capabilities + isolation + provenance`. This is where Kerno becomes genuinely differentiated.

### 75. The strategic conclusion

The repository already has enough functionality. The next problem is **not feature scarcity** — it is **semantic consolidation**:

```
                 Kerno Core
                ┌─────────────┐
                │    State    │
                └──────┬──────┘
                       │
                ┌──────▼──────┐
                │    Event    │
                └──────┬──────┘
                       │
                ┌──────▼──────┐
                │   Action    │
                └──────┬──────┘
                       │
                ┌──────▼──────┐
                │   Policy    │
                └──────┬──────┘
                       │
                ┌──────▼──────┐
                │  Execution  │
                └──────┬──────┘
                       │
                ┌──────▼──────┐
                │   Kernel    │
                └─────────────┘
```

Everything else becomes a subsystem around those primitives:

```
Kerno today    "LLM + persistent Jupyter + many capabilities"
                      ↓
Kerno next     "Stateful agent execution runtime"
                      ↓
Kerno target   "Agent-native computational kernel"
```

That target is considerably more compelling — and technically more coherent — than simply continuing to add agent features.

---

## Phase IV — Turn the audit into an implementation-grade architecture

Stop discussing Kerno as a collection of modules and define the **runtime contract** that those modules must obey.

### 76. The core abstraction should be `Execution`

Not `KernelRuntime`, `BaseLoop`, `ProgramAgent`, or `Skill` — but `Execution`. Everything else produces, authorizes, observes, or persists executions:

```
                    ┌──────────────┐
                    │    Agent     │
                    └──────┬───────┘
                           │
                     creates Action
                           │
                           ▼
                    ┌──────────────┐
                    │   Policy     │
                    └──────┬───────┘
                           │
                        authorized
                           │
                           ▼
                    ┌──────────────┐
                    │  Execution   │
                    └──────┬───────┘
                           │
                ┌──────────┼──────────┐
                ▼          ▼          ▼
             Kernel     Service    Capability
```

This gives the entire project one vocabulary.

### 77. Define the execution record

```python
ExecutionRecord(
    execution_id,
    session_id,
    agent_id,
    action_id,

    requested_at,
    started_at,
    completed_at,

    executor,
    kernel_id,
    kernel_generation,

    status,
    input_hash,
    code_hash,

    capabilities,
    resource_limits,

    stdout,
    stderr,
    outputs,

    error,
    parent_execution_id,
)
```

The record is **immutable after completion**, except for explicitly modeled lifecycle transitions.

### 78. Execution IDs become the universal correlation key

Today several subsystems have their own identifiers. Instead, everything should be correlated through `execution_id`:

```
execution_id = exec_00000042
```

appears in:

```
event log
kernel trace
telemetry
notebook metadata
artifact provenance
audit record
checkpoint
error report
```

Then debugging becomes straightforward:

```
"Why was report.csv wrong?"
  → artifact provenance
  → execution 42
  → action 42
  → generated code
  → inputs
  → kernel output
  → agent decision
```

That is runtime-grade observability.

### 79. Introduce an immutable event envelope

```python
Event(
    event_id,
    event_type,
    timestamp,

    execution_id,
    session_id,
    agent_id,

    sequence,
    payload,

    parent_event_id,
)
```

This creates a causal chain:

```
evt100 TaskStarted
    ↓
evt101 ActionProposed
    ↓
evt102 ActionAuthorized
    ↓
evt103 ExecutionStarted
    ↓
evt104 KernelOutput
    ↓
evt105 ArtifactCreated
    ↓
evt106 ExecutionCompleted
```

Now the runtime has a history that can be reconstructed.

### 80. Do not let telemetry become the event log

Telemetry and audit have different purposes:

- **Telemetry:** optimized for metrics, latency, CPU, memory, rates, dashboards.
- **Event log:** optimized for causality, state transitions, replay, audit, debugging, provenance.
- **Audit log:** optimized for security decisions, authorization, identity, privileged actions.

```
                   Event Stream
                   /      |       \
                  /       |        \
           Telemetry     Audit    Replay
```

One event source, multiple projections.

### 81. Introduce a real scheduler

Once executions become first-class, Kerno needs a scheduler:

```
Scheduler
├── pending queue
├── running executions
├── priorities
├── concurrency
├── quotas
├── cancellation
├── retry policy
└── resource allocation
```

Then:

```
Agent
   │
   ▼
Action
   │
   ▼
Scheduler
   │
   ├── Kernel A
   ├── Kernel B
   ├── Kernel C
   └── Remote executor
```

This is where Kerno starts looking like a real runtime.

### 82. Scheduling policy should be explicit

An action might specify:

```
priority = NORMAL
timeout = 30s
cpu = 1
memory = 512MB
network = NONE
```

The scheduler decides which kernel, when, and under what limits. The agent should not make those decisions directly.

### 83. Cancellation must propagate

```
User
  ↓
Agent
  ↓
Action
  ↓
Kernel
```

If the user cancels:

```
User cancellation
        ↓
Agent cancellation
        ↓
Action cancellation
        ↓
Kernel interrupt
        ↓
Execution terminated
```

Cancellation should be a first-class state transition, not an arbitrary exception:

```
RUNNING
    ↓
CANCEL_REQUESTED
    ↓
INTERRUPTING
    ↓
CANCELLED
```

### 84. Timeouts should have escalation

Don't just call `interrupt_kernel()` once. Use:

```
deadline reached
       ↓
soft interrupt
       ↓
wait
       ↓
hard termination
       ↓
kernel restart
```

For an isolated kernel:

```
soft interrupt
       ↓ SIGINT equivalent
       ↓ grace period
       ↓ SIGTERM
       ↓ SIGKILL
```

This gives predictable execution behavior.

### 85. Resource accounting should be attached to executions

For every execution:

```
CPU time
wall time
memory peak
output bytes
input bytes
disk usage
network bytes
kernel restarts
```

Then `ExecutionBudget` can be enforced:

```
Task budget:
  max_wall_time = 10 min
  max_cpu = 2 min
  max_memory = 2 GB
  max_output = 20 MB
  max_artifacts = 50
```

This is much more robust than only counting loop iterations.

### 86. Agent budgets should be hierarchical

A program agent could receive:

```
Agent budget
     │
     ├── Planning budget
     ├── Execution budget
     ├── Memory budget
     └── Child-agent budget
```

Then a child agent cannot accidentally consume unlimited resources:

```
Parent: 100 units
  ├── Child A: 30
  ├── Child B: 40
  └── Parent remaining: 30
```

This becomes particularly important for hierarchical/multi-agent loops.

### 87. Capability tokens are preferable to global permissions

Instead of `security_profile = "research"`, internally issue scoped capability grants:

```
CapabilityGrant
├── capability
├── subject
├── scope
├── expiration
├── issuer
└── constraints
```

Example:

```
filesystem.read
scope = /workspace/datasets/**
expires = session end
```

Or:

```
network.connect
scope = api.example.com:443
expires = 60 seconds
```

Far more precise.

### 88. Capabilities should be attenuable

A parent agent should be able to give a child agent **less** privilege, never more:

```
Parent capabilities
         │
         ▼
    attenuation
         │
         ▼
Child capabilities
```

Example:

```
Parent: filesystem.read, filesystem.write, network.connect
Child:  filesystem.read
```

This is a very powerful property for hierarchical agents.

### 89. Treat child agents as security principals

Each agent should have:

```
agent_id
identity
parent_agent_id
capabilities
budget
policy
session
```

Then:

```
Agent A
   ├── Agent B
   │     └── Agent D
   └── Agent C
```

forms a security tree. An event can answer *"which agent caused this external action?"* without ambiguity.

### 90. Human approval should be another capability

Don't special-case human approval in the agent loop. Represent `RequestHumanApproval` as an action:

```
Agent
  ↓
Action: delete production data
  ↓
Policy
  ↓
REQUIRES_APPROVAL
  ↓
Human
  ↓
Approved / Denied
```

This is the natural bridge to high-assurance workflows.

### 91. Kerno should distinguish dry-run from live execution

```
ExecutionMode
├── SIMULATE
├── DRY_RUN
├── LIVE
└── REPLAY
```

- **SIMULATE:** no real side effects.
- **DRY_RUN:** validate intended operations but don't commit.
- **LIVE:** real execution.
- **REPLAY:** execute recorded actions.

Especially useful for autonomous systems.

### 92. Side effects should be explicitly declared

An action could declare:

```
effects:
  filesystem.write
  network.connect
```

Then the policy engine can reason before execution:

```
Read-only analysis:  effects = none
Save report:         effects = filesystem.write
Call external API:   effects = network.connect
```

Substantially safer than inferring side effects from arbitrary Python.

### 93. Add an effect ledger

After execution:

```
Declared effects:
  filesystem.write

Observed effects:
  /workspace/report.csv
  /workspace/report.ipynb
```

Then compare `declared ⊇ observed`. If unexpected effects occur: **SECURITY VIOLATION**. A powerful defense-in-depth mechanism.

### 94. Artifact management should be content-addressed

Instead of storing `report.csv`, `report2.csv`, `report-final.csv`, internally use `sha256:<hash>` as the artifact identity:

```
ArtifactRef
├── digest
├── media_type
├── size
├── creator_execution
└── metadata
```

The user can still see `report.csv`, but internally it is immutable. This makes provenance and deduplication much easier.

### 95. Artifacts should be immutable

An execution should **create** `artifact A`, not mutate it silently. If modified:

```
artifact A
    ↓
artifact B
```

with provenance `B derived_from A`. This gives the runtime a reproducible data lineage.

### 96. The notebook is then just another artifact

Instead of `Notebook = session`, use:

```
Session
  ├── Event log
  ├── State checkpoints
  ├── Artifacts
  └── Notebook projection
```

This is cleaner and avoids overloading Jupyter's `.ipynb` format with responsibilities it was never designed to handle.

### 97. Kernel execution should become pluggable

```python
class Executor(Protocol):
    async def execute(
        self,
        action: Action,
        context: ExecutionContext,
    ) -> ExecutionResult:
        ...
```

Implementations can be:

```
LocalJupyterExecutor
DockerJupyterExecutor
RemoteJupyterExecutor
WasmExecutor
RustExecutor
SubprocessExecutor
MockExecutor
```

Strategically important: Kerno no longer depends architecturally on one execution mechanism.

### 98. This also creates a clean testing strategy

- Unit tests: `MockExecutor` — without starting IPython.
- Integration tests: `LocalJupyterExecutor`.
- Security tests: `DockerJupyterExecutor`.
- Production: `RemoteJupyterExecutor`.

This makes the test suite faster and more deterministic.

### 99. The LLM provider should also be an execution dependency

```
Brain
├── OpenAI
├── Anthropic
├── OpenRouter
├── local model
└── deterministic test model
```

The runtime should depend on an interface:

```python
class Brain(Protocol):
    async def decide(...) -> Decision:
        ...
```

Then tests can inject a `ScriptedBrain` and deterministically reproduce an agent run. Essential for reliable integration tests.

### 100. A fully replayable test becomes possible

```
ScriptedBrain
      ↓
Action 1
      ↓
Mock/real executor
      ↓
Observation
      ↓
Action 2
      ↓
...
```

Then CI can verify the entire state machine without depending on a live LLM — far superior to trying to make tests deterministic around actual model outputs.

### 101. Formal state-machine testing

Properties:

```
P1:  completed execution cannot return to running
P2:  denied action cannot execute
P3:  cancelled action cannot commit
P4:  artifact provenance always references a valid execution
P5:  event sequence is monotonic
P6:  child capability set ⊆ parent capability set
P7:  replay does not invoke Brain
P8:  kernel restart increments generation
P9:  session survives kernel restart
P10: every execution has exactly one terminal state
```

These are much more valuable than hundreds of narrow tests.

### 102. A particularly important invariant: exactly one terminal outcome

An execution must eventually be one of:

```
COMPLETED
FAILED
CANCELLED
REJECTED
EXPIRED
```

and never two simultaneously. This sounds trivial, but autonomous systems often encounter race conditions (`timeout + kernel returns + cancellation`) without a formal state machine. An atomic execution transition mechanism prevents this.

### 103. Event ordering must be defined

Distributed execution eventually creates races. Define:

```
sequence number
logical timestamp
causal parent
```

rather than relying only on wall-clock timestamps:

```
evt10 ActionStarted
evt11 KernelStarted
evt12 KernelOutput
evt13 ActionCompleted
```

Even if timestamps have millisecond collisions, sequence ordering remains deterministic.

### 104. Kerno's architecture can then become distributed

Once execution is abstracted:

```
Controller
     │
     ▼
Scheduler
     │
     ├── Worker 1 → Kernel
     ├── Worker 2 → Kernel
     └── Worker 3 → Kernel
```

The agent doesn't care where execution occurs: remote kernels, GPU workers, ARM workers, isolated cloud workers, local mobile workers, edge execution — without changing the agent abstraction.

### 105. This is where Kerno becomes potentially relevant to broader runtime work

The conceptual architecture starts resembling an **agent-native runtime**, with an important distinction from a traditional async runtime.

A normal async runtime schedules `Future, Task, IO event, Waker`. An agent-native runtime could schedule `Agent, Action, Observation, State transition, Checkpoint`:

```
Traditional runtime:  Task → Future → Poll → Waker
Agent runtime:        Agent → Action → Execute → Observe → State transition
```

Kerno is already close to this conceptual territory. The missing piece is making those concepts **first-class runtime primitives rather than behavior distributed across Python classes**.

### 106. The potential architecture becomes

```
                   KERNO RUNTIME
         ┌───────────────────────────────┐
         │           Scheduler           │
         └───────────────┬───────────────┘
                         │
                   Agent Tasks
                         │
         ┌───────────────▼───────────────┐
         │        Agent State Machine    │
         └───────────────┬───────────────┘
                         │
                      Actions
                         │
         ┌───────────────▼───────────────┐
         │       Capability Broker       │
         └───────────────┬───────────────┘
                         │
                      Policy
                         │
         ┌───────────────▼───────────────┐
         │       Execution Engine        │
         └───────┬─────────────┬─────────┘
                 │             │
                 ▼             ▼
           Kernel Worker   Service Worker
                 │
                 ▼
          Isolated Compute
                 │
                 ▼
           Observation
                 │
                 ▼
            Event Log
                 │
         ┌───────┼─────────┐
         ▼       ▼         ▼
      Memory  Artifacts  Telemetry
```

That is the architecture to use as the **Kerno target model**.

### 107. Recommended next implementation milestone

Rather than attempting a huge rewrite, define a focused **Kerno Runtime Core v0.1** milestone:

**Required**

```
[ ] Action
[ ] Execution
[ ] ExecutionResult
[ ] Event
[ ] AgentState
[ ] ExecutionEngine
[ ] Policy interface
[ ] Executor interface
[ ] execution_id correlation
[ ] explicit terminal states
[ ] cancellation
[ ] timeout
```

**Then**

```
[ ] capability broker
[ ] kernel isolation
[ ] checkpoint identity
[ ] artifact provenance
[ ] replay
```

**Only afterwards**

```
[ ] advanced multi-agent
[ ] skill evolution
[ ] sophisticated planning
[ ] distributed scheduling
```

This sequence prevents the project from becoming increasingly feature-rich while its foundational semantics remain implicit.

### 108. Bottom line of Phase IV

Kerno's biggest opportunity: it should not try to compete primarily on "How many agent loops and skills can we provide?" It should compete on:

> **"How reliably can an autonomous program execute, persist state, recover, reproduce results, and prove what happened?"**

That changes the project from an `AI framework` into an `execution runtime` and eventually an `agent-native kernel`. The Jupyter dependency then stops being the identity of Kerno — it becomes **Kerno's first kernel backend**.

And that is the architectural direction to lock down before making another large feature expansion.

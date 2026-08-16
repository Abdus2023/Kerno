# 12 — Critical Security Findings

## K-SEC-01 — direct kernel bootstrap bypass

```text
KernelPool._bootstrap()
 → KernelRuntime.execute()
```

bypasses `ExecutionEngine`.

**Fix:** trusted bootstrap path with validated/signed skills.

---

## K-SEC-02 — soft-reset reuse across trust domains

```text
Task A
 → %reset
 → Task B
```

same process.

**Fix:** no process reuse for untrusted code.

---

## K-SEC-03 — pool has no trust-domain identity

Only `task_id` is tracked.

**Fix:** tenant/principal/security-profile binding.

---

## K-SEC-04 — resource thresholds are reactive

`MAX_MEMORY`, lifetime, etc. detect problems after they occur.

**Fix:** cgroups/OS-level limits.

---

## K-SEC-05 — child-process containment

Killing the kernel doesn't automatically prove all descendants are dead.

**Fix:** worker process group/cgroup/container.

---

## K-SEC-06 — no demonstrated network boundary

Blocking Python APIs isn't enough.

**Fix:** network namespace or deny-by-default egress.

---

## K-SEC-07 — no demonstrated filesystem boundary

AllowList is not enough.

**Fix:** isolated filesystem/mount namespace.

---

## 37. The architecture should not be thrown away

This is important.

I would **not** replace Kerno's current execution architecture.

Instead:

```text
Current Kerno
      │
      ▼
ExecutionEngine
      │
      ▼
WorkerLauncher       ← NEW
      │
      ▼
SandboxedWorker      ← NEW
      │
      ▼
KernelRuntime
```

The existing code becomes the **control plane**.

The new worker layer becomes the **containment plane**.

---

## 38. Ideal final architecture

```text
                         KERNO
                           │
              ┌────────────┴────────────┐
              │                         │
        CONTROL PLANE             DATA PLANE
              │                         │
        Agent / LLM                Sandbox Worker
              │                         │
       ExecutionEngine              Jupyter
              │                         │
      CapabilityBroker              Python
              │                         │
        ApprovalGate          ┌─────────┼─────────┐
              │               │         │         │
        EffectLedger       FS        NET       PROC
              │               │         │         │
         Audit Ledger       OS isolation / cgroups
```

This is where the project becomes a serious agent execution platform rather than simply a sophisticated Python/Jupyter orchestrator.

---

## The next step

The remaining audit should now move from Python code into **deployment and packaging configuration**:

```text
Dockerfile
compose files
pyproject.toml
kernelspecs
entrypoints
systemd/service files
CI workflows
security documentation
```

We need to search specifically for:

```text
docker
podman
sandbox
seccomp
namespace
cgroup
unshare
firejail
bubblewrap
nsjail
setrlimit
resource.setrlimit
prlimit
cap_drop
network_mode
read_only
no-new-privileges
```

If none of those exist, we can make a definitive statement:

> **The `arena/01a0064f-kerno` branch has strong application-level capability governance and real process-separated Jupyter execution, but its kernel is not yet demonstrably OS-sandboxed.**

That would be the current **highest-confidence security conclusion**.

---

## deployment / OS-sandbox audit

I searched the `arena/01a0064f-kerno` branch specifically for the OS-level containment mechanisms we identified as the remaining gap.

The result is important:

> **I found no repository evidence for Docker/Podman sandboxing, seccomp, cgroups, Linux namespaces, `unshare`, Bubblewrap, Firejail, nsjail, `setrlimit`/`prlimit`, capability dropping, `no_new_privileges`, or an equivalent worker-isolation layer.**

I also searched for Docker/Compose/systemd deployment configuration and direct subprocess isolation parameters and found no matching implementation evidence.

So we can now raise the confidence of the previous conclusion substantially.

---

## 1. What Kerno definitely has

The branch has a genuine execution architecture:

```text
                    Kerno
                      │
                      ▼
              ExecutionEngine
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
 Capability       Approval        Policy
  Broker            Gate         AllowList
       │              │              │
       └──────────────┼──────────────┘
                      ▼
                KernelRuntime
                      │
                      ▼
              Jupyter/Python
                      │
                      ▼
                    OS
```

This is not a toy architecture.

The control plane is thoughtfully separated.

---

## 2. What Kerno does NOT currently demonstrate

The data-plane boundary is missing:

```text
Kernel
  │
  ├── unrestricted filesystem?       ⚠️
  ├── unrestricted network?          ⚠️
  ├── same UID?                      ⚠️
  ├── same namespaces?               ⚠️
  ├── same capabilities?             ⚠️
  ├── same environment/secrets?      ⚠️
  ├── unrestricted child processes?  ⚠️
  └── unrestricted resources?        ⚠️
```

There is no evidence in the branch that these are independently constrained.

---

## 3. This changes the security terminology

I would now explicitly avoid calling Kerno:

> "a secure Python sandbox"

Instead:

> **Kerno is a policy-governed Jupyter/Python execution system with process-level kernel isolation and strong execution provenance, but without demonstrated OS-level containment.**

That description is defensible from the source we've inspected.

---

## 4. Why the distinction matters

Suppose an agent produces:

```python
open("/etc/passwd").read()
```

The ExecutionEngine can decide:

```text
capability check
       ↓
DENY
```

Excellent.

But suppose a new Python API, library, or indirect capability provides filesystem access.

The real question becomes:

> Can the kernel process physically access `/etc/passwd`?

Without an OS boundary, potentially **yes**.

That's why:

```text
policy
```

and:

```text
containment
```

must be separate layers.

---

## 5. The same applies to networking

Kerno can prohibit obvious:

```python
requests.get(...)
```

But an attacker might use:

```python
socket
urllib
http.client
asyncio
subprocess
ctypes
native libraries
```

The strongest solution isn't to enumerate every Python API.

It is:

```text
kernel
   ↓
network namespace
   ↓
no interface
```

or:

```text
kernel
   ↓
egress firewall
   ↓
allowlist
```

Then even a previously unknown Python networking mechanism cannot simply bypass the policy.

---

## 6. Filesystem containment should work the same way

Don't try to make Python safe by banning:

```text
open
pathlib
os
shutil
```

Instead:

```text
worker filesystem
       │
       ├── /app       read-only
       ├── /input     controlled
       ├── /output    controlled
       └── /tmp       isolated
```

and make the host filesystem inaccessible.

Then Python can retain normal filesystem APIs without automatically obtaining host access.

---

## 7. Resource controls need to move outside Python

Current Kerno monitoring such as:

```text
MAX_MEMORY
MAX_LIFETIME
health checks
```

is operationally useful.

But there is a hierarchy:

```text
Telemetry
   ↓
Detection
   ↓
Recovery
   ↓
Enforcement
```

Kerno already has a lot of:

```text
Detection + Recovery
```

It needs:

```text
Enforcement
```

at the OS level.

---

## 8. Recommended worker architecture

I would add a new package:

```text
kerno/
├── execution/
│   └── engine.py
│
├── kernel/
│   ├── runtime.py
│   └── pool.py
│
└── sandbox/
    ├── spec.py
    ├── launcher.py
    ├── policy.py
    ├── limits.py
    └── lifecycle.py
```

The important separation is:

```text
ExecutionEngine
      │
      ▼
SandboxLauncher
      │
      ▼
KernelRuntime
```

The ExecutionEngine should **not** itself become a Linux sandbox implementation.

---

## 9. `SandboxSpec`

I'd define something conceptually like:

```python
SandboxSpec(
    filesystem=FilesystemPolicy(...),
    network=NetworkPolicy(...),
    resources=ResourcePolicy(...),
    identity=IdentityPolicy(...),
    environment=EnvironmentPolicy(...),
    process=ProcessPolicy(...),
)
```

Then the worker launcher becomes deterministic.

---

## 10. Example security profile

A default untrusted profile could be:

```text
profile: untrusted-python

filesystem:
    root: isolated
    host_mounts: none
    writable:
        /tmp
        /workspace/output

network:
    enabled: false

processes:
    child_processes: false

resources:
    memory: 512 MiB
    cpu: 1 CPU
    pids: 32
    disk: 100 MiB
    wall_time: 120 s

environment:
    inherit_host_env: false

secrets:
    none
```

This would be vastly stronger than an allowlist alone.

---

## 11. Security profiles should be explicit

For example:

```text
trusted
analysis
networked-analysis
document-processing
untrusted
```

Each profile gets:

```text
filesystem
network
resources
capabilities
secrets
kernel lifecycle
```

The agent cannot choose arbitrary values.

It requests:

```text
profile = "analysis"
```

and Kerno resolves that profile.

---

## 12. Never allow the agent to request:

```text
network = unrestricted
filesystem = host
memory = unlimited
secrets = all
```

Instead:

```text
Agent
  ↓
requested capabilities
  ↓
policy
  ↓
intersection
  ↓
security profile
```

Conceptually:

```text
effective_caps =
    requested
    ∩
    profile
    ∩
    tenant
    ∩
    administrator_policy
```

---

## 13. The capability broker and sandbox should cooperate

Today:

```text
CapabilityBroker
      ↓
"kernel.execute allowed"
```

We can extend the model:

```text
CapabilityBroker
      ↓
allowed execution
      ↓
WorkerSpec
      ↓
SandboxLauncher
```

So authorization doesn't merely answer:

> "May this agent execute?"

It also determines:

> "Under which containment profile may it execute?"

---

## 14. This creates a very strong security invariant

For every execution:

```text
execution_id
    ↓
security_profile
    ↓
worker_id
    ↓
kernel_generation
    ↓
capabilities
    ↓
resource limits
    ↓
filesystem policy
    ↓
network policy
```

Everything becomes traceable.

---

## 15. Provenance can then record the actual sandbox

For example:

```json
{
  "execution_id": "...",
  "worker_id": "...",
  "kernel_generation": 7,
  "security_profile": "untrusted",
  "network": "disabled",
  "filesystem": "isolated",
  "memory_mb": 512,
  "cpu": 1,
  "pids": 32,
  "capabilities": [
    "kernel.execute"
  ]
}
```

Now the audit record says not merely:

> "Python code executed."

It says:

> "Python code executed inside **this exact security configuration**."

That's a major improvement.

---

## 16. Kernel generation should become part of the security identity

We already found:

```text
generation += 1
```

on restart.

That's useful.

The identity should become:

```text
worker_id
+
kernel_generation
+
execution_id
```

So:

```text
worker-17 / generation-4
```

is distinguishable from:

```text
worker-17 / generation-5
```

even if the worker ID gets reused.

---

## 17. Soft reset should increment a state epoch too

Currently the kernel can survive:

```text
Task A
 ↓
%reset
 ↓
Task B
```

I recommend:

```text
kernel_generation = process generation
state_epoch = reset generation
```

For example:

```text
worker-17
kernel-generation: 4
state-epoch: 12
```

Every soft reset:

```text
state_epoch += 1
```

Every hard restart:

```text
kernel_generation += 1
state_epoch = 0
```

This gives much better provenance.

---

## 18. For hostile execution, skip soft reset entirely

This should become a hard rule:

```text
if trust_domain == untrusted:
    destroy_worker()
```

Not:

```text
%reset -f
```

The performance cost is real, but security isolation is more important.

---

## 19. We can recover performance differently

Instead of:

```text
same Python process
→ reset
→ reuse
```

use:

```text
pre-created isolated workers
```

For example:

```text
SandboxPool
│
├── Worker A
├── Worker B
├── Worker C
└── Worker D
```

Each worker is already isolated at the OS level.

Then:

```text
Task 1 → Worker A
Task complete → destroy A
```

and immediately:

```text
create Worker E
```

while B/C/D continue serving other tasks.

---

## 20. Even better: snapshot the base worker

If startup becomes expensive:

```text
immutable sandbox image
       ↓
fast worker clone
       ↓
fresh kernel
```

Potential technologies could include containers or lightweight Linux isolation, depending on deployment requirements.

The important point is architectural:

> **Optimize creation of isolated workers rather than weakening isolation through process reuse.**

---

## 21. The skill problem should be fixed at the same time

We found:

```text
skills_path
 ↓
read file
 ↓
runtime.execute()
```

The sandbox architecture gives us a clean solution:

```text
Skill
 ↓
validate
 ↓
hash/signature
 ↓
security profile
 ↓
sandbox worker
 ↓
bootstrap
```

Now even trusted skill code executes inside a controlled worker.

---

## 22. This eliminates a dangerous assumption

Currently Kerno effectively assumes:

```text
skill = trusted
```

A stronger architecture says:

```text
skill = trusted source
```

does **not** imply:

```text
skill = unlimited OS authority
```

That's a much better security principle.

---

## 23. Defense in depth becomes:

```text
                UNTRUSTED CODE
                      │
                      ▼
              Static policy
                      │
                      ▼
             Capability broker
                      │
                      ▼
               Approval gate
                      │
                      ▼
                Effect policy
                      │
                      ▼
                Sandbox worker
                      │
              ┌───────┼───────┐
              ▼       ▼       ▼
             FS      NET     PROC
              │       │       │
              └───────┼───────┘
                      ▼
                     OS
```

An attacker has to defeat multiple independent layers.

---

## 24. The current architecture is therefore worth preserving

I want to emphasize this because the audit isn't saying:

> "Kerno needs to be rewritten."

Quite the opposite.

The existing architecture provides an excellent **control-plane foundation**.

The missing component is essentially:

```text
SandboxLauncher
```

plus:

```text
SecurityProfile
```

and:

```text
trust-domain-aware worker lifecycle
```

---

## 25. Proposed roadmap

## Phase S0 — terminology

Document:

```text
process isolation ≠ OS sandbox
soft reset ≠ security isolation
```

---

## Phase S1 — secure lifecycle

Implement:

```text
SandboxWorker
WorkerSpec
WorkerIdentity
SecurityProfile
```

---

## Phase S2 — OS containment

Add:

```text
filesystem isolation
network isolation
UID isolation
process-tree isolation
resource limits
```

---

## Phase S3 — trust-aware pooling

Implement:

```text
tenant_id
principal_id
trust_domain
security_profile
```

as first-class pool attributes.

---

## Phase S4 — skill integrity

Add:

```text
skill hash
manifest
signature/trust state
capability declaration
```

---

## Phase S5 — adversarial testing

Test:

```text
filesystem escape
network escape
child-process persistence
resource exhaustion
secret discovery
kernel reuse
cross-tenant state leakage
skill bypass
origin escalation
```

---

## 26. P0 test: filesystem

The test should run against a real worker.

Attempt:

```python
from pathlib import Path
Path("/etc/passwd").read_text()
```

The expected result isn't merely:

```text
ExecutionEngine DENIED
```

We want:

```text
execution allowed
+
OS denies access
```

That proves containment independently of policy.

---

## 27. P0 test: network

Run:

```python
import socket
socket.create_connection(("1.1.1.1", 53), timeout=2)
```

For the `network_disabled` profile:

```text
must fail at OS/network layer
```

This proves the sandbox rather than the Python policy.

---

## 28. P0 test: process escape

Try:

```python
import subprocess
subprocess.Popen(["sleep", "300"])
```

Then terminate the kernel.

Verify:

```text
kernel dead
child dead
```

If the child survives:

```text
FAIL
```

---

## 29. P0 test: cross-session contamination

Task A:

```python
secret = "A"
```

Task B:

```python
"secret" in globals()
```

Expected:

```text
False
```

Then test harder:

```text
sys.modules
monkey patches
threads
environment
file descriptors
```

---

## 30. P0 test: environment leakage

Worker:

```python
import os
dict(os.environ)
```

Verify that sensitive host variables are absent.

Especially:

```text
API keys
cloud credentials
database credentials
GitHub credentials
tokens
private paths
```

---

## 31. P0 test: resource exhaustion

Attempt:

```python
x = bytearray(...)
```

until memory limit is reached.

Expected:

```text
worker killed/restricted
```

rather than:

```text
host OOM
```

This is one of the most important tests.

---

## 32. P0 test: fork bomb / PID exhaustion

Attempt process creation.

The worker must be restricted by:

```text
PID limit
```

or equivalent.

The host must remain healthy.

---

## 33. P0 test: secret exfiltration

With secrets deliberately present **outside** the worker:

```text
worker
 ↓
attempt filesystem/env/network access
```

Expected:

```text
cannot access
```

This tests the entire security model rather than one API.

---

## 34. Current definitive conclusion

After this additional repository search, the security picture is now considerably clearer:

### Strong

- ExecutionEngine choke point
- capability authorization
- approval handling
- policy layer
- audit correlation
- effect ledger
- cancellation
- restart
- kernel generation
- process-level Jupyter isolation

### Needs hardening

- origin separation
- skill bootstrap
- kernel pooling
- trust-domain binding
- soft-reset semantics

### Missing / unproven

- OS filesystem sandbox
- network isolation
- process-tree containment
- memory enforcement
- CPU enforcement
- PID limits
- UID isolation
- namespace isolation
- seccomp/capability restrictions
- secret/environment isolation

The targeted GitHub searches found **no implementation evidence for those OS-level mechanisms** in this branch.

---

## 35. The key architectural verdict

So the project should currently be thought of as:

```text
             Kerno
               │
       ┌───────┴────────┐
       │                │
   CONTROL PLANE     EXECUTION
       │                │
   strong           separate
   policy           process
   audit            kernel
   governance          │
                       │
                 ──────┴──────
                 MISSING WALL
                 ─────────────
                       │
                       ▼
                    host OS
```

The next engineering milestone is therefore not another allowlist rule.

It is to **build the missing wall** between the Python kernel and the host OS.

Once that exists, the existing `ExecutionEngine` + capability + provenance architecture can become the control plane for a genuinely hardened Kerno execution platform.

---

## packaging, optional skills, and the real meaning of `kerno[all]`

We should now connect the security audit with the package/install design, because the branch's `pyproject.toml` reveals an important architectural point.

The branch is **Kerno 0.2.0**, described as a "kernel-native agent runtime," with Jupyter/IPython as the execution body.

---

## 1. Your original commands are valid for this branch

The project defines these optional dependency groups:

```text
kerno[timeseries]
kerno[nlp]
kerno[graphs]
kerno[documents]
kerno[all]
```

Specifically:

| Extra | Installs | Purpose |
|---|---|---|
| `timeseries` | `statsmodels` | decomposition / forecasting |
| `nlp` | `nltk` | NLP / sentiment |
| `graphs` | `networkx` | graph analysis |
| `documents` | `pdfplumber`, `python-docx` | PDF / DOCX |
| `all` | all major optional stacks + `psutil`, `tabulate` | broad/full workstation |

This is explicitly encoded in `pyproject.toml`.

So:

```bash
pip install "kerno[all]"
```

is the appropriate command if you want the complete optional skill ecosystem.

---

## 2. But `kerno[all]` does NOT mean "everything Kerno can do"

This is an important distinction.

The base package already installs:

```text
jupyter-client
nbformat
ipykernel
pyyaml
pandas
numpy
matplotlib
scikit-learn
scipy
requests
openpyxl
```

So `all` is really:

```text
base dependencies
+
LLM providers
+
SQL
+
advanced skills
```

not literally every Python package imaginable.

---

## 3. The base installation is already quite large

Conceptually:

```text
pip install kerno

        │
        ├── Jupyter execution
        ├── data analysis
        ├── NumPy/Pandas
        ├── visualization
        ├── ML
        ├── SciPy
        ├── HTTP
        └── Excel
```

Then:

```text
kerno[all]

        │
        ├── everything above
        ├── Anthropic
        ├── OpenAI
        ├── SQLAlchemy
        ├── psutil
        ├── statsmodels
        ├── NLTK
        ├── NetworkX
        ├── pdfplumber
        ├── python-docx
        └── tabulate
```

---

## 4. `psutil` is especially interesting

Notice something subtle.

`psutil` is **not** in the base dependencies.

It appears only in:

```toml
all = [
    ...
    "psutil>=5.9",
    ...
]
```

But our kernel-pool audit found code using `psutil` for resource/health monitoring.

That means the full stack installs a dependency that the runtime can use for monitoring.

This deserves a closer look because it raises a packaging question:

> **Can core runtime functionality fail when users install plain `kerno` rather than `kerno[all]`?**

---

## 5. This is exactly the sort of dependency boundary we should test

There are two legitimate architectures.

### Architecture A — `psutil` is genuinely optional

Then Kerno must gracefully degrade:

```text
psutil installed
    → enhanced resource monitoring

psutil absent
    → basic runtime still works
```

### Architecture B — `psutil` is required by core runtime

Then it belongs in:

```toml
dependencies = [...]
```

not only:

```toml
all = [...]
```

---

## 6. This should be treated as a packaging invariant

We want:

```text
pip install kerno
        ↓
core runtime works
```

and:

```text
pip install "kerno[all]"
        ↓
full skill workstation works
```

Not:

```text
pip install kerno
        ↓
runtime eventually crashes because an optional package
was actually required
```

---

## 7. LLM providers are correctly separated

The package defines:

```text
anthropic = ["anthropic>=0.20"]
openai    = ["openai>=1.0"]
```

This is good dependency design.

A user who uses OpenAI shouldn't have to install Anthropic.

Likewise:

```bash
pip install "kerno[anthropic]"
```

shouldn't pull in OpenAI.

---

## 8. This also reduces the attack surface

This matters for our security work.

Compare:

```bash
pip install kerno
```

with:

```bash
pip install "kerno[all]"
```

The latter installs substantially more executable third-party code.

For an agent runtime, every extra package potentially expands:

```text
attack surface
+
dependency complexity
+
supply-chain surface
+
native-library surface
```

So `all` should not automatically be the recommended production deployment.

---

## 9. A better production strategy

For a controlled deployment:

```bash
pip install kerno
```

plus only what is required.

For example:

```bash
pip install "kerno[openai,timeseries,documents]"
```

This gives:

```text
OpenAI
+
time series
+
documents
```

without pulling the complete ecosystem.

---

## 10. `kerno[all]` is best viewed as a workstation profile

The README explicitly describes the project as loading a:

> full analytical workstation

into the kernel.

That's a useful conceptual model.

So I'd document the profiles as:

```text
minimal
       ↓
core runtime

analysis
       ↓
core + standard analytical skills

research
       ↓
documents + NLP + analysis

full
       ↓
everything
```

---

## 11. There is an interesting mismatch between package extras and skill inventory

The README advertises many built-in skills:

```text
data
viz
ml
stats
text
nlp
timeseries
synthetic
features
quality
report
docs
network
simulation
optimization
finance
experiment
meta
llm_tools
api
web
filesystem
sql
```

But the optional dependency groups are much smaller.

That means Kerno's skill system isn't simply:

```text
one extra = one skill
```

Instead:

```text
skill
   ↓
may use
   ↓
base dependency
or
optional dependency
```

That's fine, but it makes dependency discovery important.

---

## 12. The skill registry should declare dependencies

I would extend each skill manifest conceptually:

```yaml
name: timeseries
requires:
  python:
    - statsmodels>=0.14
capabilities:
  - kernel.execute
```

Then Kerno can answer:

```text
skill: timeseries
status: available
dependency: installed
```

or:

```text
skill: timeseries
status: unavailable
missing:
  - statsmodels
```

instead of allowing the LLM to discover the problem through an exception.

---

## 13. This fits Kerno's existing meta-skill architecture

The README already exposes:

```text
search_skills(...)
register_skill(...)
```

and describes the meta layer as supporting:

> self-registering skills, inspection, search.

So dependency metadata should become part of the skill contract.

---

## 14. A skill should have four dimensions

I recommend:

```text
SkillSpec
├── identity
├── dependencies
├── capabilities
└── security_profile
```

For example:

```text
timeseries
├── dependency: statsmodels
├── capability: kernel.execute
├── filesystem: none
├── network: none
└── security: analysis
```

For:

```text
web
```

you might have:

```text
web
├── dependency: requests
├── capability: network
├── filesystem: controlled
└── security: networked-analysis
```

This makes the security model much more compositional.

---

## 15. This is where the package architecture and sandbox architecture meet

We can model the effective worker as:

```text
Task
 │
 ▼
Requested skills
 │
 ▼
Dependency resolver
 │
 ▼
Capability resolver
 │
 ▼
Security profile
 │
 ▼
SandboxSpec
 │
 ▼
Worker
 │
 ▼
Kernel
```

This is much more powerful than simply loading every skill into every kernel.

---

## 16. `kerno[all]` should NOT imply all capabilities

This is critical.

Installing:

```bash
pip install "kerno[all]"
```

should mean:

> all software dependencies are available.

It should **not** mean:

> the agent automatically receives filesystem, network, SQL, web, or arbitrary execution authority.

These are different layers:

```text
installed package
        ≠
enabled skill
        ≠
granted capability
        ≠
OS permission
```

This should become a core Kerno security principle.

---

## 17. Example

Suppose the machine has:

```bash
pip install "kerno[all]"
```

The agent should still potentially receive:

```text
timeseries
stats
viz
```

while:

```text
filesystem
web
sql
```

remain disabled.

Then:

```text
installed ≠ authorized
```

Excellent defense in depth.

---

## 18. SQL deserves special attention

The optional dependency:

```text
sqlalchemy>=2.0
```

is included in `all`.

The README advertises:

```text
sql
connections
queries
schema inspection
table stats
```

This is potentially one of the highest-risk built-in skill families.

Why?

Because SQL capability can become:

```text
agent
 ↓
database credentials
 ↓
arbitrary query
 ↓
data exfiltration/modification
```

So SQL should absolutely have an explicit capability:

```text
database.read
database.write
database.ddl
```

rather than simply:

```text
sql
```

---

## 19. Web/API skills need the same treatment

The README advertises:

```text
api / web / filesystem
```

including downloads and file discovery.

These should not all collapse into:

```text
kernel.execute
```

Instead:

```text
web.read
web.download
filesystem.read
filesystem.write
```

should be independently governable.

---

## 20. The security model should therefore evolve from:

```text
kernel.execute
```

to:

```text
kernel.execute
filesystem.read
filesystem.write
network.connect
network.listen
database.read
database.write
process.spawn
secret.read
```

This gives the capability broker meaningful granularity.

---

## 21. And the sandbox should enforce the same semantics

For example:

```text
Capability:
    filesystem.read = /workspace/data
```

should translate to an OS policy such as:

```text
worker
├── /workspace/data    read-only
├── /workspace/output  read-write
└── host filesystem    inaccessible
```

So capability authorization and OS containment agree.

---

## 22. This gives us an important design equation

The effective authority of an agent should be:

```text
Effective Authority =
    LLM Request
    ∩
    Skill Capabilities
    ∩
    Security Profile
    ∩
    Administrator Policy
    ∩
    OS Sandbox
```

The agent gets the **intersection**, never the union.

That's the architecture I'd recommend for Kerno.

---

## 23. Packaging audit result

### Good

- clean optional dependency groups
- separate OpenAI/Anthropic extras
- dedicated timeseries/NLP/graph/document extras
- `all` convenience profile
- development dependencies separated
- package entry point defined
- Python >=3.11 declared

All of this is directly represented in `pyproject.toml`.

### Needs verification

- whether every runtime import is represented in the correct dependency group
- whether `psutil` is truly optional
- whether skill dependencies are validated before bootstrap
- whether missing optional packages produce clean diagnostics

### Architectural risk

- installing an extra package doesn't itself constrain its authority
- all-skills bootstrap can enlarge the kernel attack surface
- skill bootstrap currently deserves the same scrutiny as agent-generated execution

---

## 24. Recommended CLI behavior

Eventually:

```bash
kerno doctor
```

should report:

```text
Kerno 0.2.0

Core runtime        OK
Jupyter kernel      OK

Skills
  data              OK
  viz               OK
  ml                OK
  stats             OK
  timeseries        MISSING statsmodels
  nlp               OK
  graphs            MISSING networkx
  documents         OK

Security
  ExecutionEngine   OK
  CapabilityBroker  OK
  Sandbox           NOT CONFIGURED
  Network isolation NOT CONFIGURED
  Filesystem        HOST
  Resource limits   MONITORING ONLY

WARNING:
This installation is not suitable for hostile/untrusted code.
```

That would make the actual security posture immediately visible.

---

## 25. The most valuable next implementation isn't another skill

At this point, adding another analytical skill is less important than adding:

```text
kerno/security/
    profiles.py
    worker.py
    sandbox.py
    capabilities.py
```

Then:

```text
kerno doctor
```

can verify the environment.

---

## 26. Final architecture we're converging toward

```text
                    ┌───────────────┐
                    │      LLM      │
                    └───────┬───────┘
                            │
                            ▼
                     Agent / Loop
                            │
                            ▼
                  ┌─────────────────┐
                  │ ExecutionEngine │
                  └────────┬────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
       Capabilities     Approval       Policy
            │              │              │
            └──────────────┼──────────────┘
                           ▼
                      Skill Resolver
                           │
                           ▼
                    Security Profile
                           │
                           ▼
                     SandboxSpec
                           │
                           ▼
                    Sandbox Worker
                           │
                           ▼
                     KernelRuntime
                           │
                           ▼
                       Jupyter
                           │
                           ▼
                          OS
```

This is the **Kerno architecture I would target**.

The existing project already covers much of the upper half. The major engineering frontier is the lower half: **turning policy into independently enforceable worker isolation**.

And the packaging work we just examined gives us another important principle:

> **`kerno[all]` should install capability *implementations*, not automatically grant capability *authority*.**

---

## a critical correction to the security assessment

I found something more important in `kerno/security/allowlist.py` and its tests.

The project has a **real two-layer allowlist design**:

1. static checks before execution;
2. an import hook inside the kernel.

That is good architecture.

However, the implementation has a **fundamental limitation** that should now be elevated to a high-priority finding:

> **The allowlist is not a reliable security boundary for hostile Python code.**

It is useful as a policy guardrail, but it cannot safely replace OS-level containment.

---

## 1. The static checker is regex-based

`AllowList.check()` scans source using regular expressions:

```text
blocked pattern
      ↓
regex search
      ↓
allow / deny
```

and imports are detected with a regex matching:

```text
import X
from X import Y
```

This is useful for ordinary generated code.

But Python is a dynamic language.

A regex source scanner cannot establish:

> "This program cannot perform operation X."

It can only establish:

> "I didn't find one of the patterns I know about."

That distinction is crucial.

---

## 2. Example: the allowlist blocks the obvious attack

This is correctly rejected:

```python
import subprocess
subprocess.run(...)
```

The tests explicitly verify that.

Likewise:

```python
open(..., "w")
```

is rejected by the data-analysis profile.

Good.

---

## 3. But the security model relies on recognizing dangerous syntax

The implementation contains patterns such as:

```text
subprocess
urllib
requests
socket
shutil
importlib
os.environ
```

and blocked calls such as:

```text
eval()
exec()
compile()
__import__()
```

This catches conventional LLM-generated attacks.

It does **not** prove semantic safety.

---

## 4. The import hook has an especially important exception

The generated kernel hook says:

```text
if top_level in sys.modules:
    allow import
```

The rationale is that Jupyter internals may already have imported modules.

Operationally, that's understandable.

Security-wise, however:

> **`sys.modules` becomes part of the trusted attack surface.**

If a powerful module is already loaded into the kernel, the import restriction does not prevent access to it.

---

## 5. Even more importantly: standard-library modules are automatically allowed

The hook explicitly says:

```text
if top_level in sys.stdlib_module_names:
    allow
```

This is a major design decision.

It means the `allowed_modules` list isn't actually:

> "only these modules."

It is closer to:

> "these modules, plus every Python standard-library module, plus everything already loaded."

That is much broader.

---

## 6. Why this matters

The Python standard library contains powerful functionality.

Examples include modules capable of:

```text
process management
dynamic loading
native interfaces
filesystem operations
signals
environment manipulation
networking
```

So:

```text
"standard library"
```

cannot safely be treated as synonymous with:

```text
"safe"
```

---

## 7. `ctypes` is the obvious category to worry about

`ctypes` is part of Python's standard library.

The current kernel hook's rule:

```text
stdlib module → allow
```

therefore means a policy based solely on this hook cannot establish that native-code interfaces are unavailable.

This is exactly why an OS sandbox is still necessary.

The problem isn't just:

```text
Can the agent import subprocess?
```

It is:

```text
Can the Python process obtain arbitrary OS capabilities?
```

Those are very different questions.

---

## 8. The same problem exists with already-loaded modules

The kernel allows imports from:

```text
sys.modules
```

because Jupyter needs them.

But the security implication is:

```text
kernel internals
       ↓
loaded module
       ↓
agent can import it
```

So the module-import boundary is not a complete capability boundary.

---

## 9. The `read_only()` profile is therefore not actually OS read-only

The README describes:

```python
AllowList.read_only()
```

as:

> Maximum restriction. Read-only operations only. Suitable for untrusted environments or public-facing agents.

That wording is too strong.

The implementation blocks many obvious write operations, but it doesn't create a read-only operating-system environment.

Therefore I would change the documentation to something like:

> **Best-effort read-only Python policy; not a security sandbox.**

That would accurately reflect the implementation.

---

## 10. This is the most important documentation correction so far

Current conceptual model:

```text
read_only
   ↓
untrusted environment
```

Recommended model:

```text
read_only policy
   ↓
reduced accidental/deliberate API access
   ↓
NOT a hostile-code boundary
```

Then:

```text
untrusted environment
   ↓
OS sandbox
```

---

## 11. The tests currently prove policy behavior, not containment

The unit tests are good for what they test.

They verify things like:

```text
eval → blocked
subprocess → blocked
file write → blocked
requests → blocked
```

But they don't establish:

```text
cannot access host filesystem
cannot open network socket
cannot spawn surviving process
cannot access host secrets
cannot consume unlimited memory
```

Those require **integration/adversarial tests against a real worker**.

---

## 12. We should split security tests into three classes

## Layer A — source policy

Fast unit tests:

```text
code
 ↓
AllowList
 ↓
PASS / DENY
```

Keep these.

---

## Layer B — kernel policy

Real Jupyter integration:

```text
code
 ↓
kernel
 ↓
import hook
 ↓
PASS / DENY
```

These verify that the generated enforcement code actually works.

---

## Layer C — OS containment

Real sandbox:

```text
code
 ↓
sandboxed worker
 ↓
OS
```

These verify actual containment.

This is the layer Kerno currently lacks.

---

## 13. The security tests should deliberately attack the assumptions

For example:

### Test 1 — alternate import path

Try to reach a forbidden capability without literally writing:

```python
import subprocess
```

The point isn't to publish bypass tricks; the point is to test whether the policy depends on lexical matching.

Expected:

```text
policy may fail
OS sandbox must still hold
```

---

## 14. Test 2 — preloaded module

Because `sys.modules` is explicitly trusted, test what sensitive modules are already loaded:

```text
kernel startup
      ↓
enumerate loaded modules
      ↓
security review
```

The result should become part of the kernel security contract.

---

## 15. Test 3 — standard-library surface

Because standard-library modules are automatically permitted, audit:

```text
stdlib
   ↓
dangerous capability classification
```

Don't classify modules merely as:

```text
stdlib = safe
```

Instead:

```text
stdlib:
  pure computation
  filesystem
  network
  process
  native
  cryptographic/secrets
```

---

## 16. A better import policy

The current rule is approximately:

```text
allowed
OR already loaded
OR stdlib
```

A hardened policy should be closer to:

```text
explicitly allowed
OR
trusted kernel-internal import
```

The distinction is important.

The agent's namespace and the kernel's bootstrap namespace should not have identical authority.

---

## 17. Ideal design: separate bootstrap and agent capabilities

Conceptually:

```text
Jupyter kernel
│
├── trusted runtime imports
│
└── agent execution namespace
      │
      └── restricted capabilities
```

Instead of modifying one global `builtins.__import__` and assuming that is sufficient.

---

## 18. But even that should NOT be the final security boundary

This is the key conclusion.

Even a perfect Python import policy would still be vulnerable to:

```text
interpreter implementation bugs
native extensions
Jupyter internals
dependency vulnerabilities
unexpected object capabilities
```

Therefore:

```text
Python policy
```

should be defense-in-depth.

The authoritative boundary should be:

```text
OS sandbox
```

---

## 19. There's another architectural distinction we should introduce

Kerno currently has:

```text
AllowList
```

I recommend explicitly renaming its conceptual role to:

> **Execution Policy**

because "allowlist" sounds stronger than what it can guarantee.

Then:

```text
ExecutionPolicy
      │
      ├── static checks
      ├── runtime import policy
      └── capability requirements
```

while:

```text
SandboxPolicy
      │
      ├── filesystem
      ├── network
      ├── processes
      ├── memory
      ├── CPU
      └── identity
```

are separate.

---

## 20. This produces a clean architecture

```text
                 Agent
                   │
                   ▼
           ExecutionPolicy
                   │
         ┌─────────┼─────────┐
         ▼         ▼         ▼
      Static     Import   Capability
      checks      hook      broker
         │         │         │
         └─────────┼─────────┘
                   ▼
             SandboxPolicy
                   │
                   ▼
            Sandbox Worker
                   │
                   ▼
             KernelRuntime
```

That's the architecture I would now recommend.

---

## 21. Security levels should be renamed accordingly

### Level 0

```text
Trusted
```

No meaningful restrictions.

### Level 1

```text
Policy-controlled
```

AllowList + capability broker.

### Level 2

```text
Process-isolated
```

Fresh Jupyter process.

### Level 3

```text
OS-sandboxed
```

Filesystem/network/resource/process containment.

### Level 4

```text
Hardened
```

OS sandbox + restricted privileges + immutable worker + audit integrity.

---

## 22. One particularly important README change

The current README says:

```text
AllowList.read_only()
```

is suitable for:

> untrusted environments or public-facing agents.

I would change that.

Something like:

```text
AllowList.read_only()
```

> Best-effort execution policy for reducing filesystem/network/write operations. It is not a sandbox and must not be used as the sole containment mechanism for hostile code.

Then explicitly recommend:

```text
untrusted code → OS sandbox
```

---

## 23. The good news

This finding does **not** invalidate Kerno's architecture.

Actually, it clarifies it.

The existing security components are valuable:

```text
InputSanitizer
AllowList
CapabilityBroker
ApprovalGate
EffectLedger
ExecutionEngine
Audit
```

They form a strong **policy and governance layer**.

We simply shouldn't pretend they are equivalent to OS containment.

---

## 24. Revised security model

I would now write Kerno's threat model as:

```text
                TRUST BOUNDARY
                     │
                     ▼
              ┌─────────────┐
              │    KERNO    │
              │ Control     │
              │ Plane       │
              └──────┬──────┘
                     │
              policy / approval
                     │
                     ▼
              ┌─────────────┐
              │   WORKER    │
              │             │
              │  Jupyter    │
              │  Python     │
              └──────┬──────┘
                     │
             OS SANDBOX ← NEW
                     │
              ┌──────┼──────┐
              ▼      ▼      ▼
             FS     NET    PROC
```

The worker is where the security boundary needs to become physically enforceable.

---

## 25. Priority update

After inspecting the actual allowlist implementation, I'd reprioritize the roadmap:

| Priority | Work |
|---|---|
| **P0** | OS-level sandbox |
| **P0** | Fix/limit skill bootstrap bypass |
| **P0** | Trust-aware kernel pooling |
| **P0** | Adversarial security tests |
| **P1** | Separate trusted/runtime imports from agent imports |
| **P1** | Skill dependency manifests |
| **P1** | `kerno doctor` |
| **P1** | Resource enforcement |
| **P2** | Cryptographic audit chain |
| **P2** | More granular capabilities |

---

## 26. One more important observation about `kerno[all]`

Now that we've seen the security implementation, the earlier packaging recommendation becomes even more important.

Installing:

```bash
pip install "kerno[all]"
```

adds packages such as:

```text
statsmodels
nltk
networkx
pdfplumber
python-docx
sqlalchemy
anthropic
openai
psutil
```

Those packages become available to the kernel.

Therefore:

```text
kerno[all]
```

should be regarded as a **development/research workstation profile**, not automatically as the safest production profile.

---

## 27. Production principle

Use:

```bash
pip install kerno
```

then add only required extras.

For example:

```bash
pip install "kerno[openai,documents,timeseries]"
```

Then grant only the capabilities required by the task.

That gives:

```text
installed dependencies
        ↓
available skills
        ↓
enabled skills
        ↓
granted capabilities
        ↓
sandbox permissions
```

Every layer reduces authority.

---

## 28. The ultimate invariant

This is the invariant I would put into Kerno's security specification:

> **No Python-level policy failure may become an OS-level security failure.**

In other words:

```text
AllowList bypass
       ↓
should NOT
       ↓
host compromise
```

Instead:

```text
AllowList bypass
       ↓
Sandbox still contains worker
       ↓
attack fails
       ↓
audit records attempt
       ↓
worker can be destroyed
```

That's defense in depth.

---

## Current verdict after this round

The `arena/01a0064f-kerno` branch is **architecturally much stronger than a simple LLM wrapper**, and its security layer is substantive rather than cosmetic. The code has static policy checks, runtime import controls, capability-oriented execution, approval handling, and audit/provenance machinery.

But the `AllowList` must **not** be treated as a hostile-Python sandbox. Its regex checks, `sys.modules` exception, and automatic trust of standard-library modules demonstrate why the OS boundary is essential.

### The next decisive audit target is now:

**`ExecutionEngine → capability broker → actual policy decision → skill bootstrap → every path that can call `KernelRuntime.execute()`**

We should map **every execution path** and prove whether any path can reach the kernel without passing through the intended policy chain. That will tell us whether the previously identified bootstrap route is the only bypass—or whether there are additional execution paths.

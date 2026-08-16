# 04 — Skill Registry And Composition

---

## Next: Kerno's Skill Registry and Composition Layer

This is where the audit becomes much more interesting. The repository is implementing a **runtime skill system**, not merely a collection of helper modules.

[Kerno — `arena/01a0064f-kerno`](https://github.com/Abdus2023/Kerno/tree/arena%2F01a0064f-kerno)

### 1. The central model

`SkillRegistry` describes a skill as something loaded into a kernel namespace and tracks:

```text
name
source_file
signature
docstring
code_hash
```

It also explicitly aims to prevent LLM-generated code from shadowing registered skills and to expose a manifest that the LLM can inspect. <sup>[source]</sup>

So the intended architecture is:

```text
                    Kerno Agent
                        │
                        ▼
                 SkillRegistry
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
       loading       manifest      integrity
          │
          ▼
     KernelRuntime
          │
          ▼
     IPython namespace
```

That's a strong concept: **capabilities become inspectable, composable, and addressable objects rather than anonymous functions.**

---

## 2. Skill composition is a real dependency graph

`SkillComposer` defines:

```python
CodeSkill
FileSkill
ComposedSkill
SkillSet
```

and each skill can carry:

```text
name
code
dependencies
version
description
tags
```

<sup>[source]</sup>

This allows:

```text
data
 │
 ├── viz
 │
 ├── stats
 │
 └── introspect
       │
       └── meta
```

and:

```text
data
 │
 └── timeseries
       │
       └── finance
```

The resolver performs a dependency-first traversal before loading skills. <sup>[source]</sup>

That's a good foundation for an agentic runtime.

---

## 3. The `full_stack_skills()` definition is revealing

The full stack explicitly wires together around **27 built-in skills**, including:

```text
data
viz
introspect
meta
ml
stats
text
nlp
timeseries
synthetic
features
quality
anomaly
report
artifacts
export
docs
filesystem
synth
network
graph
simulation
optimization
finance
experiment
llm_tools
api
web
sql
```

<sup>[source]</sup>

This gives us a much clearer picture of what Kerno actually is:

```text
                           KERNO
                             │
       ┌─────────────────────┼─────────────────────┐
       │                     │                     │
     Data                  Reasoning             I/O
       │                     │                     │
   ┌───┼────┐          ┌─────┼─────┐        ┌─────┼─────┐
   ▼   ▼    ▼          ▼     ▼     ▼        ▼     ▼     ▼
 data stats features  ML   anomaly experiment API   web filesystem
       │
       ├── NLP
       ├── time series
       ├── graph
       ├── finance
       └── documents
```

This is much closer to a **general-purpose analytical agent runtime** than a conventional notebook library.

---

## 4. Important finding: dependency resolution is currently weaker than it looks

This code:

```python
for dep in skill.dependencies:
    if dep in self._skills:
        visit(dep)
```

means the resolver only visits a dependency **if that dependency is already present in the `SkillSet`**. <sup>[source]</sup>

That means:

```text
Skill A
  requires B
```

does **not** automatically produce an error if B isn't registered.

Instead:

```text
A.dependencies = ["B"]

SkillSet contains:
A

SkillSet does NOT contain:
B
```

results in:

```text
A
```

rather than:

```text
ERROR: missing dependency B
```

That is a significant semantic issue.

### Desired behavior

A robust resolver should distinguish:

```text
dependency exists
dependency missing
dependency cycle
```

For example:

```text
A → B → C
```

works.

But:

```text
A → B
```

where B is absent should produce:

```text
MissingSkillDependency:
  skill = A
  dependency = B
```

rather than silently proceeding.

---

## 5. Cycles are another issue

The current resolver uses:

```python
visited: set[str]
```

which prevents infinite recursion.

That's good.

But it doesn't distinguish:

```text
A → B → A
```

from:

```text
A → B
```

A production dependency resolver should maintain both:

```text
visited
active_stack
```

so it can detect:

```text
DependencyCycle:
A → B → C → A
```

instead of silently treating the node as already visited.

### Better algorithm

```text
visit(A)
 │
 ├── active = {A}
 │
 └── visit(B)
       │
       ├── active = {A,B}
       │
       └── visit(A)
              │
              └── A ∈ active
                    ↓
                 CYCLE
```

This becomes especially important as the skill ecosystem grows.

---

## 6. There is a more serious issue in `check_integrity()`

This is the most important finding so far.

The registry records:

```python
code_hash = sha256(source_code)
```

when registering a skill. <sup>[source]</sup>

But later, `check_integrity()` calculates:

```python
sha256(str(current_runtime_value))
```

and compares that against the **source-code hash**.

In other words:

```text
registration:

sha256(source code)
        │
        ▼
stored hash

verification:

sha256(str(runtime object))
        │
        ▼
compare with source hash
```

These are fundamentally different things.

### Example

Suppose the skill source is:

```python
def hello():
    return "hello"
```

Registration:

```text
SHA256(source text)
=
abc123...
```

Verification:

```text
str(hello)
=
<function hello at 0x...>

SHA256(...)
=
xyz789...
```

Therefore:

```text
abc123 != xyz789
```

even though the function has **not been modified**.

So `check_integrity()` is currently very likely to report false violations.

This should be classified as:

> **Integrity verification logic defect — high priority.**

The security intent is good, but the evidence mechanism is incorrect.

---

## 7. How integrity verification should work

There are several valid designs.

### Option A — retain the original source

Store:

```text
source code
source hash
```

and compare the current source before execution.

### Option B — hash normalized code

For generated functions, inspect:

```python
inspect.getsource(function)
```

then hash the normalized source.

But this can be problematic for dynamically executed code.

### Option C — hash the registered code object

For pure Python functions:

```text
function.__code__
```

can provide:

```text
co_code
co_consts
co_names
co_varnames
```

but this is not necessarily a stable semantic identity across Python versions.

### Option D — explicit provenance

For Kerno, I prefer:

```text
SkillRecord
├── source_hash
├── source_origin
├── registration_time
├── version
└── exported_names
```

and verify the **actual source artifact**, not the string representation of the live object.

---

## 8. The namespace protection idea is good — but needs hardening

The registry attempts to install:

```python
class _ProtectedNamespace(dict):
    def __setitem__(...)
```

and then:

```python
_ip.user_ns.__class__ = _ProtectedNamespace
```

<sup>[source]</sup>

The conceptual goal is excellent:

```text
LLM-generated code
       │
       ▼
user namespace
       │
       ▼
"pandas" / "analyze" / "forecast"
       │
       ▼
protected skill?
       │
       ├── yes → reject
       └── no  → allow
```

But this is an area that absolutely needs a real-IPython integration test.

Why?

Because modifying the `__class__` of an existing dictionary-like namespace is dependent on the runtime object's implementation and Python's layout rules.

The code catches only:

```python
except NameError:
```

which handles "not in IPython", but **not arbitrary failure when changing the namespace class**. <sup>[source]</sup>

So:

```text
IPython environment
       │
       ▼
get_ipython()
       │
       ▼
user_ns
       │
       ▼
__class__ replacement
       │
       ├── works → protection
       └── fails → potentially load failure
```

needs explicit testing.

---

## 9. Another subtle security issue: protection is not isolation

Even if `_ProtectedNamespace` works perfectly, it only protects names.

It does **not** sandbox Python.

A skill running inside the kernel can potentially access Python capabilities available to that process.

For example, namespace protection doesn't prevent:

```python
import os
```

or:

```python
open(...)
```

or other Python runtime operations.

Therefore:

```text
SkillRegistry protection
```

should **not** be described as:

```text
sandbox
```

It is better described as:

> **namespace integrity / capability-name protection**

rather than execution isolation.

This distinction is crucial for an agent runtime.

---

## 10. `load_code()` is powerful

The registry accepts arbitrary code strings:

```python
registry.load_code(kernel, code, name)
```

and executes them through:

```text
kernel.execute(...)
```

<sup>[source]</sup>

That means the actual trust boundary is:

```text
Agent / LLM
      │
      ▼
generated Python
      │
      ▼
SkillRegistry
      │
      ▼
KernelRuntime.execute()
      │
      ▼
Python process
```

This is a **very powerful primitive**.

It enables Kerno's flexibility, but it also means the kernel is essentially a code-execution environment.

So the architecture must explicitly distinguish:

```text
trusted skill code
```

from:

```text
LLM-generated code
```

and:

```text
external/untrusted skill
```

---

## 11. The architecture needs a capability trust model

I would recommend evolving it toward:

```text
                     Skill
                       │
             ┌─────────┴─────────┐
             │                   │
          metadata             trust
             │                   │
      ┌──────┼──────┐      ┌─────┼─────┐
      ▼      ▼      ▼      ▼     ▼     ▼
     name   hash   deps   core  user  external
```

For example:

```text
TRUSTED_CORE
TRUSTED_USER
UNTRUSTED_GENERATED
UNTRUSTED_EXTERNAL
```

Then the runtime can enforce different policies.

---

## 12. The `full_stack_skills()` composition also reveals a design opportunity

Currently the full stack explicitly imports every built-in module:

```python
from kerno.skills.builtins.data import get_code ...
from kerno.skills.builtins.viz import get_code ...
...
```

<sup>[source]</sup>

This is simple and deterministic.

But as the number of skills grows, a **manifest-driven registry** would scale better:

```toml
[skills.timeseries]
module = "kerno.skills.builtins.timeseries"
depends = ["data", "viz"]
extra = "timeseries"
```

Then:

```text
manifest
    │
    ▼
skill discovery
    │
    ├── dependency resolution
    ├── optional dependency check
    ├── trust policy
    └── registration
```

This would eliminate a lot of duplicated wiring.

However, I would **not** rush to implement this yet. The current explicit registry has the advantage of being easy to audit.

---

## 13. Most important architectural conclusion so far

Kerno's actual model appears to be:

```text
                    ┌───────────────┐
                    │    Agent      │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ Skill Composer │
                    └───────┬───────┘
                            │
                      dependency graph
                            │
                            ▼
                    ┌───────────────┐
                    │ Skill Registry │
                    └───────┬───────┘
                            │
                   generated Python
                            │
                            ▼
                    ┌───────────────┐
                    │ KernelRuntime  │
                    └───────┬───────┘
                            │
                            ▼
                     IPython kernel
                            │
               ┌────────────┼────────────┐
               ▼            ▼            ▼
             data         analysis      tools
```

And that explains why your extras matter so much:

```text
pip extra
   │
   ▼
third-party capability
   │
   ▼
built-in skill
   │
   ▼
SkillComposer
   │
   ▼
SkillRegistry
   │
   ▼
kernel capability
   │
   ▼
agent
```

So **packaging, skills, composition, registry, and kernel execution are one architectural system**. They shouldn't be audited independently.

---

## Current findings

###  Strong

- Optional dependencies are generally lazy-loaded.
- Built-in skills correspond to real capabilities.
- Skill metadata/provenance is explicitly modeled.
- Skill composition supports dependency ordering.
- LLM-facing skill manifest exists.
- Namespace-shadowing protection is a thoughtful design.
- Generated skill code is tested separately from normal Python modules.
- Multiple capability stacks (`minimal`, `analysis`, `ML`, `NLP`, `timeseries`, `full`) are explicitly modeled. <sup>[source]</sup>

###  Needs improvement

- Missing skill dependencies aren't reported.
- Dependency cycles aren't explicitly detected.
- `security=[]` needs clearer semantics/documentation.
- `all` dependency ownership needs reconciliation.
- Runtime NLTK resource acquisition should be made deterministic.
- Time-series functionality needs real behavioral tests.
- Document/text capability boundaries could be cleaner.

###  High priority

**`SkillRegistry.check_integrity()` appears logically incorrect.**

It hashes the registered **source code** but verifies against the hash of the runtime object's `str(...)` representation. Those are not equivalent representations. <sup>[source]</sup>

**The namespace protection mechanism also needs an actual live-IPython test before it should be treated as a security guarantee.**

And most importantly:

> **Namespace protection is not Python sandboxing.**

The next audit target should therefore be **`KernelRuntime.execute()` and the kernel lifecycle**, because that is the actual execution boundary underneath the entire skill system.

# 02 — Dependency Architecture

---

Ah — **yes, this is a completely different Kerno**, and your original `pip install` commands are in fact directly relevant to it.

I checked your repository:

[Abdus2023/Kerno — branch `arena/01a0064f-kerno`](https://github.com/Abdus2023/Kerno/tree/arena%2F01a0064f-kerno)

The branch contains a Python `pyproject.toml` defining **Kerno 0.2.0**, described as:

> "A kernel-native agent runtime. Brain meets body."

And, importantly, it explicitly defines the extras you listed. <sup>[source]</sup>

## The actual dependency architecture

The project has a normal/core dependency layer:

```text
kerno
├── jupyter-client >= 8.0
├── nbformat >= 5.9
├── ipykernel >= 6.0
├── pyyaml >= 6.0
├── pandas >= 2.0
├── numpy >= 1.24
├── matplotlib >= 3.7
├── scikit-learn >= 1.3
├── scipy >= 1.10
├── requests >= 2.31
└── openpyxl >= 3.1
```

Then optional capability groups:

```text
                    KERNO 0.2.0
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       Core          Optional        Development
          │              │              │
          │       ┌──────┼──────┐       │
          │       │      │      │       │
       Python    AI     Data   Content   Tests
```

The actual extras are:

```toml
[project.optional-dependencies]

anthropic
openai
sql
timeseries
nlp
graphs
documents
security
all
dev
```

<sup>[source]</sup>

---

## 1. `timeseries`

Your command is **valid**:

```bash
pip install "kerno[timeseries]"
```

It installs:

```text
statsmodels >= 0.14
```

<sup>[source]</sup>

This is intended for statistical/time-series functionality.

Conceptually:

```text
Kernel / agent observations
          │
          ▼
      time series
          │
     ┌────┼────┐
     ▼    ▼    ▼
   trend seasonality residual
     │
     └──────┬──────┘
            ▼
       forecasting
```

The important distinction is that `statsmodels` is **not part of Kerno's mandatory dependency set**. Users who don't need time-series functionality don't have to install it.

That's good packaging design.

---

## 2. `nlp`

```bash
pip install "kerno[nlp]"
```

Installs:

```text
nltk >= 3.8
```

<sup>[source]</sup>

This creates an optional NLP capability layer.

Potential uses include:

```text
agent observations
       │
       ▼
     text
       │
       ▼
      NLP
   ┌───┼────┐
   ▼   ▼    ▼
tokens sentiment classification
```

Again, NLTK is deliberately **not installed by the core package**.

---

## 3. `graphs`

```bash
pip install "kerno[graphs]"
```

Installs:

```text
networkx >= 3.1
```

<sup>[source]</sup>

This makes graph/network analysis available.

For an agent runtime, this could be particularly useful for representing:

```text
Agent
 │
 ├── Tool
 │
 ├── Memory
 │
 ├── Task
 │
 ├── Dependency
 │
 └── Event
```

as a graph:

```text
        ┌──────────┐
        │  Agent   │
        └────┬─────┘
       ┌─────┼─────┐
       ▼     ▼     ▼
     Task   Tool  Memory
       │
       ▼
   Dependency
```

---

## 4. `documents`

```bash
pip install "kerno[documents]"
```

This is actually two dependencies:

```text
pdfplumber >= 0.10
python-docx >= 1.1
```

<sup>[source]</sup>

So Kerno can optionally acquire document-processing capabilities for:

```text
PDF
 │
 └── pdfplumber

DOCX
 │
 └── python-docx
```

A potential pipeline is:

```text
PDF / DOCX
     │
     ▼
document extraction
     │
     ▼
normalized text
     │
     ▼
NLP / indexing / analysis
     │
     ▼
Kerno knowledge
```

This is particularly interesting when combined with the `nlp` extra.

---

## 5. `anthropic`

```bash
pip install "kerno[anthropic]"
```

Installs:

```text
anthropic >= 0.20
```

This provides the Anthropic integration.

---

## 6. `openai`

```bash
pip install "kerno[openai]"
```

Installs:

```text
openai >= 1.0
```

This provides OpenAI integration.

So AI dependencies are also kept out of the base installation.

---

## 7. `sql`

```bash
pip install "kerno[sql]"
```

Installs:

```text
sqlalchemy >= 2.0
```

This creates an optional database/SQL layer.

---

## 8. `security`

Interestingly:

```toml
security = []
```

<sup>[source]</sup>

So currently:

```bash
pip install "kerno[security]"
```

is syntactically valid but **does not install any additional dependency**.

This is effectively a reserved capability namespace at the moment.

That's something I'd flag during the audit because an empty extra can be intentional, but it should ideally be documented.

---

## 9. `all`

This is the important one.

Your command:

```bash
pip install "kerno[all]"
```

**is explicitly supported by this branch.**

The project defines:

```toml
all = [
    "anthropic>=0.20",
    "openai>=1.0",
    "sqlalchemy>=2.0",
    "psutil>=5.9",
    "statsmodels>=0.14",
    "nltk>=3.8",
    "networkx>=3.1",
    "pdfplumber>=0.10",
    "python-docx>=1.1",
    "tabulate>=0.9",
]
```

<sup>[source]</sup>

So:

```bash
pip install "kerno[all]"
```

means installing the complete optional capability stack.

---

## 10. There is an important inconsistency to investigate

Notice this:

The individual extras include:

```text
anthropic
openai
sql
timeseries
nlp
graphs
documents
security
```

But `all` also contains:

```text
psutil
tabulate
```

while those are **not exposed as their own extras**.

And the base dependencies already include:

```text
pandas
numpy
matplotlib
scikit-learn
scipy
...
```

So the dependency model is currently:

```text
                       Kerno
                         │
             ┌───────────┴───────────┐
             │                       │
            core                  optional
             │                       │
       always installed       ┌───────┼────────┐
                              │       │        │
                           AI/Data  Graphs  Documents
                              │
                         ┌────┴────┐
                         │         │
                    anthropic    openai
```

But `all` is not literally implemented as:

```toml
all = [
    "kerno[anthropic]",
    "kerno[openai]",
    ...
]
```

PEP 621 extras contain dependency specifications, so the current implementation simply repeats the actual packages.

That works, but creates a **maintenance/duplication risk**.

---

## 11. `dev`

The branch also defines:

```bash
pip install "kerno[dev]"
```

with:

```text
pytest
pytest-asyncio
pytest-timeout
anthropic
statsmodels
networkx
tabulate
```

<sup>[source]</sup>

This is intended for development/testing rather than end users.

There is also:

```toml
asyncio_mode = "auto"
timeout = 300
```

and an integration marker:

```text
integration: requires a running kernel
```

<sup>[source]</sup>

That is significant because it shows this isn't merely a collection of Python utilities: the project has a testing model that distinguishes normal tests from **real-kernel integration tests**.

---

## 12. Installation matrix

For this Kerno, the clean installation guide is:

| Goal | Command |
|---|---|
| Core | `pip install kerno` |
| Anthropic | `pip install "kerno[anthropic]"` |
| OpenAI | `pip install "kerno[openai]"` |
| SQL | `pip install "kerno[sql]"` |
| Time series | `pip install "kerno[timeseries]"` |
| NLP | `pip install "kerno[nlp]"` |
| Graphs | `pip install "kerno[graphs]"` |
| Documents | `pip install "kerno[documents]"` |
| Security | `pip install "kerno[security]"` |
| Development | `pip install "kerno[dev]"` |
| Everything | `pip install "kerno[all]"` |

And multiple extras can be combined:

```bash
pip install "kerno[anthropic,openai,timeseries,nlp,graphs,documents]"
```

---

## 13. The architecture makes much more sense now

With the correct repository identified, your original dependency design can be interpreted as:

```text
                         KERNO
                           │
             ┌─────────────┴─────────────┐
             │                           │
           CORE                       OPTIONAL
             │                           │
      ┌──────┼────────┐        ┌─────────┼──────────┐
      │      │        │        │         │          │
   Jupyter  Data    ML       AI       Analytics   Documents
      │      │        │        │         │          │
      │      │        │        │         │          │
      ▼      ▼        ▼        ▼         ▼          ▼
  ipykernel pandas sklearn   OpenAI   statsmodels  PDF
  nbformat  numpy  scipy     Anthropic NetworkX    DOCX
```

This is a much more coherent architecture for a **kernel-native agent runtime**.

---

## One particularly important observation

The base package already requires:

```text
pandas
numpy
matplotlib
scikit-learn
scipy
```

while `statsmodels`, NLTK, NetworkX, and document parsers remain optional. <sup>[source]</sup>

That suggests a deliberate philosophy:

> **Keep the common computational/agent runtime stack installed, while moving specialized capabilities into extras.**

That is generally a sensible approach, especially if Kerno is intended to remain usable in constrained environments.

---

### So the corrected conclusion

**You were right.** There are two unrelated projects named Kerno.

The `optiqor/kerno` repository I initially inspected is a Go/eBPF Kubernetes incident-diagnosis project.

Your repository:

[Abdus2023/Kerno](https://github.com/Abdus2023/Kerno)

is a **Python 3.11+ kernel-native agent runtime**, version **0.2.0** on the branch you supplied, and **does explicitly implement**:

```text
timeseries → statsmodels
nlp        → nltk
graphs     → networkx
documents  → pdfplumber + python-docx
all        → full optional stack
```

So your original commands are valid for **your Kerno project**. <sup>[source]</sup>

The next useful step is a **deep audit of this exact branch's packaging**: verify every declared extra against actual imports/usages/tests, check whether `all` is complete, find orphan dependencies (`psutil`, `tabulate`, etc.), and determine whether the extras are truly optional or accidentally required at runtime.

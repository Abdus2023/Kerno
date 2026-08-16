[← Back to index](./README.md) | [Next section →](./02-dependency-architecture.md)

# Kerno Optional Packages

> **Provider:** ChatGPT
> **Date:** 16/08/2026, 09:43:02
> **Source:** [ChatGPT](https://chatgpt.com/c/6a817809-2f14-83ea-98e6-d99ee66261c1)
> **Active Node:** `1a63d8e1-d058-4cd2-b8a8-d8b94380fdef`

---

## [1] USER

```
pip install "kerno[timeseries]"   # statsmodels decomposition/forecasting
pip install "kerno[nlp]"          # NLTK sentiment
pip install "kerno[graphs]"       # networkx analysis
pip install "kerno[documents]"    # PDF / DOCX parsing

# Full stack
pip install "kerno[all]"
```

---

## [2] CHATGPT (gpt-5-6)

These are the optional **Kerno** packages as `extras` in `pip`:

<details>
<summary><strong>💻 Code Block (bash) — 14 lines</strong></summary>

```bash
# Time-series analysis / forecasting
pip install "kerno[timeseries]"

# NLP / sentiment analysis
pip install "kerno[nlp]"

# Graph / network analysis
pip install "kerno[graphs]"

# PDF / DOCX document parsing
pip install "kerno[documents]"

# Full stack — all extras
pip install "kerno[all]"
```

</details>

You can also install several extras at once:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[timeseries,nlp,graphs,documents]"
```

</details>

### What is each extra supposed to provide?

| Extra | Usage |
|---|---|
| `timeseries` | `statsmodels` for analysis, decomposition, forecasting |
| `nlp` | `nltk` for text processing and sentiment |
| `graphs` | `networkx` for network and relationship analysis |
| `documents` | PDF / DOCX parsing tools |
| `all` | the entire optional stack |

**Important note:** if this is about the **Kerno** repository we were auditing, we should not assume these extras are actually defined in `pyproject.toml`. I can audit the `pyproject.toml`/`setup.cfg` in the repository and verify that **every extra name, every dependency, and `kerno[all]` actually works**.

---

## [3] USER

Full information and explanation

---

## [4] CHATGPT (gpt-5-6)

<details>
<summary><strong>🛠️ q7dr546</strong></summary>

**Input:**

```json
{"query":"The user is asking for full information and explanation of the Kerno Python optional dependency extras: kerno[timeseries], kerno[nlp], kerno[graphs], kerno[documents], kerno[all]. Prior context indicates they want deep audits of the Kerno GitHub repository itself, so repository-specific verification of pyproject.toml extras and dependency behavior may materially affect the answer."}
```

</details>

<details>
<summary><strong>🛠️ api_tool.list_resources</strong></summary>

**Input:**

```json
{"paths":["GitHub"],"query":"repository"}
```

</details>

*(Tool execution: api_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search_repositories","args":{"query":"Kerno","per_page":10}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"optiqor/kerno","path":"pyproject.toml","ref":"main"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"optiqor/kerno","path":"README.md","ref":"main"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"query":"statsmodels","repository_name":"optiqor/kerno","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"query":"networkx","repository_name":"optiqor/kerno","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>💭 Thinking Process</strong></summary>

> Reviewed Kerno extras and dependencies across timeseries, NLP, graphs, and documents

</details>

---

## [5] CHATGPT (gpt-5-6)

There is a very important point that must be corrected first: **the commands you sent are not valid for the Kerno repository we are reviewing (`optiqor/kerno`)**.

I checked the repository itself, not just the general `pip` syntax.

**optiqor/kerno on GitHub:** https://github.com/optiqor/kerno

## 1. Current Kerno is not a Python package

The repository clearly defines itself as:

> **Kubernetes-native incident diagnosis engine built on eBPF**

It is built primarily as a **Go agent / single binary**, not a pip-installable Python library. The README describes it as a Go program running on Linux/Kubernetes, with eBPF, DaemonSet, Helm, systemd, and Docker.  <sup>[source]</sup>

Also, attempting to verify:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
pyproject.toml
```

</details>

on the `main` branch did not find the file, and searching the repository for:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
statsmodels
networkx
```

</details>

did not find these dependencies.

Therefore there is currently no basis to say that:

<details>
<summary><strong>💻 Code Block (bash) — 5 lines</strong></summary>

```bash
pip install "kerno[timeseries]"
pip install "kerno[nlp]"
pip install "kerno[graphs]"
pip install "kerno[documents]"
pip install "kerno[all]"
```

</details>

are commands supported by Kerno.

---

# 2. What does `[timeseries]` actually mean?

The syntax:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "package[extra]"
```

</details>

is the **Python packaging extras** mechanism.

For example, if we had:

<details>
<summary><strong>💻 Code Block (toml) — 5 lines</strong></summary>

```toml
[project.optional-dependencies]
timeseries = [
    "statsmodels",
    "pandas",
]
```

</details>

then:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[timeseries]"
```

</details>

means:

> Install Kerno + the additional dependencies required for time-series analysis.

But this does not happen automatically just by writing the name `[timeseries]`. The package itself must have declared this extra in its metadata.

---

# 3. What did the names you wrote mean?

If there were a **Python project** designed this way, the intended design could be:

### `timeseries`

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[timeseries]"
```

</details>

It could, for example, contain:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
pandas
numpy
statsmodels
scipy
```

</details>

And the goal:

- Time-series analysis
- decomposition
- trend detection
- seasonality
- forecasting
- anomaly detection
- moving averages
- ARIMA / SARIMA
- exponential smoothing

For example:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
raw metrics
     │
     ▼
time series
     │
     ├── trend
     ├── seasonality
     ├── residual
     │
     ▼
forecast / anomaly detection
```

</details>

But **this is not a stack currently present in the Kerno we examined**.

---

# 4. `nlp`

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[nlp]"
```

</details>

In the default design I proposed earlier, it was meant to provide:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
NLTK
```

</details>

And it could be used for:

- tokenization
- stop-word processing
- stemming
- sentiment analysis
- text classification
- incident/error text analysis

For example:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

```text
"TCP retransmits increased significantly"
                     │
                     ▼
                   NLP
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
       entities              sentiment
```

</details>

But again:

**There is no evidence in current Kerno that `kerno[nlp]` exists.**

---

# 5. `graphs`

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[graphs]"
```

</details>

The idea here would usually be:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
networkx
```

</details>

for graph/network analysis.

For example, you could represent:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
Node
 │
 ├── Pod
 │    └── Container
 │
 ├── Process
 │
 ├── Network connection
 │
 └── Service
```

</details>

Then convert the relationships into a graph:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
Pod A ──TCP──> Pod B
  │
  └──runs──> Process
                │
                └──opens──> File
```

</details>

And this is theoretically useful for:

- dependency analysis
- service relationships
- process relationships
- network topology
- root-cause propagation

But the actual search in Kerno did not find `networkx`.

---

# 6. `documents`

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[documents]"
```

</details>

This was also a hypothetical design for a Python application.

It could contain tools such as:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
PDF parser
DOCX parser
HTML parser
text extraction
```

</details>

And the usage would be like:

<details>
<summary><strong>💻 Code Block (text) — 13 lines</strong></summary>

```text
PDF
 │
 ▼
text extraction
 │
 ▼
normalization
 │
 ▼
NLP
 │
 ▼
knowledge / incident analysis
```

</details>

But **current Kerno is not built this way**.

---

# 7. What about `[all]`?

In Python packaging, you can define:

<details>
<summary><strong>💻 Code Block (toml) — 13 lines</strong></summary>

```toml
[project.optional-dependencies]

timeseries = [...]
nlp = [...]
graphs = [...]
documents = [...]

all = [
    "statsmodels",
    "nltk",
    "networkx",
    "...",
]
```

</details>

And then:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[all]"
```

</details>

means:

> Install the base package + all optional dependencies.

But `all` is **not a magic keyword in pip**.

If the package does not define it, an error of this type will appear:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
WARNING: kerno does not provide the extra 'all'
```

</details>

or installation fails depending on the package/source state.

---

# 8. The important difference: pip syntax vs Kerno functionality

There are two completely different levels:

### Level one — Python packaging

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "foo[nlp]"
```

</details>

This is just a dependency management mechanism.

### Level two — program functionality

The existence of:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
[nlp]
```

</details>

does not mean the program automatically becomes capable of NLP.

There must be code that uses:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
import nltk
```

</details>

or similar.

Therefore the full chain must be proven:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
extra declared
      ↓
dependency installed
      ↓
code imports dependency
      ↓
feature exists
      ↓
feature is tested
      ↓
feature is documented
```

</details>

---

# 9. And this is very important for Kerno

For the repository we are reviewing, the actual picture is different:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
Kerno
│
├── Go
├── eBPF
├── Linux kernel
├── Kubernetes
├── Helm
├── systemd
├── Prometheus
└── optional AI providers
```

</details>

And not:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

```text
Kerno
│
├── Python
├── statsmodels
├── NLTK
├── NetworkX
├── PDF parser
└── DOCX parser
```

</details>

The README itself mentions that Kerno works as a **lightweight Go agent**, and shows commands such as:

<details>
<summary><strong>💻 Code Block (bash) — 10 lines</strong></summary>

```bash
kerno doctor
kerno explain
kerno predict
kerno trace syscall
kerno trace disk
kerno trace sched
kerno watch tcp
kerno watch oom
kerno watch fd
kerno start
```

</details>

And it mentions AI integrations with Anthropic, OpenAI, and Ollama as optional features.  <sup>[source]</sup>

---

# 10. What was wrong in my previous answer?

My previous answer treated the text you sent as if it were a **real definition of Python extras in Kerno**.

That was an unjustified conclusion.

I should have said:

> "This is generally valid syntax for Python extras, but we must first verify that Kerno itself defines these extras."

And after examining the repository, the current result is:

| Extra | Verification status in `optiqor/kerno` |
|---|---|
| `kerno[timeseries]` | ❌ existence not confirmed |
| `kerno[nlp]` | ❌ existence not confirmed |
| `kerno[graphs]` | ❌ existence not confirmed |
| `kerno[documents]` | ❌ existence not confirmed |
| `kerno[all]` | ❌ existence not confirmed |
| `statsmodels` | ❌ did not appear in the repository search |
| `networkx` | ❌ did not appear in the repository search |
| Python `pyproject.toml` | ❌ not present at the expected path |

**Therefore these commands should not be recorded as Kerno features or as installation instructions for the repository.**

---

## 11. If the goal is to add these capabilities to Kerno

Here the topic becomes different and interesting.

Instead of turning Kerno into a Python application, optional analysis can be built on top of the **Go/eBPF core**:

<details>
<summary><strong>💻 Code Block (text) — 15 lines</strong></summary>

```text
                    KERNO
                      │
             ┌────────┴────────┐
             │                 │
          Go/eBPF           Event API
             │                 │
             │        ┌────────┼─────────┐
             │        │        │         │
             ▼        ▼        ▼         ▼
          Kernel    Metrics   Graph     Text
          signals   series   model     reports
                              │
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
             topology     dependency    RCA
```

</details>

Then advanced analysis can be made **plugins / optional services** instead of introducing Python dependencies into the core binary.

For example:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
kerno-core
    │
    ├── kerno doctor
    ├── kerno trace
    ├── kerno watch
    │
    └── analytics
          ├── timeseries
          ├── graph
          ├── NLP
          └── documents
```

</details>

And this preserves the core feature the project focuses on: **a single lightweight Go binary with eBPF**, instead of loading the core with huge data-analysis libraries.  <sup>[source]</sup>

### Conclusion

**The five commands you sent represent a possible design for a Python package, and not a proven installation interface for current Kerno.**

And most importantly: since we are auditing Kerno itself, we must always distinguish between:

**"This is a good design that could be added"**

and

**"This actually exists in the repository."**

In this case, the current evidence supports only the second for **Go/eBPF/Kubernetes/AI integrations**, and not `pip + statsmodels/NLTK/NetworkX/PDF/DOCX`.  <sup>[source]</sup>

---

---
[← Back to index](./README.md) | [Next section →](./02-dependency-architecture.md)

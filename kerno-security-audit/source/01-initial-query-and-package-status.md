# 01 — Initial Query And Package Status

## Kerno Optional Packages

---

These are the optional **Kerno** packages as `extras` in `pip`:

```bash
## Time-series analysis / forecasting
pip install "kerno[timeseries]"

## NLP / sentiment analysis
pip install "kerno[nlp]"

## Graph / network analysis
pip install "kerno[graphs]"

## PDF / DOCX document parsing
pip install "kerno[documents]"

## Full stack — all extras
pip install "kerno[all]"
```

You can also install several extras at once:

```bash
pip install "kerno[timeseries,nlp,graphs,documents]"
```

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

There is a very important point that must be corrected first: **the commands you sent are not valid for the Kerno repository we are reviewing (`optiqor/kerno`)**.

I checked the repository itself, not just the general `pip` syntax.

**optiqor/kerno on GitHub:** https://github.com/optiqor/kerno

## 1. Current Kerno is not a Python package

The repository clearly defines itself as:

> **Kubernetes-native incident diagnosis engine built on eBPF**

It is built primarily as a **Go agent / single binary**, not a pip-installable Python library. The README describes it as a Go program running on Linux/Kubernetes, with eBPF, DaemonSet, Helm, systemd, and Docker.  <sup>[source]</sup>

Also, attempting to verify:

```text
pyproject.toml
```

on the `main` branch did not find the file, and searching the repository for:

```text
statsmodels
networkx
```

did not find these dependencies.

Therefore there is currently no basis to say that:

```bash
pip install "kerno[timeseries]"
pip install "kerno[nlp]"
pip install "kerno[graphs]"
pip install "kerno[documents]"
pip install "kerno[all]"
```

are commands supported by Kerno.

---

## 2. What does `[timeseries]` actually mean?

The syntax:

```bash
pip install "package[extra]"
```

is the **Python packaging extras** mechanism.

For example, if we had:

```toml
[project.optional-dependencies]
timeseries = [
    "statsmodels",
    "pandas",
]
```

then:

```bash
pip install "kerno[timeseries]"
```

means:

> Install Kerno + the additional dependencies required for time-series analysis.

But this does not happen automatically just by writing the name `[timeseries]`. The package itself must have declared this extra in its metadata.

---

## 3. What did the names you wrote mean?

If there were a **Python project** designed this way, the intended design could be:

### `timeseries`

```bash
pip install "kerno[timeseries]"
```

It could, for example, contain:

```text
pandas
numpy
statsmodels
scipy
```

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

But **this is not a stack currently present in the Kerno we examined**.

---

## 4. `nlp`

```bash
pip install "kerno[nlp]"
```

In the default design I proposed earlier, it was meant to provide:

```text
NLTK
```

And it could be used for:

- tokenization
- stop-word processing
- stemming
- sentiment analysis
- text classification
- incident/error text analysis

For example:

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

But again:

**There is no evidence in current Kerno that `kerno[nlp]` exists.**

---

## 5. `graphs`

```bash
pip install "kerno[graphs]"
```

The idea here would usually be:

```text
networkx
```

for graph/network analysis.

For example, you could represent:

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

Then convert the relationships into a graph:

```text
Pod A ──TCP──> Pod B
  │
  └──runs──> Process
                │
                └──opens──> File
```

And this is theoretically useful for:

- dependency analysis
- service relationships
- process relationships
- network topology
- root-cause propagation

But the actual search in Kerno did not find `networkx`.

---

## 6. `documents`

```bash
pip install "kerno[documents]"
```

This was also a hypothetical design for a Python application.

It could contain tools such as:

```text
PDF parser
DOCX parser
HTML parser
text extraction
```

And the usage would be like:

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

But **current Kerno is not built this way**.

---

## 7. What about `[all]`?

In Python packaging, you can define:

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

And then:

```bash
pip install "kerno[all]"
```

means:

> Install the base package + all optional dependencies.

But `all` is **not a magic keyword in pip**.

If the package does not define it, an error of this type will appear:

```text
WARNING: kerno does not provide the extra 'all'
```

or installation fails depending on the package/source state.

---

## 8. The important difference: pip syntax vs Kerno functionality

There are two completely different levels:

### Level one — Python packaging

```bash
pip install "foo[nlp]"
```

This is just a dependency management mechanism.

### Level two — program functionality

The existence of:

```text
[nlp]
```

does not mean the program automatically becomes capable of NLP.

There must be code that uses:

```python
import nltk
```

or similar.

Therefore the full chain must be proven:

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

---

## 9. And this is very important for Kerno

For the repository we are reviewing, the actual picture is different:

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

And not:

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

The README itself mentions that Kerno works as a **lightweight Go agent**, and shows commands such as:

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

And it mentions AI integrations with Anthropic, OpenAI, and Ollama as optional features.  <sup>[source]</sup>

---

## 10. What was wrong in my previous answer?

My previous answer treated the text you sent as if it were a **real definition of Python extras in Kerno**.

That was an unjustified conclusion.

I should have said:

> "This is generally valid syntax for Python extras, but we must first verify that Kerno itself defines these extras."

And after examining the repository, the current result is:

| Extra | Verification status in `optiqor/kerno` |
|---|---|
| `kerno[timeseries]` |  existence not confirmed |
| `kerno[nlp]` |  existence not confirmed |
| `kerno[graphs]` |  existence not confirmed |
| `kerno[documents]` |  existence not confirmed |
| `kerno[all]` |  existence not confirmed |
| `statsmodels` |  did not appear in the repository search |
| `networkx` |  did not appear in the repository search |
| Python `pyproject.toml` |  not present at the expected path |

**Therefore these commands should not be recorded as Kerno features or as installation instructions for the repository.**

---

## 11. If the goal is to add these capabilities to Kerno

Here the topic becomes different and interesting.

Instead of turning Kerno into a Python application, optional analysis can be built on top of the **Go/eBPF core**:

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

Then advanced analysis can be made **plugins / optional services** instead of introducing Python dependencies into the core binary.

For example:

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

And this preserves the core feature the project focuses on: **a single lightweight Go binary with eBPF**, instead of loading the core with huge data-analysis libraries.  <sup>[source]</sup>

### Conclusion

**The five commands you sent represent a possible design for a Python package, and not a proven installation interface for current Kerno.**

And most importantly: since we are auditing Kerno itself, we must always distinguish between:

**"This is a good design that could be added"**

and

**"This actually exists in the repository."**

In this case, the current evidence supports only the second for **Go/eBPF/Kubernetes/AI integrations**, and not `pip + statsmodels/NLTK/NetworkX/PDF/DOCX`.  <sup>[source]</sup>

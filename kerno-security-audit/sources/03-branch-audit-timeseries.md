[← Back to index](./README.md) | [Next section →](./04-skill-registry-and-composition.md)

## [10] USER

Continue

---

## [11] CHATGPT (gpt-5-6)

<details>
<summary><strong>🛠️ api_tool.list_resources</strong></summary>

**Input:**

```json
{"paths":["GitHub"],"query":"search"}
```

</details>

*(Tool execution: api_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"import statsmodels","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"import nltk","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"import networkx","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"pdfplumber","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"from nltk","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"statsmodels","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/search","args":{"repository_name":"Abdus2023/Kerno","query":"sqlalchemy","topn":20}}
```

</details>

*(Tool execution: api_tool.call_tool)*

*(Tool execution: api_tool.call_tool)*

Yes. Now that we have the **correct Kerno repository and branch**, we can go deeper.

I checked the actual source tree against the extras, rather than relying only on `pyproject.toml`. The result is encouraging: **the optional dependencies correspond to real built-in skills**. <sup>[source]</sup>

# Kerno 0.2.0 — dependency/feature audit

[Kerno — `arena/01a0064f-kerno`](https://github.com/Abdus2023/Kerno/tree/arena%2F01a0064f-kerno)

## 1. Time-series: `statsmodels`

The package declares:

<details>
<summary><strong>💻 Code Block (toml) — 1 lines</strong></summary>

```toml
timeseries = ["statsmodels>=0.14"]
```

</details>

and the repository contains:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kerno/skills/builtins/timeseries.py
```

</details>

The repository search also finds `statsmodels` associated with that implementation. <sup>[source]</sup>

So this is not an invented/unused extra.

Architecture:

<details>
<summary><strong>💻 Code Block (text) — 14 lines</strong></summary>

```text
                    Kerno
                      │
                 Skill system
                      │
              ┌───────┴───────┐
              │               │
          timeseries       other skills
              │
              ▼
          statsmodels
              │
       ┌──────┼──────┐
       ▼      ▼      ▼
     trend  season  forecast
```

</details>

### Installation

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[timeseries]"
```

</details>

---

# 2. NLP: `nltk`

The declaration is:

<details>
<summary><strong>💻 Code Block (toml) — 1 lines</strong></summary>

```toml
nlp = ["nltk>=3.8"]
```

</details>

And there is a corresponding implementation:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kerno/skills/builtins/nlp.py
```

</details>

The repository search confirms NLTK usage in that skill. <sup>[source]</sup>

This establishes an important dependency chain:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
pyproject.toml
      │
      ▼
nltk dependency
      │
      ▼
kerno/skills/builtins/nlp.py
      │
      ▼
NLP capability
```

</details>

So:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[nlp]"
```

</details>

is structurally justified.

---

# 3. Graph analysis: `networkx`

The declaration is:

<details>
<summary><strong>💻 Code Block (toml) — 1 lines</strong></summary>

```toml
graphs = ["networkx>=3.1"]
```

</details>

And the source contains:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kerno/skills/builtins/graph.py
```

</details>

with NetworkX usage. <sup>[source]</sup>

There is also:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kerno/skills/builtins/network.py
```

</details>

which is worth investigating separately because **network operations and graph analysis are conceptually different capabilities**. <sup>[source]</sup>

This gives Kerno an architecture like:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
                    Kerno
                      │
             ┌────────┴────────┐
             │                 │
          Network             Graph
             │                 │
             ▼                 ▼
       network operations   NetworkX
                               │
                               ▼
                         graph analysis
```

</details>

This distinction could become important for the public API.

---

# 4. Documents: `pdfplumber` + `python-docx`

The declaration:

<details>
<summary><strong>💻 Code Block (toml) — 4 lines</strong></summary>

```toml
documents = [
    "pdfplumber>=0.10",
    "python-docx>=1.1",
]
```

</details>

is backed by:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kerno/skills/builtins/docs.py
```

</details>

The repository search finds `pdfplumber` there. <sup>[source]</sup>

So the dependency chain is:

<details>
<summary><strong>💻 Code Block (text) — 12 lines</strong></summary>

```text
                  documents
                     │
              ┌──────┴──────┐
              ▼             ▼
         pdfplumber      python-docx
              │             │
              ▼             ▼
             PDF           DOCX
              │             │
              └──────┬──────┘
                     ▼
              document skill
```

</details>

This is exactly the kind of functionality that should remain optional because PDF/DOCX parsing is not required by every Kerno deployment.

---

# 5. SQL: `SQLAlchemy`

The same pattern exists for SQL:

<details>
<summary><strong>💻 Code Block (toml) — 1 lines</strong></summary>

```toml
sql = ["sqlalchemy>=2.0"]
```

</details>

and the repository has:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kerno/skills/builtins/sql.py
```

</details>

with SQLAlchemy associated with it. <sup>[source]</sup>

So:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[sql]"
```

</details>

is also backed by a real built-in skill.

---

# 6. The architecture is actually skill-oriented

This is the most important thing emerging from the audit.

The dependency groups aren't just arbitrary package bundles.

They correspond to **built-in Kerno skills**:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
kerno/
└── skills/
    └── builtins/
        ├── timeseries.py
        ├── nlp.py
        ├── graph.py
        ├── network.py
        ├── docs.py
        └── sql.py
```

</details>

That means the architecture is closer to:

<details>
<summary><strong>💻 Code Block (text) — 16 lines</strong></summary>

```text
                         KERNO
                           │
                           ▼
                     Agent Runtime
                           │
                      Skill Layer
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
          ▼                ▼                 ▼
      Built-in          Optional          External
       skills            deps              tools
          │                │
     ┌────┼────┐      ┌────┼────┐
     ▼    ▼    ▼      ▼    ▼    ▼
    SQL  NLP Graph  NLTK  Stats  NetworkX
```

</details>

This is much more interesting than simply saying "Kerno has optional Python dependencies."

---

# 7. Why the optional extras are good architecture

Imagine someone only wants Kerno's core kernel/agent functionality.

They run:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install kerno
```

</details>

They don't necessarily need:

- NLTK
- NetworkX
- statsmodels
- PDF parsing
- DOCX parsing
- SQLAlchemy
- OpenAI
- Anthropic

Those packages can add significant dependency weight and potential security/update surface.

Instead:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
Core
 │
 ├── Jupyter
 ├── NumPy
 ├── Pandas
 ├── SciPy
 └── Scikit-learn
```

</details>

then selectively:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
+ [nlp]
+ [graphs]
+ [documents]
+ [timeseries]
+ [sql]
+ [openai]
+ [anthropic]
```

</details>

This is a sensible capability-oriented packaging model.

---

# 8. But there is a potential problem with `all`

The current declaration is:

<details>
<summary><strong>💻 Code Block (toml) — 12 lines</strong></summary>

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

</details>

<sup>[source]</sup>

But the individual extras are:

<details>
<summary><strong>💻 Code Block (text) — 8 lines</strong></summary>

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

</details>

There are two packages in `all` that deserve special attention:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
psutil
tabulate
```

</details>

They aren't represented as their own public extras.

That isn't necessarily wrong.

But we need to answer:

> **Why does `all` need them?**

If they're used by core code, they probably belong in `dependencies`.

If they're only used by a particular optional skill, they should probably belong to that skill's extra.

If they're only used by CLI presentation/diagnostics, another extra may make more sense.

This is a **dependency ownership question**.

---

# 9. `security = []` deserves investigation

Currently:

<details>
<summary><strong>💻 Code Block (toml) — 1 lines</strong></summary>

```toml
security = []
```

</details>

This means:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install "kerno[security]"
```

</details>

adds nothing.

But the repository contains:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
kerno/security/allowlist.py
```

</details>

as seen in the search results. <sup>[source]</sup>

That's interesting.

It suggests the name `security` may represent a **logical capability**, even though it currently has no third-party dependency.

That could actually be perfectly valid:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
security capability
        │
        ▼
pure Python implementation
        │
        └── no optional external package
```

</details>

If that's intentional, the README should explain it.

Otherwise users may reasonably ask:

> "Why does `[security]` exist if installing it changes nothing?"

---

# 10. `dev` is different from `all`

This distinction should remain.

### `all`

Means:

> Give me every runtime capability.

### `dev`

Means:

> Give me what I need to develop/test Kerno.

Currently `dev` includes:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
pytest
pytest-asyncio
pytest-timeout
anthropic
statsmodels
networkx
tabulate
```

</details>

<sup>[source]</sup>

But notice something:

`dev` does **not** include:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
nltk
pdfplumber
python-docx
openai
sqlalchemy
```

</details>

That raises a testing-coverage question.

If there are tests for those capabilities, `dev` may be incomplete.

---

# 11. This leads to the next audit: import safety

The most important thing I would check next is whether optional dependencies are imported **lazily**.

Good:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
def analyze():
    import statsmodels
    ...
```

</details>

or:

<details>
<summary><strong>💻 Code Block (python) — 4 lines</strong></summary>

```python
try:
    import statsmodels
except ImportError:
    statsmodels = None
```

</details>

Bad for an optional feature:

<details>
<summary><strong>💻 Code Block (python) — 2 lines</strong></summary>

```python
# module import happens immediately
import statsmodels
```

</details>

at the top of a module that gets imported by Kerno's core skill registry.

Why?

Because then:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install kerno
```

</details>

could unexpectedly fail simply because `statsmodels` isn't installed.

The desired architecture is:

<details>
<summary><strong>💻 Code Block (text) — 17 lines</strong></summary>

```text
pip install kerno
        │
        ▼
core starts successfully
        │
        ▼
optional skill discovered
        │
        ▼
dependency check
        │
   ┌────┴─────┐
   ▼          ▼
installed   missing
   │          │
   ▼          ▼
execute    clear error
```

</details>

rather than:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
pip install kerno
        │
        ▼
import everything
        │
        ▼
ModuleNotFoundError
```

</details>

---

# 12. The next major audit target

I would now audit each built-in skill against four dimensions:

| Skill | Extra | Dependency | Source | Lazy import | Tests |
|---|---|---|---|---|---|
| Time series | `timeseries` | statsmodels | `timeseries.py` | ⏳ | ⏳ |
| NLP | `nlp` | NLTK | `nlp.py` | ⏳ | ⏳ |
| Graph | `graphs` | NetworkX | `graph.py` | ⏳ | ⏳ |
| Documents | `documents` | pdfplumber/docx | `docs.py` | ⏳ | ⏳ |
| SQL | `sql` | SQLAlchemy | `sql.py` | ⏳ | ⏳ |
| Anthropic | `anthropic` | Anthropic SDK | AI skill | ⏳ | ⏳ |
| OpenAI | `openai` | OpenAI SDK | AI skill | ⏳ | ⏳ |
| Security | `security` | none | `security/*` | N/A | ⏳ |

This will tell us whether the packaging is merely **declared correctly** or is actually **runtime-correct**.

And that distinction is critical.

---

## Current evidence status

### Confirmed

**Packaging:**

`pyproject.toml` explicitly defines the extras. <sup>[source]</sup>

**Time series:**

`timeseries.py` exists and is associated with `statsmodels`. <sup>[source]</sup>

**NLP:**

`nlp.py` exists and is associated with NLTK. <sup>[source]</sup>

**Graphs:**

`graph.py` exists and is associated with NetworkX. <sup>[source]</sup>

**Documents:**

`docs.py` exists and is associated with `pdfplumber`. <sup>[source]</sup>

**SQL:**

`sql.py` exists and is associated with SQLAlchemy. <sup>[source]</sup>

### Not yet proven

We have **not yet established**:

1. every optional import is lazy/safe;
2. every extra has complete test coverage;
3. `all` contains every runtime dependency actually needed;
4. `dev` contains everything required to run the full test suite;
5. optional skills fail gracefully when their extra isn't installed;
6. documentation matches actual CLI/API behavior;
7. the PyPI/package build contains all intended skill modules;
8. the extras work from a clean virtual environment.

**That is the next level of the Kerno audit.**

---

## [12] USER

Continue

---

## [13] CHATGPT (gpt-5-6)

<details>
<summary><strong>🛠️ api_tool.list_resources</strong></summary>

**Input:**

```json
{"paths":["GitHub"],"query":"fetch"}
```

</details>

*(Tool execution: api_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/skills/builtins/timeseries.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/skills/builtins/nlp.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/skills/builtins/graph.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"kerno/skills/builtins/docs.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>🛠️ api_tool.call_tool</strong></summary>

**Input:**

```python3
{"path":"/GitHub/link_6a4b426bf2dc8191936e50abee50da0a/fetch_file","args":{"repository_full_name":"Abdus2023/Kerno","path":"tests/unit/test_advanced_skills.py","ref":"arena/01a0064f-kerno"}}
```

</details>

*(Tool execution: api_tool.call_tool)*

<details>
<summary><strong>💭 Thinking Process</strong></summary>

> Reviewing Optional Dependencies and Test Coverage

</details>

---

## [14] CHATGPT (gpt-5-6)

## Continue — deeper audit of the actual Kerno branch

I went one level deeper into the implementation. We can now distinguish **good architecture**, **real issues**, and **things that still need verification**.

### 1. The optional-import design is mostly correct

This is a strong point.

For example, `timeseries.py` does **not** import `statsmodels` when the module is loaded. Instead, `ts_decompose()` performs:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
from statsmodels.tsa.seasonal import seasonal_decompose
```

</details>

inside the function and converts a missing dependency into a useful error. <sup>[source]</sup>

Likewise, the graph implementation imports NetworkX only when the graph functionality is invoked. <sup>[source]</sup>

And the document implementation explicitly states that PDF/DOCX packages are imported only when a document is actually read. <sup>[source]</sup>

So the intended behavior is:

<details>
<summary><strong>💻 Code Block (text) — 9 lines</strong></summary>

```text
pip install kerno
        │
        ▼
Kerno starts
        │
        ├── timeseries not used ──► no statsmodels required
        ├── graph not used ───────► no networkx required
        ├── PDF not used ─────────► no pdfplumber required
        └── DOCX not used ────────► no python-docx required
```

</details>

**This is good.**

---

# 2. NLP is particularly well designed — but has one concern

The NLP implementation says:

> "Heavy imports are lazy so kernel startup stays fast." <sup>[source]</sup>

And `_ensure_vader()` imports NLTK only when sentiment analysis is actually requested.

It also attempts to acquire the VADER lexicon if it is not already present:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
NLTK
 │
 ├── installed?
 │      │
 │      └── yes
 │
 └── VADER data?
        │
        ├── yes → use it
        │
        └── no → nltk.download(...)
```

</details>

That is convenient for interactive use.

### But this creates a reproducibility concern.

A package should ideally not silently depend on network access during a normal function call.

For an offline/server/container deployment:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
nltk.download("vader_lexicon")
```

</details>

may fail.

The code does have a fallback lexicon, which is good, but this means the same call can produce different-quality results depending on whether the NLTK resource happens to be available. <sup>[source]</sup>

### Recommendation

Prefer:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
Kerno installation
      │
      ▼
optional NLP extra
      │
      ▼
explicit resource setup
      │
      ▼
VADER available
```

</details>

rather than making runtime behavior depend on an implicit download.

A future interface could be:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
kerno setup nlp
```

</details>

or:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
python -m kerno setup nlp
```

</details>

with explicit reporting:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
✓ nltk installed
✓ vader_lexicon installed
✓ NLP skill ready
```

</details>

That would be much more deterministic.

---

# 3. The graph implementation has a dependency boundary that makes sense

`build_graph()` imports NetworkX lazily and raises:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
networkx is required
```

</details>

if it isn't installed. <sup>[source]</sup>

The API is also nicely structured:

<details>
<summary><strong>💻 Code Block (python) — 3 lines</strong></summary>

```python
build_graph(...)
graph_centrality(...)
draw_graph(...)
```

</details>

So there is a clear progression:

<details>
<summary><strong>💻 Code Block (text) — 11 lines</strong></summary>

```text
edge table
   │
   ▼
build_graph()
   │
   ▼
NetworkX graph
   │
   ├── graph_centrality()
   │
   └── draw_graph()
```

</details>

That's a good skill boundary.

---

# 4. The document skill is broader than just PDF/DOCX

This is an important discovery.

The `documents` extra provides:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
PDF
DOCX
```

</details>

but `docs.py` also contains pure-Python functionality:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
chunk_text()
extract_patterns()
```

</details>

So:

<details>
<summary><strong>💻 Code Block (text) — 6 lines</strong></summary>

```text
documents
│
├── read_pdf()
├── read_docx()
├── chunk_text()
└── extract_patterns()
```

</details>

The latter two don't require `pdfplumber` or `python-docx`. <sup>[source]</sup>

This raises a packaging/design question:

> Should `chunk_text()` and `extract_patterns()` really be coupled to the `documents` extra?

Maybe not.

A cleaner architecture could eventually be:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
text
├── chunk_text
└── extract_patterns

documents
├── read_pdf
└── read_docx
```

</details>

That would allow:

<details>
<summary><strong>💻 Code Block (bash) — 1 lines</strong></summary>

```bash
pip install kerno
```

</details>

to use basic text processing without installing document parsers.

This isn't necessarily a bug, but it's a **dependency-boundary improvement**.

---

# 5. The tests are doing something very useful

The advanced skill tests don't simply import the optional third-party packages at test-module startup.

Instead, they retrieve the generated skill source through:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
module.get_code()
```

</details>

then execute it in a controlled namespace. <sup>[source]</sup>

This matches Kerno's unusual architecture:

<details>
<summary><strong>💻 Code Block (text) — 10 lines</strong></summary>

```text
Python module
      │
      ▼
get_code()
      │
      ▼
generated skill source
      │
      ▼
execution inside kernel context
```

</details>

That's important.

Kerno isn't simply:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
import module
call function
```

</details>

It has a **skill-code generation/execution layer**.

That changes how we should audit it.

---

# 6. NLP has an actual fallback test

The test deliberately makes NLTK unavailable:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
fake import
     │
     └── nltk → ImportError
```

</details>

and then verifies that sentiment analysis still works. <sup>[source]</sup>

That's excellent testing of the optional dependency boundary.

The test also exercises clustering.

So we have evidence that the authors thought about:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
optional dependency missing
             ↓
        graceful fallback
```

</details>

rather than simply:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
ModuleNotFoundError
```

</details>

---

# 7. Graph functionality has integration-with-dependency testing

The test suite explicitly does:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
pytest.importorskip("networkx")
```

</details>

before exercising graph functionality. <sup>[source]</sup>

Then it tests both:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
network.py
graph.py
```

</details>

and checks:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
degree
pagerank
betweenness
```

</details>

This is useful because it validates the actual third-party integration rather than merely checking that the source parses.

---

# 8. But there is an obvious testing gap

Look at the tests included in `test_advanced_skills.py`.

There is testing for:

- NLP
- NetworkX/graph
- documents' pure text functions
- artifacts
- simulation
- optimization
- finance
- experiments
- metadata
- LLM tools

But the file does **not appear to actually execute the statsmodels-powered functions** such as:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
ts_decompose()
```

</details>

and the other time-series operations.

The test imports:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
timeseries
```

</details>

and includes it in:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
MODULES
```

</details>

but the generic test only checks:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
ast.parse(module.get_code())
```

</details>

for each module. <sup>[source]</sup>

That's a meaningful difference:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
AST parses
       ≠
runtime works
```

</details>

So currently we have stronger evidence for:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
timeseries source validity
```

</details>

than for:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
statsmodels integration correctness
```

</details>

---

# 9. Time-series implementation itself deserves a dedicated test suite

There are several meaningful behaviors in `timeseries.py`:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
ts_prepare()
_detect_period()
ts_decompose()
ts_summary()
ts_forecast_linear()
ts_detect_anomalies()
ts_seasonality_check()
```

</details>

<sup>[source]</sup>

These deserve direct tests.

For example:

### `ts_prepare`

Test:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
unsorted dates
      ↓
sorted index
      ↓
numeric conversion
      ↓
optional resampling
```

</details>

### `ts_decompose`

Test:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
short series
     ↓
correct ValueError
```

</details>

and:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
adequate seasonal series
     ↓
trend
seasonal
residual
```

</details>

### `ts_forecast_linear`

Test:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
perfect linear series
       ↓
R² ≈ 1
       ↓
correct slope
       ↓
correct horizon
```

</details>

### `ts_detect_anomalies`

Test all three:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
zscore
iqr
rolling
```

</details>

### `ts_seasonality_check`

Test known periodic synthetic data.

This would turn the time-series extra from **source-tested** into **behavior-tested**.

---

# 10. There is also a scientific-validity issue

This is more important than a normal unit-test issue.

`ts_summary()` calls:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
likely_stationary =
    mean_shift < 0.1
```

</details>

That is only a **heuristic**, not a formal stationarity test. <sup>[source]</sup>

Calling the result:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
"likely_stationary"
```

</details>

is reasonable if explicitly documented as a heuristic.

But users could easily interpret it as:

> "The series passed a statistical stationarity test."

It hasn't.

A stronger implementation could optionally expose:

<details>
<summary><strong>💻 Code Block (text) — 2 lines</strong></summary>

```text
ADF
KPSS
```

</details>

through statsmodels.

For example:

<details>
<summary><strong>💻 Code Block (text) — 4 lines</strong></summary>

```text
ts_stationarity_test()
       │
       ├── ADF
       └── KPSS
```

</details>

while retaining:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
ts_summary()
```

</details>

as a fast heuristic.

---

# 11. Forecasting also needs careful labeling

`ts_forecast_linear()` is explicitly a linear polynomial extrapolation:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
np.polyfit(x, y, 1)
```

</details>

It calculates R² and extrapolates future values. <sup>[source]</sup>

That's perfectly valid as a **baseline forecast**.

But R² measures goodness of fit to the historical data; it does **not** establish that the future forecast is accurate.

Therefore:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
R² = 0.99
```

</details>

doesn't mean:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
forecast accuracy = 99%
```

</details>

The API/documentation should make this distinction very clear.

A future version could add:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
train/test split
walk-forward validation
MAE
RMSE
MAPE
```

</details>

for actual forecast evaluation.

---

# 12. One more important issue: plotting is forced into skills

Several functions automatically create/display Matplotlib figures.

For example:

<details>
<summary><strong>💻 Code Block (text) — 3 lines</strong></summary>

```text
ts_decompose()
ts_forecast_linear()
ts_detect_anomalies()
```

</details>

generate plots automatically. <sup>[source]</sup>

The design documentation says:

> "Always visualize alongside numerical results."

That's a deliberate UX decision.

For a Jupyter-native system, this makes sense.

But for:

<details>
<summary><strong>💻 Code Block (text) — 5 lines</strong></summary>

```text
headless server
CLI
automated agent
API execution
CI
```

</details>

automatic visualization can become undesirable.

A stronger API would separate:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
analysis
```

</details>

from:

<details>
<summary><strong>💻 Code Block (text) — 1 lines</strong></summary>

```text
presentation
```

</details>

For example:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
result = ts_decompose(series, plot=False)
```

</details>

and then:

<details>
<summary><strong>💻 Code Block (python) — 1 lines</strong></summary>

```python
plot_timeseries_decomposition(result)
```

</details>

This would make Kerno more composable.

---

# 13. Current audit status

I would now classify the extras like this:

| Extra | Declaration | Real source | Lazy dependency | Runtime test | Assessment |
|---|---|---|---|---|---|
| `timeseries` | ✅ | ✅ | ✅ | ⚠️ limited | **Needs tests** |
| `nlp` | ✅ | ✅ | ✅ | ✅ | **Good; resource issue** |
| `graphs` | ✅ | ✅ | ✅ | ✅ | **Good** |
| `documents` | ✅ | ✅ | ✅ | ⚠️ partial | **Good; boundary refinement** |
| `sql` | ✅ | ✅ | likely | ⚠️ not established | **Needs tests** |
| `anthropic` | ✅ | real AI tooling | needs audit | partial | **Needs audit** |
| `openai` | ✅ | needs deeper check | needs audit | partial | **Needs audit** |
| `security` | ✅ empty | ✅ security code | N/A | needs audit | **Explain/document** |
| `all` | ✅ | multiple | — | — | **Needs dependency reconciliation** |
| `dev` | ✅ | — | — | partial | **Needs coverage audit** |

---

# 14. The bigger architectural picture

We're starting to see that Kerno is not simply a package with optional libraries.

It's closer to:

<details>
<summary><strong>💻 Code Block (text) — 16 lines</strong></summary>

```text
                         KERNO
                           │
                 ┌─────────┴─────────┐
                 │                   │
             Kernel Runtime       Skill Runtime
                 │                   │
                 │            ┌──────┼────────┐
                 │            │      │        │
                 │           Data   AI      Knowledge
                 │            │      │        │
                 │         ┌──┼──┐  │    ┌───┼────┐
                 │         │  │  │  │    │   │    │
                 │        TS NLP Graph SQL Docs
                 │
                 ▼
             Jupyter/IPython
```

</details>

And the optional dependencies are effectively **capability activation mechanisms**.

That's a strong direction.

---

## Next audit stage

The next thing I'd investigate is **the skill loader/registry itself**.

Specifically:

<details>
<summary><strong>💻 Code Block (text) — 7 lines</strong></summary>

```text
kerno/skills/
    │
    ├── discovery
    ├── registry
    ├── builtins
    ├── execution
    └── get_code()
```

</details>

Because that is where we can answer the most important architectural questions:

1. **How are built-in skills discovered?**
2. **When is their generated code executed?**
3. **Can one missing optional dependency break skill registration?**
4. **How does Kerno report an unavailable capability?**
5. **Can an agent dynamically select a skill?**
6. **Are skills isolated from the host/kernel?**
7. **What prevents a generated skill from escaping its intended execution boundary?**
8. **How does `kerno[all]` map onto the actual skill registry?**

That is the point where this moves from a **dependency audit** into a genuine **Kerno architecture/security audit**.

---

---
[← Previous section](./02-dependency-architecture.md) | [Back to index](./README.md) | [Next section →](./04-skill-registry-and-composition.md)

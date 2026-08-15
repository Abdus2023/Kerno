# kerno

*A kernel-native agent runtime. Connect a brain (LLM) to a body (Jupyter kernel).*

```python
from kerno import run

result = run("Analyze data.csv and plot the revenue distribution", llm=my_llm)
```

---

## The Core Idea

A Jupyter kernel already has persistent memory (namespace), an execution
engine (IPython), rich I/O (plots, tables, HTML), and a message protocol (ZMQ).
The only missing piece is the decision-making loop — which is exactly what an LLM provides.

**kerno connects them.**

---

## Installation

```bash
pip install kerno

# With Anthropic
pip install "kerno[anthropic]"

# With OpenAI
pip install "kerno[openai]"

# Full stack
pip install "kerno[all]"
```

---

## Quick Start

```python
import anthropic
from kerno import run, Message

client = anthropic.Anthropic()

def my_llm(messages: list[Message]) -> str:
    response = client.messages.create(
        model      = "claude-opus-4-5",
        max_tokens = 4096,
        system     = messages[0].content,
        messages   = [{"role": m.role, "content": m.content} for m in messages[1:]],
    )
    return response.content[0].text

result = run(
    task    = "Generate 500 rows of sales data, profile it, and plot distributions",
    llm     = my_llm,
    verbose = True,
)
print(result.status, result.cells_executed)
```

---

## Loop Strategies

| Loop | Use When |
|------|----------|
| `reactive` | Short, well-defined tasks |
| `reflect` | Open-ended exploration — each cell followed by explicit reflection |
| `plan` | Multi-step tasks with known structure — plan first, verify each step |
| `hierarchical` | Cost-sensitive — cheap executor LLM, expensive planner LLM |
| `multi_agent` | Quality-critical — analyst + critic + narrator on shared kernel |
| `debate` | High-stakes decisions — two agents argue opposite positions |

---

## Built-in Skills

Loaded into every kernel automatically:

```python
# Data
df = load("data.csv")
stats = profile(df)
df_clean = clean_nulls(df, strategy="fill")
checkpoint(df_clean)

# Visualization
plot_distributions(df)
plot_correlation(df)
plot_timeseries(df, "date", ["revenue", "units"])
plot_comparison(df, "region", "revenue")
plot_scatter(df, "discount", "churn_rate", color_col="segment")

# ML
splits = split(df, target="churn_flag")
model  = train_classifier(splits["X_train"], splits["y_train"])
cv     = cross_validate_model(model, X, y)
metrics = evaluate_classifier(model, splits["X_test"], splits["y_test"])
importances = feature_importance(model, splits["feature_names"])

# Statistics
ttest(group_a, group_b)
anova(group_1, group_2, group_3)
bootstrap_ci(series, statistic=np.median)
correlate(x, y)

# Introspection
what_exists()
schema_of("df")
diagnose("model")
memory_report()
```

---

## Memory

Sessions remember their outcomes:

```python
from kerno import run, SimpleMemoryStore

memory = SimpleMemoryStore(".kerno/memory.json")

# Session 1
run("Analyze Q3 sales performance", llm=my_llm, memory=memory)

# Session 2 — recalls Session 1
run("Compare Q4 to last quarter", llm=my_llm, memory=memory)
```

---

## Security

```python
from kerno import run, AllowList

# Restrict to data analysis operations only
result = run(
    task      = "Analyze uploaded_data.csv",
    llm       = my_llm,
    allowlist = AllowList.data_analysis(),
)
```

Profiles: `AllowList.permissive()` | `AllowList.data_analysis()` | `AllowList.read_only()`

---

## Parallel Execution

```python
from kerno import run_with_pool

results = run_with_pool(
    tasks     = ["Analyze region A", "Analyze region B", "Analyze region C"],
    llm       = my_llm,
    pool_size = 3,       # 3 kernels, 3 tasks simultaneously
)
```

---

## Notebooks

Every session can produce a reproducible Jupyter notebook:

```python
result = run(task, llm=my_llm, save_notebook=True, notebook_dir="sessions")
# → sessions/20240127_143022_analyze_q3_sales.ipynb
```

Resume an interrupted session:

```python
from kerno import continue_from_notebook

result = continue_from_notebook(
    path     = "sessions/interrupted_analysis.ipynb",
    llm      = my_llm,
    new_task = "Complete the analysis from where it stopped",
)
```

---

## Configuration

```python
from kerno import KernoConfig, run_with_config

config = KernoConfig.for_production()
result = run_with_config("Analyze sales data", llm=my_llm, config=config)
```

Or from environment variables:
```bash
KERNO_KERNEL_MAX_CELLS=100
KERNO_MEMORY_ENABLED=true
KERNO_SECURITY_PROFILE=data_analysis
KERNO_OUTPUT_SAVE_NOTEBOOK=true
```

---

## CLI

```bash
# Run a task
kerno run "Analyze data.csv" --loop reflect --save-notebook

# List past sessions    
kerno session list

# Search memory
kerno memory search "churn prediction"

# Environment check
kerno doctor

# Show metrics
kerno metrics
```

---

## Plugins

```python
from kerno import run, PluginRegistry, TimingPlugin, CostEstimatorPlugin

plugins = (
    PluginRegistry()
    .register(TimingPlugin())
    .register(CostEstimatorPlugin(model="claude-opus-4-5"))
)

result = run(task, llm=my_llm, plugins=plugins)
# [timing] Session: 14.3s  Avg cell: 2.4s  Slowest: 8.1s
# [cost]   Estimated: $0.0234  (~4,200 in tokens, ~890 out tokens)
```

---

## Architecture

```
kerno/
├── kernel/          KernelRuntime, KernelPool
├── loop/            ReactiveLoop, ReflectReviseLoop, PlanExecuteLoop,
│                    HierarchicalLoop, MultiAgentLoop, DebateLoop
├── context/         PromptBuilder, HistoryCompressor
├── skills/          SkillRegistry + builtins (data, viz, ml, stats, web, sql)
├── errors/          ErrorClassifier, RecoveryStrategy
├── memory/          SimpleMemoryStore, ChromaMemoryStore
├── security/        AllowList, InputSanitizer
├── comms/           KernoComm (structured ZMQ messages)
├── telemetry/       Tracer, Metrics, StructuredLogger
├── audit/           NotebookAuditTrail
├── notebook/        continuation (resume from .ipynb)
├── plugins/         PluginRegistry, BasePlugin, built-in plugins
└── cli/             kerno run / session / memory / config / doctor
```

---

## License

MIT

# examples/11_composable.py
"""
Example 11: Demonstrating composability at every layer.
Shows: swapping components, custom pipelines, composed LLMs, custom skills.
"""

from kerno.compose    import Session
from kerno.llm.wrappers import CachedLLM, RetryLLM, FallbackLLM, ModelRouter
from kerno.memory.simple import SimpleMemoryStore
from kerno.security.allowlist import AllowList
from kerno.skills.composer import SkillSet, CodeSkill, analysis_skills, ml_skills
from kerno.plugins.registry import TimingPlugin, CostEstimatorPlugin
from kerno.steps      import (
    GenerateCodeStep, ExecuteStep, TransformCodeStep,
    FormatOutputStep, CompressHistoryStep, CompletionCheckStep,
    InjectMemoryStep, StoreMemoryStep,
)
from kerno.steps.transform  import (
    NormalizationTransformer, TimingTransformer, AllowListTransformer
)
from kerno.steps.format     import AnomalyFlagFormatter
from kerno.pipeline   import LoopStep, Pipeline


# ── Approach 1: Builder API (readable, minimal) ────────────────────────────────

def example_builder():
    """
    Uses the Session builder API to configure and run a session.
    Requires a real LLM — shown as a template.
    """
    # In production, replace with a real LLM:
    # from kerno.llm.adapters import anthropic_llm
    # llm = RetryLLM(anthropic_llm("claude-opus-4-5"))

    # This example shows the builder pattern; uncomment and add a real LLM to run:
    # result = (
    #     Session()
    #     .with_llm(llm)
    #     .with_kernel()
    #     .with_skills(ml_skills())
    #     .with_memory(SimpleMemoryStore(".kerno/memory.json"))
    #     .with_security(AllowList.data_analysis())
    #     .with_plugins(TimingPlugin(), CostEstimatorPlugin())
    #     .with_loop("reflect", max_cells=40)
    #     .with_notebook(save=True)
    #     .verbose(True)
    #     .run("Build a churn prediction model on the sales data")
    # )
    # print(result.status)
    print("Example builder pattern — add a real LLM to run")


# ── Approach 2: Fully custom pipeline ─────────────────────────────────────────

def example_custom_pipeline():
    """
    Every step is explicit and independently swappable.
    Requires a real LLM and kernel — shown as a template.
    """
    # from kerno.kernel.runtime import KernelRuntime
    # from kerno.llm.adapters import anthropic_llm
    # llm      = anthropic_llm("claude-opus-4-5")
    # memory   = SimpleMemoryStore()
    # allowlist = AllowList.data_analysis()

    # with KernelRuntime() as kernel:
    #     from kerno.skills.bootstrap import bootstrap
    #     bootstrap(kernel)

    #     cell_pipeline = Pipeline([
    #         GenerateCodeStep(llm),
    #         TransformCodeStep([
    #             NormalizationTransformer(),
    #             AllowListTransformer(allowlist),
    #             TimingTransformer(),
    #         ]),
    #         ExecuteStep(kernel),
    #         FormatOutputStep([AnomalyFlagFormatter()]),
    #         CompressHistoryStep(llm, threshold=15),
    #         CompletionCheckStep(),
    #     ])

    #     full_pipeline = Pipeline([
    #         InjectMemoryStep(memory),
    #         LoopStep(cell_pipeline, done=lambda s: s.complete, max_iterations=30),
    #         StoreMemoryStep(memory),
    #     ])

    #     from kerno.interfaces import AgentState
    #     state = AgentState(task="Analyze and profile the kernel namespace")
    #     final = full_pipeline.run(state)
    #     print("Complete: {}  Cells: {}".format(final.complete, len(final.history)))
    print("Example custom pipeline — add a real LLM to run")


# ── Approach 3: Composed LLM ───────────────────────────────────────────────────

def example_composed_llm():
    """
    Build an LLM that caches, retries, and routes.
    Requires Anthropic SDK — shown as a template.
    """
    # from kerno.llm.adapters import anthropic_llm
    # cheap    = anthropic_llm("claude-haiku-4-5")
    # expensive = anthropic_llm("claude-opus-4-5")

    # smart_llm = CachedLLM(
    #     RetryLLM(
    #         ModelRouter([
    #             (lambda msgs: len(msgs) > 25,   expensive),
    #             (lambda msgs: True,              cheap),
    #         ]),
    #         max_retries = 3,
    #     ),
    #     persist_path = ".kerno/llm_cache.json",
    # )

    # result = (
    #     Session()
    #     .with_llm(smart_llm)
    #     .with_kernel()
    #     .with_loop("reactive", max_cells=20)
    #     .run("Profile the default namespace and list all available skills")
    # )
    # print("Cache hits after run: {}".format(smart_llm.cache_size))
    print("Example composed LLM — add Anthropic/OpenAI SDK to run")


# ── Approach 4: Composed skills ────────────────────────────────────────────────

def example_composed_skills():
    """
    Compose standard skills with a domain-specific custom skill.
    """
    domain_skill = CodeSkill(
        name        = "sales_domain",
        description = "Domain-specific sales analysis functions",
        code        = '''
def load_sales_data(year: int = 2024):
    """Load and validate sales data for a given year."""
    import pandas as pd
    import numpy as np
    n = 1000
    df = pd.DataFrame({
        "date":    pd.date_range("{}-01-01".format(year), periods=n, freq="D"),
        "region":  np.random.choice(["North", "South", "East", "West"], n),
        "product": np.random.choice(["A", "B", "C"], n),
        "revenue": np.random.exponential(1000, n),
        "units":   np.random.randint(1, 50, n),
        "churn":   np.random.binomial(1, 0.15, n),
    })
    print("✓ Loaded {} sales data: {}".format(year, df.shape))
    return df

def quarterly_summary(df):
    """Summarize performance by quarter and region."""
    df["quarter"] = df["date"].dt.to_period("Q")
    return (
        df.groupby(["quarter", "region"])
        .agg(revenue=("revenue", "sum"), units=("units", "sum"))
        .reset_index()
    )
'''.format(2024),
        dependencies = ["data"],
    )

    # Compose standard + domain skills
    my_skills = analysis_skills() | SkillSet().add(domain_skill)

    print("Composed skills: {}".format(my_skills.names()))
    print("Load order: {}".format(my_skills._load_order()))
    print("Total skill count: {}".format(len(my_skills)))


if __name__ == "__main__":
    print("Example 1: Builder API")
    example_builder()

    print("\nExample 4: Composed skills (doesn't require LLM)")
    example_composed_skills()

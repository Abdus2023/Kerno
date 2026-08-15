"""
Example 12: Advanced composition patterns.

Demonstrates five composable patterns:
  1. Observable pipeline  — intercept before/after/error callbacks
  2. Adaptive LLM routing — route to different models based on context
  3. Validated pipeline    — enforce invariants at every step
  4. Composed domain skills — merge skill sets with operators
  5. Declarative from YAML — build pipelines from configuration
"""

from kerno.interfaces import AgentState
from kerno.pipeline import Pipeline, LoopStep, ConditionalStep, IdentityStep
from kerno.interceptors import InterceptedPipeline, StateRecorder, InvariantChecker
from kerno.llm.wrappers import ModelRouter, CachedLLM, RetryLLM, FallbackLLM
from kerno.skills.composer import SkillSet, CodeSkill
from kerno.config_dsl import PipelineCompiler, TEMPLATES


# ── Pattern 1: Observable pipeline ────────────────────────────────────────────

class PrintStep:
    """Step that prints and marks state."""
    def __init__(self, label):
        self.label = label
    def run(self, state):
        state.metadata[self.label] = True
        return state


def observable_pipeline():
    """
    Wrap a pipeline with interceptors that observe execution
    without modifying the state.
    """
    recorder = StateRecorder()

    inner = Pipeline([
        PrintStep("step1"),
        PrintStep("step2"),
        PrintStep("step3"),
    ])

    observed = InterceptedPipeline(
        inner,
        on_before=recorder.capture("before"),
        on_after=recorder.capture("after"),
    )

    state = AgentState(task="observe me")
    result = observed.run(state)

    print("Observations recorded: {}".format(len(recorder.snapshots)))
    if len(recorder.snapshots) >= 2:
        diff = recorder.diff(0, 1)
        print("State diff: {}".format(diff))

    return result


# ── Pattern 2: Adaptive LLM routing ──────────────────────────────────────────

def adaptive_llm_routing():
    """
    Route to different LLMs based on message characteristics.
    Implements cost optimization without changing application code.
    """
    def cheap_llm(messages):
        return "cheap response"

    def expensive_llm(messages):
        return "detailed expert response"

    def planner_llm(messages):
        return "structured plan"

    router = ModelRouter([
        # Long context → expensive model
        (lambda msgs: sum(len(m.content) for m in msgs) > 500, expensive_llm),
        # Planning keywords → planner
        (lambda msgs: any("plan" in m.content.lower() for m in msgs), planner_llm),
        # Default → cheap
        (lambda msgs: True, cheap_llm),
    ])

    from kerno.types import Message

    # Short query → cheap
    short_msgs = [Message(role="user", content="quick question")]
    result_short = router(short_msgs)
    print("Short query → {}".format(result_short))

    # Long query → expensive
    long_msgs = [Message(role="user", content="x" * 600)]
    result_long = router(long_msgs)
    print("Long query → {}".format(result_long))

    # Planning query → planner
    plan_msgs = [Message(role="user", content="plan the project roadmap")]
    result_plan = router(plan_msgs)
    print("Plan query → {}".format(result_plan))


# ── Pattern 3: Validated pipeline ────────────────────────────────────────────

def validated_pipeline():
    """
    Enforce invariants at every step transition.
    Invariants are checked before and after each step.
    """
    checker = InvariantChecker([
        lambda s: s.task != "",            # Task never empty
        lambda s: len(s.history) <= 100,   # No infinite loops
    ])

    inner = Pipeline([
        PrintStep("validated_step1"),
        PrintStep("validated_step2"),
    ])

    validated = InterceptedPipeline(
        inner,
        on_before=checker.check_before,
        on_after=checker.check_after,
    )

    state = AgentState(task="validated task")
    result = validated.run(state)

    try:
        checker.assert_ok()
        print("All invariants passed!")
    except Exception as e:
        print("Invariant violations: {}".format(e))

    return result


# ── Pattern 4: Composed domain skills ─────────────────────────────────────────

def composed_skills():
    """
    Merge skill sets using | (merge) and - (subtract) operators.
    Build custom skill stacks from preset combinations.
    """
    data_skills = SkillSet()
    data_skills.add(CodeSkill("pandas_loader", "import pandas as pd\npd.read_csv"))
    data_skills.add(CodeSkill("data_cleaner", "df.dropna()", dependencies=["pandas_loader"]))

    viz_skills = SkillSet()
    viz_skills.add(CodeSkill("matplotlib", "import matplotlib.pyplot as plt"))
    viz_skills.add(CodeSkill("seaborn", "import seaborn as sns", dependencies=["matplotlib"]))

    ml_skills = SkillSet()
    ml_skills.add(CodeSkill("sklearn", "from sklearn.model_selection import train_test_split"))

    # Merge data + viz
    analysis = data_skills | viz_skills
    print("Analysis skills: {}".format(analysis.names()))

    # Merge all three
    full_stack = analysis | ml_skills
    print("Full stack skills: {}".format(full_stack.names()))

    # Subtract unwanted skills
    lightweight = full_stack - ["seaborn", "sklearn"]
    print("Lightweight skills: {}".format(lightweight.names()))

    # Get combined code
    print("Combined code preview (first 200 chars):")
    print(full_stack.combined_code()[:200])


# ── Pattern 5: Declarative from YAML ─────────────────────────────────────────

def declarative_pipeline():
    """
    Build a pipeline from a YAML configuration string.
    No Python code needed — just declare the steps.
    """
    class MockLLM:
        def __call__(self, messages):
            return "print('hello')"

    class MockKernel:
        def execute(self, code, **kwargs):
            from kerno.types import CellOutput
            return CellOutput(text="ok")
        def execute_silent(self, code, **kwargs):
            return ""
        @property
        def namespace(self):
            return "{}"
        @property
        def is_alive(self):
            return True

    compiler = PipelineCompiler(llm=MockLLM(), kernel=MockKernel())

    # Use a built-in template
    pipeline = compiler.from_yaml(TEMPLATES["reactive"])
    print("Pipeline steps from reactive template: {}".format(len(pipeline.steps)))

    # Custom YAML spec
    custom_spec = """
steps:
  - generate: {llm: default}
  - execute: {}
  - check: {}
"""
    custom_pipeline = compiler.from_yaml(custom_spec)
    print("Custom pipeline steps: {}".format(len(custom_pipeline.steps)))

    # Visualize
    from kerno.graph import PipelineGraph
    graph = PipelineGraph.from_pipeline(pipeline)
    print("Pipeline graph ASCII:")
    print(graph.ascii())


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Pattern 1: Observable pipeline")
    print("=" * 60)
    observable_pipeline()

    print("\n" + "=" * 60)
    print("Pattern 2: Adaptive LLM routing")
    print("=" * 60)
    adaptive_llm_routing()

    print("\n" + "=" * 60)
    print("Pattern 3: Validated pipeline")
    print("=" * 60)
    validated_pipeline()

    print("\n" + "=" * 60)
    print("Pattern 4: Composed domain skills")
    print("=" * 60)
    composed_skills()

    print("\n" + "=" * 60)
    print("Pattern 5: Declarative from YAML")
    print("=" * 60)
    declarative_pipeline()

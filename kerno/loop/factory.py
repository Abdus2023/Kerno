# kerno/loop/factory.py
"""
Loop factory: build any loop strategy from composable steps.

This replaces the class hierarchy (BaseLoop → ReactiveLoop → ReflectReviseLoop → ...)
with a flat collection of step combinations.

The factory knows which steps to combine for each strategy.
You can also compose your own strategy from scratch.
"""

from __future__ import annotations

from typing import Optional

from kerno.interfaces  import AgentState, Executor, LLM, Memory
from kerno.pipeline    import LoopStep, Pipeline
from kerno.steps       import (
    CompressHistoryStep, CompletionCheckStep,
    ExecuteStep, FormatOutputStep,
    GenerateCodeStep, InjectMemoryStep,
    ReflectAndGenerateStep, StoreMemoryStep,
    TransformCodeStep,
)
from kerno.steps.transform import NormalizationTransformer


def is_complete(state: AgentState) -> bool:
    return state.complete or bool(state.error)


def make_reactive(
    kernel:      Executor,
    llm:         LLM,
    memory:      Optional[Memory]  = None,
    transformers: list             = None,
    formatters:   list             = None,
    max_cells:    int              = 50,
    compress_after: int            = 20,
) -> LoopStep:
    """
    Build a ReactiveLoop from composable steps.

    observe → generate → transform → execute → format → compress → check
    """
    steps = []

    # Memory injection (once, at start — handled by InjectMemoryStep's guard)
    if memory:
        steps.append(InjectMemoryStep(memory))

    # Core cell pipeline
    cell_steps = [
        GenerateCodeStep(llm),
        TransformCodeStep([NormalizationTransformer()] + (transformers or [])),
        ExecuteStep(kernel),
        FormatOutputStep(formatters or []),
        CompressHistoryStep(llm, threshold=compress_after),
        CompletionCheckStep(),
    ]

    if memory:
        cell_steps.append(StoreMemoryStep(memory))

    cell_pipeline = Pipeline(cell_steps)
    return LoopStep(cell_pipeline, done=is_complete, max_iterations=max_cells)


def make_reflect(
    kernel:      Executor,
    llm:         LLM,
    memory:      Optional[Memory] = None,
    max_cells:   int              = 50,
    compress_after: int           = 20,
) -> LoopStep:
    """
    Build a ReflectReviseLoop.
    Difference from reactive: GenerateCodeStep → ReflectAndGenerateStep.
    That's it. Same pipeline, one step swapped.
    """
    steps = []
    if memory:
        steps.append(InjectMemoryStep(memory))

    cell_steps = [
        ReflectAndGenerateStep(llm),       # ← only difference
        TransformCodeStep([NormalizationTransformer()]),
        ExecuteStep(kernel),
        FormatOutputStep(),
        CompressHistoryStep(llm, threshold=compress_after),
        CompletionCheckStep(),
    ]
    if memory:
        cell_steps.append(StoreMemoryStep(memory))

    return LoopStep(
        Pipeline(cell_steps),
        done           = is_complete,
        max_iterations = max_cells,
    )


def make_plan_execute(
    kernel:    Executor,
    llm:       LLM,
    memory:    Optional[Memory] = None,
    max_cells: int              = 50,
) -> Pipeline:
    """
    Build a PlanExecuteLoop.
    Structure: plan once, then loop on (execute + verify).
    """
    from kerno.steps.plan import PlanStep, VerifyStep

    plan_step    = PlanStep(llm)
    execute_loop = LoopStep(
        Pipeline([
            GenerateCodeStep(llm),
            TransformCodeStep([NormalizationTransformer()]),
            ExecuteStep(kernel),
            FormatOutputStep(),
            VerifyStep(llm),
            CompletionCheckStep(),
        ]),
        done           = is_complete,
        max_iterations = max_cells,
    )

    steps = [plan_step, execute_loop]
    if memory:
        steps = [InjectMemoryStep(memory)] + steps + [StoreMemoryStep(memory)]

    return Pipeline(steps)


def make_custom(steps: list) -> LoopStep:
    """
    Build a completely custom loop from an arbitrary list of steps.

    Example:
        loop = make_custom([
            InjectMemoryStep(memory),
            GenerateCodeStep(llm),
            AllowListTransformer(allowlist),   # inject security
            ExecuteStep(kernel),
            StoreInsightStep(memory, llm),     # learn from outputs
            CompletionCheckStep(),
        ])
    """
    from kerno.pipeline import LoopStep, Pipeline
    return LoopStep(
        Pipeline(steps),
        done           = is_complete,
        max_iterations = 50,
    )

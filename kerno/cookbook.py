# kerno/cookbook.py
"""
Cookbook: ready-to-use pipeline recipes.

Each recipe function returns a Pipeline that can be run directly
or composed into larger pipelines.

Usage:
    from kerno.cookbook import quick_analysis

    result = quick_analysis(
        task="Analyze sales.csv",
        llm=my_llm,
        kernel=my_kernel,
    )

    # Or compose into a larger pipeline:
    from kerno.pipeline import Pipeline
    result = Pipeline([
        quick_analysis(llm, kernel),
        review_step,
    ]).run(state)
"""

from __future__ import annotations

from typing import Any

from kerno.interfaces import AgentState
from kerno.loop.factory import is_complete
from kerno.pipeline import LoopStep, Pipeline
from kerno.steps.compress import CompletionCheckStep, CompressHistoryStep
from kerno.steps.execute import ExecuteStep
from kerno.steps.format import FormatOutputStep
from kerno.steps.generate import GenerateCodeStep, ReflectAndGenerateStep
from kerno.steps.memory import InjectMemoryStep, StoreMemoryStep
from kerno.steps.plan import PlanStep, VerifyStep
from kerno.steps.transform import NormalizationTransformer, TransformCodeStep


def _base_steps(
    llm:    Any,
    kernel: Any,
    memory: Any = None,
    transformers: list = None,
    formatters:   list = None,
) -> list:
    """Build the common cell-execution steps."""
    steps = [
        GenerateCodeStep(llm),
        TransformCodeStep(
            [NormalizationTransformer()] + (transformers or [])
        ),
        ExecuteStep(kernel),
        FormatOutputStep(formatters or []),
    ]
    return steps


def quick_analysis(
    llm:    Any,
    kernel: Any,
    *,
    memory: Any = None,
    max_cells: int = 50,
) -> LoopStep:
    """
    Quick data analysis: reactive loop, minimal configuration.
    The simplest useful pipeline.
    """
    cell_steps = _base_steps(llm, kernel, memory)
    cell_steps.append(CompletionCheckStep())

    if memory:
        cell_steps.append(StoreMemoryStep(memory))

    steps = []
    if memory:
        steps.append(InjectMemoryStep(memory))
    steps.append(LoopStep(
        Pipeline(cell_steps),
        done=is_complete,
        max_iterations=max_cells,
    ))

    return Pipeline(steps)


def deep_analysis(
    llm:    Any,
    kernel: Any,
    *,
    memory: Any = None,
    max_cells: int = 50,
) -> LoopStep:
    """
    Deep analysis with reflection: each cell is reviewed before
    the next is generated. Slower but more thorough.
    """
    cell_steps = [
        ReflectAndGenerateStep(llm),
        TransformCodeStep([NormalizationTransformer()]),
        ExecuteStep(kernel),
        FormatOutputStep(),
        CompletionCheckStep(),
    ]

    if memory:
        cell_steps.append(StoreMemoryStep(memory))

    steps = []
    if memory:
        steps.append(InjectMemoryStep(memory))
    steps.append(LoopStep(
        Pipeline(cell_steps),
        done=is_complete,
        max_iterations=max_cells,
    ))

    return Pipeline(steps)


def secure_analysis(
    llm:       Any,
    kernel:    Any,
    allowlist: Any,
    *,
    memory:    Any = None,
    max_cells: int = 50,
) -> Pipeline:
    """
    Secure analysis: reactive loop with safety guard.
    The allowlist restricts what code can be executed.
    """
    from kerno.steps.transform import AllowListTransformer

    transformers = [NormalizationTransformer(), AllowListTransformer(allowlist)]
    cell_steps = _base_steps(llm, kernel, memory, transformers=transformers)
    cell_steps.append(CompletionCheckStep())

    if memory:
        cell_steps.append(StoreMemoryStep(memory))

    steps = []
    if memory:
        steps.append(InjectMemoryStep(memory))
    steps.append(LoopStep(
        Pipeline(cell_steps),
        done=is_complete,
        max_iterations=max_cells,
    ))

    return Pipeline(steps)


def resilient_analysis(
    llm:    Any,
    kernel: Any,
    *,
    memory:    Any = None,
    max_cells: int = 50,
    max_retries: int = 3,
) -> Pipeline:
    """
    Resilient analysis: wraps the execute step with retry.
    Handles transient kernel failures gracefully.
    """
    from kerno.pipeline import RetryStep

    cell_steps = [
        GenerateCodeStep(llm),
        TransformCodeStep([NormalizationTransformer()]),
        RetryStep(ExecuteStep(kernel), max_retries=max_retries),
        FormatOutputStep(),
        CompletionCheckStep(),
    ]

    if memory:
        cell_steps.append(StoreMemoryStep(memory))

    steps = []
    if memory:
        steps.append(InjectMemoryStep(memory))
    steps.append(LoopStep(
        Pipeline(cell_steps),
        done=is_complete,
        max_iterations=max_cells,
    ))

    return Pipeline(steps)


def production_pipeline(
    llm:    Any,
    kernel: Any,
    *,
    memory: Any = None,
    plugins: Any = None,
    max_cells: int = 50,
) -> Pipeline:
    """
    Production-ready pipeline: reactive loop with full middleware stack.
    Includes timing, logging, tracing, budget enforcement, and checkpointing.
    """
    from kerno.middleware import (
        TimedMiddleware, LoggedMiddleware,
        BudgetMiddleware, PluginMiddleware, wrap,
        apply_middleware,
    )

    cell_steps = [
        GenerateCodeStep(llm),
        TransformCodeStep([NormalizationTransformer()]),
        ExecuteStep(kernel),
        FormatOutputStep(),
        CompletionCheckStep(),
    ]

    if memory:
        cell_steps.append(StoreMemoryStep(memory))

    # Apply middleware to each cell step
    cell_pipeline = Pipeline(cell_steps)

    # Wrap the whole pipeline in budget middleware
    budgeted = BudgetMiddleware(cell_pipeline, max_cells=max_cells)

    steps = []
    if memory:
        steps.append(InjectMemoryStep(memory))
    if plugins:
        steps.append(PluginMiddleware(budgeted, plugins))
    else:
        steps.append(budgeted)

    return Pipeline(steps)


def multi_agent_review(
    llm:    Any,
    kernel: Any,
    *,
    memory: Any = None,
    max_cells: int = 30,
) -> Pipeline:
    """
    Multi-agent style review: plan, then execute with verification.
    Each cell is verified before the next is planned.
    """
    cell_steps = [
        GenerateCodeStep(llm),
        TransformCodeStep([NormalizationTransformer()]),
        ExecuteStep(kernel),
        FormatOutputStep(),
        VerifyStep(llm),
        CompletionCheckStep(),
    ]

    if memory:
        cell_steps.append(StoreMemoryStep(memory))

    steps = []
    if memory:
        steps.append(InjectMemoryStep(memory))
    steps.append(PlanStep(llm))
    steps.append(LoopStep(
        Pipeline(cell_steps),
        done=is_complete,
        max_iterations=max_cells,
    ))

    return Pipeline(steps)


def custom_pipeline(
    llm:    Any,
    kernel: Any,
    *,
    memory: Any = None,
    steps:  list = None,
) -> Pipeline:
    """
    Build a fully custom pipeline from an arbitrary list of steps.
    Falls back to a basic reactive pipeline if no steps provided.
    """
    if steps:
        return Pipeline(steps)

    # Default: simple reactive
    return quick_analysis(llm, kernel, memory=memory)

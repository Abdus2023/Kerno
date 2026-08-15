# kerno/pipeline.py
"""
Pipeline: compose Steps into a processing graph.

A Step is anything with .run(AgentState) -> AgentState.
A Pipeline is a sequence of Steps — and is itself a Step.

This is the composability primitive.

Examples:
    # Linear pipeline
    pipe = Pipeline([
        InjectMemoryStep(memory),
        GenerateCodeStep(llm, context_builder),
        TransformCodeStep([SafetyTransformer(), TimingTransformer()]),
        ExecuteStep(kernel),
        FormatOutputStep(formatter),
        CompressHistoryStep(compressor),
    ])

    # Branching pipeline
    pipe = Pipeline([
        GenerateCodeStep(llm, context_builder),
        ConditionalStep(
            condition = lambda s: "model.fit" in s.metadata.get("last_code", ""),
            if_true   = Pipeline([TimingStep(), CheckpointStep()]),
            if_false  = IdentityStep(),
        ),
        ExecuteStep(kernel),
    ])

    # Nested pipeline
    reflect_pipe = Pipeline([
        GenerateCodeStep(llm),
        ExecuteStep(kernel),
        ReflectStep(llm),      # Extra step: reflect on the output
    ])
    plan_pipe = Pipeline([
        PlanStep(llm),
        LoopStep(reflect_pipe, max_iterations=10, done=is_complete),
    ])
"""

from __future__ import annotations

from typing import Callable, Optional

from kerno.interfaces import AgentState, Step


class Pipeline:
    """
    A sequence of Steps executed in order.
    A Pipeline is itself a Step — pipelines nest freely.
    """

    def __init__(self, steps: list[Step]):
        self.steps = steps

    def run(self, state: AgentState) -> AgentState:
        for step in self.steps:
            if state.complete or state.error:
                break
            state = step.run(state)
        return state

    def then(self, step: Step) -> "Pipeline":
        """Append a step. Returns new pipeline (immutable)."""
        return Pipeline(self.steps + [step])

    def __or__(self, other: Step) -> "Pipeline":
        """Pipe operator: pipe1 | step2"""
        return self.then(other)

    def __repr__(self) -> str:
        names = [getattr(s, "__class__.__name__", str(s)) for s in self.steps]
        return "Pipeline([{}])".format(", ".join(names))


class IdentityStep:
    """Pass-through step. Useful as a no-op in conditional branches."""
    def run(self, state: AgentState) -> AgentState:
        return state


class ConditionalStep:
    """Branch on a condition."""
    def __init__(
        self,
        condition: Callable[[AgentState], bool],
        if_true:   Step,
        if_false:  Step = None,
    ):
        self.condition = condition
        self.if_true   = if_true
        self.if_false  = if_false or IdentityStep()

    def run(self, state: AgentState) -> AgentState:
        if self.condition(state):
            return self.if_true.run(state)
        return self.if_false.run(state)


class LoopStep:
    """
    Repeat a step until done or max_iterations reached.
    The inner step can be any Step — including a Pipeline.
    """
    def __init__(
        self,
        step:           Step,
        done:           Callable[[AgentState], bool],
        max_iterations: int = 50,
    ):
        self.step           = step
        self.done           = done
        self.max_iterations = max_iterations

    def run(self, state: AgentState) -> AgentState:
        for _ in range(self.max_iterations):
            if self.done(state):
                state.complete = True
                break
            state = self.step.run(state)
            if state.complete or state.error:
                break
        return state


class ParallelStep:
    """
    Run multiple steps on the same state concurrently.
    Merges results via a combiner function.
    Each step receives a copy of the state; combiner reconciles.
    """
    def __init__(
        self,
        steps:    list[Step],
        combiner: Callable[[AgentState, list[AgentState]], AgentState],
        max_workers: int = 4,
    ):
        self.steps      = steps
        self.combiner   = combiner
        self.max_workers= max_workers

    def run(self, state: AgentState) -> AgentState:
        import copy
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as ex:
            futures = [
                ex.submit(step.run, copy.deepcopy(state))
                for step in self.steps
            ]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        return self.combiner(state, results)


class RetryStep:
    """
    Retry a step up to max_retries times on error.
    """
    def __init__(self, step: Step, max_retries: int = 3):
        self.step        = step
        self.max_retries = max_retries

    def run(self, state: AgentState) -> AgentState:
        last_error = None
        for attempt in range(self.max_retries):
            result = self.step.run(state)
            if not result.error:
                return result
            last_error = result.error
            if attempt < self.max_retries - 1:
                state.metadata["retry_attempt"] = attempt + 1
        state.error = last_error
        return state

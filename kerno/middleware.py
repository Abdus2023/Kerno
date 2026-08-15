# kerno/middleware.py
"""
Middleware: wrap any Step with cross-cutting behavior.

The difference between a Step and Middleware:
  Step:       transforms AgentState
  Middleware: wraps a Step, observes execution, can modify before/after

Middleware composes exactly like function decorators.
Any Step can be wrapped with any combination of middleware.

Usage:
    step = ExecuteStep(kernel)

    # Wrap with middleware
    step = Timed(Logged(Traced(step)))

    # Or use the fluent API:
    step = (
        ExecuteStep(kernel)
        | wrap(Timed)
        | wrap(Logged)
        | wrap(Traced)
    )
"""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

from kerno.interfaces import AgentState, Step


# ── Base ──────────────────────────────────────────────────────────────────────

class Middleware:
    """
    Base class for middleware.
    Wraps a Step and delegates to it.
    Subclasses override before() and/or after().
    """

    def __init__(self, step: Step):
        self.step = step

    def run(self, state: AgentState) -> AgentState:
        state = self.before(state)
        state = self.step.run(state)
        state = self.after(state)
        return state

    def before(self, state: AgentState) -> AgentState:
        return state

    def after(self, state: AgentState) -> AgentState:
        return state

    def then(self, other: Step) -> "Pipeline":
        """Allow: step | wrap(M1) | wrap(M2)"""
        from kerno.pipeline import Pipeline
        return Pipeline([self, other])


# ── Built-in middleware ───────────────────────────────────────────────────────

class TimedMiddleware(Middleware):
    """Records execution time of the wrapped step."""

    def __init__(self, step: Step, label: str = ""):
        super().__init__(step)
        self.label = label or type(step).__name__

    def before(self, state: AgentState) -> AgentState:
        state.metadata["_timer_{}".format(self.label)] = time.monotonic()
        return state

    def after(self, state: AgentState) -> AgentState:
        start = state.metadata.pop("_timer_{}".format(self.label), time.monotonic())
        ms    = (time.monotonic() - start) * 1000
        state.metadata.setdefault("step_timings", {})[self.label] = round(ms, 2)
        return state


class TracedMiddleware(Middleware):
    """Wraps step execution in a telemetry span."""

    def __init__(self, step: Step, span_name: str = ""):
        super().__init__(step)
        self.span_name = span_name or type(step).__name__
        from kerno.telemetry.tracer import get_tracer
        self._tracer = get_tracer()

    def run(self, state: AgentState) -> AgentState:
        attrs = {
            "session.id":  state.session_id,
            "step.type":   type(self.step).__name__,
            "cell.num":    len(state.history) + 1,
        }
        with self._tracer.span("step.{}".format(self.span_name), attrs) as span:
            result = self.step.run(state)
            span.set("cell.had_error",
                     bool(result.history and result.history[-1].output.has_error))
            return result


class LoggedMiddleware(Middleware):
    """Logs step entry and exit."""

    def __init__(self, step: Step, verbose: bool = False):
        super().__init__(step)
        self.verbose = verbose
        from kerno.telemetry.logger import get_logger
        self.log = get_logger("kerno.step")

    def before(self, state: AgentState) -> AgentState:
        if self.verbose:
            print("  → {} (cell {})".format(type(self.step).__name__, len(state.history) + 1))
        self.log.debug("Step start", step=type(self.step).__name__,
                       cell=len(state.history) + 1)
        return state

    def after(self, state: AgentState) -> AgentState:
        had_error = bool(state.history and state.history[-1].output.has_error)
        icon      = "✗" if had_error else "→"
        if self.verbose and state.history:
            text = state.history[-1].output.as_text(max_chars=80)
            print("  {} {}".format(icon, text))
        self.log.debug("Step end", step=type(self.step).__name__,
                       had_error=had_error)
        return state


class PluginMiddleware(Middleware):
    """Fires plugin hooks around step execution."""

    def __init__(self, step: Step, plugins):
        super().__init__(step)
        self.plugins = plugins

    def after(self, state: AgentState) -> AgentState:
        if state.history:
            cell = state.history[-1]
            self.plugins.on_cell_complete(cell)
            if cell.output.has_error:
                from kerno.errors.classifier import ErrorClassifier
                classified = ErrorClassifier().classify(cell.output.error)
                self.plugins.on_error(cell, classified)
        return state


class GuardMiddleware(Middleware):
    """
    Stops execution if a guard condition is met.
    The guard sees state BEFORE the step runs.
    If the guard returns True, the step is skipped.
    """

    def __init__(
        self,
        step:  Step,
        guard: Callable[[AgentState], bool],
        reason: str = "guard condition met",
    ):
        super().__init__(step)
        self.guard  = guard
        self.reason = reason

    def run(self, state: AgentState) -> AgentState:
        if self.guard(state):
            state.metadata["guard_triggered"] = self.reason
            return state
        return self.step.run(state)


class BudgetMiddleware(Middleware):
    """
    Hard stop after a cell budget is exhausted.
    Prevents runaway loops.
    """

    def __init__(self, step: Step, max_cells: int):
        super().__init__(step)
        self.max_cells = max_cells

    def before(self, state: AgentState) -> AgentState:
        if len(state.history) >= self.max_cells:
            state.error    = "Cell budget exhausted ({})".format(self.max_cells)
            state.complete = True
        return state


class CheckpointMiddleware(Middleware):
    """
    Checkpoints kernel state every N cells.
    Transparent — the wrapped step doesn't know about it.
    """

    def __init__(self, step: Step, kernel, every: int = 10):
        super().__init__(step)
        self.kernel = kernel
        self.every  = every

    def after(self, state: AgentState) -> AgentState:
        if len(state.history) % self.every == 0:
            self.kernel.execute(
                """
import joblib as _jl, pathlib as _pl, pandas as _pd
_ckpt = _pl.Path('_checkpoints'); _ckpt.mkdir(exist_ok=True)
for _n, _o in list(globals().items()):
    if _n.startswith('_'): continue
    try:
        if isinstance(_o, _pd.DataFrame):
            _o.to_parquet(_ckpt / f'{_n}.parquet')
        elif hasattr(_o, '__sklearn_tags__'):
            _jl.dump(_o, _ckpt / f'{_n}.joblib')
    except: pass
""",
                silent=True, timeout=30,
            )
        return state


# ── Fluent wrapping ───────────────────────────────────────────────────────────

def wrap(
    middleware_cls,
    *args,
    **kwargs,
) -> Callable[[Step], Middleware]:
    """
    Return a wrapping function for use in chains.

    Usage:
        step = ExecuteStep(kernel)
        step = wrap(TimedMiddleware)(step)
        step = wrap(LoggedMiddleware, verbose=True)(step)
    """
    def _wrap(step: Step) -> Middleware:
        return middleware_cls(step, *args, **kwargs)
    return _wrap


def apply_middleware(
    step:        Step,
    middlewares: list[Callable[[Step], Middleware]],
) -> Step:
    """
    Apply a list of middleware wrappers to a step.
    Applied right-to-left (outermost last).

    Usage:
        step = apply_middleware(ExecuteStep(kernel), [
            wrap(TimedMiddleware),
            wrap(TracedMiddleware),
            wrap(LoggedMiddleware, verbose=True),
        ])
    """
    for mw in reversed(middlewares):
        step = mw(step)
    return step

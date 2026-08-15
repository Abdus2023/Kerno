"""Unit tests for Middleware system."""

import pytest

from kerno.interfaces import AgentState
from kerno.middleware import (
    Middleware, TimedMiddleware, LoggedMiddleware,
    GuardMiddleware, BudgetMiddleware,
    wrap, apply_middleware,
)


# ── Helper steps ──────────────────────────────────────────────────────────────

class TrackingStep:
    """Step that tracks whether it was run."""
    def __init__(self, key="ran"):
        self.key = key
    def run(self, state):
        state.metadata[self.key] = True
        return state


class CounterStep:
    """Step that increments a counter."""
    def run(self, state):
        state.metadata["count"] = state.metadata.get("count", 0) + 1
        return state


# ── TestTimedMiddleware ───────────────────────────────────────────────────────

class TestTimedMiddleware:
    """Tests for TimedMiddleware."""

    def test_records_timing(self):
        step = TrackingStep()
        timed = TimedMiddleware(step)
        state = AgentState(task="test")
        result = timed.run(state)
        assert result.metadata["ran"] is True
        assert "step_timings" in result.metadata
        assert "TrackingStep" in result.metadata["step_timings"]

    def test_custom_label(self):
        step = TrackingStep()
        timed = TimedMiddleware(step, label="custom")
        state = AgentState(task="test")
        result = timed.run(state)
        assert "custom" in result.metadata["step_timings"]

    def test_timing_value_is_positive(self):
        step = TrackingStep()
        timed = TimedMiddleware(step)
        state = AgentState(task="test")
        result = timed.run(state)
        ms = result.metadata["step_timings"]["TrackingStep"]
        assert ms >= 0


class TestGuardMiddleware:
    """Tests for GuardMiddleware."""

    def test_guard_skips_step(self):
        step = TrackingStep()
        guard = GuardMiddleware(
            step,
            guard=lambda s: True,  # Always guard
            reason="blocked",
        )
        state = AgentState(task="test")
        result = guard.run(state)
        assert "ran" not in result.metadata
        assert result.metadata["guard_triggered"] == "blocked"

    def test_guard_passes_when_not_triggered(self):
        step = TrackingStep()
        guard = GuardMiddleware(
            step,
            guard=lambda s: False,  # Never guard
        )
        state = AgentState(task="test")
        result = guard.run(state)
        assert result.metadata["ran"] is True
        assert "guard_triggered" not in result.metadata

    def test_guard_with_condition_on_state(self):
        step = CounterStep()
        guard = GuardMiddleware(
            step,
            guard=lambda s: s.metadata.get("skip", False),
            reason="skip requested",
        )
        state = AgentState(task="test")
        state.metadata["skip"] = True
        result = guard.run(state)
        assert "count" not in result.metadata

        state2 = AgentState(task="test")
        result2 = guard.run(state2)
        assert result2.metadata["count"] == 1


class TestBudgetMiddleware:
    """Tests for BudgetMiddleware."""

    def test_budget_exhausted(self):
        step = CounterStep()
        budget = BudgetMiddleware(step, max_cells=2)

        # Run once to add history
        state = AgentState(task="test")
        state.history = ["cell1", "cell2"]  # Already at budget
        result = budget.run(state)
        assert result.error is not None
        assert "budget" in result.error.lower() or "exhausted" in result.error.lower()

    def test_budget_not_exhausted(self):
        step = CounterStep()
        budget = BudgetMiddleware(step, max_cells=10)
        state = AgentState(task="test")
        result = budget.run(state)
        assert result.error is None
        assert result.metadata["count"] == 1


class TestApplyMiddleware:
    """Tests for wrap() and apply_middleware()."""

    def test_wrap_function(self):
        step = TrackingStep()
        wrapped = wrap(TimedMiddleware)(step)
        assert isinstance(wrapped, TimedMiddleware)
        state = AgentState(task="test")
        result = wrapped.run(state)
        assert result.metadata["ran"] is True

    def test_wrap_with_args(self):
        step = TrackingStep()
        wrapped = wrap(GuardMiddleware, guard=lambda s: False)(step)
        state = AgentState(task="test")
        result = wrapped.run(state)
        assert result.metadata["ran"] is True

    def test_apply_middleware_list(self):
        step = TrackingStep()
        middlewares = [
            wrap(TimedMiddleware),
            wrap(GuardMiddleware, guard=lambda s: False),
        ]
        wrapped = apply_middleware(step, middlewares)
        state = AgentState(task="test")
        result = wrapped.run(state)
        assert result.metadata["ran"] is True
        assert "step_timings" in result.metadata

    def test_apply_middleware_guard_blocks(self):
        step = TrackingStep()
        middlewares = [
            wrap(TimedMiddleware),
            wrap(GuardMiddleware, guard=lambda s: True, reason="blocked"),
        ]
        wrapped = apply_middleware(step, middlewares)
        state = AgentState(task="test")
        result = wrapped.run(state)
        assert "ran" not in result.metadata

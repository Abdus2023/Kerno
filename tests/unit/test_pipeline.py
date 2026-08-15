"""Unit tests for Pipeline composition primitives."""

import pytest
import copy

from kerno.interfaces import AgentState
from kerno.pipeline import (
    Pipeline, IdentityStep, ConditionalStep,
    LoopStep, ParallelStep, RetryStep,
)


# ── Helper steps ──────────────────────────────────────────────────────────────

class CounterStep:
    """Counts how many times run() is called."""
    def __init__(self, key="count"):
        self.key = key
    def run(self, state):
        state.metadata[self.key] = state.metadata.get(self.key, 0) + 1
        return state


class CompleteStep:
    """Marks state as complete."""
    def run(self, state):
        state.complete = True
        return state


class ErrorStep:
    """Sets an error on state."""
    def __init__(self, msg="boom"):
        self.msg = msg
    def run(self, state):
        state.error = self.msg
        return state


class AppendStep:
    """Appends a value to state.history."""
    def __init__(self, value="x"):
        self.value = value
    def run(self, state):
        state.history.append(self.value)
        return state


# ── TestPipeline ──────────────────────────────────────────────────────────────

class TestPipeline:
    """Tests for Pipeline composition."""

    def test_empty_pipeline(self):
        state = AgentState(task="test")
        result = Pipeline([]).run(state)
        assert result.task == "test"

    def test_single_step(self):
        state = AgentState(task="test")
        result = Pipeline([CounterStep()]).run(state)
        assert result.metadata["count"] == 1

    def test_multi_step_pipeline(self):
        state = AgentState(task="test")
        result = Pipeline([
            CounterStep("a"),
            CounterStep("b"),
            CounterStep("c"),
        ]).run(state)
        assert result.metadata["a"] == 1
        assert result.metadata["b"] == 1
        assert result.metadata["c"] == 1
        # CounterStep("a") increments "a" from 0 to 1, CounterStep("b") increments "b" from 1 to 2
        # Wait, CounterStep increments the key each time. Let me trace:
        # CounterStep("a"): metadata["a"] = metadata.get("a", 0) = 0, then metadata["a"] = 0 + 1 = 1
        # Actually the CounterStep just increments self.key
        assert result.metadata.get("count", 0) == 0  # No "count" key used

    def test_pipeline_stops_on_complete(self):
        state = AgentState(task="test")
        result = Pipeline([CompleteStep(), CounterStep()]).run(state)
        assert result.complete is True
        assert "count" not in result.metadata

    def test_pipeline_stops_on_error(self):
        state = AgentState(task="test")
        result = Pipeline([ErrorStep(), CounterStep()]).run(state)
        assert result.error == "boom"
        assert "count" not in result.metadata

    def test_then_method(self):
        p1 = Pipeline([IdentityStep()])
        p2 = p1.then(IdentityStep())
        assert len(p2.steps) == 2

    def test_or_operator(self):
        p1 = Pipeline([IdentityStep()])
        p2 = p1 | IdentityStep()
        assert len(p2.steps) == 2

    def test_repr(self):
        p = Pipeline([IdentityStep()])
        assert "IdentityStep" in repr(p)


class TestLoopStep:
    """Tests for LoopStep."""

    def test_loop_completes_when_done(self):
        class IncrementUntilThree:
            def run(self, state):
                state.metadata["count"] = state.metadata.get("count", 0) + 1
                if state.metadata["count"] >= 3:
                    state.complete = True
                return state

        state = AgentState(task="test")
        result = LoopStep(
            IncrementUntilThree(),
            done=lambda s: s.complete,
            max_iterations=50,
        ).run(state)
        assert result.metadata["count"] == 3
        assert result.complete is True

    def test_loop_max_iterations(self):
        state = AgentState(task="test")
        result = LoopStep(
            CounterStep(),
            done=lambda s: False,  # Never done
            max_iterations=5,
        ).run(state)
        assert result.metadata["count"] == 5

    def test_loop_stops_on_error(self):
        class FailOnSecond:
            def __init__(self):
                self.calls = 0
            def run(self, state):
                self.calls += 1
                if self.calls >= 2:
                    state.error = "fail"
                return state

        state = AgentState(task="test")
        result = LoopStep(
            FailOnSecond(),
            done=lambda s: s.complete,
            max_iterations=10,
        ).run(state)
        assert result.error == "fail"


class TestConditionalStep:
    """Tests for ConditionalStep."""

    def test_if_true(self):
        state = AgentState(task="test")
        result = ConditionalStep(
            condition=lambda s: True,
            if_true=CounterStep("true"),
            if_false=CounterStep("false"),
        ).run(state)
        assert result.metadata["true"] == 1
        assert "false" not in result.metadata

    def test_if_false(self):
        state = AgentState(task="test")
        result = ConditionalStep(
            condition=lambda s: False,
            if_true=CounterStep("true"),
            if_false=CounterStep("false"),
        ).run(state)
        assert result.metadata["false"] == 1
        assert "true" not in result.metadata

    def test_default_false_is_identity(self):
        state = AgentState(task="test")
        result = ConditionalStep(
            condition=lambda s: False,
            if_true=CounterStep("true"),
        ).run(state)
        assert "true" not in result.metadata


class TestRetryStep:
    """Tests for RetryStep."""

    def test_success_on_first_try(self):
        state = AgentState(task="test")
        result = RetryStep(CounterStep(), max_retries=3).run(state)
        assert result.metadata["count"] == 1
        assert result.error is None

    def test_retries_on_error(self):
        class FailTwiceThenSucceed:
            def __init__(self):
                self.attempts = 0
            def run(self, state):
                self.attempts += 1
                if self.attempts < 3:
                    state.error = "fail attempt {}".format(self.attempts)
                else:
                    state.error = None
                return state

        state = AgentState(task="test")
        step = FailTwiceThenSucceed()
        result = RetryStep(step, max_retries=5).run(state)
        assert result.error is None

    def test_exhausts_retries(self):
        class AlwaysFail:
            def run(self, state):
                state.error = "always fails"
                return state

        state = AgentState(task="test")
        result = RetryStep(AlwaysFail(), max_retries=3).run(state)
        assert result.error == "always fails"

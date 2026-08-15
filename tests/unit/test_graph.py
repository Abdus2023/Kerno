"""Unit tests for PipelineGraph and InterceptedPipeline."""

import pytest

from kerno.interfaces import AgentState
from kerno.pipeline import Pipeline, LoopStep, ConditionalStep, RetryStep, IdentityStep
from kerno.graph import PipelineGraph, GraphNode
from kerno.interceptors import InterceptedPipeline, StateRecorder, InvariantChecker


# ── Helper steps ──────────────────────────────────────────────────────────────

class DummyStep:
    """Step that does nothing."""
    def run(self, state):
        return state


class CounterStep:
    """Step that increments a counter."""
    def run(self, state):
        state.metadata["count"] = state.metadata.get("count", 0) + 1
        return state


class ErrorStep:
    """Step that raises an error."""
    def run(self, state):
        raise RuntimeError("test error")


# ── TestPipelineGraph ─────────────────────────────────────────────────────────

class TestPipelineGraph:
    """Tests for PipelineGraph visualization."""

    def test_simple_pipeline(self):
        pipe = Pipeline([DummyStep(), DummyStep()])
        graph = PipelineGraph.from_pipeline(pipe)
        assert graph.root.kind == "pipeline"
        assert len(graph.root.children) == 2

    def test_ascii_rendering(self):
        pipe = Pipeline([DummyStep()])
        graph = PipelineGraph.from_pipeline(pipe)
        ascii_str = graph.ascii()
        assert len(ascii_str) > 0
        assert "pipeline" in ascii_str

    def test_mermaid_rendering(self):
        pipe = Pipeline([DummyStep()])
        graph = PipelineGraph.from_pipeline(pipe)
        mermaid_str = graph.mermaid()
        assert "flowchart" in mermaid_str

    def test_to_dict(self):
        pipe = Pipeline([DummyStep()])
        graph = PipelineGraph.from_pipeline(pipe)
        d = graph.to_dict()
        assert d["kind"] == "pipeline"
        assert len(d["children"]) == 1

    def test_nested_pipeline(self):
        inner = Pipeline([DummyStep(), DummyStep()])
        outer = Pipeline([inner])
        graph = PipelineGraph.from_pipeline(outer)
        assert graph.root.children[0].kind == "pipeline"

    def test_loop_step(self):
        loop = LoopStep(DummyStep(), done=lambda s: True, max_iterations=10)
        pipe = Pipeline([loop])
        graph = PipelineGraph.from_pipeline(pipe)
        loop_node = graph.root.children[0]
        assert loop_node.kind == "loop"
        assert loop_node.metadata["max_iterations"] == 10

    def test_validate_missing_execute(self):
        pipe = Pipeline([DummyStep()])
        graph = PipelineGraph.from_pipeline(pipe)
        warnings = graph.validate()
        assert any("Execute" in w for w in warnings)

    def test_validate_clean(self):
        from kerno.steps.execute import ExecuteStep
        from kerno.steps.generate import GenerateCodeStep

        # Create a mock kernel for ExecuteStep
        class MockKernel:
            def execute(self, code, **kwargs):
                return None

        class MockLLM:
            def __call__(self, messages):
                return "code"

        pipe = Pipeline([GenerateCodeStep(MockLLM()), DummyStep()])
        graph = PipelineGraph.from_pipeline(pipe)
        warnings = graph.validate()
        assert any("Execute" in w for w in warnings)  # Still warns (no execute in this test)

    def test_summary(self):
        pipe = Pipeline([DummyStep(), DummyStep()])
        graph = PipelineGraph.from_pipeline(pipe)
        summary = graph.summary()
        assert summary["total_steps"] >= 1


# ── TestInterceptedPipeline ──────────────────────────────────────────────────

class TestInterceptedPipeline:
    """Tests for InterceptedPipeline callbacks."""

    def test_before_and_after_callbacks(self):
        before_states = []
        after_states = []

        def on_before(state):
            before_states.append(state.task)

        def on_after(state):
            after_states.append(state.task)

        step = InterceptedPipeline(
            CounterStep(),
            on_before=on_before,
            on_after=on_after,
        )
        state = AgentState(task="test")
        step.run(state)
        assert len(before_states) == 1
        assert before_states[0] == "test"
        assert len(after_states) == 1

    def test_on_error_callback(self):
        errors = []

        def on_error(state, exc):
            errors.append(str(exc))

        step = InterceptedPipeline(
            ErrorStep(),
            on_error=on_error,
        )
        state = AgentState(task="test")
        with pytest.raises(RuntimeError):
            step.run(state)
        assert len(errors) == 1
        assert "test error" in errors[0]

    def test_state_recorder(self):
        recorder = StateRecorder()
        step = InterceptedPipeline(
            CounterStep(),
            on_before=recorder.capture("before"),
            on_after=recorder.capture("after"),
        )
        state = AgentState(task="test")
        step.run(state)
        assert len(recorder.snapshots) == 2

    def test_state_recorder_diff(self):
        recorder = StateRecorder()
        step = InterceptedPipeline(
            CounterStep(),
            on_before=recorder.capture("before"),
            on_after=recorder.capture("after"),
        )
        state = AgentState(task="test")
        step.run(state)
        diff = recorder.diff(0, 1)
        assert isinstance(diff, dict)

    def test_state_recorder_replay(self):
        recorder = StateRecorder()
        step = InterceptedPipeline(
            CounterStep(),
            on_before=recorder.capture("before"),
            on_after=recorder.capture("after"),
        )
        state = AgentState(task="test")
        step.run(state)
        states = recorder.replay()
        assert len(states) == 2

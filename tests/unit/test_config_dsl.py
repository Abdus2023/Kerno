"""Unit tests for PipelineCompiler and config DSL."""

import pytest

from kerno.config_dsl import PipelineCompiler, TEMPLATES


# ── Helpers ───────────────────────────────────────────────────────────────────

class MockKernel:
    """Mock kernel for testing."""
    def execute(self, code, **kwargs):
        from kerno.types import CellOutput
        return CellOutput(text="mock output")

    def execute_silent(self, code, **kwargs):
        return ""

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


class MockLLM:
    """Mock LLM for testing."""
    def __call__(self, messages):
        return "print('hello')"


# ── TestPipelineCompiler ─────────────────────────────────────────────────────

class TestPipelineCompiler:
    """Tests for declarative pipeline compilation."""

    def test_reactive_template_compiles(self):
        compiler = PipelineCompiler(llm=MockLLM(), kernel=MockKernel())
        pipeline = compiler.from_yaml(TEMPLATES["reactive"])
        assert pipeline is not None
        assert len(pipeline.steps) > 0

    def test_all_templates_compile(self):
        compiler = PipelineCompiler(llm=MockLLM(), kernel=MockKernel())
        for name, yaml_str in TEMPLATES.items():
            pipeline = compiler.from_yaml(yaml_str)
            assert pipeline is not None
            assert len(pipeline.steps) > 0

    def test_unknown_step_warns(self):
        compiler = PipelineCompiler(llm=MockLLM(), kernel=MockKernel())
        with pytest.warns(UserWarning, match="Unknown step type"):
            compiler.compile({"steps": [{"unknown_step": {}}]})

    def test_dict_compile(self):
        compiler = PipelineCompiler(llm=MockLLM(), kernel=MockKernel())
        spec = {
            "steps": [
                {"generate": {"llm": "default"}},
                {"execute": {}},
                {"check": {}},
            ]
        }
        pipeline = compiler.compile(spec)
        assert len(pipeline.steps) == 3

    def test_memory_injection(self):
        from kerno.memory.simple import SimpleMemoryStore
        compiler = PipelineCompiler(
            llm=MockLLM(),
            kernel=MockKernel(),
            memory=SimpleMemoryStore(),
        )
        spec = {
            "steps": [
                {"inject_memory": {"memory": "simple"}},
                {"generate": {"llm": "default"}},
                {"check": {}},
            ]
        }
        pipeline = compiler.compile(spec)
        assert len(pipeline.steps) == 3

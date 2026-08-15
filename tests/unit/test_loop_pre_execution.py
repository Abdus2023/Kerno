"""Tests for BaseLoop pre-execution plugin hooks."""

from kerno.loop.reactive import ReactiveLoop
from kerno.plugins.pack.safety import BlockedExecution, HardGuardrailPlugin
from kerno.plugins.registry import BasePlugin, PluginRegistry


class DummyKernel:
    def __init__(self):
        self.executed = []
        self.is_alive = True
        self.namespace = "{}"

    def execute(self, code, timeout=120):
        self.executed.append(code)
        class Output:
            has_error = False
            error = None
            stdout = "ok"
            stderr = ""
            def as_text(self, n=300): return self.stdout
        return Output()


def dummy_llm(messages):
    # First call generates the dangerous cell; later completion is never reached
    # because the hard guard blocks execution.
    return "import os\nos.system('echo blocked')"


def test_loop_converts_blocked_execution_to_cell_error():
    registry = PluginRegistry().register(HardGuardrailPlugin())
    loop = ReactiveLoop(kernel=DummyKernel(), llm=dummy_llm, plugins=registry, max_cells=2)
    result = loop.run("run a dangerous shell command")
    assert result.error_count >= 1
    assert result.cells[0].output.has_error
    assert result.cells[0].output.error.ename == "BlockedExecution"


def test_loop_allows_pre_execution_rewrite():
    class Rewriter(BasePlugin):
        name = "rewriter"
        def on_before_cell(self, code):
            return "print('rewritten')"

    kernel = DummyKernel()
    def llm(messages): return "print('original')"
    loop = ReactiveLoop(kernel=kernel, llm=llm, plugins=PluginRegistry().register(Rewriter()), max_cells=1)
    loop.run("rewrite test")
    assert kernel.executed == ["print('rewritten')"]

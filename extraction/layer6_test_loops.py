# tests/behavioral/test_loops.py
"""
Behavioral tests for execution loops.
These use a real kernel but a mock LLM to control exactly what code runs.
"""

import pytest
from unittest.mock import MagicMock

from kerno.kernel.runtime import KernelRuntime
from kerno.loop.reactive   import ReactiveLoop
from kerno.loop.reflect    import ReflectReviseLoop
from kerno.types           import Message, SessionStatus


def make_mock_llm(responses: list[str]):
    """
    Returns a mock LLM that returns responses in sequence.
    On exhaustion, returns a TASK_COMPLETE cell.
    """
    responses = list(responses)
    call_count = [0]

    def llm(messages):
        i = call_count[0]
        call_count[0] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: mock task done"

    return llm


@pytest.fixture
def kernel():
    with KernelRuntime() as k:
        yield k


@pytest.mark.integration
class TestReactiveLoop:

    def test_completes_on_signal(self, kernel):
        llm  = make_mock_llm(["x = 1", "y = 2", "# TASK_COMPLETE: done"])
        loop = ReactiveLoop(kernel=kernel, llm=llm, max_cells=10)

        result = loop.run("Test task")

        assert result.status == SessionStatus.COMPLETE
        assert result.cells_executed == 3

    def test_stops_at_max_cells(self, kernel):
        # LLM never signals completion
        llm  = make_mock_llm(["x = 1"] * 100)
        loop = ReactiveLoop(kernel=kernel, llm=llm, max_cells=5)

        result = loop.run("Infinite task")

        assert result.status == SessionStatus.MAX_CELLS
        assert result.cells_executed == 5

    def test_error_recovery_continues(self, kernel):
        llm = make_mock_llm([
            "raise ValueError('intentional')",   # Cell 1: error
            "x = 'recovered'",                   # Cell 2: recovery
            "# TASK_COMPLETE: done",              # Cell 3: complete
        ])
        loop   = ReactiveLoop(kernel=kernel, llm=llm, max_cells=10)
        result = loop.run("Error recovery test")

        assert result.status      == SessionStatus.COMPLETE
        assert result.error_count == 1
        assert result.recovery_count == 1

    def test_state_accumulates_across_cells(self, kernel):
        llm = make_mock_llm([
            "a = 10",
            "b = a * 2",       # Uses variable from cell 1
            "print(b)",        # Should print 20
            "# TASK_COMPLETE: done",
        ])
        loop   = ReactiveLoop(kernel=kernel, llm=llm, max_cells=10)
        result = loop.run("State accumulation test")

        # Find the cell that printed b
        print_cell = result.cells[2]
        assert "20" in print_cell.output.stdout

    def test_session_result_has_metadata(self, kernel):
        llm    = make_mock_llm(["# TASK_COMPLETE: quick"])
        loop   = ReactiveLoop(kernel=kernel, llm=llm, max_cells=5)
        result = loop.run("Metadata test")

        assert result.session_id != ""
        assert result.task       == "Metadata test"
        assert result.duration   > 0
        assert result.ended_at   is not None


@pytest.mark.integration
class TestReflectReviseLoop:

    def test_generates_reflections(self, kernel):
        """
        ReflectReviseLoop makes TWO LLM calls per cell:
        one for the code, one for the reflection.
        Verify both happen.
        """
        # Override to complete after 1 code cell
        call_count = [0]
        def controlled_llm(messages):
            call_count[0] += 1
            if call_count[0] == 1:
                return "x = 42"                     # Code
            elif call_count[0] == 2:
                return "Set x=42. All good."         # Reflection
            else:
                return "# TASK_COMPLETE: done"       # Next code cell

        loop   = ReflectReviseLoop(kernel=kernel, llm=controlled_llm, max_cells=10)
        result = loop.run("Reflection test")

        assert result.status == SessionStatus.COMPLETE
        assert len(loop._reflections) > 0

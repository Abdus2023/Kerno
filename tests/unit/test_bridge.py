"""
Unit tests for the SessionResult <-> AgentState bridge (audit #76):
one vocabulary across both execution models.
"""

from kerno.bridge import result_to_state, state_to_result
from kerno.interfaces import AgentState
from kerno.types import Cell, CellOutput, SessionResult, SessionStatus


def make_result(status=SessionStatus.COMPLETE):
    return SessionResult(
        session_id="sess-1",
        task="analyze",
        status=status,
        cells=[
            Cell(code="x = 1", output=CellOutput(stdout="1"), cell_num=1),
            Cell(code="print(x)", output=CellOutput(stdout="1"), cell_num=2),
        ],
        final_namespace='{"x": "int=1"}',
        summary="computed x",
        execution_ids=["exec_00000001", "exec_00000002"],
        blocked_rules=["subprocess"],
    )


class TestResultToState:

    def test_carries_history_and_namespace(self):
        state = result_to_state(make_result())
        assert state.task == "analyze"
        assert len(state.history) == 2
        assert state.history[0].code == "x = 1"
        assert state.namespace == '{"x": "int=1"}'
        assert state.summary == "computed x"
        assert state.session_id == "sess-1"

    def test_complete_maps_to_complete(self):
        state = result_to_state(make_result())
        assert state.complete is True
        assert state.error is None

    def test_interrupted_maps_to_incomplete(self):
        state = result_to_state(make_result(status=SessionStatus.INTERRUPTED))
        assert state.complete is False
        assert state.error == "INTERRUPTED"

    def test_metadata_carries_ledger(self):
        state = result_to_state(make_result())
        assert state.metadata["execution_ids"] == [
            "exec_00000001", "exec_00000002",
        ]
        assert state.metadata["blocked_rules"] == ["subprocess"]
        assert state.execution_counter == 2

    def test_task_override(self):
        state = result_to_state(make_result(), task="new task")
        assert state.task == "new task"


class TestStateToResult:

    def test_complete_state_round_trip(self):
        state = result_to_state(make_result())
        result = state_to_result(state)
        assert result.status == SessionStatus.COMPLETE
        assert result.session_id == "sess-1"
        assert result.task == "analyze"
        assert result.cells_executed == 2
        assert result.final_namespace == '{"x": "int=1"}'
        assert result.summary == "computed x"

    def test_errored_state_maps_to_error_unhandled(self):
        state = AgentState(task="t", error="KERNEL_DIED", complete=False)
        result = state_to_result(state)
        assert result.status == SessionStatus.ERROR_UNHANDLED

    def test_open_state_maps_to_max_cells(self):
        state = AgentState(task="t")
        result = state_to_result(state)
        assert result.status == SessionStatus.MAX_CELLS

    def test_status_override(self):
        state = AgentState(task="t", complete=True)
        result = state_to_result(state, status_override=SessionStatus.INTERRUPTED)
        assert result.status == SessionStatus.INTERRUPTED

    def test_full_round_trip(self):
        original = make_result()
        result = state_to_result(result_to_state(original))
        assert result.session_id == original.session_id
        assert [c.code for c in result.cells] == [c.code for c in original.cells]
        assert result.execution_ids == original.execution_ids
        assert result.blocked_rules == original.blocked_rules
        assert result.status == original.status

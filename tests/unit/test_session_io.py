"""
Unit tests for SessionResult serialization — persistence, replay, audit
across processes.
"""

from kerno.session import (
    load_session, save_session, session_from_dict, session_to_dict,
)
from kerno.types import Cell, CellError, CellOutput, SessionResult, SessionStatus


def make_rich_result():
    cells = [
        Cell(
            code="x = 1\nprint(x)",
            output=CellOutput(
                stdout="1",
                stderr="",
                result="1",
                displays=[{"html": "<b>1</b>"}],
                images=["iVBORw0KGgo="],           # base64 PNG
                duration=0.042,
                execution_id="exec_00000001",
            ),
            cell_num=1, author="agent",
            reasoning="compute x",
        ),
        Cell(
            code="raise ValueError('boom')",
            output=CellOutput(
                error=CellError(
                    ename="ValueError", evalue="boom",
                    traceback="Traceback...\nValueError: boom",
                ),
                execution_id="exec_00000002",
            ),
            cell_num=2, author="agent",
        ),
    ]
    return SessionResult(
        session_id="sess-serial", task="analyze sales",
        status=SessionStatus.INTERRUPTED, cells=cells,
        final_namespace='{"x": "int=1"}', summary="partial",
        started_at=100.0, ended_at=200.0,
        execution_ids=["exec_00000001", "exec_00000002"],
        blocked_rules=["subprocess"],
    )


class TestSessionSerialization:

    def test_round_trip_preserves_everything(self):
        original = make_rich_result()
        restored = session_from_dict(session_to_dict(original))

        assert restored.session_id == "sess-serial"
        assert restored.task == "analyze sales"
        assert restored.status == SessionStatus.INTERRUPTED
        assert restored.final_namespace == '{"x": "int=1"}'
        assert restored.summary == "partial"
        assert restored.started_at == 100.0
        assert restored.ended_at == 200.0
        assert restored.execution_ids == ["exec_00000001", "exec_00000002"]
        assert restored.blocked_rules == ["subprocess"]

        c1 = restored.cells[0]
        assert c1.code == "x = 1\nprint(x)"
        assert c1.output.stdout == "1"
        assert c1.output.result == "1"
        assert c1.output.displays == [{"html": "<b>1</b>"}]
        assert c1.output.images == ["iVBORw0KGgo="]
        assert c1.output.duration == 0.042
        assert c1.output.execution_id == "exec_00000001"
        assert c1.reasoning == "compute x"

        c2 = restored.cells[1]
        assert c2.output.has_error
        assert c2.output.error.ename == "ValueError"
        assert c2.output.error.evalue == "boom"
        assert "ValueError: boom" in c2.output.error.traceback
        assert c2.output.execution_id == "exec_00000002"

    def test_empty_result_round_trip(self):
        r = SessionResult(
            session_id="s", task="t", status=SessionStatus.MAX_CELLS, cells=[],
        )
        restored = session_from_dict(session_to_dict(r))
        assert restored.status == SessionStatus.MAX_CELLS
        assert restored.cells == []

    def test_save_and_load_json(self, tmp_path):
        original = make_rich_result()
        path = save_session(original, str(tmp_path / "sess.json"))
        assert path.exists()
        restored = load_session(path)
        assert restored.session_id == "sess-serial"
        assert restored.cells_executed == 2

    def test_serialized_is_json_clean(self):
        import json
        data = session_to_dict(make_rich_result())
        json.dumps(data)  # must not raise

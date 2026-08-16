"""
Unit tests for execution modes: SIMULATE/DRY_RUN/LIVE/REPLAY (audit #91),
DryRunExecutor, ReplayExecutor, and replay_session (audit #58: replay
without the LLM).
"""

import pytest

from kerno.execution.modes import (
    DryRunExecutor, ExecutionMode, ReplayExecutor, replay_session,
)
from kerno.security.allowlist import AllowList
from kerno.types import Cell, CellOutput, SessionResult, SessionStatus


class TestExecutionModeEnum:

    def test_four_modes(self):
        assert {m.name for m in ExecutionMode} == {
            "SIMULATE", "DRY_RUN", "LIVE", "REPLAY",
        }


class TestDryRunExecutor:

    def test_does_not_execute(self):
        dry = DryRunExecutor()
        out = dry.execute("open('/etc/passwd', 'w').write('x')")
        assert not out.has_error          # dry run: nothing happened
        assert "would execute" in out.stdout
        assert dry.checked == ("open('/etc/passwd', 'w').write('x')",)

    def test_policy_still_enforced(self):
        dry = DryRunExecutor(allowlist=AllowList.data_analysis())
        out = dry.execute("import subprocess\nsubprocess.run(['curl'])")
        assert out.has_error
        assert out.error.ename == "AllowListViolation"

    def test_clean_code_passes_policy(self):
        dry = DryRunExecutor(allowlist=AllowList.data_analysis())
        out = dry.execute("import pandas as pd\ndf = pd.DataFrame()")
        assert not out.has_error

    def test_executor_protocol(self):
        dry = DryRunExecutor()
        assert dry.namespace == "{}"
        assert dry.is_alive is True
        assert dry.execute_silent("x = 1") == ""


class TestReplayExecutor:

    def _recording(self):
        return [
            Cell(code="x = 1", output=CellOutput(stdout="1"), cell_num=1),
            Cell(code="y = 2", output=CellOutput(stdout="2"), cell_num=2),
        ]

    def test_serves_outputs_in_order(self):
        replay = ReplayExecutor(self._recording())
        assert replay.execute("x = 1").stdout == "1"
        assert replay.execute("y = 2").stdout == "2"
        assert replay.remaining == 0

    def test_exhaustion_returns_error_cell(self):
        replay = ReplayExecutor(self._recording())
        replay.execute("x = 1")
        replay.execute("y = 2")
        out = replay.execute("z = 3")
        assert out.has_error
        assert out.error.ename == "ReplayExhausted"

    def test_replay_log_tracks_served_index(self):
        replay = ReplayExecutor(self._recording())
        replay.execute("x = 1")
        replay.execute("y = 2")
        assert replay.replay_log == (("x = 1", 0), ("y = 2", 1))


class TestReplaySession:
    """Audit #58: re-execute recorded actions without the LLM."""

    class FakeKernel:
        def __init__(self):
            self.calls = []

        def execute(self, code, timeout=120.0, silent=False):
            self.calls.append(code)
            if "error" in code:
                from kerno.types import CellError
                return CellOutput(error=CellError("ValueError", "boom"))
            return CellOutput(stdout=f"ran:{code[:20]}")

        def execute_silent(self, code, timeout=15.0):
            return "ok"

        @property
        def namespace(self):
            return "{}"

        @property
        def is_alive(self):
            return True

    def _recorded_session(self):
        cells = [
            Cell(code="x = 1", output=CellOutput(stdout="1"), cell_num=1),
            Cell(code="print(x)", output=CellOutput(stdout="1"), cell_num=2),
        ]
        return SessionResult(
            session_id="sess-abc", task="original", status=SessionStatus.COMPLETE,
            cells=cells,
        )

    def test_replays_all_cells_without_llm(self):
        kernel = self.FakeKernel()
        result = self._recorded_session()

        replayed = replay_session(result, kernel)

        assert kernel.calls == ["x = 1", "print(x)"]
        assert len(replayed.cells) == 2
        assert replayed.status == SessionStatus.COMPLETE
        assert replayed.cells[0].output.stdout == "ran:x = 1"

    def test_replay_marks_errors(self):
        kernel = self.FakeKernel()
        cells = [
            Cell(code="x = 1", output=CellOutput(), cell_num=1),
            Cell(code="raise error", output=CellOutput(), cell_num=2),
        ]
        result = SessionResult(
            session_id="s", task="t", status=SessionStatus.COMPLETE, cells=cells,
        )
        replayed = replay_session(result, kernel)
        assert replayed.status == SessionStatus.ERROR_UNHANDLED
        assert replayed.cells[1].output.error.ename == "ValueError"

    def test_replay_applies_allowlist(self):
        kernel = self.FakeKernel()
        cells = [
            Cell(code="import subprocess", output=CellOutput(), cell_num=1),
        ]
        result = SessionResult(
            session_id="s", task="t", status=SessionStatus.COMPLETE, cells=cells,
        )
        replayed = replay_session(result, kernel, allowlist=AllowList.data_analysis())
        assert replayed.cells[0].output.has_error
        assert replayed.cells[0].output.error.ename == "AllowListViolation"
        # The violating code never reached the kernel
        assert kernel.calls == []

    def test_replay_accepts_an_engine_directly(self):
        from kerno.execution.engine import ExecutionEngine
        kernel = self.FakeKernel()
        engine = ExecutionEngine(kernel)
        result = self._recorded_session()

        replayed = replay_session(result, engine)

        assert len(replayed.cells) == 2
        assert not replayed.cells[0].output.has_error

    def test_replay_never_calls_llm_by_construction(self):
        # There is no llm parameter — replay is LLM-free by construction.
        import inspect
        sig = inspect.signature(replay_session)
        assert "llm" not in sig.parameters

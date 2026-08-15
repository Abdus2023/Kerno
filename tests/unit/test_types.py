# tests/unit/test_types.py
"""Unit tests for core types — fast, no kernel required."""

import pytest
from kerno.types import CellError, CellOutput, Cell, SessionResult, SessionStatus


class TestCellOutput:

    def test_as_text_empty(self):
        out = CellOutput()
        assert out.as_text() == "[no output]"
        assert out.is_empty

    def test_as_text_stdout(self):
        out = CellOutput(stdout="hello world\n")
        assert "hello world" in out.as_text()
        assert not out.is_empty

    def test_as_text_truncates_long_stdout(self):
        long_text = "x" * 10_000
        out       = CellOutput(stdout=long_text)
        result    = out.as_text(max_chars=500)
        assert len(result) < 1000         # Significantly shorter
        assert "omitted" in result        # Truncation marker present

    def test_as_text_error_first(self):
        out = CellOutput(
            stdout="some output",
            error=CellError(ename="KeyError", evalue="'missing'"),
        )
        text = out.as_text()
        assert text.index("[ERROR]") < text.index("some output")

    def test_as_text_strips_html_from_displays(self):
        out = CellOutput(displays=[{"html": "<table><tr><td>42</td></tr></table>"}])
        text = out.as_text()
        assert "42" in text
        assert "<table>" not in text

    def test_has_error(self):
        out = CellOutput(error=CellError("ValueError", "bad value"))
        assert out.has_error
        assert not CellOutput().has_error

    def test_images_in_text(self):
        out = CellOutput(images=["base64data==", "base64data2=="])
        assert "2 plot(s)" in out.as_text()


class TestSessionResult:

    def _make_cells(self, specs: list[bool]) -> list[Cell]:
        """specs: list of booleans, True = cell had error"""
        cells = []
        for i, had_error in enumerate(specs):
            error = CellError("E", "e") if had_error else None
            cell  = Cell(
                code     = f"cell_{i}",
                output   = CellOutput(error=error),
                cell_num = i + 1,
            )
            cells.append(cell)
        return cells

    def test_error_count(self):
        cells  = self._make_cells([False, True, False, True, False])
        result = SessionResult(
            session_id = "s1", task = "test",
            status     = SessionStatus.COMPLETE,
            cells      = cells,
        )
        assert result.error_count == 2

    def test_recovery_count(self):
        # error then success = 1 recovery
        cells  = self._make_cells([False, True, False, False])
        result = SessionResult(
            session_id = "s1", task = "test",
            status     = SessionStatus.COMPLETE,
            cells      = cells,
        )
        assert result.recovery_count == 1

    def test_cells_executed(self):
        cells  = self._make_cells([False, False, False])
        result = SessionResult(
            session_id = "s1", task = "test",
            status     = SessionStatus.COMPLETE,
            cells      = cells,
        )
        assert result.cells_executed == 3

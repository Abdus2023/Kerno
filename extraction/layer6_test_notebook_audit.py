# tests/unit/test_notebook_audit.py
"""Unit tests for notebook audit trail — no kernel required."""

import json
import tempfile
from pathlib import Path

import nbformat
import pytest

from kerno.audit.notebook import NotebookAuditTrail
from kerno.types import Cell, CellError, CellOutput, SessionResult, SessionStatus


def _make_cell(
    num:       int,
    code:      str        = "x = 1",
    stdout:    str        = "",
    had_error: bool       = False,
    reasoning: str | None = None,
) -> Cell:
    error = CellError("ValueError", "bad") if had_error else None
    return Cell(
        code      = code,
        output    = CellOutput(stdout=stdout, error=error),
        cell_num  = num,
        reasoning = reasoning,
    )


class TestNotebookAuditTrail:

    def test_creates_valid_notebook(self):
        trail = NotebookAuditTrail(task="test task", session_id="s-001")
        trail.add_task_header("test task")
        trail.add_cell(_make_cell(1, "x = 1", ""))

        nb = trail._nb
        nbformat.validate(nb)   # Raises if invalid

    def test_task_header_in_first_cell(self):
        trail = NotebookAuditTrail(task="Analyze Q3 sales")
        trail.add_task_header("Analyze Q3 sales")

        first_cell = trail._nb.cells[0]
        assert first_cell.cell_type == "markdown"
        assert "Analyze Q3 sales" in first_cell.source

    def test_reasoning_cell_before_code(self):
        trail = NotebookAuditTrail(task="test")
        trail.add_cell(_make_cell(1, "df = load('data.csv')", reasoning="I'll load the data first"))

        cell_types = [c.cell_type for c in trail._nb.cells]
        # markdown (reasoning) then code
        assert cell_types == ["markdown", "code"]
        assert "I'll load the data first" in trail._nb.cells[0].source

    def test_error_annotation_cell(self):
        trail = NotebookAuditTrail(task="test")
        trail.add_cell(_make_cell(1, "bad_code()", had_error=True))

        # Should have: error annotation (markdown) + code cell
        markdown_cells = [c for c in trail._nb.cells if c.cell_type == "markdown"]
        assert any("⚠️" in c.source or "Error" in c.source for c in markdown_cells)

    def test_stdout_captured_in_output(self):
        trail = NotebookAuditTrail(task="test")
        trail.add_cell(_make_cell(1, "print('hello')", stdout="hello\n"))

        code_cells = [c for c in trail._nb.cells if c.cell_type == "code"]
        assert len(code_cells) == 1

        stream_outputs = [o for o in code_cells[0].outputs if o.output_type == "stream"]
        assert any("hello" in o.text for o in stream_outputs)

    def test_saves_to_disk(self, tmp_path):
        trail = NotebookAuditTrail(task="save test")
        trail.add_task_header("save test")
        trail.add_cell(_make_cell(1))

        path = trail.save(str(tmp_path))

        assert path.exists()
        assert path.suffix == ".ipynb"

        # Verify it's a valid notebook
        with open(path) as f:
            nb = nbformat.read(f, as_version=4)
        nbformat.validate(nb)

    def test_from_result_builds_complete_notebook(self, tmp_path):
        cells = [
            _make_cell(1, "df = load('x.csv')", "Shape: (100, 5)\n"),
            _make_cell(2, "df.describe()", had_error=False),
            _make_cell(3, "bad()", had_error=True),
            _make_cell(4, "df.head()", "   col1\n0     1\n"),
        ]
        result = SessionResult(
            session_id = "s-test",
            task       = "Test task",
            status     = SessionStatus.COMPLETE,
            cells      = cells,
        )

        trail = NotebookAuditTrail.from_result(result)
        path  = trail.save(str(tmp_path))

        with open(path) as f:
            nb = nbformat.read(f, as_version=4)

        nbformat.validate(nb)

        # Summary cell should exist
        all_text = " ".join(c.source for c in nb.cells if c.cell_type == "markdown")
        assert "COMPLETE" in all_text

# kerno/audit/notebook.py
"""
NotebookAuditTrail: writes the agent session as a Jupyter notebook.

The notebook is not a log file. It is the primary artifact.
  - Every cell is reproducible
  - Agent reasoning is captured in Markdown cells
  - Errors and recoveries are explicitly marked
  - The notebook can be opened in JupyterLab and re-run by a human

The audit trail is the memory that persists beyond any single session.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import nbformat

from kerno.types import Cell, SessionResult, SessionStatus


class NotebookAuditTrail:
    """
    Incrementally builds a notebook from agent execution.

    Usage — incremental (inside a loop):
        trail = NotebookAuditTrail(task="Analyze sales data")
        trail.add_task_header("Analyze sales data")
        trail.add_cell(cell)              # After each execution
        trail.save("sessions/")

    Usage — from completed result:
        trail = NotebookAuditTrail.from_result(result)
        trail.save("sessions/")
    """

    def __init__(self, task: str, session_id: str = ""):
        self._nb         = nbformat.v4.new_notebook()
        self._task       = task
        self._session_id = session_id
        self._started_at = datetime.now()

        # Notebook metadata
        self._nb.metadata.update({
            "kernelspec": {
                "display_name": "Python 3",
                "language":     "python",
                "name":         "python3",
            },
            "kerno": {
                "session_id": session_id,
                "task":       task,
                "started_at": self._started_at.isoformat(),
                "framework":  "kerno",
            }
        })

    # ── Building ───────────────────────────────────────────────────────────────

    def add_task_header(self, task: str) -> None:
        """Add a title cell at the top of the notebook."""
        ts   = self._started_at.strftime("%Y-%m-%d %H:%M:%S")
        text = (
            f"# Agent Session\n\n"
            f"**Task:** {task}\n\n"
            f"**Session ID:** `{self._session_id}`  \n"
            f"**Started:** {ts}\n\n"
            f"---"
        )
        self._nb.cells.append(nbformat.v4.new_markdown_cell(text))

    def add_cell(self, cell: Cell) -> None:
        """
        Add one executed cell and its output to the notebook.
        Optionally prepends a reasoning Markdown cell.
        """
        # Reasoning cell (if present)
        if cell.reasoning:
            md = nbformat.v4.new_markdown_cell(
                f"### 💭 Reasoning (Cell {cell.cell_num})\n{cell.reasoning}"
            )
            md.metadata["kerno_cell_type"] = "reasoning"
            self._nb.cells.append(md)

        # Error annotation cell
        if cell.output.has_error:
            err_text = (
                f"### ⚠️ Error in Cell {cell.cell_num}\n"
                f"`{cell.output.error.ename}: {cell.output.error.evalue}`"
            )
            self._nb.cells.append(nbformat.v4.new_markdown_cell(err_text))

        # Code cell with outputs
        code_cell = nbformat.v4.new_code_cell(cell.code)
        code_cell.outputs = self._convert_outputs(cell)
        code_cell.metadata.update({
            "kerno_cell_num":  cell.cell_num,
            "kerno_author":    cell.author,
            "kerno_duration":  cell.output.duration,
            "kerno_had_error": cell.output.has_error,
        })
        self._nb.cells.append(code_cell)

    def add_summary(self, result: SessionResult) -> None:
        """Add a final summary cell when the session completes."""
        status_emoji = {
            SessionStatus.COMPLETE:        "✅",
            SessionStatus.MAX_CELLS:       "⏱️",
            SessionStatus.INTERRUPTED:     "⛔",
            SessionStatus.KERNEL_DIED:     "💀",
            SessionStatus.ERROR_UNHANDLED: "❌",
        }.get(result.status, "❓")

        duration = f"{result.duration:.1f}s" if result.duration else "unknown"

        text = (
            f"---\n\n"
            f"## {status_emoji} Session Complete\n\n"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Status | `{result.status.name}` |\n"
            f"| Cells executed | {result.cells_executed} |\n"
            f"| Errors | {result.error_count} |\n"
            f"| Self-corrections | {result.recovery_count} |\n"
            f"| Duration | {duration} |\n\n"
        )

        if result.summary:
            text += f"### Summary\n{result.summary}\n"

        self._nb.cells.append(nbformat.v4.new_markdown_cell(text))

    # ── Saving ─────────────────────────────────────────────────────────────────

    def save(self, directory: str = "sessions") -> Path:
        """
        Write the notebook to disk.

        Args:
            directory: Directory to save into (created if not exists)

        Returns:
            Path to the saved notebook
        """
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)

        ts       = self._started_at.strftime("%Y%m%d_%H%M%S")
        safe_task = (
            self._task[:40]
            .replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
        filename  = f"{ts}_{safe_task}.ipynb"
        path      = output_dir / filename

        with open(path, "w") as f:
            nbformat.write(self._nb, f)

        return path

    # ── Class Methods ──────────────────────────────────────────────────────────

    @classmethod
    def from_result(cls, result: SessionResult) -> "NotebookAuditTrail":
        """
        Build a complete notebook from a finished SessionResult.
        """
        trail = cls(task=result.task, session_id=result.session_id)
        trail.add_task_header(result.task)

        for cell in result.cells:
            trail.add_cell(cell)

        trail.add_summary(result)
        return trail

    # ── Internals ─────────────────────────────────────────────────────────────

    def _convert_outputs(self, cell: Cell) -> list:
        """
        Convert CellOutput into nbformat output objects.
        This is what makes the notebook re-renderable in JupyterLab.
        """
        outputs = []

        # Stream output (stdout/stderr)
        if cell.output.stdout:
            outputs.append(nbformat.v4.new_output(
                output_type = "stream",
                name        = "stdout",
                text        = cell.output.stdout,
            ))

        if cell.output.stderr:
            outputs.append(nbformat.v4.new_output(
                output_type = "stream",
                name        = "stderr",
                text        = cell.output.stderr,
            ))

        # Rich display outputs
        for display in cell.output.displays:
            if "html" in display:
                outputs.append(nbformat.v4.new_output(
                    output_type = "display_data",
                    data        = {"text/html": display["html"]},
                    metadata    = {},
                ))
            if "json" in display:
                outputs.append(nbformat.v4.new_output(
                    output_type = "display_data",
                    data        = {
                        "application/json": display["json"],
                        "text/plain":       json.dumps(display["json"])[:200],
                    },
                    metadata    = {},
                ))

        # Images (base64 PNG)
        for img_b64 in cell.output.images:
            outputs.append(nbformat.v4.new_output(
                output_type = "display_data",
                data        = {
                    "image/png":  img_b64,
                    "text/plain": "<Figure>",
                },
                metadata    = {},
            ))

        # Execute result
        if cell.output.result:
            outputs.append(nbformat.v4.new_output(
                output_type     = "execute_result",
                execution_count = cell.cell_num,
                data            = {"text/plain": cell.output.result},
                metadata        = {},
            ))

        # Error
        if cell.output.has_error:
            tb = cell.output.error.traceback or ""
            outputs.append(nbformat.v4.new_output(
                output_type = "error",
                ename       = cell.output.error.ename,
                evalue      = cell.output.error.evalue,
                traceback   = tb.split("\n") if tb else [],
            ))

        return outputs

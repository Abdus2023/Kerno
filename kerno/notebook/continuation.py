"""
NotebookContinuation: load a prior session notebook and continue from it.

Use cases:
  - A session was interrupted — resume from where it stopped
  - A human modified a notebook — let the agent continue from the human's changes
  - Multi-day analyses — session 2 starts from session 1's state

Design:
  - Re-execute the notebook cells to restore kernel state
  - Feed the execution history to the LLM as context
  - The agent continues as if it had run all prior cells itself
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import nbformat

from kerno.kernel.runtime import KernelRuntime
from kerno.types          import Cell, CellOutput, CellError, SessionResult


def load_notebook(
    path:    str,
    kernel:  KernelRuntime,
    *,
    re_execute: bool   = True,
    stop_on_error: bool = False,
    timeout_per_cell: float = 120.0,
    verbose: bool  = False,
    engine:  Optional[object] = None,
) -> tuple[list[Cell], str]:
    """
    Load a prior notebook into a kernel and return its execution history.

    Args:
        path:             Path to .ipynb file
        kernel:           Running KernelRuntime to execute into
        re_execute:       If True, re-execute code cells to restore state.
                          If False, only load the history (no execution).
        stop_on_error:    If True, stop if any cell raises an error.
        timeout_per_cell: Per-cell execution timeout.
        verbose:          Print cell-by-cell progress.
        engine:           Optional ExecutionEngine (K-001). When given,
                          re-execution goes THROUGH the choke point so
                          policy applies to the recorded cells; without
                          it, raw re-execution is an explicit opt-in for
                          trusted callers only.

    Returns:
        (cells, task): list of Cell objects + original task description
    """
    nb_path = Path(path)
    if not nb_path.exists():
        raise FileNotFoundError(f"Notebook not found: {path}")

    with open(nb_path) as f:
        nb = nbformat.read(f, as_version=4)

    task = nb.metadata.get("kerno", {}).get("task", "")
    cells: list[Cell] = []

    for i, nb_cell in enumerate(nb.cells):
        if nb_cell.cell_type != "code":
            continue

        code = nb_cell.source.strip()
        if not code:
            continue

        # Skip kerno-internal cells
        if code.startswith("# Recovery hint injected by kerno"):
            continue

        if re_execute:
            if verbose:
                print(f"  [load] Cell {i}: {code[:60].replace(chr(10), ' ')}")

            # K-001: re-execution goes through the choke point when an
            # engine is provided (policy applies to recorded cells).
            if engine is not None:
                output = engine.execute(code, timeout=timeout_per_cell)
            else:
                output = kernel.execute(code, timeout=timeout_per_cell)

            if output.has_error:
                if verbose:
                    print(f"    ✗ {output.error.ename}: {output.error.evalue}")
                if stop_on_error:
                    break
            else:
                if verbose and output.stdout:
                    print(f"    → {output.stdout[:80].strip()}")
        else:
            # Build output from saved notebook outputs (no re-execution)
            output = _outputs_from_nb_cell(nb_cell)

        cells.append(Cell(
            code     = code,
            output   = output,
            cell_num = len(cells) + 1,
            author   = nb_cell.metadata.get("kerno_author", "agent"),
        ))

    if verbose:
        print(f"  Loaded {len(cells)} cells from {nb_path.name}")

    return cells, task


def continue_from_notebook(
    path:        str,
    llm:         object,
    new_task:    Optional[str] = None,
    *,
    loop:        str           = "reactive",
    re_execute:  bool          = True,
    max_cells:   int           = 50,
    verbose:     bool          = False,
    **loop_kwargs,
) -> SessionResult:
    """
    Load a prior notebook and continue the analysis from where it left off.

    Delegates to kerno.session.resume_from_notebook, the SECURE path:
    the recorded cells are re-executed on a fresh kernel THROUGH the
    ExecutionEngine (policy re-applied, blocked cells stay blocked),
    then the LLM continues. `re_execute` is accepted for backward
    compatibility; state restoration through the engine is always on.

    Args:
        path:       Path to .ipynb file from a prior session
        llm:        LLM callable
        new_task:   Override the task (default: resume original task)
        loop:       Loop strategy for continuation
        re_execute: Accepted for backward compatibility (state is
                    restored through the engine regardless)
        max_cells:  Max new cells to generate
        verbose:    Verbose output
        loop_kwargs: Additional kwargs (allowlist, capability_broker,
                    budget, cell_timeout, auto_restart, kernel_name)

    Returns:
        SessionResult

    Usage:
        # Resume an interrupted session
        result = continue_from_notebook(
            path     = "sessions/20240127_analyze_q3_sales.ipynb",
            llm      = my_llm,
            new_task = "The Q3 analysis was interrupted. "
                       "Please complete the regional breakdown and conclusions.",
        )
    """
    from kerno.session import resume_from_notebook as _secure_resume

    return _secure_resume(
        path,
        llm,
        new_task       = new_task,
        loop           = loop,
        max_cells      = max_cells,
        verbose        = verbose,
        **loop_kwargs,
    )


def _outputs_from_nb_cell(nb_cell) -> CellOutput:
    """Build CellOutput from saved notebook cell outputs (no re-execution)."""
    outputs: list[dict] = []
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    result_text: Optional[str] = None
    error: Optional[CellError] = None

    for output in nb_cell.get("outputs", []):
        output_type = output.get("output_type", "")

        if output_type == "stream":
            text = output.get("text", "")
            if output.get("name") == "stderr":
                stderr_parts.append(text)
            else:
                stdout_parts.append(text)

        elif output_type == "execute_result":
            data = output.get("data", {})
            if "text/plain" in data:
                result_text = data["text/plain"]

        elif output_type == "error":
            error = CellError(
                ename     = output.get("ename", ""),
                evalue    = output.get("evalue", ""),
                traceback = "\n".join(output.get("traceback", [])),
            )

    return CellOutput(
        stdout   = "".join(stdout_parts),
        stderr   = "".join(stderr_parts),
        result   = result_text,
        error    = error,
    )

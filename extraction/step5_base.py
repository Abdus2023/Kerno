# kerno/loop/base.py
"""
BaseLoop: the primitive execution loop.
All other loops inherit from this or compose it.

This is the irreducible core:
  LLM → code → kernel → output → LLM → ...
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from kerno.context.builder import PromptBuilder
from kerno.context.compressor import HistoryCompressor
from kerno.kernel.runtime import KernelRuntime
from kerno.types import (
    Cell, CellOutput, LLMCallable, Message,
    SessionResult, SessionStatus
)


# Signals the agent can emit to control the loop
COMPLETE_SIGNAL  = "# TASK_COMPLETE"
HANDOFF_SIGNAL   = "# HANDOFF:"
CHECKPOINT_EVERY = 10  # cells


class BaseLoop(ABC):
    """
    Abstract base for all execution loops.

    Subclasses implement `_next_cell()` which determines
    what code to generate next.
    The infrastructure (execution, history, compression, termination)
    lives here.
    """

    def __init__(
        self,
        kernel:     KernelRuntime,
        llm:        LLMCallable,
        max_cells:  int   = 50,
        cell_timeout: float = 120.0,
        compress_after: int = 20,
        verbose:    bool  = False,
    ):
        self.kernel          = kernel
        self.llm             = llm
        self.max_cells       = max_cells
        self.cell_timeout    = cell_timeout
        self.compress_after  = compress_after
        self.verbose         = verbose

        self._builder    = PromptBuilder()
        self._compressor = HistoryCompressor(llm)

        # Session state
        self._history:  list[Cell] = []
        self._summary:  str        = ""
        self._task:     str        = ""
        self._session_id: str      = str(uuid.uuid4())

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, task: str) -> SessionResult:
        """
        Execute the agent loop for a given task.

        Args:
            task: Natural language task description

        Returns:
            SessionResult with full execution record
        """
        self._task       = task
        self._history    = []
        self._summary    = ""
        started_at       = time.time()

        # Ensure checkpoint directory exists
        Path("_checkpoints").mkdir(exist_ok=True)

        status = SessionStatus.MAX_CELLS

        for cell_num in range(1, self.max_cells + 1):

            # ── Get next code from LLM ─────────────────────────────────────
            try:
                code = self._next_cell(cell_num)
            except Exception as e:
                if self.verbose:
                    print(f"[kerno] LLM error: {e}")
                status = SessionStatus.ERROR_UNHANDLED
                break

            if self.verbose:
                self._print_cell(cell_num, code)

            # ── Execute in kernel ──────────────────────────────────────────
            if not self.kernel.is_alive:
                status = SessionStatus.KERNEL_DIED
                break

            output = self.kernel.execute(code, timeout=self.cell_timeout)

            if self.verbose:
                self._print_output(output)

            # ── Record ────────────────────────────────────────────────────
            cell = Cell(
                code=code,
                output=output,
                cell_num=cell_num,
                author="agent",
            )
            self._history.append(cell)

            # ── On-execution hook (subclasses may override) ────────────────
            self._on_cell_complete(cell)

            # ── Auto-checkpoint ────────────────────────────────────────────
            if cell_num % CHECKPOINT_EVERY == 0:
                self._auto_checkpoint()

            # ── Compress history if needed ─────────────────────────────────
            if self._compressor.should_compress(self._history, self.compress_after):
                older         = self._history[:-10]
                new_summary   = self._compressor.compress(older)
                self._summary = (
                    f"{self._summary}\n\n{new_summary}".strip()
                    if self._summary else new_summary
                )
                self._history = self._history[-10:]

            # ── Termination check ──────────────────────────────────────────
            if COMPLETE_SIGNAL in code:
                status = SessionStatus.COMPLETE
                break

            # Unrecoverable kernel errors
            if output.has_error:
                ename = output.error.ename
                if ename in ("SystemExit", "KeyboardInterrupt"):
                    status = SessionStatus.INTERRUPTED
                    break
                # All other errors: let the LLM see and recover

        return SessionResult(
            session_id      = self._session_id,
            task            = task,
            status          = status,
            cells           = list(self._history),
            final_namespace = self.kernel.namespace,
            summary         = self._summary,
            started_at      = started_at,
            ended_at        = time.time(),
        )

    # ── Abstract Interface ─────────────────────────────────────────────────────

    @abstractmethod
    def _next_cell(self, cell_num: int) -> str:
        """
        Generate the next cell to execute.
        Subclasses implement their specific strategy here.

        Args:
            cell_num: Current cell number (1-indexed)

        Returns:
            Python source code to execute
        """
        ...

    # ── Hooks ──────────────────────────────────────────────────────────────────

    def _on_cell_complete(self, cell: Cell) -> None:
        """Called after each cell completes. Override for custom behavior."""
        pass

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_messages(self) -> list[Message]:
        """Build the current message list for the LLM."""
        return self._builder.build(
            task      = self._task,
            history   = self._history,
            namespace = self.kernel.namespace,
            summary   = self._summary,
        )

    def _call_llm(self, messages: list[Message]) -> str:
        """Call the LLM and return the response as a string."""
        return self.llm(messages)

    def _auto_checkpoint(self) -> None:
        """Silently checkpoint key objects to disk."""
        code = """
import joblib, pathlib, pandas as pd
_ckpt = pathlib.Path('_checkpoints')
_ckpt.mkdir(exist_ok=True)
for _name, _obj in list(globals().items()):
    if _name.startswith('_'): continue
    try:
        if isinstance(_obj, pd.DataFrame):
            _obj.to_parquet(_ckpt / f'{_name}.parquet')
        elif hasattr(_obj, '__sklearn_tags__'):
            joblib.dump(_obj, _ckpt / f'{_name}.joblib')
    except Exception:
        pass
"""
        self.kernel.execute(code, silent=True, timeout=30)

    def _print_cell(self, num: int, code: str) -> None:
        border  = "─" * 60
        preview = code[:200] + ("..." if len(code) > 200 else "")
        print(f"\n{border}")
        print(f"  Cell {num}")
        print(f"{border}")
        print(preview)

    def _print_output(self, output: CellOutput) -> None:
        text = output.as_text(max_chars=400)
        if output.has_error:
            print(f"  ✗ {text}")
        elif text != "[no output]":
            print(f"  → {text[:200]}")
        else:
            print("  → [no output]")

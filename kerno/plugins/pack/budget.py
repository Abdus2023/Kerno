"""Budget and guard plugin for cell/token/time limits."""

from __future__ import annotations

import time
from dataclasses import dataclass

from kerno.plugins.registry import BasePlugin


@dataclass
class BudgetSnapshot:
    cells: int
    elapsed: float
    input_chars: int
    output_chars: int
    budget_exceeded: bool


class BudgetPlugin(BasePlugin):
    """
    Track cells, elapsed time, and approximate character/token budgets.

    The plugin cannot cancel an already-running loop safely, but it exposes a
    ``budget_exceeded`` flag and prints warnings so loops/agents can check
    ``plugin.exceeded`` before continuing.
    """

    name = "budget"

    def __init__(
        self,
        max_cells: int = 50,
        max_seconds: float = 600.0,
        max_input_chars: int = 200_000,
        max_output_chars: int = 200_000,
    ):
        self.max_cells = max_cells
        self.max_seconds = max_seconds
        self.max_input_chars = max_input_chars
        self.max_output_chars = max_output_chars
        self.cells = 0
        self.input_chars = 0
        self.output_chars = 0
        self.started = 0.0
        self.exceeded = False

    def on_session_start(self, task: str, session_id: str) -> None:
        self.cells = 0
        self.input_chars = 0
        self.output_chars = 0
        self.exceeded = False
        self.started = time.monotonic()

    def on_cell_complete(self, cell) -> None:
        self.cells += 1
        self.input_chars += len(cell.code or "")
        output = getattr(cell, "output", None)
        if output is not None:
            self.output_chars += len(getattr(output, "stdout", "") or "")
            self.output_chars += len(getattr(output, "result", "") or "")

        if self.cells >= self.max_cells:
            self._warn(f"cell budget reached ({self.cells}/{self.max_cells})")

    def on_session_complete(self, result) -> None:
        snapshot = self.snapshot()
        print(
            "[budget] cells={cells} elapsed={elapsed:.1f}s "
            "in_chars={in_chars:,} out_chars={out_chars:,}".format(
                cells=snapshot.cells,
                elapsed=snapshot.elapsed,
                in_chars=snapshot.input_chars,
                out_chars=snapshot.output_chars,
            ),
            flush=True,
        )

    def snapshot(self) -> BudgetSnapshot:
        elapsed = time.monotonic() - self.started if self.started else 0.0
        exceeded = (
            self.cells >= self.max_cells
            or elapsed >= self.max_seconds
            or self.input_chars >= self.max_input_chars
            or self.output_chars >= self.max_output_chars
        )
        self.exceeded = self.exceeded or exceeded
        return BudgetSnapshot(
            cells=self.cells,
            elapsed=elapsed,
            input_chars=self.input_chars,
            output_chars=self.output_chars,
            budget_exceeded=self.exceeded,
        )

    def _warn(self, message: str) -> None:
        self.exceeded = True
        print(f"[budget] {message}", flush=True)

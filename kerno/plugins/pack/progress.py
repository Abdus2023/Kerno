"""Rich progress and observability plugin."""

from __future__ import annotations

import sys
import time
from typing import Any

from kerno.plugins.registry import BasePlugin


class ProgressPlugin(BasePlugin):
    """
    Print compact, human-readable progress during a kerno session.

    The plugin never raises: plugin failures must not interrupt execution.
    It is intentionally dependency-free so it works in minimal kernels.
    """

    name = "progress"

    def __init__(
        self,
        stream: Any = None,
        show_output_preview: bool = True,
        preview_chars: int = 120,
    ):
        self.stream = stream if stream is not None else sys.stdout
        self.show_output_preview = show_output_preview
        self.preview_chars = preview_chars
        self._started_at = 0.0
        self._cell_count = 0
        self._error_count = 0
        self._last_duration = 0.0

    def on_session_start(self, task: str, session_id: str) -> None:
        self._started_at = time.monotonic()
        self._cell_count = 0
        self._error_count = 0
        self._emit(f"▶ session {session_id} started: {task[:120]}")

    def on_cell_complete(self, cell) -> None:
        self._cell_count += 1
        self._last_duration = float(getattr(getattr(cell, "output", None), "duration", 0.0) or 0.0)
        output = self._preview(cell)
        suffix = f" {output}" if output and self.show_output_preview else ""
        self._emit(
            f"  ✓ cell {cell.cell_num} in {self._last_duration:.2f}s{suffix}"
        )

    def on_error(self, cell, classified_error) -> None:
        self._error_count += 1
        ename = getattr(getattr(cell, "output", None), "error", None)
        ename = getattr(ename, "ename", "Error") if ename else "Error"
        hint = getattr(classified_error, "recovery_hint", None) or ""
        label = getattr(classified_error, "error_class", None)
        label = getattr(label, "name", label)
        self._emit(f"  ✗ cell {cell.cell_num}: {label or ename} — {hint}")

    def on_session_complete(self, result) -> None:
        total = time.monotonic() - self._started_at if self._started_at else 0.0
        status = getattr(getattr(result, "status", None), "name", "DONE")
        self._emit(
            "■ session complete: "
            f"status={status} cells={self._cell_count} "
            f"errors={self._error_count} total={total:.2f}s"
        )

    def _preview(self, cell) -> str:
        text = cell.output.as_text(self.preview_chars * 2) if hasattr(cell, "output") else ""
        text = " ".join(text.split())
        if len(text) > self.preview_chars:
            text = text[: self.preview_chars].rstrip() + "…"
        return text

    def _emit(self, message: str) -> None:
        try:
            print(message, file=self.stream, flush=True)
        except Exception:
            pass

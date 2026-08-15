"""Structured telemetry plugin for sessions and cells."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from kerno.plugins.registry import BasePlugin


class TelemetryPlugin(BasePlugin):
    """
    Emit JSONL records for session/cell lifecycle events.

    Each record is a compact JSON object. By default records are written to
    ``_kerno/telemetry/<session_id>.jsonl`` and also appended to
    ``self.events`` for in-process inspection.
    """

    name = "telemetry"

    def __init__(
        self,
        directory: str = "_kerno/telemetry",
        stdout: bool = False,
        metadata: dict | None = None,
    ):
        self.directory = Path(directory)
        self.stdout = stdout
        self.metadata = metadata or {}
        self.session_id = ""
        self.task = ""
        self.events: list[dict[str, Any]] = []
        self._start = 0.0
        self._path: Path | None = None

    def on_session_start(self, task: str, session_id: str) -> None:
        self.session_id = session_id
        self.task = task
        self._start = time.time()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path = self.directory / f"{session_id}.jsonl"
        self._record("session_start", task=task)

    def on_cell_complete(self, cell) -> None:
        output = getattr(cell, "output", None)
        self._record(
            "cell_complete",
            cell=cell.cell_num,
            duration=getattr(output, "duration", None),
            has_error=getattr(output, "has_error", False),
            stdout_chars=len(getattr(output, "stdout", "") or ""),
            images=len(getattr(output, "images", []) or []),
            displays=len(getattr(output, "displays", []) or []),
        )

    def on_error(self, cell, classified_error) -> None:
        original = getattr(getattr(classified_error, "original", None), "ename", None)
        error_class = getattr(getattr(classified_error, "error_class", None), "name", None)
        self._record(
            "error",
            cell=cell.cell_num,
            error_class=error_class,
            ename=original,
            recovery_hint=getattr(classified_error, "recovery_hint", None),
        )

    def on_session_complete(self, result) -> None:
        status = getattr(getattr(result, "status", None), "name", "DONE")
        self._record(
            "session_complete",
            status=status,
            cells=getattr(result, "cells_executed", None),
            errors=getattr(result, "error_count", None),
            duration=getattr(result, "duration", None),
        )

    def _record(self, event: str, **fields: Any) -> None:
        record = {
            "ts": time.time(),
            "event": event,
            "session_id": self.session_id,
            "task": self.task,
            **self.metadata,
            **fields,
        }
        self.events.append(record)
        line = json.dumps(record, default=str, ensure_ascii=False)
        if self._path is not None:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        if self.stdout:
            print("[telemetry]", line, flush=True)

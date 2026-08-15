"""
Structured JSON logger for kerno.
Every log entry is a JSON object — machine-parseable by default.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional


class Level(IntEnum):
    DEBUG   = 10
    INFO    = 20
    WARNING = 30
    ERROR   = 40


class StructuredLogger:
    """
    Writes structured JSON log entries to stderr and optionally a file.

    Every entry has:
      ts, level, logger, message, + any extra fields passed as kwargs
    """

    def __init__(
        self,
        name:       str,
        level:      Level = Level.INFO,
        file_path:  Optional[str] = ".kerno/kerno.log",
    ):
        self.name      = name
        self.level     = level
        self._lock     = threading.Lock()
        self._file     = None

        if file_path:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(p, "a")

    def debug(self, message: str, **kwargs) -> None:
        self._log(Level.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self._log(Level.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self._log(Level.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        self._log(Level.ERROR, message, **kwargs)

    def _log(self, level: Level, message: str, **kwargs) -> None:
        if level < self.level:
            return

        entry = {
            "ts":      time.time(),
            "level":   level.name,
            "logger":  self.name,
            "message": message,
            **{k: self._serialize(v) for k, v in kwargs.items()},
        }

        line = json.dumps(entry)

        with self._lock:
            print(line, file=sys.stderr)
            if self._file:
                self._file.write(line + "\n")
                self._file.flush()

    @staticmethod
    def _serialize(v: Any) -> Any:
        if isinstance(v, (str, int, float, bool, type(None))):
            return v
        return str(v)[:500]


_loggers: dict[str, StructuredLogger] = {}
_lock = threading.Lock()


def get_logger(name: str = "kerno") -> StructuredLogger:
    with _lock:
        if name not in _loggers:
            _loggers[name] = StructuredLogger(name)
        return _loggers[name]

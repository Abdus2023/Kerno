# kerno/streaming/protocol.py
"""
Streaming protocol: the events emitted during a session.

Every meaningful state transition emits a typed event.
Consumers subscribe to event streams — they don't poll.

EventKind taxonomy:
  SESSION_*  — session lifecycle
  CELL_*     — cell lifecycle
  OUTPUT_*   — kernel output chunks
  LLM_*      — LLM call events
  MEMORY_*   — memory operations
  ERROR_*    — error events
  SKILL_*    — skill loading
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum        import Enum, auto
from typing      import Any, Optional
import time


class EventKind(Enum):
    # Session lifecycle
    SESSION_START     = auto()
    SESSION_COMPLETE  = auto()
    SESSION_ERROR     = auto()

    # Cell lifecycle
    CELL_START        = auto()
    CELL_COMPLETE     = auto()
    CELL_ERROR        = auto()

    # Output chunks (streaming)
    OUTPUT_STDOUT     = auto()
    OUTPUT_STDERR     = auto()
    OUTPUT_IMAGE      = auto()
    OUTPUT_HTML       = auto()
    OUTPUT_RESULT     = auto()

    # LLM events
    LLM_START         = auto()
    LLM_COMPLETE      = auto()
    LLM_TOKEN         = auto()    # Token-level streaming (if supported)

    # Memory
    MEMORY_RETRIEVED  = auto()
    MEMORY_STORED     = auto()

    # Errors
    ERROR_CLASSIFIED  = auto()
    ERROR_RECOVERED   = auto()

    # Skills
    SKILL_LOADED      = auto()

    # Planning
    PLAN_CREATED      = auto()
    PLAN_STEP_START   = auto()
    PLAN_STEP_DONE    = auto()

    # Namespace
    NAMESPACE_CHANGED = auto()


@dataclass
class StreamEvent:
    """
    One event in the session stream.
    All fields are JSON-serializable — events cross process boundaries.
    """
    kind:       EventKind
    session_id: str
    timestamp:  float         = field(default_factory=time.time)
    payload:    dict[str, Any] = field(default_factory=dict)
    cell_num:   Optional[int]  = None
    error:      Optional[str]  = None

    def to_dict(self) -> dict:
        return {
            "kind":       self.kind.name,
            "session_id": self.session_id,
            "timestamp":  self.timestamp,
            "payload":    self.payload,
            "cell_num":   self.cell_num,
            "error":      self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StreamEvent":
        return cls(
            kind       = EventKind[data["kind"]],
            session_id = data["session_id"],
            timestamp  = data.get("timestamp", time.time()),
            payload    = data.get("payload", {}),
            cell_num   = data.get("cell_num"),
            error      = data.get("error"),
        )

    # ── Factories ──────────────────────────────────────────────────────────────

    @classmethod
    def session_start(cls, session_id: str, task: str) -> "StreamEvent":
        return cls(
            kind       = EventKind.SESSION_START,
            session_id = session_id,
            payload    = {"task": task},
        )

    @classmethod
    def cell_start(cls, session_id: str, cell_num: int, code: str) -> "StreamEvent":
        return cls(
            kind       = EventKind.CELL_START,
            session_id = session_id,
            cell_num   = cell_num,
            payload    = {"code_preview": code[:80].replace("\n", " ")},
        )

    @classmethod
    def output_stdout(cls, session_id: str, cell_num: int, text: str) -> "StreamEvent":
        return cls(
            kind       = EventKind.OUTPUT_STDOUT,
            session_id = session_id,
            cell_num   = cell_num,
            payload    = {"text": text},
        )

    @classmethod
    def output_image(cls, session_id: str, cell_num: int, b64: str) -> "StreamEvent":
        return cls(
            kind       = EventKind.OUTPUT_IMAGE,
            session_id = session_id,
            cell_num   = cell_num,
            payload    = {"base64": b64, "mime": "image/png"},
        )

    @classmethod
    def cell_complete(cls, session_id: str, cell_num: int,
                      had_error: bool, duration_ms: float) -> "StreamEvent":
        return cls(
            kind       = EventKind.CELL_COMPLETE,
            session_id = session_id,
            cell_num   = cell_num,
            payload    = {
                "had_error":   had_error,
                "duration_ms": duration_ms,
            },
        )

    @classmethod
    def session_complete(
        cls, session_id: str, status: str, cells: int, duration_s: float
    ) -> "StreamEvent":
        return cls(
            kind       = EventKind.SESSION_COMPLETE,
            session_id = session_id,
            payload    = {
                "status":     status,
                "cells":      cells,
                "duration_s": duration_s,
            },
        )

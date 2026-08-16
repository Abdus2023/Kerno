# kerno/types.py
"""
Shared types for the kerno framework.
These are the nouns. Everything else is verbs.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# ─── Execution Types ──────────────────────────────────────────────────────────

@dataclass
class CellOutput:
    """
    The structured result of executing one cell.
    Everything the kernel can emit, in one place.
    """
    stdout:   str                    = ""
    stderr:   str                    = ""
    result:   Optional[str]          = None   # The cell's return value (text/plain)
    displays: list[dict]             = field(default_factory=list)  # HTML, JSON, etc.
    images:   list[str]              = field(default_factory=list)  # base64 PNG
    error:    Optional["CellError"]  = None
    duration: float                  = 0.0    # Wall time in seconds
    execution_id: Optional[str]      = None   # Universal correlation key (audit #78)

    @property
    def has_error(self) -> bool:
        return self.error is not None

    @property
    def is_empty(self) -> bool:
        return (
            not self.stdout and not self.stderr and
            self.result is None and not self.displays and
            not self.images and not self.has_error
        )

    def as_text(self, max_chars: int = 3000) -> str:
        """
        Render output as text for LLM consumption.
        Information-dense: errors first, then output, then metadata.
        """
        parts: list[str] = []

        if self.error:
            parts.append(f"[ERROR] {self.error.ename}: {self.error.evalue}")
            if self.error.traceback:
                # Last 5 lines: most relevant
                tb_tail = "\n".join(self.error.traceback.split("\n")[-5:])
                parts.append(tb_tail)

        if self.stdout:
            text = self.stdout
            if len(text) > max_chars:
                head = text[: max_chars // 2]
                tail = text[-(max_chars // 4) :]
                text = (
                    f"{head}\n"
                    f"... [{len(self.stdout) - max_chars} chars omitted] ...\n"
                    f"{tail}"
                )
            parts.append(text.rstrip())

        if self.result and self.result not in (self.stdout or ""):
            parts.append(f"→ {self.result[:500]}")

        if self.images:
            parts.append(f"[{len(self.images)} plot(s) generated]")

        if self.displays:
            for d in self.displays[:3]:
                if "html" in d:
                    # Strip tags for LLM — keep data, not markup
                    import re
                    text = re.sub(r"<[^>]+>", " ", d["html"])
                    text = re.sub(r"\s+", " ", text).strip()
                    parts.append(text[:500])

        return "\n".join(parts) if parts else "[no output]"


@dataclass
class CellError:
    ename:     str
    evalue:    str
    traceback: str = ""


@dataclass
class Cell:
    """One unit of execution: code in, output out."""
    code:      str
    output:    CellOutput
    cell_num:  int
    author:    str = "agent"          # "agent" | "human" | "system"
    timestamp: float = field(default_factory=time.time)
    reasoning: Optional[str] = None   # LLM's thinking before writing the code


# ─── Session Types ────────────────────────────────────────────────────────────

class SessionStatus(Enum):
    RUNNING         = auto()
    COMPLETE        = auto()
    MAX_CELLS       = auto()
    INTERRUPTED     = auto()
    KERNEL_DIED     = auto()
    ERROR_UNHANDLED = auto()


@dataclass
class SessionResult:
    """The full record of a completed agent session."""
    session_id:      str
    task:            str
    status:          SessionStatus
    cells:           list[Cell]
    final_namespace: str          = "{}"   # JSON snapshot
    summary:         str          = ""
    started_at:      float        = field(default_factory=time.time)
    ended_at:        Optional[float] = None
    # ── Execution-ledger correlation (audit #78) ────────────────────────
    # Set by run()/run_with_pool(): the execution_ids this session
    # produced (universal correlation key) and the policy rules that
    # blocked cells, so callers can cross-reference the engine audit.
    execution_ids:   list         = field(default_factory=list)
    blocked_rules:   list         = field(default_factory=list)

    @property
    def duration(self) -> float:
        if self.ended_at:
            return self.ended_at - self.started_at
        return time.time() - self.started_at

    @property
    def cells_executed(self) -> int:
        return len(self.cells)

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.cells if c.output.has_error)

    @property
    def recovery_count(self) -> int:
        """
        Cells that followed an error cell.
        Heuristic for self-correction events.
        """
        count = 0
        for i in range(1, len(self.cells)):
            if self.cells[i - 1].output.has_error and not self.cells[i].output.has_error:
                count += 1
        return count


# ─── LLM Interface ────────────────────────────────────────────────────────────

@dataclass
class Message:
    role:    str   # "system" | "user" | "assistant"
    content: str


# The LLM is just a callable. No base class needed.
# Type alias for clarity.
LLMCallable = Any  # (messages: list[Message]) -> str


# ─── Error Classification ─────────────────────────────────────────────────────

class ErrorClass(Enum):
    # Semantic: LLM misunderstood data or environment
    WRONG_COLUMN     = auto()
    WRONG_ASSUMPTION = auto()
    WRONG_API        = auto()
    WRONG_TYPE       = auto()

    # Resource: environment lacks something
    MODULE_NOT_FOUND = auto()
    FILE_NOT_FOUND   = auto()
    OUT_OF_MEMORY    = auto()
    TIMEOUT          = auto()

    # Logic: valid code, wrong algorithm
    DIMENSION_MISMATCH   = auto()
    INDEX_OUT_OF_BOUNDS  = auto()
    DIVISION_BY_ZERO     = auto()

    # Syntax: LLM wrote invalid Python
    SYNTAX_ERROR         = auto()

    # State: kernel disagrees with LLM's belief
    UNDEFINED_VARIABLE   = auto()
    NAMESPACE_DESYNC     = auto()

    # Unknown
    UNCLASSIFIED         = auto()

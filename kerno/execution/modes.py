# kerno/execution/modes.py
"""
Execution modes and replay (audit #58, #91, #100).

    ExecutionMode
    ├── SIMULATE  — no real side effects (pure echo)
    ├── DRY_RUN   — validate intended operations but don't commit
    ├── LIVE      — real execution (the default engine path)
    └── REPLAY    — execute already-recorded actions

Replay is one of Kerno's strongest features: a recorded session can be
re-executed WITHOUT the LLM (audit #58), so debugging and CI never depend
on a live model. Combined with a recorded SessionResult:

    Agent run
        ├── live mode    → engine.execute(...)
        └── replay mode  → replay_session(result, kernel)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from kerno.execution.engine import ExecutionEngine
from kerno.provenance import ProvenanceGraph
from kerno.security.allowlist import AllowList, AllowListViolation
from kerno.types import Cell, CellError, CellOutput, SessionResult, SessionStatus


class ExecutionMode(Enum):
    """The four execution modes of the runtime (audit #91)."""

    SIMULATE = auto()   # no real side effects
    DRY_RUN  = auto()   # validate intended operations, don't commit
    LIVE     = auto()   # real execution
    REPLAY   = auto()   # execute recorded actions


class DryRunExecutor:
    """
    Validates code without executing it (SIMULATE / DRY_RUN modes).

    Implements the Executor protocol. If an allowlist is attached, code
    that would be blocked is reported as an AllowListViolation error cell —
    the same shape the agent loop sees in LIVE mode — so dry runs are
    faithful policy checks.
    """

    def __init__(
        self,
        allowlist: Optional[AllowList] = None,
        mode:      ExecutionMode = ExecutionMode.DRY_RUN,
    ):
        self._allowlist = allowlist
        self.mode       = mode
        self._checked:  list[str] = []

    def execute(
        self,
        code:         str,
        timeout:      float = 120.0,
        silent:       bool  = False,
        cancel_event: "object | None" = None,
    ) -> CellOutput:
        self._checked.append(code)
        if self._allowlist is not None:
            try:
                self._allowlist.check(code)
            except AllowListViolation as exc:
                return CellOutput(
                    error=CellError(
                        ename  = "AllowListViolation",
                        evalue = str(exc),
                    )
                )
        preview = code[:60].replace("\n", " ")
        return CellOutput(
            stdout="[{}] would execute: {}…".format(
                self.mode.name.lower(), preview
            )
        )

    def execute_silent(self, code: str, timeout: float = 15.0) -> str:
        return ""

    @property
    def namespace(self) -> str:
        return "{}"

    @property
    def is_alive(self) -> bool:
        return True

    @property
    def checked(self) -> tuple[str, ...]:
        """All code validated so far."""
        return tuple(self._checked)


class ReplayExecutor:
    """
    Serves recorded cell outputs in order (REPLAY mode).

    Implements the Executor protocol over a list of recorded Cells, so a
    pipeline or loop can be re-run against history without a kernel or an
    LLM (audit #100: fully replayable tests). When the recording is
    exhausted, further executions return a ReplayExhausted error cell.
    """

    def __init__(self, recorded: list[Cell]):
        self._recorded = list(recorded)
        self._index    = 0
        self._log: list[tuple[str, int]] = []   # (requested code, served index)

    def execute(
        self,
        code:         str,
        timeout:      float = 120.0,
        silent:       bool  = False,
        cancel_event: "object | None" = None,
    ) -> CellOutput:
        if self._index >= len(self._recorded):
            return CellOutput(
                error=CellError(
                    ename  = "ReplayExhausted",
                    evalue = "no more recorded cells to replay",
                )
            )
        served = self._recorded[self._index]
        self._log.append((code, self._index))
        self._index += 1
        return served.output

    def execute_silent(self, code: str, timeout: float = 15.0) -> str:
        return self.execute(code, timeout=timeout, silent=True).stdout.strip()

    @property
    def namespace(self) -> str:
        return "{}"

    @property
    def is_alive(self) -> bool:
        return True

    @property
    def replay_log(self) -> tuple[tuple[str, int], ...]:
        """(requested_code, recorded_index) for every served execution."""
        return tuple(self._log)

    @property
    def remaining(self) -> int:
        return len(self._recorded) - self._index


def replay_session(
    result:      SessionResult,
    executor:    object,
    *,
    allowlist:   Optional[AllowList] = None,
    provenance:  Optional[ProvenanceGraph] = None,
    timeout:     float = 120.0,
) -> SessionResult:
    """
    Re-execute a recorded session WITHOUT the LLM (audit #58).

    Every agent cell of `result` is executed again through the execution
    choke point against the given executor (a KernelRuntime, or an
    ExecutionEngine). The LLM is never invoked: replay is deterministic
    with respect to the recorded actions.

    Args:
        result:     The recorded session to replay.
        executor:   KernelRuntime or ExecutionEngine to replay against.
        allowlist:  Optional policy re-applied during replay (the same
                    allowlist that governed the original run).
        provenance: Optional provenance graph to record replay executions.

    Returns:
        A new SessionResult with fresh outputs. Status is COMPLETE when
        every replayed cell executed without error, otherwise
        ERROR_UNHANDLED.
    """
    if isinstance(executor, ExecutionEngine):
        engine = executor
    else:
        engine = ExecutionEngine(
            executor, allowlist=allowlist, provenance=provenance
        )

    replayed: list[Cell] = []
    had_error = False
    for i, cell in enumerate(result.cells, start=1):
        output = engine.execute(cell.code, timeout=timeout)
        if output.has_error:
            had_error = True
        replayed.append(Cell(
            code     = cell.code,
            output   = output,
            cell_num = i,
            author   = cell.author,
        ))

    return SessionResult(
        session_id      = result.session_id,
        task            = "[replay] " + result.task,
        status          = (
            SessionStatus.ERROR_UNHANDLED if had_error else SessionStatus.COMPLETE
        ),
        cells           = replayed,
        final_namespace = engine.namespace,
        summary         = "Replay of {} ({} cells, {} errors)".format(
            result.session_id, len(replayed), sum(1 for c in replayed if c.output.has_error)
        ),
        started_at      = result.started_at,
        ended_at        = time.time(),
    )

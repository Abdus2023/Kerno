# kerno/interceptors.py
"""
Interceptors: observe and enforce invariants on pipeline execution.

Unlike Middleware (which wraps individual Steps), Interceptors
observe the entire pipeline execution from outside.

Three patterns:
  - InterceptedPipeline: before/after/error callbacks on the whole pipeline
  - StateRecorder: snapshot, diff, and replay AgentState transitions
  - InvariantChecker: assert invariants hold at every step
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable, Optional

from kerno.interfaces import AgentState, Step


# ── InterceptedPipeline ───────────────────────────────────────────────────────

class InterceptedPipeline:
    """
    A Step that wraps a pipeline and fires callbacks:
      - on_before(state)  → before the pipeline runs
      - on_after(state)   → after the pipeline runs (success)
      - on_error(state, error) → if the pipeline raises

    Callbacks are purely observational — they cannot modify state.
    """

    def __init__(
        self,
        step:      Step,
        *,
        on_before:  Callable[[AgentState], None]       = None,
        on_after:   Callable[[AgentState], None]       = None,
        on_error:   Callable[[AgentState, Exception], None] = None,
    ):
        self.step     = step
        self.on_before = on_before
        self.on_after  = on_after
        self.on_error  = on_error

    def run(self, state: AgentState) -> AgentState:
        if self.on_before:
            self.on_before(state)

        try:
            result = self.step.run(state)
            if self.on_after:
                self.on_after(result)
            return result
        except Exception as exc:
            if self.on_error:
                self.on_error(state, exc)
            raise


# ── StateRecorder ─────────────────────────────────────────────────────────────

@dataclass
class StateSnapshot:
    """A snapshot of AgentState at one point in time."""
    step_name:  str
    step_index: int
    state:      AgentState


class StateRecorder:
    """
    Records AgentState snapshots at every step transition.
    Supports diffing and replaying.

    Usage:
        recorder = StateRecorder()
        step = InterceptedPipeline(
            pipeline,
            on_before=recorder.capture("before"),
            on_after=recorder.capture("after"),
        )
        # ... run pipeline ...
        diffs = recorder.diff(0, 1)
        replayed = recorder.replay()
    """

    def __init__(self):
        self.snapshots: list[StateSnapshot] = []

    def capture(self, label: str = "") -> Callable[[AgentState], None]:
        """Return a callback that captures state snapshots."""
        def _capture(state: AgentState) -> None:
            idx = len(self.snapshots)
            self.snapshots.append(StateSnapshot(
                step_name=label,
                step_index=idx,
                state=copy.deepcopy(state),
            ))
        return _capture

    def diff(self, i: int, j: int) -> dict:
        """Diff two snapshots by index. Returns changed fields."""
        if i >= len(self.snapshots) or j >= len(self.snapshots):
            raise IndexError("Snapshot index out of range")

        s1 = self.snapshots[i].state
        s2 = self.snapshots[j].state
        changes = {}

        for field_name in ("task", "namespace", "summary", "session_id",
                           "complete", "error"):
            v1 = getattr(s1, field_name)
            v2 = getattr(s2, field_name)
            if v1 != v2:
                changes[field_name] = {"from": v1, "to": v2}

        if s1.history != s2.history:
            changes["history_len"] = {
                "from": len(s1.history),
                "to": len(s2.history),
            }

        if s1.metadata != s2.metadata:
            changes["metadata"] = {"from": dict(s1.metadata), "to": dict(s2.metadata)}

        return changes

    def replay(self) -> list[AgentState]:
        """Return all recorded states in order."""
        return [snap.state for snap in self.snapshots]


# ── InvariantChecker ──────────────────────────────────────────────────────────

class InvariantChecker:
    """
    Asserts that invariants hold at every step.
    Raises InvariantViolation if any check fails.

    Usage:
        checker = InvariantChecker([
            lambda s: s.task != "",           # task never empty
            lambda s: not s.error or s.complete,  # error implies stop
        ])
        step = InterceptedPipeline(
            pipeline,
            on_before=checker.check_before,
            on_after=checker.check_after,
        )
    """

    def __init__(self, invariants: list[Callable[[AgentState], bool]]):
        self.invariants = invariants
        self.violations: list[str] = []

    def _check(self, state: AgentState, phase: str) -> None:
        for i, inv in enumerate(self.invariants):
            if not inv(state):
                msg = "Invariant {} violated at {} (task={!r})".format(
                    i, phase, state.task[:50]
                )
                self.violations.append(msg)

    def check_before(self, state: AgentState) -> None:
        self._check(state, "before")

    def check_after(self, state: AgentState) -> None:
        self._check(state, "after")

    def assert_ok(self) -> None:
        """Raise if any violations were recorded."""
        if self.violations:
            raise InvariantViolation(
                "{} invariant(s) violated:\n{}".format(
                    len(self.violations),
                    "\n".join(self.violations),
                )
            )


class InvariantViolation(Exception):
    """Raised when an invariant check fails."""


# ── Built-in invariant factories ──────────────────────────────────────────────

def make_monotonic_check(key: str) -> Callable[[AgentState], bool]:
    """
    Return an invariant that a numeric metadata key is monotonically
    increasing (or non-decreasing).

    Usage:
        checker = InvariantChecker([
            make_monotonic_check("cell_count"),
        ])
    """
    last = {"value": None}

    def check(state: AgentState) -> bool:
        current = state.metadata.get(key)
        if current is None:
            return True
        if last["value"] is not None and current < last["value"]:
            return False
        last["value"] = current
        return True

    return check


def no_infinite_loops(max_cells: int = 200) -> Callable[[AgentState], bool]:
    """
    Return an invariant that history never exceeds max_cells.
    Prevents runaway loops.

    Usage:
        checker = InvariantChecker([
            no_infinite_loops(100),
        ])
    """
    def check(state: AgentState) -> bool:
        return len(state.history) <= max_cells
    return check

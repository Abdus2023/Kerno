# kerno/execution/budget.py
"""
ExecutionBudget — resource accounting attached to executions (audit #85).

    ExecutionBudget
    ├── max_executions     — how many cells may run
    ├── max_wall_time      — total wall-clock seconds across executions
    └── max_output_bytes   — cumulative stdout bytes

Enforcement model:
    - max_executions is enforced BEFORE the kernel is touched
      (a new execution is refused with a BudgetExceeded error cell).
    - wall time and output are enforced AFTER recording, so a completed
      execution is never truncated mid-flight; the NEXT execution is
      refused once the budget is exhausted.

BudgetedExecutor wraps any Executor (usually the ExecutionEngine) and
implements the Executor protocol, so loops accept it transparently.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from kerno.types import CellError, CellOutput


class BudgetExceeded(RuntimeError):
    """Raised when an execution budget limit is exceeded."""

    def __init__(self, limit: str, spent: float, allowed: float):
        self.limit   = limit
        self.spent   = spent
        self.allowed = allowed
        super().__init__(
            "Budget exceeded [{}]: spent {} of allowed {}".format(
                limit, spent, allowed
            )
        )


@dataclass
class ExecutionBudget:
    """Limits for a task's executions."""

    max_executions:   Optional[int]   = None   # cells
    max_wall_time:    Optional[float] = None   # seconds, cumulative
    max_output_bytes: Optional[int]   = None   # bytes, cumulative stdout


@dataclass
class BudgetSnapshot:
    """Current budget usage (for observability / dashboards)."""

    executions:   int   = 0
    wall_time_s:  float = 0.0
    output_bytes: int   = 0

    def to_dict(self) -> dict:
        return {
            "executions":   self.executions,
            "wall_time_s":  round(self.wall_time_s, 3),
            "output_bytes": self.output_bytes,
        }


class BudgetTracker:
    """Accumulates usage against an ExecutionBudget."""

    def __init__(self, budget: ExecutionBudget):
        self.budget = budget
        self._executions   = 0
        self._wall_time    = 0.0
        self._output_bytes = 0
        self._exceeded: Optional[BudgetExceeded] = None

    # ── Checks ────────────────────────────────────────────────────────────

    def check_can_start(self) -> None:
        """
        Refuse to start a new execution when the budget is exhausted.

        Raises the sticky BudgetExceeded (wall/output limits) if one was
        hit by a previous execution, or the executions limit if reached.
        """
        if self._exceeded is not None:
            raise self._exceeded
        if (
            self.budget.max_executions is not None
            and self._executions >= self.budget.max_executions
        ):
            raise BudgetExceeded(
                "max_executions", self._executions, self.budget.max_executions
            )

    def record(self, duration_s: float, output_bytes: int) -> None:
        """
        Accumulate a completed execution; raise when a limit is crossed.

        The exceeded state is sticky: once any wall/output limit is hit,
        every subsequent check_can_start() refuses.
        """
        self._executions   += 1
        self._wall_time    += duration_s
        self._output_bytes += output_bytes

        try:
            if (
                self.budget.max_wall_time is not None
                and self._wall_time > self.budget.max_wall_time
            ):
                raise BudgetExceeded(
                    "max_wall_time", round(self._wall_time, 3),
                    self.budget.max_wall_time,
                )
            if (
                self.budget.max_output_bytes is not None
                and self._output_bytes > self.budget.max_output_bytes
            ):
                raise BudgetExceeded(
                    "max_output_bytes", self._output_bytes,
                    self.budget.max_output_bytes,
                )
        except BudgetExceeded as exc:
            self._exceeded = exc
            raise

    # ── View ──────────────────────────────────────────────────────────────

    @property
    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            executions   = self._executions,
            wall_time_s  = self._wall_time,
            output_bytes = self._output_bytes,
        )

    @property
    def exhausted(self) -> bool:
        return self._exceeded is not None or (
            self.budget.max_executions is not None
            and self._executions >= self.budget.max_executions
        )


class BudgetedExecutor:
    """
    Executor wrapper enforcing an ExecutionBudget.

    When the budget is exhausted, execute() returns a BudgetExceeded error
    cell WITHOUT touching the underlying executor — the agent loop sees a
    normal failed cell and stops recovering.
    """

    def __init__(
        self,
        executor: object,
        budget:   ExecutionBudget,
        tracker:  Optional["BudgetTracker"] = None,
    ):
        self._executor = executor
        self._tracker  = tracker or BudgetTracker(budget)

    def execute(
        self,
        code:    str,
        timeout: float = 120.0,
        silent:  bool  = False,
        **kwargs,
    ) -> CellOutput:
        try:
            self._tracker.check_can_start()
        except BudgetExceeded as exc:
            return CellOutput(error=CellError(
                ename  = "BudgetExceeded",
                evalue = str(exc),
            ))

        start  = time.monotonic()
        output = self._executor.execute(
            code, timeout=timeout, silent=silent, **kwargs
        )
        duration_s = time.monotonic() - start

        try:
            self._tracker.record(duration_s, len(output.stdout))
        except BudgetExceeded:
            # This execution completed; the NEXT one will be refused.
            pass

        return output

    def execute_silent(self, code: str, timeout: float = 15.0, **kwargs) -> str:
        output = self.execute(code, timeout=timeout, silent=True, **kwargs)
        return output.stdout.strip()

    @property
    def namespace(self) -> str:
        return self._executor.namespace

    @property
    def is_alive(self) -> bool:
        return self._executor.is_alive

    @property
    def tracker(self) -> BudgetTracker:
        return self._tracker

    @property
    def raw_kernel(self) -> object:
        """Passthrough to the underlying kernel (for trusted infrastructure)."""
        inner = getattr(self._executor, "raw_kernel", None)
        return inner if inner is not None else self._executor

    @property
    def records(self):
        """Passthrough to the underlying engine's audit records."""
        return getattr(self._executor, "records", ())

    @property
    def blocked_count(self) -> int:
        return getattr(self._executor, "blocked_count", 0)


# ── Hierarchical budgets (audit #86) ──────────────────────────────────────────

class BudgetAllocationError(RuntimeError):
    """Raised when a child budget exceeds the parent's remaining budget."""


class BudgetAllocator:
    """
    Derives child budgets from a parent budget (audit #86).

        Parent: 100 units
          ├── Child A: 30
          ├── Child B: 40
          └── Parent remaining: 30

    Children can never exceed what the parent has left — a child agent
    cannot consume unlimited resources. Allocations are tracked so the
    parent's remaining budget is always known.
    """

    def __init__(self, parent: ExecutionBudget):
        self._parent            = parent
        self._allocated_exec    = 0
        self._allocated_time    = 0.0
        self._allocated_output  = 0
        self._children: list[ExecutionBudget] = []

    # ── Allocation ───────────────────────────────────────────────────────

    def allocate(
        self,
        *,
        executions:  Optional[int]   = None,
        wall_time:   Optional[float] = None,
        output_bytes: Optional[int]  = None,
        name:        str             = "",
    ) -> ExecutionBudget:
        """
        Allocate a child budget from the parent's remaining capacity.

        Every requested limit must be within what the parent has left;
        None means "inherit the parent's remaining limit" (which is
        still capped by the parent's total).
        """
        child = ExecutionBudget(
            max_executions   = self._remaining_exec(executions),
            max_wall_time    = self._remaining_time(wall_time),
            max_output_bytes = self._remaining_output(output_bytes),
        )
        # Commit the allocation
        self._allocated_exec   += (
            executions if executions is not None
            else (self._parent.max_executions or 0)
        )
        self._allocated_time   += (
            wall_time if wall_time is not None
            else (self._parent.max_wall_time or 0.0)
        )
        self._allocated_output += (
            output_bytes if output_bytes is not None
            else (self._parent.max_output_bytes or 0)
        )
        child_name = name or "child-{}".format(len(self._children) + 1)
        self._children.append(child)
        self._names = getattr(self, "_names", {})
        self._names[child_name] = child
        return child

    # ── Remaining budget ─────────────────────────────────────────────────

    @property
    def remaining(self) -> ExecutionBudget:
        """What the parent can still allocate."""
        return ExecutionBudget(
            max_executions   = self._remaining_exec(None),
            max_wall_time    = self._remaining_time(None),
            max_output_bytes = self._remaining_output(None),
        )

    def remaining_exec(self) -> Optional[int]:
        return self._remaining_exec(None)

    def remaining_time(self) -> Optional[float]:
        return self._remaining_time(None)

    def remaining_output(self) -> Optional[int]:
        return self._remaining_output(None)

    # ── Internals ────────────────────────────────────────────────────────

    def _remaining_exec(self, requested: Optional[int]) -> Optional[int]:
        if self._parent.max_executions is None:
            return requested        # unlimited parent → grant the request
        remaining = self._parent.max_executions - self._allocated_exec
        if requested is not None and requested > remaining:
            raise BudgetAllocationError(
                "requested {} executions, only {} remain".format(
                    requested, remaining
                )
            )
        return remaining if requested is None else requested

    def _remaining_time(self, requested: Optional[float]) -> Optional[float]:
        if self._parent.max_wall_time is None:
            return requested        # unlimited parent → grant the request
        remaining = self._parent.max_wall_time - self._allocated_time
        if requested is not None and requested > remaining:
            raise BudgetAllocationError(
                "requested {}s wall time, only {}s remain".format(
                    requested, remaining
                )
            )
        return remaining if requested is None else requested

    def _remaining_output(self, requested: Optional[int]) -> Optional[int]:
        if self._parent.max_output_bytes is None:
            return requested        # unlimited parent → grant the request
        remaining = self._parent.max_output_bytes - self._allocated_output
        if requested is not None and requested > remaining:
            raise BudgetAllocationError(
                "requested {} output bytes, only {} remain".format(
                    requested, remaining
                )
            )
        return remaining if requested is None else requested

    def __repr__(self) -> str:
        return (
            "BudgetAllocator(allocated={} exec, {}s, {}B; "
            "remaining={})".format(
                self._allocated_exec,
                round(self._allocated_time, 2),
                self._allocated_output,
                self.remaining,
            )
        )

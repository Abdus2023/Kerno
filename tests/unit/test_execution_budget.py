"""
Unit tests for ExecutionBudget (audit #85) and BudgetedExecutor.
"""

import pytest

from kerno.execution.budget import (
    BudgetExceeded, BudgetTracker, BudgetedExecutor, ExecutionBudget,
)
from kerno.types import CellOutput


class FakeKernel:
    def __init__(self):
        self.calls = []

    def execute(self, code, timeout=120.0, silent=False):
        self.calls.append(code)
        if silent:
            return CellOutput(stdout="")
        return CellOutput(stdout="out:" + code)

    def execute_silent(self, code, timeout=15.0):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


class TestBudgetTracker:

    def test_tracks_usage(self):
        tracker = BudgetTracker(ExecutionBudget())
        tracker.record(duration_s=1.5, output_bytes=100)
        tracker.record(duration_s=0.5, output_bytes=50)
        snap = tracker.snapshot
        assert snap.executions == 2
        assert snap.wall_time_s == 2.0
        assert snap.output_bytes == 150

    def test_max_executions_enforced(self):
        tracker = BudgetTracker(ExecutionBudget(max_executions=2))
        tracker.check_can_start()
        tracker.record(0.1, 10)
        tracker.check_can_start()
        tracker.record(0.1, 10)
        with pytest.raises(BudgetExceeded, match="max_executions"):
            tracker.check_can_start()

    def test_max_wall_time_enforced(self):
        tracker = BudgetTracker(ExecutionBudget(max_wall_time=1.0))
        tracker.record(duration_s=0.6, output_bytes=10)
        with pytest.raises(BudgetExceeded, match="max_wall_time"):
            tracker.record(duration_s=0.6, output_bytes=10)

    def test_max_output_enforced(self):
        tracker = BudgetTracker(ExecutionBudget(max_output_bytes=100))
        tracker.record(0.1, 60)
        with pytest.raises(BudgetExceeded, match="max_output_bytes"):
            tracker.record(0.1, 60)

    def test_exhausted_property(self):
        tracker = BudgetTracker(ExecutionBudget(max_executions=1))
        assert tracker.exhausted is False
        tracker.record(0.1, 1)
        assert tracker.exhausted is True


class TestBudgetedExecutor:

    def test_forwards_to_underlying(self):
        kernel = FakeKernel()
        ex = BudgetedExecutor(kernel, ExecutionBudget(max_executions=10))
        out = ex.execute("x = 1")
        assert not out.has_error
        assert out.stdout == "out:x = 1"
        assert kernel.calls == ["x = 1"]

    def test_refuses_when_budget_exhausted(self):
        kernel = FakeKernel()
        ex = BudgetedExecutor(kernel, ExecutionBudget(max_executions=1))

        out1 = ex.execute("x = 1")
        assert not out1.has_error
        assert len(kernel.calls) == 1

        out2 = ex.execute("y = 2")
        assert out2.has_error
        assert out2.error.ename == "BudgetExceeded"
        # The kernel must never see the refused execution
        assert len(kernel.calls) == 1

    def test_wall_time_budget_blocks_next(self):
        kernel = FakeKernel()
        # Any real execution exceeds a zero wall-time budget
        ex = BudgetedExecutor(kernel, ExecutionBudget(max_wall_time=0.0))

        ex.execute("x = 1")          # completes (recorded, over budget)
        out = ex.execute("y = 2")    # refused
        assert out.has_error
        assert out.error.ename == "BudgetExceeded"
        assert "max_wall_time" in out.error.evalue
        assert len(kernel.calls) == 1

    def test_tracker_visible_through_wrapper(self):
        kernel = FakeKernel()
        ex = BudgetedExecutor(kernel, ExecutionBudget(max_executions=5))
        ex.execute("x = 1")
        ex.execute("y = 2")
        assert ex.tracker.snapshot.executions == 2
        assert ex.tracker.snapshot.output_bytes > 0

    def test_executor_protocol(self):
        ex = BudgetedExecutor(FakeKernel(), ExecutionBudget())
        assert ex.is_alive is True
        assert ex.namespace == "{}"
        assert ex.execute_silent("x = 1") == ""

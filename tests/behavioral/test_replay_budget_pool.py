"""
Behavioral tests for replay, budgets, and the kernel pool scheduler.

Real kernels:
    - replay_session re-executes a recorded session WITHOUT the LLM
    - run() with an ExecutionBudget enforces cell limits end-to-end
    - KernelPool.health_check / restart / interrupt
"""

import pytest

from kerno import run
from kerno.execution.budget import ExecutionBudget
from kerno.execution.modes import replay_session
from kerno.kernel.pool import KernelPool
from kerno.security.allowlist import AllowList
from kerno.types import Message


def make_llm(*responses):
    responses = list(responses)
    state = {"i": 0}

    def llm(messages: list[Message]) -> str:
        i = state["i"]
        state["i"] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: mock done"

    return llm


@pytest.mark.integration
class TestReplaySession:

    def test_replay_without_llm_matches_deterministic_outputs(self):
        # Record a session with a mock LLM
        original = run(
            "Compute values",
            llm=make_llm(
                "x = 21\nprint('x =', x)",
                "y = x * 2\nprint('y =', y)",
                "# TASK_COMPLETE: computed",
            ),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
            load_default_skills=False,   # replay is the subject
        )
        assert original.status.name in ("COMPLETE", "MAX_CELLS")
        assert original.cells_executed >= 2

        # Replay on a FRESH kernel — no LLM involved
        from kerno.kernel.runtime import KernelRuntime
        with KernelRuntime() as kernel:
            replayed = replay_session(
                original, kernel, allowlist=AllowList.data_analysis()
            )

        assert replayed.status.name == "COMPLETE"
        assert len(replayed.cells) == len(original.cells)
        # Deterministic cells reproduce identical stdout
        assert replayed.cells[0].output.stdout == original.cells[0].output.stdout
        assert "y = 42" in replayed.cells[1].output.stdout

    def test_replay_reapplies_allowlist(self):
        original = run(
            "Attempt",
            llm=make_llm("import subprocess", "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            max_cells=3,
            load_default_skills=False,
        )
        assert any(
            c.output.has_error and c.output.error.ename == "AllowListViolation"
            for c in original.cells
        )

        from kerno.kernel.runtime import KernelRuntime
        with KernelRuntime() as kernel:
            replayed = replay_session(
                original, kernel, allowlist=AllowList.data_analysis()
            )

        # The violating cell is blocked AGAIN during replay
        blocked = [
            c for c in replayed.cells if c.output.has_error
            and c.output.error.ename == "AllowListViolation"
        ]
        assert blocked, "replay must re-enforce the allowlist"
        assert replayed.status.name == "ERROR_UNHANDLED"


@pytest.mark.integration
class TestRunBudget:

    def test_budget_limits_cells(self):
        # An LLM that never signals completion, so the loop would run
        # forever without the budget.
        def never_done(messages):
            return "x = 1"

        result = run(
            "Keep going",
            llm=never_done,
            budget=ExecutionBudget(max_executions=3),
            max_cells=6,
        )
        assert sum(
            1 for c in result.cells
            if not c.output.has_error
        ) == 3, "budget must cap successful executions at 3"
        assert any(
            c.output.has_error and c.output.error.ename == "BudgetExceeded"
            for c in result.cells
        ), "the over-budget attempt must surface as BudgetExceeded"

    def test_unlimited_budget_runs_normally(self):
        result = run(
            "Compute",
            llm=make_llm("print(2 + 2)", "# TASK_COMPLETE: done"),
            max_cells=5,
        )
        assert result.cells_executed >= 2
        assert all(not c.output.has_error for c in result.cells)


@pytest.mark.integration
class TestKernelPoolScheduler:

    def test_health_check_reports_all_kernels(self):
        with KernelPool(size=2, overflow=False) as pool:
            report = pool.health_check()
            assert len(report) == 2
            for kernel_id, info in report.items():
                assert info["alive"] is True
                assert info["state"] in ("AVAILABLE", "ACQUIRED")
                assert info["generation"] == 1
                assert "task_id" in info

    def test_restart_in_place_increments_generation(self):
        with KernelPool(size=1, overflow=False) as pool:
            kernel = pool.acquire("task-A")
            kernel.execute("x = 42", timeout=20)
            assert pool.health_check()["k-0001"]["generation"] == 1

            fresh = pool.restart("task-A")

            # Same runtime object (task's reference keeps working),
            # but the kernel process restarted and generation incremented.
            assert fresh is kernel
            assert kernel.generation == 2

            # Namespace was reset
            out = kernel.execute("print(x)", timeout=20)
            assert out.has_error

            pool.release("task-A", reason="complete")

    def test_interrupt_acquired_kernel(self):
        with KernelPool(size=1, overflow=False) as pool:
            kernel = pool.acquire("task-B")
            pool.interrupt("task-B")
            # Kernel still usable after interrupt
            out = kernel.execute("print('alive')", timeout=20)
            assert not out.has_error
            pool.release("task-B", reason="complete")

    def test_restart_unknown_task_raises(self):
        with KernelPool(size=1, overflow=False) as pool:
            try:
                pool.restart("ghost")
                assert False, "expected ValueError"
            except ValueError:
                pass


    def test_pool_soak_sequential_recycling(self):
        """Audit #81/#82: sequential acquisition, execution, and release across tasks."""
        with KernelPool(size=2, overflow=False) as pool:
            for i in range(5):
                task_id = f"soak-task-{i}"
                kernel = pool.acquire(task_id)
                out = kernel.execute(f"val_{i} = {i}\nprint(val_{i})", timeout=20)
                assert not out.has_error
                assert f"{i}" in out.stdout
                pool.release(task_id, reason="complete")

            # Check stats — release() resets kernels asynchronously, so
            # wait for both kernels to return to the available queue.
            import time
            deadline = time.monotonic() + 15.0
            stats = pool.stats
            while (
                time.monotonic() < deadline
                and not (stats["available"] == 2 and stats["active"] == 0)
            ):
                time.sleep(0.2)
                stats = pool.stats
            assert stats["total"] == 2
            assert stats["active"] == 0
            assert stats["available"] == 2

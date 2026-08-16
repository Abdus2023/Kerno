"""
Behavioral tests for first-class cancellation (audit #83) on real kernels:

    User cancel → agent → action → kernel interrupt → INTERRUPTED
"""

import threading
import time

import pytest

from kerno import CancellationToken, run
from kerno.security.allowlist import AllowList
from kerno.types import Message, SessionStatus


def make_llm(*responses):
    responses = list(responses)
    state = {"i": 0}

    def llm(messages: list[Message]) -> str:
        i = state["i"]
        state["i"] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: done"

    return llm


@pytest.mark.integration
class TestCancellation:

    def test_mid_cell_cancel_interrupts_hung_kernel(self):
        from kerno.execution.engine import ExecutionEngine
        from kerno.kernel.runtime import KernelRuntime
        from kerno.loop.reactive import ReactiveLoop

        kernel = KernelRuntime()
        kernel.start()
        try:
            engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
            token  = CancellationToken()

            def canceller():
                time.sleep(1.0)          # cell is already running
                token.cancel()

            threading.Thread(target=canceller, daemon=True).start()

            start = time.monotonic()
            loop = ReactiveLoop(
                kernel=engine, llm=make_llm(
                    "x = 0\nwhile True: x += 1",               # hangs (no imports)
                    "print('never reached')",
                    "# TASK_COMPLETE: done",
                ),
                max_cells=5,
            )
            result = loop.run("Long computation", cancel_token=token)
            elapsed = time.monotonic() - start

            # The session ended INTERRUPTED, not MAX_CELLS/COMPLETE
            assert result.status == SessionStatus.INTERRUPTED
            # The hung cell was terminated mid-flight
            assert result.cells[0].output.has_error
            assert result.cells[0].output.error.ename == "KernelInterrupted"
            # Cancellation is fast — no waiting for the 120s cell timeout
            assert elapsed < 30, f"cancellation took too long: {elapsed:.1f}s"
            # The kernel survived the interrupt and is usable
            assert kernel.is_alive
            out = kernel.execute("print('alive')", timeout=20)
            assert not out.has_error
        finally:
            kernel.shutdown()

    def test_pre_cancelled_token_stops_immediately(self):
        token = CancellationToken()
        token.cancel()

        result = run(
            "Never started",
            llm=make_llm("x = 1"),
            max_cells=5,
            cancel_token=token,
            load_default_skills=False,
        )

        assert result.status == SessionStatus.INTERRUPTED
        assert result.cells_executed == 0

    def test_unused_token_runs_normally(self):
        token = CancellationToken()          # never cancelled
        result = run(
            "Normal run",
            llm=make_llm("print(2 + 2)", "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
            cancel_token=token,
        )
        assert result.status == SessionStatus.COMPLETE
        assert result.cells_executed >= 2

    def test_execution_ids_and_blocked_rules_attached(self):
        """Audit #78: the result carries its execution ledger."""
        result = run(
            "Attempt",
            llm=make_llm("import subprocess", "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
            load_default_skills=False,
        )
        # Every cell produced an execution record
        assert len(result.execution_ids) == result.cells_executed
        assert result.execution_ids[0].startswith("exec_")
        assert result.execution_ids == sorted(result.execution_ids)
        # The blocked cell's rule is surfaced
        assert "subprocess" in result.blocked_rules


@pytest.mark.integration
class TestCancellationAllLoops:
    """Audit #83: cancellation works for EVERY loop strategy."""

    def test_hierarchical_loop_cancelled(self):
        token = CancellationToken()
        token.cancel()

        planner = make_llm(
            '[{"id": 1, "description": "Compute x", "depends_on": []}]',
            '{"success": true, "summary": "done", "unexpected": null}',
            "Done.",
        )
        result = run(
            "Analyze",
            llm=make_llm("x = 1\nprint(x)", "# SUBTASK_COMPLETE: done"),
            loop="hierarchical",
            planner_llm=planner,
            cancel_token=token,
            max_cells=5,
            load_default_skills=False,
        )
        assert result.status == SessionStatus.INTERRUPTED

    def test_debate_loop_cancelled(self):
        token = CancellationToken()
        token.cancel()

        result = run(
            "Is X true?",
            llm=make_llm("print('arg')"),
            loop="debate",
            position="X is true",
            n_rounds=2,
            cancel_token=token,
            max_cells=5,
            load_default_skills=False,
        )
        assert result.status == SessionStatus.INTERRUPTED

    def test_multi_agent_loop_cancelled(self):
        from kerno.loop.multi_agent import AgentRole

        token = CancellationToken()
        token.cancel()
        role = AgentRole(
            name="analyst", llm=make_llm("x = 1"),
            system="You are an analyst.",
            yield_signal="# TASK_COMPLETE",
            writes=["results_"],
        )
        result = run(
            "Analyze",
            llm=make_llm(),
            loop="multi_agent",
            roles=[role],
            cancel_token=token,
            max_cells=5,
            load_default_skills=False,
        )
        assert result.status == SessionStatus.INTERRUPTED

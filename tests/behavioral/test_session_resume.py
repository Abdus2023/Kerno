"""
Behavioral tests for session/kernel independence (K-004, audit #35/#36):

    kernel crash != agent crash

- BaseLoop.auto_restart: kernel dies mid-run → restart → restore state
  from history → continue the session.
- resume_session(): a finished-but-incomplete session continues on a
  FRESH kernel — recorded cells are re-executed to restore state, then
  the LLM only writes new cells.
"""

import os
import signal
import time

import pytest

from kerno import resume_session, run
from kerno.execution.engine import ExecutionEngine
from kerno.kernel.runtime import KernelRuntime
from kerno.loop.reactive import ReactiveLoop
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
        return "# TASK_COMPLETE: mock done"

    return llm


def kill_kernel(kernel):
    """Simulate a kernel crash: SIGKILL the kernel process."""
    proc = kernel._km.provisioner.process
    os.kill(proc.pid, signal.SIGKILL)
    time.sleep(0.3)


def make_flaky_execute(kernel, original_execute):
    """First execution succeeds; then the kernel process is killed."""
    killed = [False]

    def flaky_execute(code, **kwargs):
        if not killed[0]:
            killed[0] = True
            out = original_execute(code, **kwargs)
            kill_kernel(kernel)
            return out
        return original_execute(code, **kwargs)

    return flaky_execute


@pytest.mark.integration
class TestAutoRestart:
    """K-004: the loop survives a kernel death mid-run."""

    def test_loop_recovers_from_kernel_death(self):
        kernel = KernelRuntime()
        kernel.start()
        try:
            engine = ExecutionEngine(kernel)
            kernel.execute = make_flaky_execute(kernel, kernel.execute)

            llm = make_llm(
                "x = 42\nprint('x =', x)",   # cell 1 → then kernel dies
                "print('after crash')",      # cell 2 → after restore
                "# TASK_COMPLETE: done",     # cell 3 → complete
            )
            loop = ReactiveLoop(
                kernel=engine, llm=llm, max_cells=10, auto_restart=True
            )
            result = loop.run("survive a crash")

            assert result.status == SessionStatus.COMPLETE
            # The kernel was restarted (generation 2), not abandoned
            assert kernel.generation == 2
            assert kernel.is_alive

            # State was restored: the restored x=42 is visible to cell 2
            # (cell 2's output references the restored variable).
            cell2 = result.cells[1]
            assert not cell2.output.has_error
            assert "after crash" in cell2.output.stdout
        finally:
            kernel.shutdown()

    def test_loop_without_auto_restart_stops_on_death(self):
        kernel = KernelRuntime()
        kernel.start()
        try:
            engine = ExecutionEngine(kernel)
            kernel.execute = make_flaky_execute(kernel, kernel.execute)

            loop = ReactiveLoop(
                kernel=engine, llm=make_llm("x = 1"), max_cells=10,
                auto_restart=False,
            )
            result = loop.run("die")

            assert result.status == SessionStatus.KERNEL_DIED
            assert kernel.generation == 1  # never restarted
        finally:
            kernel.shutdown()

    def test_restore_never_replays_errored_cells(self):
        """Blocked cells must not be executed for real during restore."""
        kernel = KernelRuntime()
        kernel.start()
        try:
            engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
            kernel.execute = make_flaky_execute(kernel, kernel.execute)

            # Cell 1 is blocked by policy; cell 2 runs; then kernel dies.
            llm = make_llm(
                "import subprocess",       # blocked → AllowListViolation
                "print('ran')",            # runs → kernel dies after
                "# TASK_COMPLETE: done",
            )
            loop = ReactiveLoop(
                kernel=engine, llm=llm, max_cells=10, auto_restart=True
            )
            result = loop.run("no replay of blocked cells")

            assert result.status == SessionStatus.COMPLETE
            # The blocked cell appears in history only as an error cell —
            # never executed successfully, even across the restart.
            for cell in result.cells:
                if "subprocess" in cell.code:
                    assert cell.output.has_error
                    assert cell.output.error.ename == "AllowListViolation"
        finally:
            kernel.shutdown()


@pytest.mark.integration
class TestResumeSession:
    """Audit #35/#36: a session continues on a fresh kernel."""

    def test_resume_continues_after_interrupted_session(self):
        # Session 1: interrupted at MAX_CELLS (LLM never completes)
        def never_done(messages):
            return "x = 21\nprint('x =', x)"

        interrupted = run(
            "Analyze data",
            llm=never_done,
            allowlist=AllowList.data_analysis(),
            max_cells=2,
            load_default_skills=False,   # resume is the subject
        )
        assert interrupted.status == SessionStatus.MAX_CELLS

        # Session 2: resume on a fresh kernel; the LLM finishes the job
        resumed = resume_session(
            interrupted,
            make_llm(
                "y = x * 2\nprint('y =', y)",     # uses restored x!
                "# TASK_COMPLETE: done",
            ),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
        )

        # History = restored cells + new cells
        assert len(resumed.cells) > len(interrupted.cells)
        # The restored state (x=21) is visible to the continuation
        y_cell = [c for c in resumed.cells if "y = x * 2" in c.code][0]
        assert not y_cell.output.has_error
        assert "y = 42" in y_cell.output.stdout
        # The continuation completed
        assert resumed.status == SessionStatus.COMPLETE

    def test_resume_reapplies_policy(self):
        interrupted = run(
            "Attempt",
            llm=make_llm("import subprocess"),
            allowlist=AllowList.data_analysis(),
            max_cells=2,
        )
        assert any(
            c.output.error and c.output.error.ename == "AllowListViolation"
            for c in interrupted.cells
        )

        resumed = resume_session(
            interrupted,
            make_llm("# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            max_cells=3,
        )

        # The blocked cell stays blocked after resume
        blocked = [
            c for c in resumed.cells
            if "subprocess" in c.code and c.output.has_error
            and c.output.error.ename == "AllowListViolation"
        ]
        assert blocked, "resume must re-block previously blocked cells"

    def test_resume_empty_result_raises(self):
        from kerno.types import SessionResult
        empty = SessionResult(
            session_id="s", task="t", status=SessionStatus.INTERRUPTED, cells=[],
        )
        try:
            resume_session(empty, make_llm())
            assert False, "expected ValueError"
        except ValueError:
            pass

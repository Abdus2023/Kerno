"""
Fault injection on real kernels (audit #72): the runtime must survive
deliberate failures — kill kernel, fail execution, timeout escalation —
and the invariants (P1-P10) must hold afterwards.
"""

import pytest

from kerno.execution.engine import ExecutionEngine
from kerno.faults import FaultInjector
from kerno.invariants import (
    check_denied_never_started, check_generation_monotonic,
    check_monotonic_sequence, check_session_recovered, check_terminal_events,
)
from kerno.kernel.runtime import KernelRuntime
from kerno.loop.reactive import ReactiveLoop
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
class TestKillRecovery:
    """Kernel SIGKILL mid-session → auto-restart → restore → complete."""

    def test_session_survives_kernel_kill(self):
        kernel = KernelRuntime()
        kernel.start()
        try:
            injector = FaultInjector(kernel).kill_after(1)
            engine   = ExecutionEngine(injector)
            loop = ReactiveLoop(
                kernel=engine, llm=make_llm(
                    "x = 42\nprint('x =', x)",       # cell 1 → kernel killed after
                    "print('after crash', x)",       # cell 2 → restored state
                    "# TASK_COMPLETE: done",         # cell 3 → complete
                ),
                max_cells=10, auto_restart=True,
            )
            result = loop.run("survive injected kill")

            assert result.status == SessionStatus.COMPLETE
            assert injector.kill_count == 1
            # Kernel was restarted (generation 2), not abandoned
            assert injector.generation == 2
            assert kernel.is_alive

            # Restored state: x=42 visible to the post-crash cell
            cell2 = result.cells[1]
            assert not cell2.output.has_error
            assert "after crash 42" in cell2.output.stdout

            # Invariants hold after the recovery (P5, P8, P9)
            check_monotonic_sequence(engine.events)
            check_generation_monotonic([1, kernel.generation])
            check_session_recovered(result.status, [1, 2], auto_restart=True)
            check_terminal_events(engine.events)
            check_denied_never_started(engine.events)
        finally:
            kernel.shutdown()

    def test_fail_next_recovers_via_llm(self):
        kernel = KernelRuntime()
        kernel.start()
        try:
            injector = FaultInjector(kernel).fail_next(1)
            engine   = ExecutionEngine(injector)
            loop = ReactiveLoop(
                kernel=engine, llm=make_llm(
                    "x = 1",                          # cell 1 → injected failure
                    "x = 2\nprint('retried')",        # cell 2 → recovery
                    "# TASK_COMPLETE: done",
                ),
                max_cells=10,
            )
            result = loop.run("recover from injected failure")

            assert result.status == SessionStatus.COMPLETE
            # The injected failure appears in history as an error cell
            assert any(
                c.output.has_error and c.output.error.ename == "InjectedFailure"
                for c in result.cells
            )
            # The recovery cell ran and completed
            assert any(
                not c.output.has_error and "retried" in c.output.stdout
                for c in result.cells
            )
            # Kernel untouched by this fault
            assert kernel.generation == 1
            check_monotonic_sequence(engine.events)
            check_terminal_events(engine.events)
        finally:
            kernel.shutdown()


@pytest.mark.integration
class TestTimeoutEscalation:
    """Audit #84: soft interrupt → grace → hard kill → restart."""

    def test_escalate_policy_restarts_stuck_kernel(self):
        kernel = KernelRuntime(timeout_policy="escalate")
        kernel.start()
        try:
            # A cell that never finishes
            out = kernel.execute(
                "import time\nwhile True: time.sleep(1)",
                timeout=3,
            )
            assert out.has_error
            assert out.error.ename == "TimeoutError"

            # Escalation restarted the kernel (generation 2), which is
            # now alive and usable
            assert kernel.generation == 2
            assert kernel.is_alive
            assert kernel.state.name == "READY"

            out2 = kernel.execute("print('alive again')", timeout=20)
            assert not out2.has_error
            assert "alive again" in out2.stdout
        finally:
            kernel.shutdown()

    def test_default_interrupt_policy_does_not_restart(self):
        kernel = KernelRuntime(timeout_policy="interrupt")
        kernel.start()
        try:
            out = kernel.execute("import time\ntime.sleep(60)", timeout=2)
            assert out.has_error
            assert out.error.ename == "TimeoutError"
            # Default policy: interrupt only, no restart
            assert kernel.generation == 1
        finally:
            kernel.shutdown()

    def test_invalid_policy_rejected(self):
        with pytest.raises(ValueError, match="timeout_policy"):
            KernelRuntime(timeout_policy="nuke")

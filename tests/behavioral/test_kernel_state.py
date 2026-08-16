"""
Behavioral tests for KernelRuntime health state + generation (audit #53, #54).

A real kernel is started for each test; we verify the observable state
machine and that restart increments the generation counter.
"""

import pytest

from kerno.kernel.runtime import KernelRuntime
from kerno.kernel.state import KernelRuntimeState


@pytest.mark.integration
class TestKernelState:

    def test_lifecycle_states(self):
        kernel = KernelRuntime()
        assert kernel.state == KernelRuntimeState.CLOSED

        kernel.start()
        try:
            assert kernel.state == KernelRuntimeState.READY
            assert kernel.generation == 1

            # Execution returns the kernel to READY
            out = kernel.execute("x = 1\nprint(x)", timeout=20)
            assert not out.has_error
            assert kernel.state == KernelRuntimeState.READY

            # Busy is observable during execution
            kernel.execute(
                "import time; time.sleep(1)", timeout=20
            )
            assert kernel.state == KernelRuntimeState.READY
        finally:
            kernel.shutdown()

        assert kernel.state == KernelRuntimeState.CLOSED
        assert kernel.is_alive is False

    def test_busy_state_during_execution(self):
        kernel = KernelRuntime()
        kernel.start()
        try:
            # Long-running cell: state must read BUSY while it runs
            from threading import Thread

            observed: list = []

            def run_long():
                kernel.execute(
                    "import time; time.sleep(2)", timeout=30
                )

            t = Thread(target=run_long)
            t.start()
            t.join(timeout=1.0)
            observed.append(kernel.state)
            t.join(timeout=5.0)

            assert KernelRuntimeState.BUSY in observed
            assert kernel.state == KernelRuntimeState.READY
        finally:
            kernel.shutdown()

    def test_restart_increments_generation_and_resets_cells(self):
        kernel = KernelRuntime()
        kernel.start()
        try:
            kernel.execute("x = 42", timeout=20)
            assert kernel.cells_executed == 1

            kernel.restart()

            assert kernel.generation == 2
            assert kernel.state == KernelRuntimeState.READY
            assert kernel.cells_executed == 0

            # Namespace was reset by the restart
            out = kernel.execute("print(x)", timeout=20)
            assert out.has_error  # x no longer exists
        finally:
            kernel.shutdown()

    def test_interrupt_returns_to_ready(self):
        kernel = KernelRuntime()
        kernel.start()
        try:
            kernel.interrupt()
            assert kernel.state == KernelRuntimeState.READY
            # Kernel still usable after interrupt
            out = kernel.execute("print('alive')", timeout=20)
            assert not out.has_error
        finally:
            kernel.shutdown()


@pytest.mark.integration
class TestStickyDeadState:

    def test_killed_kernel_state_is_sticky_dead(self):
        import os
        import signal
        import time

        kernel = KernelRuntime()
        kernel.start()
        try:
            assert kernel.state == KernelRuntimeState.READY

            # SIGKILL the kernel process (real crash)
            proc = kernel._km.provisioner.process
            os.kill(proc.pid, signal.SIGKILL)
            time.sleep(0.3)

            # First read detects DEAD and caches it
            assert kernel.state == KernelRuntimeState.DEAD

            # The state must STAY DEAD on subsequent reads — never
            # bouncing back to READY (audit #53 health state)
            for _ in range(3):
                assert kernel.state == KernelRuntimeState.DEAD

            # A dead kernel refuses execution
            try:
                kernel.execute("x = 1", timeout=5)
                assert False, "expected RuntimeError on dead kernel"
            except RuntimeError:
                pass

            # restart() clears the sticky death and brings it back
            kernel.restart()
            assert kernel.state == KernelRuntimeState.READY
            assert kernel.generation == 2
            out = kernel.execute("print('alive')", timeout=15)
            assert not out.has_error
        finally:
            kernel.shutdown()

"""
Unit tests for the FaultInjector (audit #72) with a fake executor.
"""

from kerno.faults import FaultInjector
from kerno.types import CellOutput


class FakeProc:
    def poll(self):
        return None

    def kill(self):
        pass

    def wait(self, timeout=None):
        return None

class FakeKm:
    provisioner = type("Prov", (), {"process": FakeProc()})()

class FakeKernel:
    def __init__(self):
        self.calls = []
        self.alive = True
        self._km = FakeKm()

    def execute(self, code, timeout=120.0, silent=False):
        self.calls.append(code)
        if silent:
            return CellOutput(stdout="")
        return CellOutput(stdout="ran")

    def execute_silent(self, code, timeout=15.0):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return self.alive

    @property
    def generation(self):
        return 1


class TestFaultInjector:

    def test_passthrough_by_default(self):
        kernel = FakeKernel()
        inj = FaultInjector(kernel)
        out = inj.execute("x = 1")
        assert not out.has_error
        assert out.stdout == "ran"
        assert kernel.calls == ["x = 1"]

    def test_fail_next_injects_error_cells(self):
        kernel = FakeKernel()
        inj = FaultInjector(kernel).fail_next(2)

        o1 = inj.execute("a")
        o2 = inj.execute("b")
        o3 = inj.execute("c")

        assert o1.has_error and o1.error.ename == "InjectedFailure"
        assert o2.has_error and o2.error.ename == "InjectedFailure"
        assert not o3.has_error
        # Only the injected calls never reached the kernel... wait:
        # fail_next returns early — kernel never sees a, b
        assert kernel.calls == ["c"]

    def test_kill_after_fires_after_triggering_execution(self):
        kernel = FakeKernel()
        inj = FaultInjector(kernel).kill_after(2)

        inj.execute("a")     # call 1
        inj.execute("b")     # call 2 → kernel killed after
        assert inj.kill_count == 1
        assert inj._kill_at is None
        assert inj.calls == 2

    def test_executor_protocol_passthrough(self):
        kernel = FakeKernel()
        inj = FaultInjector(kernel)
        assert inj.namespace == "{}"
        assert inj.is_alive is True
        assert inj.generation == 1
        assert inj.execute_silent("x") == ""  # silent → no stdout

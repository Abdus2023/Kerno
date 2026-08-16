"""
Unit tests for distributed execution (audit #104) — controller routes to
workers; the agent abstraction never depends on the execution location.
"""

import time

from kerno.distributed import DistributedExecutor, WorkerPool
from kerno.executors import ScriptedExecutor
from kerno.types import CellOutput


class FakeExecutor:
    """Slow-ish deterministic executor that records its worker."""

    def __init__(self, worker_id):
        self.worker_id = worker_id
        self.calls = []

    def execute(self, code, timeout=120.0, silent=False, **kwargs):
        self.calls.append(code)
        return CellOutput(stdout="[{}] {}".format(self.worker_id, code))

    def execute_silent(self, code, timeout=15.0, **kwargs):
        return self.execute(code, timeout=timeout, silent=True).stdout.strip()

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


class TestWorkerPool:

    def test_distributes_round_robin(self):
        workers = []
        def factory():
            w = FakeExecutor("w{}".format(len(workers)))
            workers.append(w)
            return w

        with WorkerPool(factory, n=3) as pool:
            ex = DistributedExecutor(pool)
            out1 = ex.execute("a")
            out2 = ex.execute("b")
            out3 = ex.execute("c")
            out4 = ex.execute("d")

        assert out1.stdout.startswith("[w0]")
        assert out2.stdout.startswith("[w1]")
        assert out3.stdout.startswith("[w2]")
        assert out4.stdout.startswith("[w0]")    # wrapped around
        assert pool.total_served == 4
        # Each worker executed its share
        assert [w.calls for w in workers] == [["a", "d"], ["b"], ["c"]]

    def test_error_surfaces(self):
        def bad(kernel):
            raise RuntimeError("worker blew up")

        class BoomExecutor:
            def execute(self, code, timeout=120.0, silent=False, **kwargs):
                raise RuntimeError("worker blew up")

            def execute_silent(self, code, timeout=15.0, **kwargs):
                return ""

            @property
            def namespace(self):
                return "{}"

            @property
            def is_alive(self):
                return True

        with WorkerPool(lambda: BoomExecutor(), n=1) as pool:
            ex = DistributedExecutor(pool)
            out = ex.execute("x = 1")
        assert out.has_error
        assert out.error.ename == "DistributedError"
        assert "worker blew up" in out.error.evalue

    def test_execution_id_correlated(self):
        with WorkerPool(lambda: FakeExecutor("w0"), n=1) as pool:
            ex = DistributedExecutor(pool)
            out = ex.execute("x = 1")
        assert out.execution_id.startswith("req_")

    def test_cancel_event_interrupts_wait(self):
        from kerno.cancel import CancellationToken
        from kerno.kernel.output import CellOutput as CO

        class SlowExecutor:
            def execute(self, code, timeout=120.0, silent=False, **kwargs):
                time.sleep(10)
                return CO(stdout="late")

            def execute_silent(self, code, timeout=15.0, **kwargs):
                return ""

            @property
            def namespace(self):
                return "{}"

            @property
            def is_alive(self):
                return True

        token = CancellationToken()
        with WorkerPool(lambda: SlowExecutor(), n=1) as pool:
            ex = DistributedExecutor(pool)
            start = time.monotonic()
            t = threading_timer(token)
            out = ex.execute("slow", cancel_event=token)
            elapsed = time.monotonic() - start

        assert out.has_error
        assert elapsed < 5
        t.join()


def threading_timer(token):
    import threading
    def cancel():
        time.sleep(0.2)
        token.cancel()
    t = threading.Thread(target=cancel)
    t.start()
    return t


class TestDistributedProtocol:

    def test_executor_protocol(self):
        with WorkerPool(lambda: FakeExecutor("w0"), n=1) as pool:
            ex = DistributedExecutor(pool)
            assert ex.is_alive is True
            assert ex.namespace == "{}"
            assert ex.execute_silent("s") == "[w0] s"


class TestRemoteWorker:
    """Audit #104: Remote worker execution across network boundaries."""

    def test_remote_worker_initialization(self):
        from kerno.distributed import RemoteWorker

        worker = RemoteWorker("rw-1", "http://localhost:8001", auth_token="test-secret")
        assert worker.worker_id == "rw-1"
        assert worker.endpoint == "http://localhost:8001"
        assert worker.auth_token == "test-secret"
        assert worker.is_alive is True
        assert worker.served == 0
        worker.shutdown()
        assert worker.is_alive is False

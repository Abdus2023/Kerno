"""
Unit tests for TaskScheduler (audit #81/#82) with a fake pool.
"""

import threading
import time

from kerno.scheduler import TaskScheduler, TaskStatus


class FakePool:
    """Mimics the KernelPool acquire/release contract."""

    def __init__(self, size=2):
        self.size = size
        self.acquired = 0
        self.active_peak = 0
        self.releases = 0
        self._lock = threading.Lock()

    def acquire(self, task_id):
        with self._lock:
            self.acquired += 1
            self.active_peak = max(self.active_peak, self.acquired)
        return object()          # a dummy kernel

    def release(self, task_id, reason="complete"):
        with self._lock:
            self.acquired -= 1
            self.releases += 1


def make_fn(log, label, delay=0.0):
    def fn(kernel):
        log.append(("start", label, time.time()))
        if delay:
            time.sleep(delay)
        log.append(("end", label, time.time()))
        return label.upper()
    return fn


class TestTaskScheduler:

    def test_runs_all_tasks(self):
        pool = FakePool(size=2)
        sched = TaskScheduler(pool, max_concurrency=2)
        for i in range(3):
            sched.submit(f"t{i}", make_fn([], f"t{i}"))

        tasks = sched.run_all()

        assert all(t.status == TaskStatus.COMPLETE for t in tasks)
        assert [t.result for t in tasks] == ["T0", "T1", "T2"]
        assert sched.summary()["total"] == 3
        assert sched.summary()["COMPLETE"] == 3

    def test_priority_order(self):
        pool = FakePool(size=1)      # serial → order is deterministic
        sched = TaskScheduler(pool, max_concurrency=1)
        log = []
        sched.submit("low",  make_fn(log, "low"),  priority=1)
        sched.submit("high", make_fn(log, "high"), priority=10)
        sched.submit("mid",  make_fn(log, "mid"),  priority=5)

        sched.run_all()

        order = [label for kind, label, _ in log if kind == "start"]
        assert order == ["high", "mid", "low"]

    def test_concurrency_capped(self):
        pool = FakePool(size=2)
        sched = TaskScheduler(pool, max_concurrency=2)
        log = []
        for i in range(4):
            sched.submit(f"t{i}", make_fn(log, f"t{i}", delay=0.2))

        sched.run_all()

        assert pool.active_peak <= 2, "concurrency must never exceed the cap"
        assert pool.releases == 4

    def test_cancel_pending_task(self):
        pool = FakePool(size=2)
        sched = TaskScheduler(pool, max_concurrency=2)
        sched.submit("keep", make_fn([], "keep"))
        sched.submit("drop", make_fn([], "drop"))

        assert sched.cancel("drop") is True
        tasks = sched.run_all()

        by_id = {t.task_id: t for t in tasks}
        assert by_id["keep"].status == TaskStatus.COMPLETE
        assert by_id["drop"].status == TaskStatus.CANCELLED
        assert pool.releases == 1        # cancelled tasks never acquired

    def test_cancel_pending_all(self):
        pool = FakePool(size=2)
        sched = TaskScheduler(pool, max_concurrency=2)
        sched.submit("a", make_fn([], "a"))
        sched.submit("b", make_fn([], "b"))
        assert sched.cancel_pending() == 2
        tasks = sched.run_all()
        assert all(t.status == TaskStatus.CANCELLED for t in tasks)

    def test_duplicate_task_id_rejected(self):
        pool = FakePool(size=1)
        sched = TaskScheduler(pool)
        sched.submit("t1", make_fn([], "t1"))
        try:
            sched.submit("t1", make_fn([], "dup"))
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_task_failure_recorded(self):
        pool = FakePool(size=1)
        sched = TaskScheduler(pool, max_concurrency=1)

        def boom(kernel):
            raise RuntimeError("kaboom")

        sched.submit("bad", boom)
        tasks = sched.run_all()
        assert tasks[0].status == TaskStatus.FAILED
        assert "kaboom" in tasks[0].error
        assert pool.releases == 1        # released even on failure

    def test_task_metadata(self):
        pool = FakePool(size=1)
        sched = TaskScheduler(pool, max_concurrency=1)
        sched.submit("t1", make_fn([], "t1"), priority=7)
        task = sched.task("t1")
        assert task.priority == 7
        assert task.duration is None    # not run yet
        d = task.to_dict()
        assert d["status"] == "PENDING"
        assert d["has_result"] is False

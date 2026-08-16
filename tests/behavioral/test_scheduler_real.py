"""
Behavioral tests for TaskScheduler over a REAL KernelPool (audit #81/#82).
"""

import threading
import time

import pytest

from kerno.kernel.pool import KernelPool
from kerno.scheduler import TaskScheduler, TaskStatus


@pytest.mark.integration
class TestSchedulerRealPool:

    def test_schedules_tasks_over_real_kernels(self):
        with KernelPool(size=2, overflow=False) as pool:
            sched = TaskScheduler(pool, max_concurrency=2)
            for i in range(3):
                sched.submit(
                    f"task-{i}",
                    lambda kernel, n=i: kernel.execute_silent(
                        f"print({n} * 2)", timeout=20
                    ),
                    priority=i,
                )

            tasks = sched.run_all()

            assert all(t.status == TaskStatus.COMPLETE for t in tasks)
            results = {t.task_id: t.result for t in tasks}
            assert results["task-0"] == "0"
            assert results["task-1"] == "2"
            assert results["task-2"] == "4"
            # Kernels were released (soft-reset re-queues asynchronously,
            # so assert on release state, not the async queue depth)
            assert pool.stats["active"] == 0
            assert pool.stats["total"] == 2

    def test_concurrency_never_exceeds_pool_size(self):
        with KernelPool(size=2, overflow=False) as pool:
            sched  = TaskScheduler(pool, max_concurrency=2)
            active = [0]
            peak   = [0]
            lock   = threading.Lock()

            def work(kernel, delay):
                with lock:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                time.sleep(delay)
                with lock:
                    active[0] -= 1
                return "ok"

            for i in range(4):
                sched.submit(f"w{i}", lambda k, d=0.3: work(k, d))

            sched.run_all()

            assert peak[0] <= 2, f"concurrency exceeded pool size: {peak[0]}"

    def test_cancelled_tasks_never_acquire_kernels(self):
        with KernelPool(size=1, overflow=False) as pool:
            sched = TaskScheduler(pool, max_concurrency=1)
            sched.submit("run", lambda k: k.execute_silent("x = 1", timeout=20))
            sched.submit("skip", lambda k: "should not run")

            assert sched.cancel("skip") is True
            tasks = sched.run_all()

            by_id = {t.task_id: t for t in tasks}
            assert by_id["run"].status == TaskStatus.COMPLETE
            assert by_id["skip"].status == TaskStatus.CANCELLED

    def test_failed_task_releases_kernel(self):
        with KernelPool(size=1, overflow=False) as pool:
            sched = TaskScheduler(pool, max_concurrency=1)

            def boom(kernel):
                raise RuntimeError("task exploded")

            sched.submit("bad", boom)
            sched.run_all()

            assert sched.task("bad").status == TaskStatus.FAILED
            assert "task exploded" in sched.task("bad").error
            # The kernel was released even though the task failed
            # (soft-reset re-queues asynchronously)
            assert pool.stats["active"] == 0

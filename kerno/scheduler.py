# kerno/scheduler.py
"""
TaskScheduler — priorities + concurrency over a KernelPool (audit #81/#82).

    Scheduler
    ├── pending queue (priority-ordered)
    ├── running executions (bounded concurrency)
    ├── cancellation of pending tasks
    └── per-task results + status

Each task is a callable taking the acquired kernel (an Executor): the
agent decides WHAT to do, the scheduler decides WHICH kernel, WHEN, and
under what concurrency. The agent never manages kernels directly.
"""

from __future__ import annotations

import heapq
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

from kerno.kernel.pool import KernelPool


class TaskStatus(Enum):
    PENDING   = auto()
    RUNNING   = auto()
    COMPLETE  = auto()
    FAILED    = auto()
    CANCELLED = auto()


@dataclass
class ScheduledTask:
    """One unit of scheduled work."""

    task_id:   str
    fn:        Callable          # fn(executor) -> result
    priority:  int   = 0         # higher runs first
    status:    TaskStatus = TaskStatus.PENDING
    result:    Any    = None
    error:     str    = ""
    submitted: float = field(default_factory=time.time)
    started:   Optional[float] = None
    finished:  Optional[float] = None

    @property
    def duration(self) -> Optional[float]:
        if self.started is None or self.finished is None:
            return None
        return self.finished - self.started

    def to_dict(self) -> dict:
        return {
            "task_id":   self.task_id,
            "priority":  self.priority,
            "status":    self.status.name,
            "error":     self.error,
            "duration":  self.duration,
            "has_result": self.result is not None,
        }


class TaskScheduler:
    """
    Priority-ordered, concurrency-bounded task execution over a pool.

    Usage:
        pool = KernelPool(size=2)
        sched = TaskScheduler(pool, max_concurrency=2)
        sched.submit("t1", fn, priority=5)
        sched.submit("t2", fn, priority=1)
        results = sched.run_all()   # blocks until all tasks finish
    """

    def __init__(
        self,
        pool:            KernelPool,
        max_concurrency: Optional[int] = None,
    ):
        self._pool          = pool
        self._max_concurrency = max_concurrency or max(1, pool.size)
        self._lock          = threading.Lock()
        self._tasks: dict[str, ScheduledTask] = {}
        self._queue: list[tuple[int, int, str]] = []   # (-priority, seq, task_id)
        self._seq           = 0

    # ── Submission ───────────────────────────────────────────────────────

    def submit(
        self,
        task_id:   Optional[str] = None,
        fn:        Optional[Callable] = None,
        priority:  int = 0,
    ) -> ScheduledTask:
        """
        Queue a task. If `fn` is omitted, a partial is returned for
        later completion (deferred style): submit("t1", priority=5)
        then scheduler.run_all() executes fns set via set_fn.
        """
        if task_id is None:
            task_id = "task-" + uuid.uuid4().hex[:8]
        with self._lock:
            if task_id in self._tasks:
                raise ValueError(f"task already submitted: {task_id}")
            task = ScheduledTask(task_id=task_id, fn=fn, priority=priority)
            self._tasks[task_id] = task
            self._seq += 1
            # heapq is a min-heap → negate priority so HIGHER runs first
            heapq.heappush(self._queue, (-priority, self._seq, task_id))
        return task

    def set_fn(self, task_id: str, fn: Callable) -> None:
        """Attach (or replace) the callable for a pending task."""
        with self._lock:
            self._tasks[task_id].fn = fn

    def cancel(self, task_id: str) -> bool:
        """Cancel a PENDING task (running tasks are not interrupted)."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != TaskStatus.PENDING:
                return False
            task.status = TaskStatus.CANCELLED
            return True

    def cancel_pending(self) -> int:
        """Cancel every pending task. Returns how many were cancelled."""
        count = 0
        with self._lock:
            for task in self._tasks.values():
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED
                    count += 1
        return count

    # ── Execution ────────────────────────────────────────────────────────

    def run_all(self) -> list[ScheduledTask]:
        """
        Execute all non-cancelled tasks, honoring priority order and the
        concurrency limit. Returns tasks in submission order.
        """
        with self._lock:
            pending = [
                task for task in self._tasks.values()
                if task.status == TaskStatus.PENDING
            ]
            pending.sort(key=lambda t: -t.priority)

        def run_one(task: ScheduledTask) -> None:
            with self._lock:
                if task.status == TaskStatus.CANCELLED:
                    return
                task.status = TaskStatus.RUNNING
                task.started = time.time()
            kernel = self._pool.acquire(task.task_id)
            try:
                task.result = task.fn(kernel)
                task.status = TaskStatus.COMPLETE
            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.error  = str(exc)[:300]
            finally:
                task.finished = time.time()
                self._pool.release(task.task_id, reason="complete")

        with ThreadPoolExecutor(max_workers=self._max_concurrency) as ex:
            futures = {ex.submit(run_one, t): t for t in pending}
            for future in futures:
                future.result()          # propagate nothing; errors land on tasks

        return list(self._tasks.values())

    # ── Views ────────────────────────────────────────────────────────────

    def task(self, task_id: str) -> Optional[ScheduledTask]:
        return self._tasks.get(task_id)

    @property
    def tasks(self) -> tuple[ScheduledTask, ...]:
        return tuple(self._tasks.values())

    def summary(self) -> dict:
        """Status counts for observability."""
        counts: dict[str, int] = {}
        for task in self._tasks.values():
            counts[task.status.name] = counts.get(task.status.name, 0) + 1
        return {
            "total":       len(self._tasks),
            "max_concurrency": self._max_concurrency,
            **counts,
        }

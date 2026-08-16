# kerno/distributed.py
"""
Distributed execution (audit #104): a controller routes executions to
workers; the agent abstraction never depends on where execution happens.

    Controller
        │
        ▼
    Scheduler
        │
        ├── Worker 1 → Kernel
        ├── Worker 2 → Kernel
        └── Worker 3 → Kernel

This module provides an in-process, thread-based implementation of the
worker pattern (a real remote-transport version would swap the channel
for ZMQ/HTTP). Each worker owns ONE executor (e.g. a KernelRuntime or
DockerExecutor) and processes execution requests off a queue.

    Controller:
        pool = WorkerPool(worker_factory, n=3)
        engine = DistributedExecutor(pool)   # Executor protocol
        out = engine.execute("x = 1")

The Executor protocol is preserved, so loops, budgets, and the
ExecutionEngine can use DistributedExecutor as their backend.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from kerno.types import CellOutput


@dataclass
class ExecutionRequest:
    """One unit of distributed work."""

    request_id: str
    code:       str
    timeout:    float            = 120.0
    silent:     bool             = False
    result:     Optional[CellOutput] = None
    error:      str              = ""
    done:       threading.Event  = field(default_factory=threading.Event)

    def set_result(self, output: CellOutput) -> None:
        self.result = output
        self.done.set()

    def set_error(self, message: str) -> None:
        self.error = message
        self.done.set()


class Worker:
    """One worker: owns an executor and serves execution requests."""

    def __init__(self, worker_id: str, executor: object):
        self.worker_id = worker_id
        self.executor  = executor
        self._queue: "queue.Queue[ExecutionRequest]" = queue.Queue()
        self._thread  = threading.Thread(target=self._loop, daemon=True,
                                         name=f"kerno-worker-{worker_id}")
        self._running = True
        self._served  = 0
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            try:
                request = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                request.set_result(self.executor.execute(
                    request.code, timeout=request.timeout, silent=request.silent,
                ))
            except Exception as exc:
                request.set_error("{}: {}".format(type(exc).__name__, str(exc)[:200]))
            self._served += 1

    def submit(self, request: ExecutionRequest) -> None:
        self._queue.put(request)

    def shutdown(self) -> None:
        self._running = False
        self._thread.join(timeout=3)

    @property
    def served(self) -> int:
        return self._served

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()


class WorkerPool:
    """A pool of workers; tasks are distributed round-robin."""

    def __init__(self, worker_factory, n: int = 3):
        self._workers = [
            Worker("w{}".format(i), worker_factory())
            for i in range(n)
        ]
        self._next = 0
        self._lock = threading.Lock()

    def submit(self, request: ExecutionRequest) -> None:
        with self._lock:
            worker = self._workers[self._next % len(self._workers)]
            self._next += 1
        worker.submit(request)

    def shutdown(self) -> None:
        for worker in self._workers:
            worker.shutdown()

    @property
    def workers(self) -> tuple[Worker, ...]:
        return tuple(self._workers)

    @property
    def total_served(self) -> int:
        return sum(w.served for w in self._workers)

    def __enter__(self) -> "WorkerPool":
        return self

    def __exit__(self, *args) -> None:
        self.shutdown()


class DistributedExecutor:
    """
    Executor protocol implementation over a WorkerPool.

    Usage:
        def factory():
            return make_executor("subprocess")   # or KernelRuntime, etc.
        with WorkerPool(factory, n=2) as pool:
            ex = DistributedExecutor(pool)
            out = ex.execute("print(1+1)")
    """

    def __init__(self, pool: WorkerPool, request_timeout: float = 300.0):
        self._pool     = pool
        self._timeout  = request_timeout

    def execute(
        self,
        code:         str,
        timeout:      float = 120.0,
        silent:       bool  = False,
        cancel_event: Optional[object] = None,
    ) -> CellOutput:
        request = ExecutionRequest(
            request_id = "req_" + uuid.uuid4().hex[:8],
            code       = code,
            timeout    = timeout,
            silent     = silent,
        )
        self._pool.submit(request)

        deadline = time.monotonic() + min(self._timeout, timeout + 10)
        while not request.done.is_set():
            if cancel_event is not None and cancel_event.is_set():
                request.set_error("cancelled")
                break
            if time.monotonic() > deadline:
                request.set_error("distributed timeout")
                break
            request.done.wait(timeout=0.25)

        if request.error:
            from kerno.types import CellError
            return CellOutput(
                error=CellError(ename="DistributedError", evalue=request.error),
            )
        output = request.result
        output.execution_id = request.request_id
        return output

    def execute_silent(
        self, code: str, timeout: float = 15.0,
        cancel_event: Optional[object] = None,
    ) -> str:
        return self.execute(code, timeout=timeout, silent=True,
                            cancel_event=cancel_event).stdout.strip()

    @property
    def namespace(self) -> str:
        return "{}"

    @property
    def is_alive(self) -> bool:
        return all(w.is_alive for w in self._pool.workers)


class RemoteWorker:
    """
    Worker communicating with a remote Kerno daemon over HTTP / JSON RPC (audit #104).
    """

    def __init__(self, worker_id: str, endpoint: str, auth_token: str = ""):
        self.worker_id  = worker_id
        self.endpoint   = endpoint.rstrip("/")
        self.auth_token = auth_token
        self._served    = 0
        self._alive     = True

    def submit(self, request: ExecutionRequest) -> None:
        import threading
        t = threading.Thread(
            target = self._execute_remote,
            args   = (request,),
            daemon = True,
            name   = f"kerno-remote-worker-{self.worker_id}",
        )
        t.start()

    def _execute_remote(self, request: ExecutionRequest) -> None:
        import json
        import urllib.request
        from kerno.types import CellError, CellOutput

        url = f"{self.endpoint}/run"
        payload = json.dumps({
            "task":      request.code,
            "max_cells": 1,
            "security":  "data_analysis",
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=request.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                output = CellOutput(
                    stdout       = data.get("summary", ""),
                    execution_id = request.request_id,
                )
                request.set_result(output)
                self._served += 1
        except Exception as exc:
            request.set_error(f"RemoteWorkerError: {str(exc)}")

    def shutdown(self) -> None:
        self._alive = False

    @property
    def served(self) -> int:
        return self._served

    @property
    def is_alive(self) -> bool:
        return self._alive


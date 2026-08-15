# kerno/kernel/pool.py
"""
KernelPool: manages a collection of warm kernels ready for tasks.

Problems it solves:
  - Cold start latency (kernel takes 2-3s to start)
  - Kernel contamination between tasks (state leaks)
  - Memory accumulation over long sessions
  - Infrastructure failures (OOM, hung kernels)

Design:
  - Pre-warm N kernels at startup
  - Each kernel has lifecycle limits (cells, time, memory)
  - Acquire/release protocol with automatic reset
  - Overflow: create new kernels on demand, drain when idle
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from queue import Empty, Queue
from typing import Optional

from kerno.kernel.runtime import KernelRuntime


class KernelState(Enum):
    WARMING   = auto()   # Starting up, not yet ready
    AVAILABLE = auto()   # Ready for a task
    ACQUIRED  = auto()   # Currently in use
    RESETTING = auto()   # Being cleaned between tasks
    DEAD      = auto()   # Failed, being replaced


@dataclass
class PooledKernel:
    """
    A kernel with lifecycle metadata.
    Wraps KernelRuntime with pool-specific concerns.
    """
    runtime:        KernelRuntime
    kernel_id:      str
    state:          KernelState   = KernelState.WARMING
    created_at:     float         = field(default_factory=time.monotonic)
    acquired_at:    Optional[float] = None
    task_id:        Optional[str]   = None
    tasks_served:   int           = 0

    # ── Lifecycle limits ────────────────────────────────────────────────────

    MAX_CELLS:    int   = 200      # Hard cell limit before retirement
    MAX_LIFETIME: float = 3600.0   # 1 hour
    MAX_MEMORY:   float = 4096.0   # 4 GB RSS

    @property
    def is_expired(self) -> bool:
        age     = time.monotonic() - self.created_at
        memory  = self._safe_memory()
        cells   = self.runtime.cells_executed

        return (
            age    > self.MAX_LIFETIME or
            memory > self.MAX_MEMORY   or
            cells  > self.MAX_CELLS
        )

    @property
    def is_healthy(self) -> bool:
        return self.runtime.is_alive and not self.is_expired

    def _safe_memory(self) -> float:
        try:
            return self.runtime.memory_mb
        except Exception:
            return 0.0


class PoolExhaustedError(RuntimeError):
    """Raised when the pool cannot provide a kernel within the timeout."""


class KernelPool:
    """
    A pool of warm, ready-to-use kernels.

    Usage:
        pool = KernelPool(size=3)
        pool.start()                         # Pre-warm kernels

        kernel = pool.acquire("task-123")
        try:
            result = kernel.execute("df = pd.read_csv('data.csv')")
        finally:
            pool.release("task-123")

        pool.shutdown()

    Or as a context manager:
        with KernelPool(size=3) as pool:
            kernel = pool.acquire("task-123")
            ...
    """

    def __init__(
        self,
        size:          int   = 3,
        kernel_name:   str   = "python3",
        skills_path:   Optional[str] = None,
        overflow:      bool  = True,     # Allow creating kernels beyond `size`
        max_overflow:  int   = 10,
        acquire_timeout: float = 30.0,   # Seconds to wait for available kernel
    ):
        self.size            = size
        self.kernel_name     = kernel_name
        self.skills_path     = skills_path
        self.overflow        = overflow
        self.max_overflow    = max_overflow
        self.acquire_timeout = acquire_timeout

        self._available:  Queue[PooledKernel]       = Queue()
        self._active:     dict[str, PooledKernel]   = {}
        self._all:        list[PooledKernel]         = []
        self._lock:       threading.Lock             = threading.Lock()
        self._monitor:    Optional[threading.Thread] = None
        self._running:    bool                       = False
        self._kernel_seq: int                        = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> "KernelPool":
        """Pre-warm the pool. Returns self for chaining."""
        self._running = True

        # Warm kernels concurrently
        threads = [
            threading.Thread(target=self._warm_one, daemon=True)
            for _ in range(self.size)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Start health monitor
        self._monitor = threading.Thread(
            target=self._monitor_loop, daemon=True
        )
        self._monitor.start()

        return self

    def shutdown(self) -> None:
        """Shut down all kernels in the pool."""
        self._running = False

        with self._lock:
            kernels = list(self._all)

        for pk in kernels:
            try:
                pk.runtime.shutdown(now=True)
                pk.state = KernelState.DEAD
            except Exception:
                pass

    def __enter__(self) -> "KernelPool":
        return self.start()

    def __exit__(self, *args) -> None:
        self.shutdown()

    # ── Acquire / Release ──────────────────────────────────────────────────────

    def acquire(self, task_id: str) -> KernelRuntime:
        """
        Get a ready kernel for a task.

        Args:
            task_id: Unique identifier for the task. Used for release.

        Returns:
            A KernelRuntime ready for execution.

        Raises:
            PoolExhaustedError: if no kernel available within timeout.
        """
        with self._lock:
            if task_id in self._active:
                raise ValueError(f"Task '{task_id}' already has an acquired kernel")

        # Try to get an available kernel
        try:
            pk = self._available.get(timeout=self.acquire_timeout)
        except Empty:
            # Pool exhausted — try overflow
            if self.overflow and len(self._active) < self.max_overflow:
                pk = self._create_kernel()
            else:
                raise PoolExhaustedError(
                    f"No kernel available after {self.acquire_timeout}s. "
                    f"Active: {len(self._active)}, Size: {self.size}"
                )

        # Health check before handing out
        if not pk.is_healthy:
            pk.runtime.shutdown(now=True)
            pk.state = KernelState.DEAD
            pk = self._create_kernel()

        with self._lock:
            pk.state       = KernelState.ACQUIRED
            pk.acquired_at = time.monotonic()
            pk.task_id     = task_id
            self._active[task_id] = pk

        return pk.runtime

    def release(
        self,
        task_id: str,
        reason:  str = "complete",     # "complete" | "error" | "timeout" | "oom"
    ) -> None:
        """
        Return a kernel to the pool after a task completes.

        Args:
            task_id: The task ID used when acquiring
            reason:  Why the task ended — determines reset strategy
        """
        with self._lock:
            pk = self._active.pop(task_id, None)

        if pk is None:
            return

        pk.tasks_served += 1
        pk.task_id       = None
        pk.acquired_at   = None

        match reason:
            case "complete":
                if pk.is_expired:
                    self._retire(pk)
                else:
                    # Soft reset: clear namespace, reload skills
                    threading.Thread(
                        target=self._soft_reset,
                        args=(pk,),
                        daemon=True
                    ).start()

            case "error" | "timeout":
                # Hard reset: kernel may be in bad state
                threading.Thread(
                    target=self._hard_reset,
                    args=(pk,),
                    daemon=True
                ).start()

            case "oom":
                # Kill without replacement — pool shrinks temporarily
                self._retire(pk, replace=False)

    # ── Pool Stats ─────────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "available":    self._available.qsize(),
                "active":       len(self._active),
                "total":        len(self._all),
                "active_tasks": list(self._active.keys()),
            }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _warm_one(self) -> None:
        """Create one warm kernel and add it to the available queue."""
        pk = self._create_kernel()
        if pk.state == KernelState.AVAILABLE:
            self._available.put(pk)

    def _create_kernel(self) -> PooledKernel:
        """Create, start, bootstrap, and register a new kernel."""
        with self._lock:
            self._kernel_seq += 1
            kernel_id = f"k-{self._kernel_seq:04d}"

        runtime = KernelRuntime(kernel_name=self.kernel_name)
        pk      = PooledKernel(runtime=runtime, kernel_id=kernel_id)

        with self._lock:
            self._all.append(pk)

        try:
            runtime.start()
            self._bootstrap(runtime)
            pk.state = KernelState.AVAILABLE
        except Exception:
            pk.state = KernelState.DEAD
            try:
                runtime.shutdown(now=True)
            except Exception:
                pass

        return pk

    def _bootstrap(self, runtime: KernelRuntime) -> None:
        """Load skills and base configuration into a fresh kernel."""
        if not self.skills_path:
            return

        path = Path(self.skills_path)
        if not path.exists():
            return

        code   = path.read_text()
        output = runtime.execute(code, silent=True, timeout=60)
        # Skills load errors are non-fatal but should be surfaced
        if output.has_error:
            import warnings
            warnings.warn(
                f"[kerno] Skills bootstrap warning in {path.name}: "
                f"{output.error.evalue}"
            )

    def _soft_reset(self, pk: PooledKernel) -> None:
        """Clear namespace and reload skills. Keeps kernel process alive."""
        pk.state = KernelState.RESETTING
        try:
            pk.runtime.reset_namespace()
            self._bootstrap(pk.runtime)
            pk.state = KernelState.AVAILABLE
            self._available.put(pk)
        except Exception:
            self._hard_reset(pk)

    def _hard_reset(self, pk: PooledKernel) -> None:
        """Restart kernel process. More thorough than soft reset."""
        pk.state = KernelState.RESETTING
        try:
            pk.runtime.restart()
            self._bootstrap(pk.runtime)
            pk.state = KernelState.AVAILABLE
            self._available.put(pk)
        except Exception:
            self._retire(pk)

    def _retire(self, pk: PooledKernel, replace: bool = True) -> None:
        """Shut down a kernel permanently and optionally replace it."""
        try:
            pk.runtime.shutdown(now=True)
        except Exception:
            pass
        pk.state = KernelState.DEAD

        with self._lock:
            if pk in self._all:
                self._all.remove(pk)

        if replace:
            threading.Thread(
                target=self._warm_one,
                daemon=True
            ).start()

    def _monitor_loop(self) -> None:
        """
        Background thread: periodically checks pool health.
        Replaces dead or expired kernels proactively.
        """
        while self._running:
            time.sleep(30)

            with self._lock:
                all_kernels = list(self._all)

            for pk in all_kernels:
                if pk.state == KernelState.AVAILABLE and pk.is_expired:
                    self._retire(pk, replace=True)
                elif pk.state == KernelState.ACQUIRED:
                    # Check for runaway acquisition (stuck task)
                    if pk.acquired_at and (time.monotonic() - pk.acquired_at) > 3600:
                        # Task has been running for more than 1 hour — flag it
                        import warnings
                        warnings.warn(
                            f"[kerno] Task '{pk.task_id}' has been running "
                            f"for over 1 hour. Consider interrupting."
                        )

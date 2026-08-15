# kerno/kernel/runtime.py
"""
KernelRuntime: the single kernel instance that an agent session runs in.

This is the body. It starts, it executes cells, it tells you what it knows,
it shuts down cleanly. Nothing more, nothing less.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator, Optional

import jupyter_client

from kerno.kernel.output import CellOutput, collect, stream
from kerno.kernel.snapshot import get_snapshot, get_object_detail
from kerno.types import Cell, CellError


class KernelRuntime:
    """
    A single running Jupyter kernel.

    Wraps jupyter_client to provide a clean, agent-oriented interface.
    All ZMQ complexity lives here and nowhere else in the framework.

    Usage:
        with KernelRuntime() as kernel:
            output = kernel.execute("df = pd.read_csv('data.csv')")
            print(kernel.namespace)
    """

    def __init__(
        self,
        kernel_name:     str   = "python3",
        startup_timeout: float = 30.0,
    ):
        self.kernel_name     = kernel_name
        self.startup_timeout = startup_timeout

        self._km: Optional[jupyter_client.KernelManager] = None
        self._kc: Optional[jupyter_client.KernelClient]  = None

        self._cell_count = 0
        self._started_at: Optional[float] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> "KernelRuntime":
        """Start the kernel. Returns self for chaining."""
        self._km = jupyter_client.KernelManager(kernel_name=self.kernel_name)
        self._km.start_kernel()

        self._kc = self._km.client()
        self._kc.start_channels()
        self._kc.wait_for_ready(timeout=self.startup_timeout)

        self._started_at = time.monotonic()
        return self

    def shutdown(self, now: bool = False) -> None:
        """Shut down kernel and close channels."""
        if self._kc:
            self._kc.stop_channels()
        if self._km and self._km.is_alive():
            self._km.shutdown_kernel(now=now)

    def interrupt(self) -> None:
        """Interrupt a running cell (sends SIGINT to kernel process)."""
        if self._km:
            self._km.interrupt_kernel()

    def restart(self) -> None:
        """
        Restart the kernel process, clearing all state.
        Channels remain open — no reconnection needed.
        """
        if self._km:
            self._km.restart_kernel()
            self._kc.wait_for_ready(timeout=self.startup_timeout)
            self._cell_count = 0

    # ── Context Manager ────────────────────────────────────────────────────────

    def __enter__(self) -> "KernelRuntime":
        return self.start()

    def __exit__(self, *) -> None:
        self.shutdown()

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute(
        self,
        code:    str,
        timeout: float = 120.0,
        silent:  bool  = False,
    ) -> CellOutput:
        """
        Execute code in the kernel and return structured output.

        Args:
            code:    Python source code to execute
            timeout: Maximum seconds to wait for execution to complete
            silent:  If True, kernel does not broadcast output on IOPUB
                     (useful for introspection cells that produce no user-visible output)

        Returns:
            CellOutput with all output captured
        """
        self._assert_running()

        start   = time.monotonic()
        msg_id  = self._kc.execute(code, silent=silent)
        output  = collect(self._kc, msg_id, timeout=timeout)
        output.duration = time.monotonic() - start

        if not silent:
            self._cell_count += 1

        return output

    def execute_silent(self, code: str, timeout: float = 15.0) -> str:
        """
        Execute code silently and return stdout as a string.
        Convenience wrapper for introspection cells.
        """
        output = self.execute(code, timeout=timeout, silent=True)
        return output.stdout.strip()

    def stream_execute(
        self,
        code:    str,
        timeout: float = 300.0,
    ) -> Iterator[tuple[str, str]]:
        """
        Execute code and yield output as it arrives.
        Useful for long-running computations.

        Yields:
            ("stdout", text) | ("stderr", text) | ("error", msg) | ("done", "")
        """
        self._assert_running()
        msg_id = self._kc.execute(code)
        self._cell_count += 1
        yield from stream(self._kc, msg_id, timeout=timeout)

    # ── State Inspection ──────────────────────────────────────────────────────

    @property
    def namespace(self) -> str:
        """
        JSON string snapshot of the current kernel namespace.
        Always fresh — reflects the actual live state of the kernel.
        """
        self._assert_running()
        return get_snapshot(self._kc)

    def inspect(self, name: str) -> dict:
        """
        Return detailed type/schema information about a named object.
        """
        self._assert_running()
        return get_object_detail(self._kc, name)

    def reset_namespace(self) -> None:
        """
        Clear all user-defined variables from the namespace.
        Equivalent to %reset -f in IPython.
        Imported modules are also cleared.
        """
        self.execute("%reset -f", silent=True, timeout=10)

    # ── Health ─────────────────────────────────────────────────────────────────

    @property
    def is_alive(self) -> bool:
        return bool(self._km and self._km.is_alive())

    @property
    def cells_executed(self) -> int:
        return self._cell_count

    @property
    def uptime(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    @property
    def memory_mb(self) -> float:
        """RSS memory of the kernel process in megabytes."""
        result = self.execute_silent(
            "import psutil, os; print(psutil.Process(os.getpid()).memory_info().rss / 1e6)"
        )
        try:
            return float(result)
        except (ValueError, TypeError):
            return 0.0

    # ── Internals ──────────────────────────────────────────────────────────────

    def _assert_running(self) -> None:
        if not self.is_alive:
            raise RuntimeError(
                "KernelRuntime is not running. "
                "Call .start() or use as a context manager."
            )

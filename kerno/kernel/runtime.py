"""
KernelRuntime with telemetry instrumentation.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator, Optional

import jupyter_client

from kerno.kernel.output   import CellOutput, collect, stream
from kerno.kernel.snapshot import get_snapshot, get_object_detail
from kerno.telemetry.tracer  import get_tracer
from kerno.telemetry.metrics import get_metrics
from kerno.telemetry.logger  import get_logger
from kerno.types import Cell, CellError

log = get_logger("kerno.kernel")


class KernelRuntime:

    def __init__(
        self,
        kernel_name:     str   = "python3",
        startup_timeout: float = 30.0,
        kernel_id:       str   = "",
    ):
        self.kernel_name     = kernel_name
        self.startup_timeout = startup_timeout
        self.kernel_id       = kernel_id or "default"

        self._km: Optional[jupyter_client.KernelManager] = None
        self._kc: Optional[jupyter_client.KernelClient]  = None
        self._cell_count  = 0
        self._started_at: Optional[float] = None
        self._tracer  = get_tracer()
        self._metrics = get_metrics()

    def start(self) -> "KernelRuntime":
        with self._tracer.span("kernel.start", {"kernel.name": self.kernel_name}):
            self._km = jupyter_client.KernelManager(kernel_name=self.kernel_name)
            self._km.start_kernel()
            self._kc = self._km.client()
            self._kc.start_channels()
            self._kc.wait_for_ready(timeout=self.startup_timeout)
            self._started_at = time.monotonic()

        log.info("Kernel started", kernel_id=self.kernel_id, name=self.kernel_name)
        return self

    def shutdown(self, now: bool = False) -> None:
        if self._kc:
            self._kc.stop_channels()
        if self._km and self._km.is_alive():
            self._km.shutdown_kernel(now=now)
        log.info("Kernel shutdown", kernel_id=self.kernel_id)

    def interrupt(self) -> None:
        if self._km:
            self._km.interrupt_kernel()

    def restart(self) -> None:
        if self._km:
            self._km.restart_kernel()
            self._kc.wait_for_ready(timeout=self.startup_timeout)
            self._cell_count = 0
        log.info("Kernel restarted", kernel_id=self.kernel_id)

    def __enter__(self) -> "KernelRuntime":
        return self.start()

    def __exit__(self, *args) -> None:
        self.shutdown()

    def execute(
        self,
        code:    str,
        timeout: float = 120.0,
        silent:  bool  = False,
    ) -> CellOutput:
        self._assert_running()

        attrs = {
            "kernel.id":         self.kernel_id,
            "cell.num":          self._cell_count + 1,
            "cell.code_preview": code[:80].replace("\n", " "),
            "cell.silent":       silent,
        }

        with self._tracer.span("kernel.execute", attrs) as span:
            start   = time.monotonic()
            msg_id  = self._kc.execute(code, silent=silent)
            output  = collect(self._kc, msg_id, timeout=timeout)
            dur_ms  = (time.monotonic() - start) * 1000
            output.duration = dur_ms / 1000

            span.set("cell.duration_ms",  dur_ms)
            span.set("cell.had_error",    output.has_error)
            span.set("cell.output_bytes", len(output.stdout))
            span.set("cell.n_images",     len(output.images))

            if output.has_error:
                span.set("error.ename",  output.error.ename)
                span.set("error.evalue", output.error.evalue[:200])

            if not silent:
                self._cell_count += 1
                self._metrics.record_cell(
                    duration_ms = dur_ms,
                    had_error   = output.has_error,
                    session_id  = "",
                    loop_type   = "",
                )

                if output.has_error:
                    log.warning(
                        "Cell execution error",
                        kernel_id = self.kernel_id,
                        cell_num  = self._cell_count,
                        ename     = output.error.ename,
                        evalue    = output.error.evalue[:200],
                    )

        return output

    def execute_silent(self, code: str, timeout: float = 15.0) -> str:
        output = self.execute(code, timeout=timeout, silent=True)
        return output.stdout.strip()

    def stream_execute(self, code: str, timeout: float = 300.0) -> Iterator[tuple[str, str]]:
        self._assert_running()
        msg_id = self._kc.execute(code)
        self._cell_count += 1
        yield from stream(self._kc, msg_id, timeout=timeout)

    @property
    def namespace(self) -> str:
        self._assert_running()
        return get_snapshot(self._kc)

    def inspect(self, name: str) -> dict:
        self._assert_running()
        return get_object_detail(self._kc, name)

    def reset_namespace(self) -> None:
        self.execute("%reset -f", silent=True, timeout=10)

    @property
    def is_alive(self) -> bool:
        return bool(self._km and self._km.is_alive())

    @property
    def cells_executed(self) -> int:
        return self._cell_count

    @property
    def uptime(self) -> float:
        return (time.monotonic() - self._started_at) if self._started_at else 0.0

    @property
    def memory_mb(self) -> float:
        result = self.execute_silent(
            "import psutil, os; print(psutil.Process(os.getpid()).memory_info().rss / 1e6)"
        )
        try:
            mb = float(result)
            self._metrics.record_kernel_memory(mb, self.kernel_id)
            return mb
        except (ValueError, TypeError):
            return 0.0

    def _assert_running(self) -> None:
        if not self.is_alive:
            raise RuntimeError(
                "KernelRuntime is not running. Call .start() or use as context manager."
            )

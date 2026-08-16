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
from kerno.kernel.state    import KernelRuntimeState
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
        timeout_policy:  str   = "interrupt",
    ):
        if timeout_policy not in ("interrupt", "escalate"):
            raise ValueError(
                "timeout_policy must be 'interrupt' or 'escalate'"
            )
        self.kernel_name     = kernel_name
        self.startup_timeout = startup_timeout
        self.kernel_id       = kernel_id or "default"
        self.timeout_policy  = timeout_policy

        self._km: Optional[jupyter_client.KernelManager] = None
        self._kc: Optional[jupyter_client.KernelClient]  = None
        self._cell_count  = 0
        self._started_at: Optional[float] = None
        self._state       = KernelRuntimeState.CLOSED
        self._generation  = 1
        self._tracer  = get_tracer()
        self._metrics = get_metrics()

    def start(self) -> "KernelRuntime":
        with self._tracer.span("kernel.start", {"kernel.name": self.kernel_name}):
            self._state = KernelRuntimeState.STARTING
            self._km = jupyter_client.KernelManager(kernel_name=self.kernel_name)
            self._km.start_kernel()
            self._kc = self._km.client()
            self._kc.start_channels()
            self._kc.wait_for_ready(timeout=self.startup_timeout)
            self._started_at = time.monotonic()
            self._state      = KernelRuntimeState.READY

        log.info("Kernel started", kernel_id=self.kernel_id, name=self.kernel_name)
        return self

    def shutdown(self, now: bool = False) -> None:
        self._state = KernelRuntimeState.CLOSED
        if self._kc:
            self._kc.stop_channels()
        if self._km and self._km.is_alive():
            self._km.shutdown_kernel(now=now)
        log.info("Kernel shutdown", kernel_id=self.kernel_id)

    def interrupt(self) -> None:
        if self._km:
            self._state = KernelRuntimeState.INTERRUPTING
            self._km.interrupt_kernel()
            self._state = KernelRuntimeState.READY

    def restart(self) -> None:
        if self._km:
            self._state = KernelRuntimeState.RESTARTING
            self._km.restart_kernel()
            self._kc.wait_for_ready(timeout=self.startup_timeout)
            self._cell_count = 0
            self._generation += 1
            self._state      = KernelRuntimeState.READY
        log.info("Kernel restarted", kernel_id=self.kernel_id,
                 generation=self._generation)

    def _escalate_timeout(
        self,
        grace_s:     float = 2.0,
        kill_wait_s: float = 5.0,
    ) -> None:
        """
        Audit #84: escalate a stuck kernel through the timeout ladder.

        collect() already sent the soft interrupt (SIGINT). After a grace
        period, if the kernel is still alive we hard-terminate the process
        (SIGKILL) and restart it. If the kernel died on its own, we leave
        it dead — the loop's K-004 recovery path handles the restart.
        """
        time.sleep(grace_s)
        if not self.is_alive:
            return
        try:
            proc = self._km.provisioner.process
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=kill_wait_s)
        except Exception:
            pass
        try:
            self.restart()
        except Exception:
            self._state = KernelRuntimeState.DEAD

    def __enter__(self) -> "KernelRuntime":
        return self.start()

    def __exit__(self, *args) -> None:
        self.shutdown()

    def execute(
        self,
        code:         str,
        timeout:      float = 120.0,
        silent:       bool  = False,
        cancel_event: "object | None" = None,
    ) -> CellOutput:
        self._assert_running()

        attrs = {
            "kernel.id":         self.kernel_id,
            "kernel.generation": self._generation,
            "cell.num":          self._cell_count + 1,
            "cell.code_preview": code[:80].replace("\n", " "),
            "cell.silent":       silent,
        }

        with self._tracer.span("kernel.execute", attrs) as span:
            start   = time.monotonic()
            msg_id  = self._kc.execute(code, silent=silent)
            self._state = KernelRuntimeState.BUSY
            try:
                output  = collect(
                    self._kc, msg_id, timeout=timeout,
                    on_timeout=self.interrupt, cancel_event=cancel_event,
                )
            finally:
                self._state = KernelRuntimeState.READY
            dur_ms  = (time.monotonic() - start) * 1000
            output.duration = dur_ms / 1000

            # Audit #84: timeout escalation — soft interrupt (already sent
            # by collect) → grace period → hard termination → restart.
            if (
                self.timeout_policy == "escalate"
                and output.error is not None
                and output.error.ename == "TimeoutError"
            ):
                self._escalate_timeout()

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

    def stream_execute(
        self,
        code:         str,
        timeout:      float = 300.0,
        cancel_event: "object | None" = None,
    ) -> Iterator[tuple[str, str]]:
        self._assert_running()
        msg_id = self._kc.execute(code)
        self._cell_count += 1
        self._state = KernelRuntimeState.BUSY
        try:
            yield from stream(
                self._kc, msg_id, timeout=timeout, on_timeout=self.interrupt,
                cancel_event=cancel_event,
            )
        finally:
            self._state = KernelRuntimeState.READY

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
    def state(self) -> KernelRuntimeState:
        """Current health state (audit #53).

        DEAD is sticky: once the kernel process is observed dead, the
        state stays DEAD until an explicit restart() — a freshly-killed
        kernel must never read as READY even if the process poll lags.
        """
        if self._state == KernelRuntimeState.DEAD:
            return self._state
        if self._state in (
            KernelRuntimeState.CLOSED,
            KernelRuntimeState.STARTING,
            KernelRuntimeState.RESTARTING,
            KernelRuntimeState.INTERRUPTING,
        ):
            return self._state
        if self._km is None or not self._km.is_alive():
            # Sticky death: remember it so subsequent reads agree.
            self._state = KernelRuntimeState.DEAD
        return self._state

    @property
    def generation(self) -> int:
        """Monotonic kernel generation; incremented on restart (audit #54)."""
        return self._generation

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

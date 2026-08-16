# kerno/faults.py
"""
Fault injection for runtime verification (audit #72).

A serious runtime must survive deliberate failures:

    kill kernel · timeout execution · fail execution · fail LLM request
    corrupt checkpoint · drop event · exhaust memory/disk

FaultInjector wraps any Executor and injects faults deterministically:

    injector = FaultInjector(kernel)
    injector.fail_next(2)        # the next 2 executions return InjectedFailure
    injector.kill_after(1)       # after the 1st execution, SIGKILL the kernel

It implements the Executor protocol (plus restart/generation passthrough)
so loops and the ExecutionEngine accept it transparently — the recovery
path (K-004 auto-restart, error recovery) can be exercised end-to-end.
"""

from __future__ import annotations

import time
from typing import Optional

from kerno.types import CellError, CellOutput


class FaultInjector:
    """Deterministic fault injection over an underlying Executor."""

    def __init__(self, executor: object):
        self._executor = executor
        self._fail_next = 0
        self._kill_at: Optional[int] = None
        self._calls = 0
        self._kill_count = 0

    # ── Injection controls ───────────────────────────────────────────────

    def fail_next(self, n: int = 1) -> "FaultInjector":
        """The next `n` executions return an InjectedFailure error cell."""
        self._fail_next = max(0, n)
        return self

    def kill_after(self, n: int) -> "FaultInjector":
        """
        After the n-th execution completes, SIGKILL the kernel process.

        The triggering execution completes normally; the kernel dies
        afterwards — exactly how a real crash lands.
        """
        self._kill_at = self._calls + max(1, n)
        return self

    @property
    def kill_count(self) -> int:
        return self._kill_count

    # ── Executor protocol ─────────────────────────────────────────────────

    def execute(
        self,
        code:         str,
        timeout:      float = 120.0,
        silent:       bool  = False,
        cancel_event: "object | None" = None,
    ) -> CellOutput:
        self._calls += 1

        if self._fail_next > 0:
            self._fail_next -= 1
            return CellOutput(
                error=CellError(
                    ename  = "InjectedFailure",
                    evalue = "fault injected by FaultInjector",
                )
            )

        output = self._executor.execute(code, timeout=timeout, silent=silent)

        if self._kill_at is not None and self._calls >= self._kill_at:
            self._kill_at = None
            kill_kernel(self._executor)
            self._kill_count += 1

        return output

    def execute_silent(self, code: str, timeout: float = 15.0) -> str:
        output = self.execute(code, timeout=timeout, silent=True)
        return output.stdout.strip()

    # ── Passthroughs ──────────────────────────────────────────────────────

    @property
    def namespace(self) -> str:
        return self._executor.namespace

    @property
    def is_alive(self) -> bool:
        return self._executor.is_alive

    @property
    def raw_kernel(self) -> object:
        """The underlying kernel (for trusted infrastructure / K-004)."""
        return getattr(self._executor, "raw_kernel", None) or self._executor

    @property
    def generation(self) -> int:
        return self.raw_kernel.generation

    @property
    def calls(self) -> int:
        return self._calls

    def restart(self):
        """Passthrough for the K-004 restore path."""
        raw = self.raw_kernel
        if hasattr(raw, "restart"):
            return raw.restart()
        return None

    def shutdown(self) -> None:
        raw = self.raw_kernel
        if hasattr(raw, "shutdown"):
            raw.shutdown()


def kill_kernel(executor: object, wait_s: float = 0.5) -> None:
    """
    SIGKILL the kernel process behind an Executor (crash simulation).

    The channels are left intact so KernelRuntime.restart() can bring the
    kernel back (generation increments) — matching a real crash.
    """
    raw = getattr(executor, "raw_kernel", None) or executor
    proc = raw._km.provisioner.process
    if proc is not None and proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    time.sleep(wait_s)

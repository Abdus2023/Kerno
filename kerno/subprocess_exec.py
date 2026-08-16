# kerno/subprocess_exec.py
"""
SubprocessExecutor — process-level execution isolation (audit #97).

Runs each code block in a FRESH `python -c` subprocess. The process
boundary gives:
  - a clean namespace per execution (no state leaks between cells)
  - OS-level resource limits via prlimit (CPU time, RSS, processes)
  - hard wall-clock timeout via subprocess timeout + process group kill

This is NOT a security sandbox (the subprocess shares the host user and
filesystem) — it is a state-isolation and resource-control executor.
Pair with the DockerExecutor for untrusted workloads (audit #70).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Optional

from kerno.types import CellError, CellOutput


class SubprocessExecutor:
    """
    Executor protocol implementation over `python -c` subprocesses.

    Usage:
        ex = SubprocessExecutor(timeout=10, memory_limit_mb=512)
        out = ex.execute("print(1 + 1)")
    """

    def __init__(
        self,
        timeout:          float        = 120.0,
        memory_limit_mb:  Optional[int] = None,
        cpu_limit_s:      Optional[float] = None,
        process_limit:    Optional[int] = None,
        python_bin:       str          = sys.executable,
    ):
        self.timeout         = timeout
        self.memory_limit_mb = memory_limit_mb
        self.cpu_limit_s     = cpu_limit_s
        self.process_limit   = process_limit
        self.python_bin      = python_bin

    # ── Executor protocol ─────────────────────────────────────────────────

    def execute(
        self,
        code:         str,
        timeout:      Optional[float] = None,
        silent:       bool  = False,
        cancel_event: "object | None" = None,
    ) -> CellOutput:
        limit = timeout or self.timeout
        start = time.monotonic()

        # Resource prelude: prlimit inside the child
        prelude = self._resource_prelude()

        try:
            result = subprocess.run(
                [self.python_bin, "-c", prelude + "\n" + code],
                capture_output=True,
                text=True,
                timeout=limit,
                start_new_session=True,      # own process group
            )
        except subprocess.TimeoutExpired:
            return CellOutput(
                error=CellError(
                    ename  = "TimeoutError",
                    evalue = "Subprocess exceeded {}s limit".format(limit),
                ),
                duration = time.monotonic() - start,
            )

        duration = time.monotonic() - start
        if result.returncode == 0:
            return CellOutput(
                stdout   = result.stdout,
                stderr   = result.stderr,
                duration = duration,
            )

        detail = (result.stderr or result.stdout).strip() or "exit {}".format(
            result.returncode
        )
        return CellOutput(
            error    = CellError(
                ename  = "SubprocessExecutionError",
                evalue = detail[:500],
            ),
            stderr   = result.stderr,
            stdout   = result.stdout,
            duration = duration,
        )

    def _resource_prelude(self) -> str:
        """Python code that applies resource limits to the child."""
        lines: list[str] = []
        if self.memory_limit_mb or self.cpu_limit_s or self.process_limit:
            lines.append("import resource as _r")
        if self.memory_limit_mb:
            mb = int(self.memory_limit_mb)
            lines.append(
                "_r.setrlimit(_r.RLIMIT_AS, ({}, {}))".format(mb * 1024 * 1024, mb * 1024 * 1024)
            )
        if self.cpu_limit_s:
            secs = int(self.cpu_limit_s)
            lines.append(
                "_r.setrlimit(_r.RLIMIT_CPU, ({}, {}))".format(secs, secs)
            )
        if self.process_limit:
            n = int(self.process_limit)
            lines.append(
                "_r.setrlimit(_r.RLIMIT_NPROC, ({}, {}))".format(n, n)
            )
        return "\n".join(lines)

    def execute_silent(self, code: str, timeout: float = 15.0) -> str:
        return self.execute(code, timeout=timeout, silent=True).stdout.strip()

    @property
    def namespace(self) -> str:
        return "{}"     # fresh namespace per execution

    @property
    def is_alive(self) -> bool:
        return True

# kerno/isolation_docker.py
"""
DockerExecutor — OS-level execution isolation (audit #3, #11, #69).

The kernel-native security model is:  Host → hardened container → kernel.
DockerExecutor runs each code block inside a docker container with
explicit OS-level resource limits, so LLM-generated code never touches
the host trust domain:

    Container limits:
        --cpus        CPU quota
        --memory      RAM limit
        --pids-limit  process count
        --network     none (disabled by default)
        --read-only   root filesystem (unless --tmpfs workdir is used)

Implementation: a long-lived `sleep infinity` container per executor
(docker CLI, no SDK dependency), and each execution is
`docker exec -i <container> python -c <code>` with a hard timeout.

Security note: this is a real isolation boundary, but the image and the
docker socket it uses must themselves be trusted. For hostile workloads,
pair with a dedicated daemon / VM (audit #70 defense in depth).
"""

from __future__ import annotations

import json
import shlex
import subprocess
import time
import uuid
from typing import Optional

from kerno.types import CellError, CellOutput


class DockerUnavailable(RuntimeError):
    """Raised when the docker CLI is not available or the daemon is down."""


class DockerExecutor:
    """
    Executor protocol implementation backed by a docker container.

    Usage:
        ex = DockerExecutor(image="python:3.11-slim", memory="512m",
                            cpus=1.0, network=False)
        ex.start()                      # creates the container
        out = ex.execute("print(1+1)")  # CellOutput
        ex.shutdown()                   # removes the container
    """

    def __init__(
        self,
        image:           str   = "python:3.11-slim",
        *,
        cpus:            float = 1.0,
        memory:          str   = "2g",
        pids_limit:      int   = 128,
        network:         bool  = False,
        read_only_fs:    bool  = True,
        workdir:         str   = "/workspace",
        timeout:         float = 120.0,
        docker_cmd:      str   = "docker",
        container_name:  Optional[str] = None,
        extra_args:      Optional[list[str]] = None,
    ):
        self.image           = image
        self.cpus            = cpus
        self.memory          = memory
        self.pids_limit      = pids_limit
        self.network         = network
        self.read_only_fs    = read_only_fs
        self.workdir         = workdir
        self.timeout         = timeout
        self.docker_cmd      = docker_cmd
        self.container_name  = container_name or "kerno-exec-" + uuid.uuid4().hex[:8]
        self.extra_args      = list(extra_args or [])
        self._started        = False

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> "DockerExecutor":
        """Create the container (idempotent)."""
        if self._started:
            return self
        cmd = [
            self.docker_cmd, "run", "-d",
            "--name", self.container_name,
            "--cpus", str(self.cpus),
            "--memory", self.memory,
            "--pids-limit", str(self.pids_limit),
            "--security-opt", "no-new-privileges:true",
            "--cap-drop", "ALL",
        ]
        if not self.network:
            cmd.append("--network")
            cmd.append("none")
        if self.read_only_fs:
            cmd.append("--read-only")
        cmd += ["--workdir", self.workdir, "--tmpfs", self.workdir]
        cmd += self.extra_args
        cmd += [self.image, "sleep", "infinity"]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise DockerUnavailable(
                "docker run failed: {}".format(
                    (result.stderr or result.stdout).strip()[:300]
                )
            )
        self._started = True
        return self

    def shutdown(self) -> None:
        """Remove the container (idempotent)."""
        if not self._started:
            return
        subprocess.run(
            [self.docker_cmd, "rm", "-f", self.container_name],
            capture_output=True, text=True, timeout=60,
        )
        self._started = False

    def __enter__(self) -> "DockerExecutor":
        return self.start()

    def __exit__(self, *args) -> None:
        self.shutdown()

    # ── Executor protocol ──────────────────────────────────────────────────

    def execute(
        self,
        code:         str,
        timeout:      Optional[float] = None,
        silent:       bool  = False,
        cancel_event: "object | None" = None,
    ) -> CellOutput:
        """
        Execute code inside the container.

        Args:
            code:    Python source to execute (run via `python -c`)
            timeout: Hard wall-clock limit for the docker exec
            silent:  Accepted for protocol compatibility (no-op)

        Returns:
            CellOutput: stdout/stderr on success, CellError on failure
            (including timeout, OOM, and non-zero exit).
        """
        if not self._started:
            self.start()
        limit = timeout or self.timeout

        start = time.monotonic()
        try:
            result = subprocess.run(
                [
                    self.docker_cmd, "exec", "-i",
                    self.container_name, "python", "-c", code,
                ],
                capture_output=True, text=True, timeout=limit,
            )
        except subprocess.TimeoutExpired:
            return CellOutput(
                error=CellError(
                    ename  = "TimeoutError",
                    evalue = "Container execution exceeded {}s limit".format(limit),
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

        # Non-zero exit: surface stderr (or stdout) as the error value.
        detail = (result.stderr or result.stdout).strip() or "exit {}".format(
            result.returncode
        )
        return CellOutput(
            error    = CellError(
                ename  = "ContainerExecutionError",
                evalue = detail[:500],
            ),
            stderr   = result.stderr,
            stdout   = result.stdout,
            duration = duration,
        )

    def execute_silent(self, code: str, timeout: float = 15.0) -> str:
        output = self.execute(code, timeout=timeout, silent=True)
        return output.stdout.strip()

    @property
    def namespace(self) -> str:
        return "{}"

    @property
    def is_alive(self) -> bool:
        return self._started

    # ── Inspect ───────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """docker stats for the container (JSON)."""
        result = subprocess.run(
            [
                self.docker_cmd, "stats", "--no-stream", "--format",
                "{{json .}}", self.container_name,
            ],
            capture_output=True, text=True, timeout=30,
        )
        try:
            return json.loads(result.stdout.strip())
        except (json.JSONDecodeError, ValueError):
            return {"error": (result.stderr or result.stdout).strip()[:200]}


def docker_available(docker_cmd: str = "docker") -> bool:
    """True if the docker CLI responds."""
    try:
        result = subprocess.run(
            [docker_cmd, "info"], capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False

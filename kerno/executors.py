# kerno/executors.py
"""
Executor factory — kernel execution is pluggable (audit #97, #104).

    make_executor(kind="local")   → KernelRuntime          (real Jupyter kernel)
    make_executor(kind="docker")  → DockerExecutor         (container isolation)
    make_executor(kind="dry_run") → DryRunExecutor         (validate, don't run)
    make_executor(kind="replay")  → ReplayExecutor         (serve recorded cells)
    make_executor(kind="mock")    → ScriptedExecutor       (deterministic tests)

The agent runtime never depends on one execution mechanism: the same
loop accepts any Executor-protocol object. This is also what makes
tests fast (mock/dry_run) and security tests real (docker).
"""

from __future__ import annotations

from typing import Optional

from kerno.execution.modes import DryRunExecutor, ReplayExecutor
from kerno.kernel.runtime import KernelRuntime
from kerno.security.allowlist import AllowList
from kerno.types import Cell, CellOutput

EXECUTOR_KINDS = ("local", "docker", "dry_run", "replay", "mock", "subprocess")


class UnknownExecutorKind(ValueError):
    """Raised for an unknown executor kind."""


class ScriptedExecutor:
    """
    Deterministic executor for tests (audit #100): returns scripted
    outputs in order, then a completion output.
    """

    def __init__(self, outputs: Optional[list[CellOutput]] = None):
        self._outputs  = list(outputs or [])
        self._index    = 0
        self._requests: list[str] = []

    def execute(
        self, code: str, timeout: float = 120.0, silent: bool = False,
        cancel_event: "object | None" = None,
    ) -> CellOutput:
        self._requests.append(code)
        if self._index < len(self._outputs):
            out = self._outputs[self._index]
            self._index += 1
            return out
        return CellOutput(stdout="[mock] " + code[:40])

    def execute_silent(self, code: str, timeout: float = 15.0) -> str:
        return self.execute(code, timeout=timeout, silent=True).stdout.strip()

    @property
    def namespace(self) -> str:
        return "{}"

    @property
    def is_alive(self) -> bool:
        return True

    @property
    def requests(self) -> tuple[str, ...]:
        """Every code request (assert what the agent asked to run)."""
        return tuple(self._requests)


def make_executor(
    kind:            str,
    *,
    kernel_name:     str               = "python3",
    allowlist:       Optional[AllowList] = None,
    image:           str               = "python:3.11-slim",
    recorded:        Optional[list[Cell]] = None,
    scripted:        Optional[list[CellOutput]] = None,
    **kwargs,
):
    """
    Build an executor by kind.

    Args:
        kind:      "local" | "docker" | "dry_run" | "replay" | "mock"
        kernel_name: kernel spec for "local"
        allowlist:  policy for "dry_run" (validated, not executed)
        image:      container image for "docker"
        recorded:   recorded Cells for "replay"
        scripted:   scripted outputs for "mock"
        kwargs:     forwarded to the concrete executor constructor
    """
    if kind == "local":
        return KernelRuntime(kernel_name=kernel_name, **kwargs)
    if kind == "docker":
        from kerno.isolation_docker import DockerExecutor
        return DockerExecutor(image=image, **kwargs)
    if kind == "dry_run":
        return DryRunExecutor(allowlist=allowlist, **kwargs)
    if kind == "replay":
        if recorded is None:
            raise ValueError("kind='replay' requires recorded=[...]")
        return ReplayExecutor(recorded, **kwargs)
    if kind == "mock":
        return ScriptedExecutor(scripted, **kwargs)
    if kind == "subprocess":
        from kerno.subprocess_exec import SubprocessExecutor
        return SubprocessExecutor(**kwargs)
    raise UnknownExecutorKind(
        "unknown executor kind {!r}; choose from {}".format(
            kind, ", ".join(EXECUTOR_KINDS)
        )
    )

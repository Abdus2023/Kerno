# kerno/kernel/state.py
"""
KernelRuntimeState — the observable health state of a kernel (audit #53, #54).

    STARTING      → kernel process launching, channels connecting
    READY         → idle, accepting executions
    BUSY          → an execution is in flight
    DEGRADED      → recovering from a soft failure (reserved)
    INTERRUPTING  → interrupt signal in flight
    RESTARTING    → restart requested, waiting for readiness
    DEAD          → process gone (crash, OOM, kill)
    CLOSED        → shutdown() called; the runtime is done

Every kernel also carries a monotonic `generation` counter, incremented
on each restart, so provenance can distinguish "kernel K1, generation 2"
from an unrelated kernel (audit #54).
"""

from __future__ import annotations

from enum import Enum, auto


class KernelRuntimeState(Enum):
    STARTING      = auto()
    READY         = auto()
    BUSY          = auto()
    DEGRADED      = auto()
    INTERRUPTING  = auto()
    RESTARTING    = auto()
    DEAD          = auto()
    CLOSED        = auto()

    @property
    def terminal(self) -> bool:
        """True for states the kernel cannot leave."""
        return self in (KernelRuntimeState.DEAD, KernelRuntimeState.CLOSED)

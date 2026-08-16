# kerno/cancel.py
"""
CancellationToken — first-class cancellation (audit #83).

    User
      ↓
    Agent
      ↓
    Action
      ↓
    Kernel interrupt
      ↓
    Execution terminated

A token is a thread-safe flag that any component can set. The loop
checks it between cells; the engine checks it before execution; the
output collector watches it DURING execution and interrupts the kernel
mid-cell. Cancellation is a first-class session outcome
(SessionStatus.INTERRUPTED), not an arbitrary exception.

Usage:
    token = CancellationToken()
    result = run(task, llm, cancel_token=token)
    # ... in another thread / handler:
    token.cancel()
"""

from __future__ import annotations

import threading
import time
from typing import Optional


class CancellationToken:
    """A thread-safe cancellation flag."""

    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation. Idempotent and thread-safe."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """True once cancellation has been requested."""
        return self._event.is_set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Block until cancelled or timeout.

        Returns True if cancelled, False on timeout.
        """
        return self._event.wait(timeout)

    def wait_until(
        self,
        deadline: float,
        interval: float = 0.25,
    ) -> bool:
        """
        Poll until cancelled or the monotonic deadline passes.

        Useful inside blocking loops (e.g. output collection) where a
        plain wait would still be fine but a bounded poll keeps the
        loop responsive.
        """
        while time.monotonic() < deadline:
            if self.cancelled:
                return True
            time.sleep(interval)
        return self.cancelled


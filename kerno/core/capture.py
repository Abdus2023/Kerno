# kerno/core/capture.py
"""
Runtime checkpoint capture (audit #59, K-007).

_auto_checkpoint() serializes DataFrames inside the kernel — a clever
but UNSAFE mechanism (the checkpoint code itself runs in the agent's
trust domain, audit #15). The HOST-side capture point is the safe
alternative: after a cell completes, the loop records a Checkpoint
bound to the engine's event-stream position — exactly which state and
event sequence it represents (K-007) — with NO code executed in the
kernel.

    Checkpoint.capture(
        session_id, state_version, event_sequence, kernel_generation,
        artifact_hashes, parent=...
    )
"""

from __future__ import annotations

from typing import Optional

from kerno.core.checkpoint import Checkpoint, CheckpointStore


class CapturePoint:
    """
    Host-side checkpoint recorder attached to a session loop.

    Usage:
        store  = CheckpointStore(persist_dir="_checkpoints")
        capture = CapturePoint(store, session_id="sess-1",
                               engine=engine, kernel=kernel)

        # After each cell completes:
        capture.after_cell(cell_num, parent=last_checkpoint)

    Every checkpoint binds the current state version + engine event
    sequence + kernel generation (K-007) and is recorded WITHOUT any
    kernel-side code.
    """

    def __init__(
        self,
        store:      CheckpointStore,
        session_id: str,
        engine:     Optional[object] = None,   # ExecutionEngine (event_sequence)
        kernel:     Optional[object] = None,   # KernelRuntime (generation)
        every_n:    int = 1,
    ):
        self._store      = store
        self._session_id = session_id
        self._engine     = engine
        self._kernel     = kernel
        self._every_n    = max(1, every_n)
        self._last: Optional[Checkpoint] = None
        self._count      = 0

    def after_cell(
        self,
        cell_num:      int,
        state_version: int = 0,
        artifact_hashes: Optional[dict] = None,
    ) -> Optional[Checkpoint]:
        """Record a checkpoint after a cell if the cadence allows."""
        self._count += 1
        if self._count % self._every_n != 0:
            return None

        event_seq = 0
        if self._engine is not None:
            event_seq = getattr(self._engine, "event_sequence", 0)

        generation = 0
        if self._kernel is not None:
            generation = getattr(self._kernel, "generation", 0)

        ckpt = Checkpoint.capture(
            session_id        = self._session_id,
            state_version     = state_version,
            event_sequence    = event_seq,
            kernel_generation = generation,
            artifact_hashes   = artifact_hashes,
            summary           = "after cell {}".format(cell_num),
            parent            = self._last,
        )
        self._store.save(ckpt)
        self._last = ckpt
        return ckpt

    @property
    def last(self) -> Optional[Checkpoint]:
        return self._last

    @property
    def count(self) -> int:
        return self._count

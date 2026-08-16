# kerno/core/checkpoint.py
"""
Checkpoint — a named, consistent point in agent time (audit #59, K-007).

A checkpoint identifies EXACTLY which state and event sequence it
represents:

    checkpoint_id
    session_id
    state_version        — the AgentState version captured
    event_sequence       — the execution event stream position captured
    kernel_generation    — which kernel generation held the state
    artifact_hashes      — content-addressed artifacts at capture time

Forking from a checkpoint (audit #59/#60) produces a new branch whose
lineage points back at the checkpoint, enabling experiments from a
common state.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Checkpoint:
    """A consistent capture point of an agent session."""

    checkpoint_id:     str
    session_id:        str
    state_version:     int                 # AgentState.version at capture
    event_sequence:    int                 # execution event stream position
    kernel_generation: int   = 0           # KernelRuntime.generation at capture
    artifact_hashes:   dict  = field(default_factory=dict)  # path → sha256
    summary:           str   = ""
    parent_checkpoint_id: Optional[str] = None
    created_at:        float = field(default_factory=time.time)

    @classmethod
    def capture(
        cls,
        session_id:        str,
        state_version:     int,
        event_sequence:    int,
        kernel_generation: int   = 0,
        artifact_hashes:   Optional[dict] = None,
        summary:           str   = "",
        parent:            Optional["Checkpoint"] = None,
    ) -> "Checkpoint":
        """Create a checkpoint bound to a state version + event sequence."""
        return cls(
            checkpoint_id       = "ckpt_" + uuid.uuid4().hex[:12],
            session_id          = session_id,
            state_version       = state_version,
            event_sequence      = event_sequence,
            kernel_generation   = kernel_generation,
            artifact_hashes     = dict(artifact_hashes or {}),
            summary             = summary,
            parent_checkpoint_id = parent.checkpoint_id if parent else None,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "Checkpoint":
        return cls(**d)


class CheckpointStore:
    """
    In-memory checkpoint store with optional JSON persistence.

    Usage:
        store = CheckpointStore(persist_dir="_checkpoints")
        ckpt = store.save(Checkpoint.capture(...))
        loaded = store.load(ckpt.checkpoint_id)
    """

    def __init__(self, persist_dir: Optional[str] = None):
        self._checkpoints: dict[str, Checkpoint] = {}
        self._persist_dir = Path(persist_dir) if persist_dir else None
        if self._persist_dir:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._load_disk()

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint
        if self._persist_dir:
            path = self._persist_dir / f"{checkpoint.checkpoint_id}.json"
            path.write_text(checkpoint.to_json())
        return checkpoint

    def load(self, checkpoint_id: str) -> Optional[Checkpoint]:
        return self._checkpoints.get(checkpoint_id)

    def latest(self, session_id: str) -> Optional[Checkpoint]:
        """Most recent checkpoint for a session."""
        matches = [
            c for c in self._checkpoints.values()
            if c.session_id == session_id
        ]
        return max(matches, key=lambda c: (c.event_sequence, c.created_at)) \
            if matches else None

    def fork(
        self,
        checkpoint_id: str,
        *,
        session_id: Optional[str] = None,
    ) -> Checkpoint:
        """
        Fork a new checkpoint from an existing one (audit #59).

        The child carries the parent's state version as its baseline and
        records parent_checkpoint_id for lineage.
        """
        parent = self.load(checkpoint_id)
        if parent is None:
            raise KeyError(f"Unknown checkpoint: {checkpoint_id}")
        child = Checkpoint.capture(
            session_id        = session_id or parent.session_id,
            state_version     = parent.state_version,
            event_sequence    = parent.event_sequence,
            kernel_generation = parent.kernel_generation,
            artifact_hashes   = parent.artifact_hashes,
            summary           = f"fork of {parent.checkpoint_id}",
            parent            = parent,
        )
        return self.save(child)

    def _load_disk(self) -> None:
        if not self._persist_dir:
            return
        for path in self._persist_dir.glob("ckpt_*.json"):
            try:
                data = json.loads(path.read_text())
                ckpt = Checkpoint.from_dict(data)
                self._checkpoints[ckpt.checkpoint_id] = ckpt
            except (json.JSONDecodeError, TypeError):
                continue

    def __len__(self) -> int:
        return len(self._checkpoints)

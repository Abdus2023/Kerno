# kerno/core/__init__.py
"""
Core runtime primitives: state transitions and checkpoints.

These are the foundational semantics of the runtime (audit Phase B):
    - StateLedger     — Stateₙ + Action + Observation → Stateₙ₊₁
    - Checkpoint      — a consistent capture point (K-007)
    - CheckpointStore — save/load/fork checkpoints
"""

from kerno.core.state import StateLedger, StateTransition
from kerno.core.checkpoint import Checkpoint, CheckpointStore
from kerno.core.capture import CapturePoint

__all__ = [
    "StateLedger",
    "StateTransition",
    "Checkpoint",
    "CheckpointStore",
    "CapturePoint",
]

# kerno/core/state.py
"""
StateLedger — records every agent state transition (audit #27, #28).

A transition is the formal step of the execution model:

    Stateₙ + Actionₙ + Observationₙ → Stateₙ₊₁

The ledger stores the before/after versions plus the action and
observation, so a session's evolution can be replayed, diffed, and
correlated with the execution event stream (execution_id).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class StateTransition:
    """
    One recorded transition between agent state versions.

    transition_id:  stable identity (correlation key)
    session_id:     owning session
    from_version:   Stateₙ version number
    to_version:     Stateₙ₊₁ version number
    action:         what the agent did (code preview, plan step, ...)
    observation:    what the agent observed (output summary, error class, ...)
    execution_id:   optional cross-reference to the execution event stream
    """

    transition_id: str
    session_id:    str
    from_version:  int
    to_version:    int
    action:        Optional[str] = None
    observation:   Optional[str] = None
    execution_id:  Optional[str] = None
    timestamp:     float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "transition_id": self.transition_id,
            "session_id":    self.session_id,
            "from_version":  self.from_version,
            "to_version":    self.to_version,
            "action":        self.action,
            "observation":   self.observation,
            "execution_id":  self.execution_id,
            "timestamp":     self.timestamp,
        }


class StateLedger:
    """
    Append-only record of state transitions.

    Usage:
        ledger = StateLedger()
        s0 = AgentState(task="...")
        s1 = s0.advance(action="cell 1", observation="ok")
        ledger.record(s0, s1, action="cell 1", observation="ok",
                      execution_id="exec_00000001")
        chain = ledger.chain(session_id)
    """

    def __init__(self):
        self._transitions: list[StateTransition] = []

    def record(
        self,
        state_before: object,
        state_after:  object,
        *,
        action:       Optional[str] = None,
        observation:  Optional[str] = None,
        execution_id: Optional[str] = None,
        session_id:   Optional[str] = None,
    ) -> StateTransition:
        """Record a transition between two state versions."""
        from_version = getattr(state_before, "version", 0)
        to_version   = getattr(state_after, "version", from_version + 1)
        sid = session_id or getattr(state_after, "session_id", "") or ""

        t = StateTransition(
            transition_id = "tr_" + uuid.uuid4().hex[:12],
            session_id    = sid,
            from_version  = from_version,
            to_version    = to_version,
            action        = action,
            observation   = observation,
            execution_id  = execution_id,
        )
        self._transitions.append(t)
        return t

    def chain(self, session_id: str) -> list[StateTransition]:
        """All transitions for a session, in causal order."""
        return [t for t in self._transitions if t.session_id == session_id]

    @property
    def transitions(self) -> tuple[StateTransition, ...]:
        """Immutable view of the full ledger."""
        return tuple(self._transitions)

    @property
    def sequence(self) -> int:
        """Number of transitions recorded (monotonic)."""
        return len(self._transitions)

    def to_dict(self) -> list[dict]:
        return [t.to_dict() for t in self._transitions]

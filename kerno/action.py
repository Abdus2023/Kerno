# kerno/action.py
"""
Action model + state machine (audit #45/#46/#47/#49, P10).

The unit of execution is an Action, not bare code:

    Action(action_id, session_id, agent_id, kind, payload,
           capabilities, timeout_ms, ...)

An action lifecycle has EXPLICIT terminal states — exactly one of
SUCCESS / FAILURE / CANCELLED / REJECTED / EXPIRED (P10) — enforced by
ActionStateMachine, which rejects any transition out of a terminal
state or into an unexpected state.

Not every action requires Python (audit #47): the kind field separates
ExecuteCode from ReadArtifact, WriteArtifact, SearchMemory, etc. The
kernel is merely one execution backend.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class Idempotency(Enum):
    """Retry semantics for an action (audit #50)."""

    SAFE           = auto()   # no side effects → retry automatically
    IDEMPOTENT     = auto()   # side effects safe to repeat with the same key
    NON_IDEMPOTENT = auto()   # repeating may double-apply side effects
    UNKNOWN        = auto()   # don't automatically retry


@dataclass(frozen=True)
class RetryDecision:
    """What the retry policy decided for an action."""

    retry:       bool
    reason:      str
    require_key: bool = False

    def to_dict(self) -> dict:
        return {
            "retry":       self.retry,
            "reason":      self.reason,
            "require_key": self.require_key,
        }


def retry_policy(
    idempotency:    Idempotency,
    *,
    idempotency_key: Optional[str] = None,
    explicit_allow:  bool = False,
) -> RetryDecision:
    """
    Decide whether an action may be retried (audit #50).

    SAFE            → retry automatically
    IDEMPOTENT      → retry only with the same idempotency key
    NON_IDEMPOTENT  → retry only with explicit policy approval
    UNKNOWN         → never retry automatically

    This is what prevents `charge_credit_card()` from running twice when
    the kernel times out after the external service accepted the request.
    """
    if idempotency == Idempotency.SAFE:
        return RetryDecision(True, "safe: no side effects")
    if idempotency == Idempotency.IDEMPOTENT:
        if idempotency_key:
            return RetryDecision(True, "idempotent with key", require_key=True)
        return RetryDecision(
            False, "idempotent but no idempotency key provided",
            require_key=True,
        )
    if idempotency == Idempotency.NON_IDEMPOTENT:
        if explicit_allow:
            return RetryDecision(True, "explicit policy approval")
        return RetryDecision(
            False, "non-idempotent: explicit policy required"
        )
    return RetryDecision(False, "unknown idempotency: no automatic retry")


class ActionKind(Enum):
    EXECUTE_CODE          = auto()
    READ_ARTIFACT         = auto()
    WRITE_ARTIFACT        = auto()
    SEARCH_MEMORY         = auto()
    INVOKE_CAPABILITY     = auto()
    SEND_MESSAGE          = auto()
    CREATE_CHECKPOINT     = auto()
    SPAWN_AGENT           = auto()
    REQUEST_HUMAN_APPROVAL = auto()


@dataclass(frozen=True)
class Action:
    """One unit of execution with a stable identity (audit #46)."""

    action_id:       str
    kind:            ActionKind
    payload:         dict                      = field(default_factory=dict)
    session_id:      str                       = ""
    agent_id:        str                       = ""
    capabilities:    frozenset[str]            = frozenset()
    timeout_ms:      int                       = 120_000
    parent_action_id: Optional[str]            = None
    idempotency:     Idempotency               = Idempotency.UNKNOWN
    idempotency_key: Optional[str]             = None
    created_at:      float                     = field(default_factory=time.time)

    @classmethod
    def new(
        cls,
        kind:          ActionKind,
        *,
        payload:       Optional[dict] = None,
        session_id:    str   = "",
        agent_id:      str   = "",
        capabilities:  Optional[frozenset[str]] = None,
        timeout_ms:    int   = 120_000,
        parent_action_id: Optional[str] = None,
        idempotency:   Idempotency = Idempotency.UNKNOWN,
        idempotency_key: Optional[str] = None,
    ) -> "Action":
        return cls(
            action_id       = "act_" + uuid.uuid4().hex[:12],
            kind            = kind,
            payload         = dict(payload or {}),
            session_id      = session_id,
            agent_id        = agent_id,
            capabilities    = frozenset(capabilities or ()),
            timeout_ms      = timeout_ms,
            parent_action_id= parent_action_id,
            idempotency     = idempotency,
            idempotency_key = idempotency_key,
        )

    @property
    def code(self) -> str:
        """The code payload for EXECUTE_CODE actions."""
        return self.payload.get("code", "")


class ActionStatus(Enum):
    CREATED      = auto()
    VALIDATING   = auto()
    AUTHORIZING  = auto()
    QUEUED       = auto()
    RUNNING      = auto()
    SUCCESS      = auto()
    FAILURE      = auto()
    CANCELLED    = auto()
    REJECTED     = auto()
    EXPIRED      = auto()

    @property
    def terminal(self) -> bool:
        """Exactly-one-terminal-outcome invariant (P10)."""
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES = frozenset({
    ActionStatus.SUCCESS,
    ActionStatus.FAILURE,
    ActionStatus.CANCELLED,
    ActionStatus.REJECTED,
    ActionStatus.EXPIRED,
})


@dataclass(frozen=True)
class StatusTransition:
    from_status: ActionStatus
    to_status:   ActionStatus
    reason:      str = ""
    timestamp:   float = field(default_factory=time.time)


class ActionStateMachine:
    """
    Atomic, monotonic lifecycle for one action (audit #49).

    The machine enforces:
      - only allowed transitions (see ALLOWED)
      - exactly one terminal outcome — no transition out of a terminal
        state is ever accepted (P10)

    Usage:
        sm = ActionStateMachine(action)
        sm.transition(ActionStatus.AUTHORIZING)
        sm.transition(ActionStatus.RUNNING)
        sm.transition(ActionStatus.SUCCESS)
        assert sm.status == ActionStatus.SUCCESS
    """

    ALLOWED: dict[ActionStatus, frozenset[ActionStatus]] = {
        ActionStatus.CREATED:     frozenset({ActionStatus.AUTHORIZING,
                                             ActionStatus.EXPIRED}),
        ActionStatus.VALIDATING:  frozenset({ActionStatus.AUTHORIZING,
                                             ActionStatus.FAILURE,
                                             ActionStatus.EXPIRED}),
        ActionStatus.AUTHORIZING: frozenset({ActionStatus.QUEUED,
                                             ActionStatus.REJECTED,
                                             ActionStatus.EXPIRED}),
        ActionStatus.QUEUED:      frozenset({ActionStatus.RUNNING,
                                             ActionStatus.CANCELLED,
                                             ActionStatus.EXPIRED}),
        ActionStatus.RUNNING:     frozenset({ActionStatus.SUCCESS,
                                             ActionStatus.FAILURE,
                                             ActionStatus.CANCELLED,
                                             ActionStatus.EXPIRED}),
    }

    def __init__(self, action: Action):
        self.action  = action
        self._status = ActionStatus.CREATED
        self._history: list[StatusTransition] = []

    @property
    def status(self) -> ActionStatus:
        return self._status

    @property
    def history(self) -> tuple[StatusTransition, ...]:
        return tuple(self._history)

    def transition(
        self,
        to:     ActionStatus,
        reason: str = "",
    ) -> ActionStatus:
        """
        Move the action to `to`.

        Raises:
            InvalidTransition: if the move is not allowed or the action
                               is already in a terminal state.
        """
        if self._status.terminal:
            raise InvalidTransition(
                self.action.action_id, self._status, to,
                "action is already in terminal state {}".format(self._status.name),
            )
        allowed = self.ALLOWED.get(self._status, frozenset())
        if to not in allowed:
            raise InvalidTransition(
                self.action.action_id, self._status, to,
                "no allowed transition",
            )
        self._history.append(StatusTransition(
            from_status = self._status,
            to_status   = to,
            reason      = reason,
        ))
        self._status = to
        return self._status


class InvalidTransition(RuntimeError):
    """Raised when an action state transition is not allowed."""

    def __init__(self, action_id: str, frm: ActionStatus, to: ActionStatus, why: str):
        self.action_id = action_id
        self.from_status = frm
        self.to_status   = to
        super().__init__(
            "Invalid action transition {}: {} -> {} ({})".format(
                action_id, frm.name, to.name, why
            )
        )

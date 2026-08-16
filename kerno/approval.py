# kerno/approval.py
"""
Human approval as a capability (audit #90).

RequestHumanApproval is an ACTION, not a special case in the agent loop.
The capability broker already defines CAP_HUMAN_APPROVAL; the execution
engine consults an ApprovalGate when an execution requires it:

    Agent
      ↓
    Action: delete production data
      ↓
    capabilities = {..., "human.approval"}
      ↓
    ApprovalGate.request(...)   → APPROVED / DENIED
      ↓
    execute / rejected cell

Security default: FAIL CLOSED. If an execution requires human.approval
and no gate is installed, it is denied — never silently approved.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class ApprovalDecision(Enum):
    APPROVED = auto()
    DENIED   = auto()


@dataclass(frozen=True)
class ApprovalRequest:
    """A request to the gate describing the pending execution."""

    description:  str
    subject:      str = ""
    capabilities: frozenset[str] = frozenset()
    code_preview: str = ""
    execution_id: str = ""

    def to_dict(self) -> dict:
        return {
            "description":  self.description,
            "subject":      self.subject,
            "capabilities": sorted(self.capabilities),
            "code_preview": self.code_preview,
            "execution_id": self.execution_id,
        }


class ApprovalGate(ABC):
    """Interface for human-in-the-loop approval (audit #90)."""

    @abstractmethod
    def request(self, req: ApprovalRequest) -> ApprovalDecision:
        """Return APPROVED or DENIED for the pending execution."""


class AutoApprovalGate(ApprovalGate):
    """Automated gate — configured policy, no human (tests / trusted use)."""

    def __init__(self, decision: ApprovalDecision = ApprovalDecision.DENIED):
        self._decision = decision
        self._requests: list[ApprovalRequest] = []

    def request(self, req: ApprovalRequest) -> ApprovalDecision:
        self._requests.append(req)
        return self._decision

    @property
    def requests(self) -> tuple[ApprovalRequest, ...]:
        return tuple(self._requests)


class DenyByDefaultGate(ApprovalGate):
    """Human-in-the-loop gate: asks a callback; denies if unanswered."""

    def __init__(self, ask: Optional[callable] = None):
        # ask: (ApprovalRequest) -> bool | None  (None → deny)
        self._ask = ask or (lambda req: None)
        self._requests: list[ApprovalRequest] = []

    def request(self, req: ApprovalRequest) -> ApprovalDecision:
        self._requests.append(req)
        answer = self._ask(req)
        return (
            ApprovalDecision.APPROVED if answer is True
            else ApprovalDecision.DENIED
        )

    @property
    def requests(self) -> tuple[ApprovalRequest, ...]:
        return tuple(self._requests)

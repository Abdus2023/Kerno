# kerno/bus.py
"""
AgentBus — explicit message passing between agents (audit #33, Phase D).

K-009 gives agents SEPARATE kernels; SharedMemory gives them immutable
shared VALUES. AgentBus gives them MESSAGES: attributable, addressed,
ordered communication that the loop delivers into the recipient's
context at the start of its turn.

    Agent A → AgentBus.send(msg to B) → Agent B receives on its turn

Messages are first-class: they carry sender, recipient, kind, payload,
and a stable message_id — so they can be audited, replayed, and traced
(which agent said what, when, to whom).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

BROADCAST = "*"


@dataclass(frozen=True)
class AgentMessage:
    """One addressed message between agents (or from the host)."""

    message_id: str
    kind:       str
    payload:    dict
    sender:     str
    recipient:  str              # agent name, or BROADCAST
    timestamp:  float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "kind":       self.kind,
            "payload":    dict(self.payload),
            "sender":     self.sender,
            "recipient":  self.recipient,
            "timestamp":  self.timestamp,
        }

    @classmethod
    def new(
        cls,
        kind:      str,
        payload:   Optional[dict] = None,
        *,
        sender:    str = "host",
        recipient: str = BROADCAST,
    ) -> "AgentMessage":
        return cls(
            message_id = "msg_" + uuid.uuid4().hex[:12],
            kind       = kind,
            payload    = dict(payload or {}),
            sender     = sender,
            recipient  = recipient,
        )


class AgentBus:
    """
    Point-to-point and broadcast message delivery between agents.

    Messages are queued per recipient and delivered ONCE (receive pops).
    pending(agent) shows undelivered messages without consuming them —
    the loop uses it to inject context.
    """

    def __init__(self):
        self._mailboxes: dict[str, list[AgentMessage]] = {}
        self._history:   list[AgentMessage] = []
        self._subscribers: dict[str, list[Callable]] = {}

    # ── Sending ──────────────────────────────────────────────────────────

    def send(self, message: AgentMessage) -> AgentMessage:
        """Queue a message for its recipient (or broadcast to all)."""
        self._history.append(message)
        if message.recipient == BROADCAST:
            for mailbox in self._mailboxes.values():
                mailbox.append(message)
        else:
            self._mailboxes.setdefault(message.recipient, []).append(message)
        self._notify(message)
        return message

    def send_to(
        self,
        recipient: str,
        kind:      str,
        payload:   Optional[dict] = None,
        *,
        sender:    str = "host",
    ) -> AgentMessage:
        return self.send(AgentMessage.new(
            kind, payload, sender=sender, recipient=recipient
        ))

    def broadcast(
        self,
        kind:    str,
        payload: Optional[dict] = None,
        *,
        sender:  str = "host",
    ) -> AgentMessage:
        return self.send(AgentMessage.new(
            kind, payload, sender=sender, recipient=BROADCAST
        ))

    # ── Receiving ────────────────────────────────────────────────────────

    def pending(self, agent: str) -> list[AgentMessage]:
        """Undelivered messages for `agent` (broadcasts included), in order."""
        return list(self._mailboxes.get(agent, []))

    def receive(self, agent: str) -> list[AgentMessage]:
        """Deliver and CONSUME all pending messages for `agent`."""
        messages = self._mailboxes.pop(agent, [])
        return messages

    def has_pending(self, agent: str) -> bool:
        return bool(self._mailboxes.get(agent))

    # ── Subscriptions (host-side observers) ──────────────────────────────

    def subscribe(self, kind: str, handler: Callable[[AgentMessage], None]) -> None:
        self._subscribers.setdefault(kind, []).append(handler)

    def _notify(self, message: AgentMessage) -> None:
        for handler in self._subscribers.get(message.kind, []):
            try:
                handler(message)
            except Exception:
                pass

    # ── Views ────────────────────────────────────────────────────────────

    @property
    def history(self) -> tuple[AgentMessage, ...]:
        """Every message ever sent (immutable audit trail)."""
        return tuple(self._history)

    def messages_from(self, sender: str) -> list[AgentMessage]:
        return [m for m in self._history if m.sender == sender]

    def messages_to(self, recipient: str) -> list[AgentMessage]:
        return [
            m for m in self._history
            if m.recipient == recipient or m.recipient == BROADCAST
        ]

    def __len__(self) -> int:
        return len(self._history)

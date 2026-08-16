# kerno/llm/brain.py
"""
Deterministic brains for replayable tests and dry runs (audit #99/#100).

The runtime depends on an interface, not a provider:

    class Brain(Protocol):
        def __call__(self, messages: list[Message]) -> str: ...

ScriptedBrain implements it deterministically: it returns scripted
responses in order (then a completion cell), and counts calls — so
integration tests can verify an entire agent run without a live model
(audit #100: fully replayable tests), and P7 (replay does not invoke
the Brain) can be asserted via call_count.
"""

from __future__ import annotations

from typing import Optional

from kerno.types import Message


class ScriptedBrain:
    """
    Deterministic LLM: scripted responses, then a completion cell.

    Usage:
        brain = ScriptedBrain(
            "x = 1\\nprint(x)",
            "# TASK_COMPLETE: done",
        )
        out = brain([Message(role="user", content="go")])
        assert brain.call_count == 1

    Args:
        *responses:      exact strings to return, in order
        completion:      fallback returned after responses are exhausted
                         (defaults to a TASK_COMPLETE cell)
    """

    def __init__(
        self,
        *responses:  str,
        completion:  Optional[str] = None,
    ):
        self._responses  = list(responses)
        self._completion = completion or "# TASK_COMPLETE: done"
        self._calls      = 0
        self._history:   list[tuple[list[Message], str]] = []

    def __call__(self, messages: list[Message]) -> str:
        self._calls += 1
        if self._calls <= len(self._responses):
            response = self._responses[self._calls - 1]
        else:
            response = self._completion
        self._history.append((tuple(messages), response))
        return response

    @property
    def call_count(self) -> int:
        """Number of times the brain was invoked."""
        return self._calls

    @property
    def history(self) -> tuple[tuple[tuple[Message, ...], str], ...]:
        """(messages, response) for every call (immutable audit trail)."""
        return tuple(self._history)

    @property
    def exhausted(self) -> bool:
        """True when only the completion fallback remains."""
        return self._calls >= len(self._responses)

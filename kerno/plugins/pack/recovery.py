"""Structured error recovery assistant plugin."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field

from kerno.errors.classifier import ErrorClassifier
from kerno.plugins.registry import BasePlugin


@dataclass
class RecoveryEvent:
    cell: int
    ename: str
    error_class: str
    hint: str
    code: str


class RecoveryAssistantPlugin(BasePlugin):
    """
    Classify each cell error and print concise recovery guidance.

    The plugin also tracks repeated failures so the final session report can
    highlight persistent problem areas.
    """

    name = "recovery_assistant"

    def __init__(self, max_history: int = 20):
        self.classifier = ErrorClassifier()
        self.events: list[RecoveryEvent] = []
        self._history: deque[RecoveryEvent] = deque(maxlen=max_history)

    def on_error(self, cell, classified_error) -> None:
        output = getattr(cell, "output", None)
        error = getattr(output, "error", None)
        ename = getattr(error, "ename", "Error")
        evalue = getattr(error, "evalue", "")

        # Classified errors from unit tests may already carry a class/hint,
        # while real sessions receive a ClassifiedError from ErrorClassifier.
        provided_original = getattr(classified_error, "original", None)
        if provided_original is not None:
            ename = getattr(provided_original, "ename", ename)
            evalue = getattr(provided_original, "evalue", evalue)

        error_class = getattr(getattr(classified_error, "error_class", None), "name", "UNCLASSIFIED")
        hint = getattr(classified_error, "recovery_hint", "Inspect the traceback and retry.")

        event = RecoveryEvent(
            cell=getattr(cell, "cell_num", 0),
            ename=ename,
            error_class=error_class,
            hint=hint,
            code=(cell.code or "")[:200],
        )
        self.events.append(event)
        self._history.append(event)

        repeated = self._repeated(error_class)
        repeat_note = f" (repeated {repeated}x)" if repeated > 1 else ""
        print(
            f"[recovery] cell {event.cell}{repeat_note}: {error_class} — {hint}",
            flush=True,
        )
        if evalue:
            print(f"  {ename}: {evalue[:180]}", flush=True)

    def on_session_complete(self, result) -> None:
        if not self.events:
            return
        counts = Counter(event.error_class for event in self.events)
        top = ", ".join(f"{name}={count}" for name, count in counts.most_common(3))
        print(f"[recovery] error summary: {len(self.events)} error(s); {top}", flush=True)

    def _repeated(self, error_class: str) -> int:
        return sum(1 for event in self._history if event.error_class == error_class)

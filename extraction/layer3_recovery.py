# kerno/errors/recovery.py
"""
RecoveryStrategy: integrates the classifier into the execution loop.

The loop calls this after each failed cell to get a structured
recovery suggestion before the next LLM call.
"""

from __future__ import annotations

from kerno.errors.classifier import ClassifiedError, ErrorClassifier
from kerno.types import CellError, CellOutput, Message


class RecoveryStrategy:
    """
    Wraps ErrorClassifier with loop-level recovery logic.

    Usage (inside a loop's _on_cell_complete):
        recovery = RecoveryStrategy()
        if cell.output.has_error:
            suggestion = recovery.suggest(cell.output.error)
            # Inject suggestion into next LLM message
    """

    def __init__(self):
        self._classifier  = ErrorClassifier()
        self._error_log:  list[ClassifiedError] = []

    def suggest(self, error: CellError) -> tuple[str, bool]:
        """
        Classify an error and return recovery guidance.

        Returns:
            (formatted_hint, requires_replan)
        """
        classified = self._classifier.classify(error)
        self._error_log.append(classified)

        hint = self._classifier.format_for_llm(classified)
        return hint, classified.requires_replan

    def is_stuck(self, window: int = 3) -> bool:
        """
        Detect if the agent is repeating the same error.
        Useful for breaking out of recovery loops.
        """
        if len(self._error_log) < window:
            return False

        last_n  = self._error_log[-window:]
        classes = [e.error_class for e in last_n]

        # Same error class N times in a row
        return len(set(classes)) == 1

    def inject_hint(
        self,
        messages:   list[Message],
        error:      CellError,
    ) -> list[Message]:
        """
        Inject a recovery hint into the message list.
        The hint replaces the raw error output for better LLM guidance.
        """
        hint, _ = self.suggest(error)
        messages.append(Message(
            role    = "user",
            content = f"The previous cell raised an error:\n\n{hint}\n\n"
                      f"Recover by writing a corrected cell."
        ))
        return messages

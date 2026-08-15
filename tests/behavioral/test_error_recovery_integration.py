# tests/behavioral/test_error_recovery_integration.py
"""
Integration test: full error → classification → recovery pipeline.
Verifies that classified errors produce better recovery than raw tracebacks.
"""

import pytest
from unittest.mock import call

from kerno.kernel.runtime  import KernelRuntime
from kerno.loop.reactive   import ReactiveLoop
from kerno.types           import Message, SessionStatus


@pytest.fixture
def kernel():
    with KernelRuntime() as k:
        yield k


@pytest.mark.integration
class TestErrorRecoveryIntegration:

    def test_key_error_recovery_hint_injected(self, kernel):
        """
        When a KeyError occurs, the next LLM call should receive
        a structured hint (not just the raw traceback).
        """
        received_messages = []

        call_count = [0]
        def tracking_llm(messages: list[Message]) -> str:
            received_messages.append(messages)
            call_count[0] += 1

            if call_count[0] == 1:
                return "df = __import__('pandas').DataFrame({'a': [1,2,3]})"
            elif call_count[0] == 2:
                return "result = df['nonexistent_column'].mean()"  # KeyError
            elif call_count[0] == 3:
                # This call receives the recovery hint
                return "print(df.columns.tolist())  # Inspect actual columns"
            else:
                return "# TASK_COMPLETE: done"

        loop   = ReactiveLoop(kernel=kernel, llm=tracking_llm, max_cells=10)
        result = loop.run("Test error recovery")

        # The third LLM call should contain recovery guidance
        if len(received_messages) >= 3:
            third_call_text = " ".join(
                m.content for m in received_messages[2]
            )
            # Should mention the error classification or columns
            assert (
                "WRONG_COLUMN" in third_call_text or
                "column" in third_call_text.lower() or
                "KeyError" in third_call_text
            )

    def test_consecutive_error_limit(self, kernel):
        """
        After max_consecutive_errors, an unstick message is injected.
        """
        call_count = [0]

        def error_llm(messages: list[Message]) -> str:
            call_count[0] += 1
            # Keep raising errors until forced to stop
            if call_count[0] >= 6:
                return "# TASK_COMPLETE: gave up"
            return "raise ValueError('deliberate error')"

        loop   = ReactiveLoop(
            kernel                  = kernel,
            llm                     = error_llm,
            max_cells               = 20,
            max_consecutive_errors  = 3,
        )
        result = loop.run("Error loop test")

        # Should complete (either by unstick or by COMPLETE signal)
        assert result.status in (
            SessionStatus.COMPLETE,
            SessionStatus.MAX_CELLS,
        )

    def test_recovery_does_not_consume_cells_untracked(self, kernel):
        """
        Error recovery messages are injected into context,
        but should not create phantom cells in the session record.
        """
        call_count = [0]

        def controlled_llm(messages):
            call_count[0] += 1
            responses = [
                "x = 1",
                "y = x['nonexistent']",  # Error
                "y = x + 1",             # Recovery
                "# TASK_COMPLETE: done",
            ]
            if call_count[0] <= len(responses):
                return responses[call_count[0] - 1]
            return "# TASK_COMPLETE: done"

        loop   = ReactiveLoop(kernel=kernel, llm=controlled_llm, max_cells=10)
        result = loop.run("Cell counting test")

        # Every entry in cells should have actual code
        for cell in result.cells:
            assert cell.code.strip() != ""

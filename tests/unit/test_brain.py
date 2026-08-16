"""
Unit tests for ScriptedBrain (audit #99/#100) — deterministic brains
for replayable tests and P7 (replay never invokes the Brain).
"""

from kerno.llm.brain import ScriptedBrain
from kerno.types import Message


class TestScriptedBrain:

    def test_returns_scripted_responses_in_order(self):
        brain = ScriptedBrain("x = 1", "print(x)", "# TASK_COMPLETE: done")
        assert brain([Message(role="user", content="go")]) == "x = 1"
        assert brain([]) == "print(x)"
        assert brain([]) == "# TASK_COMPLETE: done"
        assert brain.call_count == 3

    def test_completion_fallback_after_exhaustion(self):
        brain = ScriptedBrain("only one")
        assert brain([]) == "only one"
        # After scripted responses are exhausted → completion cell
        assert brain([]) == "# TASK_COMPLETE: done"
        assert brain([]) == "# TASK_COMPLETE: done"

    def test_custom_completion(self):
        brain = ScriptedBrain(completion="# DONE: finished")
        assert brain([]) == "# DONE: finished"

    def test_call_count_and_exhausted(self):
        brain = ScriptedBrain("a", "b")
        assert brain.call_count == 0
        assert brain.exhausted is False
        brain([])
        assert brain.call_count == 1
        brain([])
        assert brain.call_count == 2
        assert brain.exhausted is True

    def test_history_records_messages_and_responses(self):
        brain = ScriptedBrain("x = 1")
        msgs = [Message(role="user", content="compute")]
        brain(msgs)
        (seen, response), = brain.history
        assert list(seen) == msgs          # stored as an immutable tuple
        assert response == "x = 1"

    def test_immutable_history(self):
        brain = ScriptedBrain("a")
        brain([])
        with pytest_raises():
            brain.history[0][0].append("tampered")


def pytest_raises():
    import pytest
    return pytest.raises(Exception)

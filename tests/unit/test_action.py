"""
Unit tests for the Action model and state machine (audit #45-#49, P10).
"""

import pytest

from kerno.action import (
    Action, ActionKind, ActionStateMachine, ActionStatus,
    InvalidTransition, TERMINAL_STATUSES,
)
from kerno.execution.engine import ExecutionEngine
from kerno.types import CellOutput


class TestActionModel:

    def test_new_generates_id_and_kind(self):
        a = Action.new(ActionKind.EXECUTE_CODE, payload={"code": "x = 1"})
        assert a.action_id.startswith("act_")
        assert a.kind == ActionKind.EXECUTE_CODE
        assert a.code == "x = 1"
        assert a.timeout_ms == 120_000

    def test_kinds_cover_non_code_actions(self):
        kinds = {k.name for k in ActionKind}
        assert {
            "EXECUTE_CODE", "READ_ARTIFACT", "WRITE_ARTIFACT",
            "SEARCH_MEMORY", "INVOKE_CAPABILITY", "SEND_MESSAGE",
            "CREATE_CHECKPOINT", "SPAWN_AGENT", "REQUEST_HUMAN_APPROVAL",
        } <= kinds

    def test_parent_link(self):
        parent = Action.new(ActionKind.EXECUTE_CODE)
        child  = Action.new(
            ActionKind.EXECUTE_CODE, parent_action_id=parent.action_id
        )
        assert child.parent_action_id == parent.action_id


class TestStateMachine:
    """P10: exactly one terminal outcome; no transitions out of it."""

    def test_happy_path(self):
        sm = ActionStateMachine(Action.new(ActionKind.EXECUTE_CODE))
        sm.transition(ActionStatus.AUTHORIZING)
        sm.transition(ActionStatus.QUEUED)
        sm.transition(ActionStatus.RUNNING)
        sm.transition(ActionStatus.SUCCESS)
        assert sm.status == ActionStatus.SUCCESS
        assert sm.status.terminal

    def test_rejected_is_terminal(self):
        sm = ActionStateMachine(Action.new(ActionKind.EXECUTE_CODE))
        sm.transition(ActionStatus.AUTHORIZING)
        sm.transition(ActionStatus.REJECTED)
        assert sm.status.terminal

    def test_no_transition_after_terminal(self):
        sm = ActionStateMachine(Action.new(ActionKind.EXECUTE_CODE))
        sm.transition(ActionStatus.AUTHORIZING)
        sm.transition(ActionStatus.QUEUED)
        sm.transition(ActionStatus.RUNNING)
        sm.transition(ActionStatus.FAILURE)
        with pytest.raises(InvalidTransition):
            sm.transition(ActionStatus.SUCCESS)  # already FAILURE — locked

    def test_illegal_transition_rejected(self):
        sm = ActionStateMachine(Action.new(ActionKind.EXECUTE_CODE))
        with pytest.raises(InvalidTransition):
            sm.transition(ActionStatus.SUCCESS)  # CREATED → SUCCESS not allowed

    def test_history_records_causal_chain(self):
        sm = ActionStateMachine(Action.new(ActionKind.EXECUTE_CODE))
        sm.transition(ActionStatus.AUTHORIZING)
        sm.transition(ActionStatus.QUEUED)
        assert [t.from_status for t in sm.history] == [
            ActionStatus.CREATED, ActionStatus.AUTHORIZING,
        ]
        assert [t.to_status for t in sm.history] == [
            ActionStatus.AUTHORIZING, ActionStatus.QUEUED,
        ]

    def test_terminal_statuses_enum(self):
        assert TERMINAL_STATUSES == frozenset({
            ActionStatus.SUCCESS, ActionStatus.FAILURE,
            ActionStatus.CANCELLED, ActionStatus.REJECTED,
            ActionStatus.EXPIRED,
        })


class TestEngineActionCorrelation:
    """The engine drives the state machine and correlates action_id."""

    class FakeKernel:
        def execute(self, code, timeout=120.0, silent=False):
            return CellOutput(stdout="ok")

        def execute_silent(self, code, timeout=15.0):
            return "ok"

        @property
        def namespace(self):
            return "{}"

        @property
        def is_alive(self):
            return True

    def test_success_drives_action_to_success(self):
        action = Action.new(ActionKind.EXECUTE_CODE, payload={"code": "x = 1"})
        engine = ExecutionEngine(self.FakeKernel())

        out = engine.execute("x = 1", action=action)

        assert not out.has_error
        assert out.execution_id is not None
        # Record correlates the action
        assert engine.records[0].action_id == action.action_id
        # Events correlate the action
        assert all(
            e.payload.get("action_id") == action.action_id
            for e in engine.events if "action_id" in e.payload
        )

    def test_policy_denial_rejects_action(self):
        from kerno.security.allowlist import AllowList
        action = Action.new(ActionKind.EXECUTE_CODE)
        engine = ExecutionEngine(
            self.FakeKernel(), allowlist=AllowList.data_analysis()
        )

        out = engine.execute("import subprocess", action=action)

        assert out.has_error
        assert out.error.ename == "AllowListViolation"
        assert engine.records[0].allowed is False
        assert engine.records[0].action_id == action.action_id

    def test_failed_cell_marks_action_failure(self):
        class FailingKernel:
            def execute(self, code, timeout=120.0, silent=False):
                from kerno.types import CellError
                return CellOutput(error=CellError("ValueError", "boom"))

            def execute_silent(self, code, timeout=15.0):
                return ""

            @property
            def namespace(self):
                return "{}"

            @property
            def is_alive(self):
                return True

        action = Action.new(ActionKind.EXECUTE_CODE)
        engine = ExecutionEngine(FailingKernel())
        engine.execute("bad()", action=action)
        assert engine.records[0].had_error is True

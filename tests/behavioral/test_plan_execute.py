# tests/behavioral/test_plan_execute.py
"""Behavioral tests for PlanExecuteLoop."""

import json
import pytest
from unittest.mock import MagicMock

from kerno.kernel.runtime   import KernelRuntime
from kerno.loop.plan_execute import PlanExecuteLoop
from kerno.types             import Message, SessionStatus


def make_mock_llm(plan_json: str, execution_responses: list[str]):
    """
    LLM mock that returns plan_json on first call,
    then execution_responses in sequence,
    then verification responses (always success),
    then COMPLETE signal.
    """
    call_log = []

    def llm(messages: list[Message]) -> str:
        call_log.append(messages)
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )

        # First call: planning
        if len(call_log) == 1:
            return plan_json

        # Verification calls: return success JSON
        if "Did the step succeed" in last_user or "You just executed step" in last_user:
            return '{"success": true, "reason": "ok", "unexpected": null}'

        # Execution calls occur once per non-planning/non-verification LLM call.
        execution_calls = [
            log for log in call_log[1:]
            if not any("Did the step succeed" in (m.content or "") for m in log)
            and not any("You just executed step" in (m.content or "") for m in log)
        ]
        idx = len(execution_calls) - 1
        if 0 <= idx < len(execution_responses):
            return execution_responses[idx]

        return "# TASK_COMPLETE: all steps done"

    llm.call_log = call_log
    return llm


@pytest.fixture
def kernel():
    with KernelRuntime() as k:
        yield k


SIMPLE_PLAN = json.dumps([
    {"id": 1, "description": "Set x to 10",   "success_criterion": "x == 10",   "depends_on": []},
    {"id": 2, "description": "Set y to x * 2", "success_criterion": "y == 20",   "depends_on": [1]},
])


@pytest.mark.integration
class TestPlanExecuteLoop:

    def test_generates_plan_before_execution(self, kernel):
        responses = ["x = 10", "y = x * 2"]
        llm       = make_mock_llm(SIMPLE_PLAN, responses)
        loop      = PlanExecuteLoop(kernel=kernel, llm=llm, max_cells=20)

        result = loop.run("Test plan-execute task")

        # Plan should have been generated
        assert len(loop._plan) == 2
        assert loop._plan[0].description == "Set x to 10"

    def test_executes_all_plan_steps(self, kernel):
        responses = ["x = 10\nprint(x)", "y = x * 2\nprint(y)"]
        llm       = make_mock_llm(SIMPLE_PLAN, responses)
        loop      = PlanExecuteLoop(kernel=kernel, llm=llm, max_cells=20)

        result = loop.run("Two-step test")

        assert result.cells_executed >= 2

    def test_state_persists_between_steps(self, kernel):
        responses = [
            "x = 42\nprint('x set to', x)",
            "y = x * 2\nprint('y =', y)",
        ]
        llm  = make_mock_llm(SIMPLE_PLAN, responses)
        loop = PlanExecuteLoop(kernel=kernel, llm=llm, max_cells=20)

        result = loop.run("State persistence test")

        # Find cell that printed y
        outputs = [c.output.stdout for c in result.cells if "y =" in c.output.stdout]
        assert any("84" in o for o in outputs)

    def test_plan_stored_as_attribute(self, kernel):
        llm  = make_mock_llm(SIMPLE_PLAN, ["x = 1"])
        loop = PlanExecuteLoop(kernel=kernel, llm=llm, max_cells=5)
        loop.run("Attribute test")

        assert hasattr(loop, "_plan")
        assert len(loop._plan) > 0

    def test_verbose_does_not_raise(self, kernel):
        llm  = make_mock_llm(
            SIMPLE_PLAN,
            ["x = 10\nprint(x)", "y = x * 2\nprint(y)"],
        )
        loop = PlanExecuteLoop(kernel=kernel, llm=llm, max_cells=10, verbose=True)

        # Should not raise even with verbose=True
        loop.run("Verbose test")

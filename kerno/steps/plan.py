# kerno/steps/plan.py
"""
Plan and verify steps for PlanExecuteLoop.
"""

from __future__ import annotations

import json
import re

from kerno.interfaces import AgentState


class PlanStep:
    """Generate an execution plan before any kernel calls."""

    _PROMPT = """\
Before writing any code, produce a numbered execution plan for this task.
Task: {task}

Output ONLY valid JSON:
[{{"id": 1, "description": "...", "success_criterion": "...", "depends_on": []}}]
"""

    def __init__(self, llm):
        self.llm = llm

    def run(self, state: AgentState) -> AgentState:
        from kerno.types import Message

        raw  = self.llm([Message(
            role    = "user",
            content = self._PROMPT.format(task=state.task)
        )])
        raw  = re.sub(r'```(?:json)?\s*', '', raw).strip()

        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            plan = []

        state.metadata["plan"]         = plan
        state.metadata["plan_step_idx"]= 0
        return state


class VerifyStep:
    """After each cell, verify whether the current plan step succeeded."""

    _PROMPT = """\
Did this step succeed?
Step: {description}
Success criterion: {criterion}
Output: {output}
JSON only: {{\"success\": true/false, \"reason\": \"...\"}}
"""

    def __init__(self, llm):
        self.llm = llm

    def run(self, state: AgentState) -> AgentState:
        plan     = state.metadata.get("plan", [])
        step_idx = state.metadata.get("plan_step_idx", 0)

        if step_idx >= len(plan) or not state.history:
            state.complete = True
            return state

        step   = plan[step_idx]
        output = state.history[-1].output.as_text(max_chars=800)

        from kerno.types import Message
        raw = self.llm([Message(
            role    = "user",
            content = self._PROMPT.format(
                description = step["description"],
                criterion   = step.get("success_criterion", ""),
                output      = output,
            )
        )])

        try:
            raw    = re.sub(r'```(?:json)?\s*', '', raw).strip()
            result = json.loads(raw)
            if result.get("success"):
                state.metadata["plan_step_idx"] = step_idx + 1
                if state.metadata["plan_step_idx"] >= len(plan):
                    state.complete = True
        except (json.JSONDecodeError, KeyError):
            state.metadata["plan_step_idx"] = step_idx + 1

        return state

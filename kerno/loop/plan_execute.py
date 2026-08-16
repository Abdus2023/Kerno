# kerno/loop/plan_execute.py
"""
PlanExecuteLoop: plan first, execute against the plan.

Difference from ReactiveLoop:
  - One planning call before any kernel execution
  - Each cell is explicitly tied to a plan step
  - LLM verifies step completion before advancing
  - Plan can be revised if a step fails unexpectedly

Best for: multi-phase analyses, ETL pipelines, tasks with known structure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from kerno.loop.base import BaseLoop, COMPLETE_SIGNAL
from kerno.types import Cell, Message, SessionResult, SessionStatus


@dataclass
class PlanStep:
    id:                  int
    description:         str
    success_criterion:   str
    depends_on:          list[int] = field(default_factory=list)
    status:              str       = "pending"   # pending | running | done | failed
    cell_range:          list[int] = field(default_factory=list)  # which cells covered this step


_PLAN_PROMPT = """\
Before writing any code, produce a numbered execution plan for this task.

Task: {task}

Rules for the plan:
- 3 to 7 steps maximum
- Each step is a discrete, independently verifiable action
- Each step has a concrete success criterion (something checkable in Python)
- Identify dependencies between steps (step N may depend on step M)
- Flag steps that might fail and need fallback

Respond with ONLY valid JSON — no prose, no markdown fences.

Format:
[
  {{
    "id": 1,
    "description": "Load and validate the raw data",
    "success_criterion": "df is a DataFrame with at least 100 rows and no null index",
    "depends_on": []
  }},
  ...
]
"""

_STEP_PROMPT = """\
You are on step {step_id} of {total_steps}.

Step description:   {description}
Success criterion:  {success_criterion}

Current kernel namespace:
{namespace}

Prior steps completed:
{prior_summary}

Write Python code to complete THIS STEP ONLY.
At the end of your code, verify the success criterion with an assert or print.
"""

_VERIFY_PROMPT = """\
You just executed step {step_id}: "{description}"
Success criterion: {success_criterion}

Output:
{output}

Did the step succeed? Reply with JSON only:
{{"success": true/false, "reason": "one sentence", "unexpected": "anything surprising or null"}}
"""

_REPLAN_PROMPT = """\
Step {step_id} failed or produced unexpected results.

Original plan remaining:
{remaining_plan}

What happened:
{what_happened}

Revise the remaining plan. Keep completed steps as-is.
Respond with ONLY JSON — the revised list of remaining steps.
"""


class PlanExecuteLoop(BaseLoop):
    """
    Plan → Execute step 1 → Verify → Execute step 2 → ...

    The plan is a stable reference that anchors the LLM's
    understanding even as execution detail accumulates.
    """

    def __init__(self, *args, replan_on_failure: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self._plan:          list[PlanStep]  = []
        self._current_step:  int             = 0
        self._step_summaries: list[str]      = []
        self._replan_on_failure = replan_on_failure

    # ── Override run() to inject planning phase ────────────────────────────────

    def run(
        self,
        task:            str,
        *,
        initial_history: Optional[list] = None,
        initial_summary: str = "",
        cancel_token:    Optional[object] = None,
    ) -> SessionResult:
        """
        Extended run: plan first, then delegate to base execution loop.
        """
        self._task = task

        # Phase 1: Generate plan (no kernel execution)
        self._plan = self._generate_plan(task)

        if self.verbose:
            self._print_plan()

        # Phase 2: Execute against plan
        return super().run(
            task,
            initial_history = initial_history,
            initial_summary = initial_summary,
            cancel_token    = cancel_token,
        )

    # ── Core loop implementation ───────────────────────────────────────────────

    def _next_cell(self, cell_num: int) -> str:
        """
        Generate code for the current plan step.
        After each cell, verify and advance the step pointer.
        """
        if self._current_step >= len(self._plan):
            # All steps done — signal completion
            return (
                f"# All {len(self._plan)} plan steps completed.\n"
                f"{COMPLETE_SIGNAL}: Task finished successfully"
            )

        step = self._plan[self._current_step]
        step.status = "running"
        step.cell_range.append(cell_num)

        prior_summary = "\n".join(
            f"  Step {i+1}: {s}"
            for i, s in enumerate(self._step_summaries)
        ) or "None yet."

        content = _STEP_PROMPT.format(
            step_id     = step.id,
            total_steps = len(self._plan),
            description = step.description,
            success_criterion = step.success_criterion,
            namespace   = self.kernel.namespace,
            prior_summary = prior_summary,
        )

        messages = self._build_messages()
        messages.append(Message(role="user", content=content))

        return self._call_llm(messages)

    def _on_cell_complete(self, cell: Cell) -> None:
        """
        After each cell, verify whether the current step succeeded.
        Advance step pointer or trigger replanning.
        """
        if self._current_step >= len(self._plan):
            return

        step      = self._plan[self._current_step]
        succeeded = self._verify_step(step, cell)

        if succeeded:
            step.status = "done"
            self._step_summaries.append(
                f"{step.description} — {step.success_criterion}"
            )
            self._current_step += 1

            if self.verbose:
                remaining = len(self._plan) - self._current_step
                print(
                    f"  ✓ Step {step.id} complete. "
                    f"{remaining} step(s) remaining."
                )

        else:
            step.status = "failed"

            if self._replan_on_failure:
                self._replan_from(self._current_step, cell)
            else:
                # Retry the same step (up to base loop's max_cells limit)
                if self.verbose:
                    print(f"  ✗ Step {step.id} failed — retrying.")

    # ── Planning Helpers ──────────────────────────────────────────────────────

    def _generate_plan(self, task: str) -> list[PlanStep]:
        """Call LLM to produce a structured plan before any execution."""
        messages = [Message(
            role="user",
            content=_PLAN_PROMPT.format(task=task)
        )]
        raw = self._call_llm(messages)
        return self._parse_plan(raw)

    def _parse_plan(self, raw: str) -> list[PlanStep]:
        """Parse LLM plan response into PlanStep objects."""
        # Strip markdown fences if LLM added them despite instructions
        raw   = re.sub(r"```(?:json)?\s*", "", raw).strip()
        steps = json.loads(raw)

        return [
            PlanStep(
                id=s["id"],
                description=s["description"],
                success_criterion=s.get("success_criterion", "no criterion"),
                depends_on=s.get("depends_on", []),
            )
            for s in steps
        ]

    def _verify_step(self, step: PlanStep, cell: Cell) -> bool:
        """Ask LLM whether a step succeeded based on cell output."""
        content = _VERIFY_PROMPT.format(
            step_id    = step.id,
            description= step.description,
            success_criterion = step.success_criterion,
            output     = cell.output.as_text(max_chars=1000),
        )

        raw = self._call_llm([Message(role="user", content=content)])

        try:
            raw   = re.sub(r"```(?:json)?\s*", "", raw).strip()
            result = json.loads(raw)
            return bool(result.get("success", False))
        except (json.JSONDecodeError, KeyError):
            # Verification call failed — assume success and continue
            return not cell.output.has_error

    def _replan_from(self, failed_step_idx: int, cell: Cell) -> None:
        """Revise the remaining plan after a step failure."""
        remaining = self._plan[failed_step_idx:]
        what_happened = (
            f"Step {self._plan[failed_step_idx].id} "
            f"'{self._plan[failed_step_idx].description}' failed.\n"
            f"Output: {cell.output.as_text(max_chars=500)}"
        )

        content = _REPLAN_PROMPT.format(
            step_id        = self._plan[failed_step_idx].id,
            remaining_plan = json.dumps([
                {"id": s.id, "description": s.description,
                 "success_criterion": s.success_criterion}
                for s in remaining
            ], indent=2),
            what_happened  = what_happened,
        )

        raw = self._call_llm([Message(role="user", content=content)])

        try:
            raw       = re.sub(r"```(?:json)?\s*", "", raw).strip()
            new_steps = json.loads(raw)

            revised = [
                PlanStep(
                    id=s["id"],
                    description=s["description"],
                    success_criterion=s.get("success_criterion", ""),
                    depends_on=s.get("depends_on", []),
                )
                for s in new_steps
            ]

            # Keep completed steps, replace remaining
            self._plan = self._plan[:failed_step_idx] + revised

            if self.verbose:
                print(f"  🔄 Replanned: {len(revised)} revised step(s).")

        except (json.JSONDecodeError, KeyError):
            # Replan failed — just retry current step
            pass

    def _print_plan(self) -> None:
        print("\n╔══ EXECUTION PLAN ═══════════════════════════════╗")
        for step in self._plan:
            deps = f" (needs: {step.depends_on})" if step.depends_on else ""
            print(f"║  {step.id}. {step.description}{deps}")
            print(f"║     ✓ {step.success_criterion}")
        print("╚═════════════════════════════════════════════════╝")

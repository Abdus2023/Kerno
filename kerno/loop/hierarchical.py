# kerno/loop/hierarchical.py
"""
HierarchicalLoop: a Planner LLM + Executor LLM operating on one shared kernel.

Why two LLMs?
  Planner:  expensive model, few calls, strategic decomposition
  Executor: cheap model,     many calls, tactical code generation

The kernel is shared. State flows between Planner and Executor
through the kernel namespace — not through message passing.

Economics (approximate):
  Single GPT-4 loop:        20-50 calls × expensive = high cost
  Hierarchical:             3-5 planner calls + 20-50 executor calls
                            = low total (few expensive + many cheap)
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from kerno.context.builder    import PromptBuilder
from kerno.context.compressor import HistoryCompressor
from kerno.errors.recovery    import RecoveryStrategy
from kerno.kernel.runtime     import KernelRuntime
from kerno.types import (
    Cell, CellOutput, LLMCallable, Message,
    SessionResult, SessionStatus,
)


COMPLETE_SIGNAL = "# TASK_COMPLETE"


@dataclass
class Subtask:
    id:                  int
    description:         str
    success_criterion:   str
    depends_on:          list[int] = field(default_factory=list)
    status:              str       = "pending"
    cells:               list[Cell] = field(default_factory=list)
    summary:             str       = ""
    unexpected_findings: str       = ""


_DECOMPOSE_PROMPT = """\
You are a senior analyst decomposing a complex task into subtasks for a junior executor.

Task: {task}

Decompose into 3-7 subtasks. Each must be:
  - Independently executable in a Python kernel
  - Verifiable (has a concrete success criterion)
  - Appropriately scoped (not too small, not too large)

Respond with ONLY valid JSON, no prose:
[
  {{
    "id": 1,
    "description": "Load and validate the raw data",
    "success_criterion": "df is a non-empty DataFrame with expected columns",
    "depends_on": []
  }}
]
"""

_SYNTHESIZE_PROMPT = """\
All subtasks are complete. Synthesize the findings into a final answer.

Task: {task}

Completed subtasks:
{subtask_summaries}

Final namespace state:
{namespace}

Write a concise synthesis (3-10 sentences):
  1. What was accomplished
  2. Key findings or results
  3. Any important caveats or unexpected discoveries
"""

_EXECUTOR_SYSTEM = """\
You are a Python code executor working inside a Jupyter kernel.
You implement ONE specific subtask at a time.

Current subtask:
  Description:        {description}
  Success criterion:  {success_criterion}

Context from prior subtasks:
{context}

Current kernel namespace:
{namespace}

Rules:
  - Write one focused Python cell per response
  - Verify the success criterion in your code (print or assert)
  - Signal completion with: # SUBTASK_COMPLETE: <one line summary>
  - Do NOT attempt other subtasks
"""

_ASSESS_PROMPT = """\
Subtask {subtask_id} just completed.

Subtask description: {description}
Success criterion:   {success_criterion}

Cell output:
{output}

Current namespace: {namespace}

Assess:
1. Did the subtask succeed? (true/false)
2. One-sentence summary of what was produced
3. Any unexpected findings that might affect the overall plan?

JSON only:
{{"success": true, "summary": "...", "unexpected": "..." or null}}
"""


class HierarchicalLoop:
    """
    Two-LLM agent: strategic Planner + tactical Executor.

    The Planner sees the big picture and decomposes tasks.
    The Executor writes Python cells for each subtask.
    Both operate on the same shared kernel.

    Usage:
        agent = HierarchicalLoop(
            kernel       = kernel,
            planner_llm  = expensive_model_fn,
            executor_llm = cheap_model_fn,
        )
        result = agent.run("Analyze Q3 sales performance")
    """

    def __init__(
        self,
        kernel:          KernelRuntime,
        planner_llm:     LLMCallable,
        executor_llm:    LLMCallable,
        max_cells_per_subtask: int   = 15,
        cell_timeout:    float       = 120.0,
        verbose:         bool        = False,
        cancel_token:   Optional[object] = None,   # cancellation (audit #83)
    ):
        self.kernel                   = kernel
        self.planner_llm              = planner_llm
        self.executor_llm             = executor_llm
        self.max_cells_per_subtask    = max_cells_per_subtask
        self.cell_timeout             = cell_timeout
        self.verbose                  = verbose
        self.cancel_token             = cancel_token

        self._builder    = PromptBuilder()
        self._compressor = HistoryCompressor(executor_llm)  # Compress with cheap model
        self._recovery   = RecoveryStrategy()

        self._subtasks:  list[Subtask] = []
        self._all_cells: list[Cell]    = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, task: str) -> SessionResult:
        """
        Run a task with hierarchical planning and execution.

        Phase 1: Planner decomposes task (1 expensive call)
        Phase 2: Executor handles each subtask (many cheap calls)
        Phase 3: Planner synthesizes (1 expensive call)
        """
        session_id = str(uuid.uuid4())
        started_at = time.time()
        status     = SessionStatus.COMPLETE   # completed unless cancelled

        # ── Phase 1: Decompose ─────────────────────────────────────────────
        if self.verbose:
            print("\n╔══ PLANNER: Decomposing task ═══════════════╗")

        self._subtasks = self._decompose(task)

        if self.verbose:
            for st in self._subtasks:
                print(f"║  {st.id}. {st.description}")
            print("╚═══════════════════════════════════════════╝")

        # ── Phase 2: Execute subtasks ──────────────────────────────────────
        for subtask in self._subtasks:
            # Audit #83: cancellation stops the session between subtasks.
            if (
                self.cancel_token is not None
                and self.cancel_token.is_set()
            ):
                status = SessionStatus.INTERRUPTED
                break

            # Check dependencies
            unmet = [
                d for d, s in zip(
                    subtask.depends_on,
                    [self._subtasks[d - 1] for d in subtask.depends_on
                     if d <= len(self._subtasks)]
                )
                if s.status != "done"
            ]
            if unmet:
                if self.verbose:
                    print(f"  ⊘ Skipping subtask {subtask.id} — unmet dependencies: {unmet}")
                subtask.status = "skipped"
                continue

            if self.verbose:
                print(f"\n── Executor: Subtask {subtask.id}/{len(self._subtasks)} ──")
                print(f"   {subtask.description}")

            self._execute_subtask(subtask, task)

            # Planner re-evaluates if something unexpected happened
            if subtask.unexpected_findings and self.verbose:
                print(f"  ⚡ Unexpected: {subtask.unexpected_findings}")

        # ── Phase 3: Synthesize (skipped entirely when cancelled) ────────
        cancelled = (
            self.cancel_token is not None and self.cancel_token.is_set()
        )
        if cancelled:
            status = SessionStatus.INTERRUPTED

        if not cancelled:
            if self.verbose:
                print("\n╔══ PLANNER: Synthesizing results ═══════════╗")

            synthesis = self._synthesize(task)
        else:
            synthesis = "Session interrupted by cancellation."

            # Add synthesis as a final cell
            synthesis_output = self.kernel.execute(
                f'from IPython.display import display, Markdown\n'
                f'display(Markdown("""\n## Final Synthesis\n{synthesis}\n"""))',
                timeout=10,
            )
            self._all_cells.append(Cell(
                code     = f"# TASK_COMPLETE: see synthesis above\n# {synthesis[:200]}",
                output   = synthesis_output,
                cell_num = len(self._all_cells) + 1,
                author   = "planner",
                reasoning= synthesis,
            ))

            if self.verbose:
                print(synthesis[:300])
                print("╚═══════════════════════════════════════════╝")

        return SessionResult(
            session_id      = session_id,
            task            = task,
            status          = status,
            cells           = self._all_cells,
            final_namespace = self.kernel.namespace,
            summary         = synthesis,
            started_at      = started_at,
            ended_at        = time.time(),
        )

    # ── Planning ──────────────────────────────────────────────────────────────

    def _decompose(self, task: str) -> list[Subtask]:
        """Call planner to decompose task into subtasks."""
        raw = self.planner_llm([
            Message(
                role    = "user",
                content = _DECOMPOSE_PROMPT.format(task=task),
            )
        ])
        return self._parse_subtasks(raw)

    def _parse_subtasks(self, raw: str) -> list[Subtask]:
        raw   = re.sub(r"```(?:json)?\s*", "", raw).strip()
        items = json.loads(raw)
        return [
            Subtask(
                id=item["id"],
                description=item["description"],
                success_criterion=item.get("success_criterion", ""),
                depends_on=item.get("depends_on", []),
            )
            for item in items
        ]

    def _synthesize(self, task: str) -> str:
        """Call planner to synthesize all subtask results."""
        summaries = "\n".join(
            f"  {st.id}. [{st.status.upper()}] {st.description}\n"
            f"     Result: {st.summary or '(no summary)'}"
            + (f"\n     Unexpected: {st.unexpected_findings}"
               if st.unexpected_findings else "")
            for st in self._subtasks
        )
        return self.planner_llm([
            Message(
                role    = "user",
                content = _SYNTHESIZE_PROMPT.format(
                    task             = task,
                    subtask_summaries= summaries,
                    namespace        = self.kernel.namespace,
                ),
            )
        ])

    # ── Execution ─────────────────────────────────────────────────────────────

    def _execute_subtask(self, subtask: Subtask, task: str) -> None:
        """
        Run the Executor loop for a single subtask.
        Uses the cheap LLM for all code generation.
        """
        subtask.status = "running"

        # Build context from completed subtasks
        context = "\n".join(
            f"  Subtask {st.id} ({st.status}): {st.summary}"
            for st in self._subtasks
            if st.status == "done" and st.summary
        ) or "No prior subtasks complete."

        history: list[Message] = []

        for cell_num in range(1, self.max_cells_per_subtask + 1):

            # Build executor messages
            system_content = _EXECUTOR_SYSTEM.format(
                description       = subtask.description,
                success_criterion = subtask.success_criterion,
                context           = context,
                namespace         = self.kernel.namespace,
            )

            messages = [Message(role="system", content=system_content)]
            messages.extend(history[-10:])   # Last 5 exchanges

            # Inject recovery hint if pending
            hint = getattr(self, "_pending_hint", None)
            if hint:
                messages.append(Message(
                    role    = "user",
                    content = f"Previous error:\n{hint}\nWrite a corrected cell."
                ))
                self._pending_hint = None

            # Generate code
            # Audit #83: a cancelled session never starts a new cell.
            if (
                self.cancel_token is not None
                and self.cancel_token.is_set()
            ):
                break

            code   = self.executor_llm(messages)
            exec_kwargs = {}
            if self.cancel_token is not None:
                exec_kwargs["cancel_event"] = self.cancel_token
            output = self.kernel.execute(
                code, timeout=self.cell_timeout, **exec_kwargs
            )

            if self.verbose:
                status_icon = "✗" if output.has_error else "→"
                preview     = output.as_text(max_chars=120)
                print(f"    [{cell_num}] {status_icon} {preview}")

            cell = Cell(
                code     = code,
                output   = output,
                cell_num = len(self._all_cells) + 1,
                author   = "executor",
            )
            subtask.cells.append(cell)
            self._all_cells.append(cell)

            # Update conversation
            history.append(Message(role="assistant", content=code))
            history.append(Message(
                role    = "user",
                content = f"Output:\n{output.as_text(max_chars=600)}"
            ))

            # Error handling
            if output.has_error:
                hint, _ = self._recovery.suggest(output.error)
                self._pending_hint = hint
                continue

            # Completion check
            if "# SUBTASK_COMPLETE" in code or "# TASK_COMPLETE" in code:
                break

        # Planner assesses the subtask outcome
        self._assess_subtask(subtask)

    def _assess_subtask(self, subtask: Subtask) -> None:
        """
        Planner assesses subtask outcome.
        Records summary and any unexpected findings.
        Uses the planner (expensive) LLM — but only once per subtask.
        """
        last_output = (
            subtask.cells[-1].output.as_text(max_chars=800)
            if subtask.cells else "[no output]"
        )

        raw = self.planner_llm([
            Message(
                role    = "user",
                content = _ASSESS_PROMPT.format(
                    subtask_id        = subtask.id,
                    description       = subtask.description,
                    success_criterion = subtask.success_criterion,
                    output            = last_output,
                    namespace         = self.kernel.namespace,
                ),
            )
        ])

        try:
            raw    = re.sub(r"```(?:json)?\s*", "", raw).strip()
            result = json.loads(raw)

            subtask.status               = "done" if result.get("success") else "failed"
            subtask.summary              = result.get("summary", "")
            subtask.unexpected_findings  = result.get("unexpected") or ""

        except (json.JSONDecodeError, KeyError):
            subtask.status  = "done"
            subtask.summary = last_output[:200]

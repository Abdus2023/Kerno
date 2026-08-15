# kerno/loop/debate.py
"""
DebateLoop: two agents argue opposite positions, a judge decides.

Inspired by Constitutional AI and adversarial collaboration.
Better than a single agent for:
  - Tasks where the "obvious" answer is wrong
  - High-stakes decisions requiring challenge
  - Finding edge cases and failure modes
  - Producing balanced analyses

Architecture:
  Proposer  → argues FOR a hypothesis / approach
  Challenger → argues AGAINST, finds flaws
  Judge      → evaluates arguments, produces final verdict

All three operate on the shared kernel.
The debate transcript is written to the kernel namespace.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from kerno.context.builder  import PromptBuilder
from kerno.errors.recovery  import RecoveryStrategy
from kerno.kernel.runtime   import KernelRuntime
from kerno.telemetry.logger import get_logger
from kerno.types import (
    Cell, CellOutput, LLMCallable, Message,
    SessionResult, SessionStatus,
)

log = get_logger("kerno.debate")

COMPLETE_SIGNAL = "# TASK_COMPLETE"


@dataclass
class DebateRound:
    """One exchange in the debate."""
    round_num:   int
    proposition: str    # Proposer's argument
    challenge:   str    # Challenger's counter
    evidence:    list[Cell] = field(default_factory=list)


@dataclass
class Verdict:
    """Judge's final verdict."""
    winner:       str    # "proposer" | "challenger" | "draw"
    confidence:   float  # 0.0 – 1.0
    reasoning:    str
    final_answer: str
    caveats:      list[str] = field(default_factory=list)


_PROPOSER_SYSTEM = """\
You are the PROPOSER agent in a structured debate.

Task: {task}
Your position: {position}

Your job:
  1. Argue FOR your position using data and code
  2. Write Python to support your argument empirically
  3. Anticipate objections and preempt them
  4. Be specific: use numbers, not vague claims

After your code produces output, summarize your argument in a comment:
# ARGUMENT: <one clear sentence stating what you proved>

You are debating round {round_num} of {total_rounds}.
Prior challenger arguments: {prior_challenges}
"""

_CHALLENGER_SYSTEM = """\
You are the CHALLENGER agent in a structured debate.

Task: {task}
You are challenging: {proposition}

Your job:
  1. Find flaws in the proposer's argument
  2. Write Python to test edge cases and counter-evidence
  3. Check assumptions, sample bias, data quality issues
  4. If the proposer is correct, say so — intellectual honesty matters

After your code, summarize your challenge:
# CHALLENGE: <one clear sentence stating what you found>

You are debating round {round_num} of {total_rounds}.
"""

_JUDGE_SYSTEM = """\
You are the JUDGE in a structured analytical debate.
Your job: evaluate the arguments and evidence, render a fair verdict.

Task that was debated: {task}

Debate transcript:
{transcript}

Current kernel state (what was actually computed):
{namespace}

Evaluate:
  1. Which arguments were supported by actual data?
  2. Which were speculation or logical errors?
  3. What is the correct answer, given the evidence?

Write your verdict as Python that:
  1. Sets `debate_verdict` to your conclusion (string)
  2. Sets `debate_confidence` to your confidence (0.0-1.0)
  3. Sets `debate_winner` to "proposer", "challenger", or "draw"
  4. Prints a clear summary

End with: # TASK_COMPLETE: <verdict in one sentence>
"""


class DebateLoop:
    """
    Structured adversarial debate between two agents.

    Usage:
        agent = DebateLoop(
            kernel      = kernel,
            proposer    = my_llm,
            challenger  = my_llm,
            judge       = my_llm,
            position    = "West region underperforms due to pricing, not product mix",
            n_rounds    = 2,
        )
        result = agent.run("Investigate West region underperformance")
    """

    def __init__(
        self,
        kernel:      KernelRuntime,
        proposer:    LLMCallable,
        challenger:  LLMCallable,
        judge:       LLMCallable,
        position:    str          = "",
        n_rounds:    int          = 2,
        cell_timeout: float       = 120.0,
        verbose:     bool         = False,
    ):
        self.kernel       = kernel
        self.proposer     = proposer
        self.challenger   = challenger
        self.judge        = judge
        self.position     = position
        self.n_rounds     = n_rounds
        self.cell_timeout = cell_timeout
        self.verbose      = verbose

        self._recovery   = RecoveryStrategy()
        self._rounds:    list[DebateRound] = []
        self._all_cells: list[Cell]        = []
        self._session_id = str(uuid.uuid4())

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, task: str) -> SessionResult:
        """
        Run a full debate and return the judged result.
        """
        started_at = time.time()

        if not self.position:
            self.position = self._generate_position(task)

        log.info(
            "Debate started",
            session_id = self._session_id,
            task       = task[:100],
            position   = self.position[:100],
        )

        if self.verbose:
            print("\n╔══ DEBATE {}╗".format("═" * 44))
            print("║  Task:     {}".format(task[:60]))
            print("║  Position: {}".format(self.position[:60]))
            print("╚{}╝".format("═" * 54))

        # Debate rounds
        for round_num in range(1, self.n_rounds + 1):
            if self.verbose:
                print("\n── Round {}/{} ──────────────────────────".format(round_num, self.n_rounds))

            debate_round = self._run_round(task, round_num)
            self._rounds.append(debate_round)

        # Judge's verdict
        if self.verbose:
            print("\n── Judge's Verdict ────────────────────────────────")

        verdict_cells = self._run_judge(task)
        self._all_cells.extend(verdict_cells)

        # Extract verdict from namespace
        verdict_text = self.kernel.execute_silent(
            "print(globals().get('debate_verdict', 'No verdict set'))"
        )

        summary = (
            "Position debated: {}\n"
            "Rounds: {}\n"
            "Verdict: {}".format(self.position, self.n_rounds, verdict_text)
        )

        return SessionResult(
            session_id      = self._session_id,
            task            = task,
            status          = SessionStatus.COMPLETE,
            cells           = self._all_cells,
            final_namespace = self.kernel.namespace,
            summary         = summary,
            started_at      = started_at,
            ended_at        = time.time(),
        )

    # ── Round Execution ───────────────────────────────────────────────────────

    def _run_round(self, task: str, round_num: int) -> DebateRound:
        """Execute one full debate round: proposer then challenger."""

        prior_challenges = "\n".join(
            "  Round {}: {}".format(r.round_num, r.challenge[:200])
            for r in self._rounds
        ) or "None yet."

        # ── Proposer turn ──────────────────────────────────────────────────────
        if self.verbose:
            print("  [Proposer]", end=" ")

        prop_system = _PROPOSER_SYSTEM.format(
            task             = task,
            position         = self.position,
            round_num        = round_num,
            total_rounds     = self.n_rounds,
            prior_challenges = prior_challenges,
        )
        prop_code   = self._generate_and_execute(
            self.proposer,
            prop_system,
            label = "proposer",
        )
        prop_text   = self._extract_marker(prop_code, "# ARGUMENT:")

        if self.verbose:
            print(prop_text[:100])

        # ── Challenger turn ────────────────────────────────────────────────────
        if self.verbose:
            print("  [Challenger]", end=" ")

        chal_system = _CHALLENGER_SYSTEM.format(
            task         = task,
            proposition  = prop_text or prop_code[:200],
            round_num    = round_num,
            total_rounds = self.n_rounds,
        )
        chal_code   = self._generate_and_execute(
            self.challenger,
            chal_system,
            label = "challenger",
        )
        chal_text   = self._extract_marker(chal_code, "# CHALLENGE:")

        if self.verbose:
            print(chal_text[:100])

        return DebateRound(
            round_num   = round_num,
            proposition = prop_text or prop_code[:300],
            challenge   = chal_text or chal_code[:300],
        )

    def _run_judge(self, task: str) -> list[Cell]:
        """Execute the judge's verdict cell."""
        transcript = "\n\n".join(
            "Round {}:\n"
            "  Proposition: {}\n"
            "  Challenge:   {}".format(r.round_num, r.proposition, r.challenge)
            for r in self._rounds
        )

        judge_system = _JUDGE_SYSTEM.format(
            task       = task,
            transcript = transcript,
            namespace  = self.kernel.namespace,
        )

        messages = [
            Message(role="system", content=judge_system),
            Message(role="user",   content="Render your verdict now."),
        ]
        code   = self.judge(messages)
        output = self.kernel.execute(code, timeout=self.cell_timeout)

        cell = Cell(
            code     = code,
            output   = output,
            cell_num = len(self._all_cells) + 1,
            author   = "judge",
        )

        if self.verbose:
            verdict = self.kernel.execute_silent(
                "print(globals().get('debate_verdict', ''))"
            )
            confidence = self.kernel.execute_silent(
                "print(globals().get('debate_confidence', ''))"
            )
            print("  Verdict:    {}".format(verdict[:100]))
            print("  Confidence: {}".format(confidence))

        return [cell]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _generate_position(self, task: str) -> str:
        """If no position given, ask the LLM to generate a debatable hypothesis."""
        messages = [Message(
            role    = "user",
            content = (
                "Task: {}\n\n"
                "Generate one clear, debatable hypothesis about this task. "
                "One sentence only. Start with 'The primary factor is...' or similar.".format(task)
            ),
        )]
        return self.proposer(messages).strip()

    def _generate_and_execute(
        self,
        llm:    LLMCallable,
        system: str,
        label:  str,
    ) -> str:
        """Generate code from the LLM and execute it in the kernel."""
        messages = [
            Message(role="system", content=system),
            Message(
                role    = "user",
                content = (
                    "Current namespace:\n{}\n\n"
                    "Write your argument as executable Python code.".format(self.kernel.namespace)
                ),
            ),
        ]

        code   = llm(messages)
        output = self.kernel.execute(code, timeout=self.cell_timeout)

        if output.has_error:
            hint, _  = self._recovery.suggest(output.error)
            messages.append(Message(role="assistant", content=code))
            messages.append(Message(
                role    = "user",
                content = "Error: {}\nWrite a corrected cell.".format(hint)
            ))
            code   = llm(messages)
            output = self.kernel.execute(code, timeout=self.cell_timeout)

        cell = Cell(
            code     = code,
            output   = output,
            cell_num = len(self._all_cells) + 1,
            author   = label,
        )
        self._all_cells.append(cell)
        return code

    @staticmethod
    def _extract_marker(code: str, marker: str) -> str:
        """Extract the text after a comment marker in generated code."""
        for line in code.split("\n"):
            if line.strip().startswith(marker):
                return line.split(marker, 1)[1].strip()
        return ""

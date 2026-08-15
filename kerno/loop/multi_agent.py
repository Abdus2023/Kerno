"""
MultiAgentLoop: multiple specialized LLMs operating on one shared kernel.

Communication between agents happens through the kernel namespace —
not through message passing. Agent A writes `results_summary`.
Agent B reads `results_summary`. The kernel is the shared memory.

Built-in agent roles:
  analyst  — loads, cleans, models data
  critic   — finds flaws, tests assumptions
  narrator — synthesizes findings for non-technical audience

Custom roles can be added freely.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from kerno.context.builder   import PromptBuilder
from kerno.errors.recovery   import RecoveryStrategy
from kerno.kernel.runtime    import KernelRuntime
from kerno.telemetry.logger  import get_logger
from kerno.types import (
    Cell, CellOutput, LLMCallable, Message,
    SessionResult, SessionStatus,
)

log = get_logger("kerno.multi_agent")

COMPLETE_SIGNAL  = "# TASK_COMPLETE"
HANDOFF_SIGNAL   = "# HANDOFF:"
YIELD_SIGNAL     = "# READY_FOR_REVIEW"


@dataclass
class AgentRole:
    """
    Defines one agent's identity, purpose, and turn policy.
    """
    name:         str
    llm:          LLMCallable
    system:       str                  # Role-specific system prompt addition
    yield_signal: str = YIELD_SIGNAL   # Signal to end this agent's turn
    max_cells:    int = 20             # Max cells per turn
    reads:        list[str] = field(default_factory=lambda: ["*"])
    writes:       list[str] = field(default_factory=list)   # Namespace prefixes it writes to


# ── Built-in role factories ───────────────────────────────────────────────────

def analyst_role(llm: LLMCallable) -> AgentRole:
    return AgentRole(
        name   = "analyst",
        llm    = llm,
        system = (
            "You are a data analyst. Your job:\n"
            "  1. Load and clean the data\n"
            "  2. Perform exploratory analysis\n"
            "  3. Build models or compute metrics\n"
            "  4. Store results with clear variable names (results_*, model_*, df_*)\n"
            "Signal turn complete with: # READY_FOR_REVIEW"
        ),
        writes = ["results_", "model_", "df_", "analysis_"],
    )


def critic_role(llm: LLMCallable) -> AgentRole:
    return AgentRole(
        name   = "critic",
        llm    = llm,
        system = (
            "You are a statistical critic. Your job:\n"
            "  1. Review the analyst's work in the kernel namespace\n"
            "  2. Check for: data quality issues, methodological flaws, look-ahead bias\n"
            "  3. Write critique to `critique_summary` variable\n"
            "  4. Write specific flags to `critique_flags` list\n"
            "Be specific. Reference variable names and line numbers where possible.\n"
            "Signal turn complete with: # READY_FOR_REVIEW"
        ),
        writes = ["critique_"],
    )


def narrator_role(llm: LLMCallable) -> AgentRole:
    return AgentRole(
        name   = "narrator",
        llm    = llm,
        system = (
            "You are a technical writer synthesizing analysis for a non-technical audience.\n"
            "Your job:\n"
            "  1. Read `results_*` and `critique_*` variables in the namespace\n"
            "  2. Write a clear narrative (3-5 paragraphs) to `narrative_summary`\n"
            "  3. Create a `key_findings` list (3-7 bullet points)\n"
            "  4. Avoid jargon. Quantify everything.\n"
            "Signal complete with: # TASK_COMPLETE: narrative ready"
        ),
        yield_signal = COMPLETE_SIGNAL,
        writes       = ["narrative_", "key_findings"],
    )


# ── The Loop ──────────────────────────────────────────────────────────────────

@dataclass
class TurnRecord:
    """Record of one agent's turn."""
    agent_name: str
    cells:      list[Cell]
    summary:    str = ""
    handoff_context: str = ""


class MultiAgentLoop:
    """
    Orchestrates multiple agents taking turns on a shared kernel.

    The turn structure:
      1. Agent executes cells until it emits its yield_signal
      2. Optional: planner assesses and decides next agent
      3. Next agent picks up from the shared namespace

    The shared kernel namespace is the communication channel.
    No message passing between agents is required.

    Usage:
        loop = MultiAgentLoop(
            kernel = kernel,
            roles  = [
                analyst_role(my_llm),
                critic_role(my_llm),
                narrator_role(my_llm),
            ],
        )
        result = loop.run("Analyze churn patterns in customer data")
    """

    def __init__(
        self,
        kernel:       KernelRuntime,
        roles:        list[AgentRole],
        turn_order:   Optional[list[str]] = None,    # By name; None = roles order
        max_turns:    int                 = 6,
        cell_timeout: float               = 120.0,
        verbose:      bool                = False,
    ):
        self.kernel       = kernel
        self.roles        = {r.name: r for r in roles}
        self.turn_order   = turn_order or [r.name for r in roles]
        self.max_turns    = max_turns
        self.cell_timeout = cell_timeout
        self.verbose      = verbose

        self._builder  = PromptBuilder()
        self._recovery = RecoveryStrategy()
        self._turns:   list[TurnRecord] = []
        self._all_cells: list[Cell]     = []
        self._session_id = str(uuid.uuid4())

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, task: str) -> SessionResult:
        """
        Run the multi-agent session.

        Each agent takes turns until the task is complete
        or max_turns is reached.
        """
        started_at = time.time()
        status     = SessionStatus.MAX_CELLS

        log.info(
            "Multi-agent session started",
            session_id = self._session_id,
            agents     = list(self.roles.keys()),
            task       = task[:100],
        )

        for turn_idx in range(self.max_turns):
            agent_name = self.turn_order[turn_idx % len(self.turn_order)]
            role       = self.roles.get(agent_name)

            if role is None:
                log.warning("Unknown agent role", name=agent_name)
                continue

            if self.verbose:
                print(f"\n{'━'*56}")
                print(f"  Turn {turn_idx + 1}: {agent_name.upper()}")
                print(f"{'━'*56}")

            turn = self._run_turn(role, task, turn_idx)
            self._turns.append(turn)
            self._all_cells.extend(turn.cells)

            # Check if the session is fully complete
            last_code = turn.cells[-1].code if turn.cells else ""
            if COMPLETE_SIGNAL in last_code:
                status = SessionStatus.COMPLETE
                break

        # Build final summary from all turns
        summary = self._build_session_summary(task)

        return SessionResult(
            session_id      = self._session_id,
            task            = task,
            status          = status,
            cells           = self._all_cells,
            final_namespace = self.kernel.namespace,
            summary         = summary,
            started_at      = started_at,
            ended_at        = time.time(),
        )

    # ── Turn Execution ────────────────────────────────────────────────────────

    def _run_turn(
        self,
        role:      AgentRole,
        task:      str,
        turn_idx:  int,
    ) -> TurnRecord:
        """
        Run one agent's turn until it yields or hits max_cells.
        """
        turn = TurnRecord(agent_name=role.name, cells=[])

        # Build prior context from previous turns
        prior_context = self._summarize_prior_turns(role.name)

        history: list[Message] = []
        recovery: Optional[str] = None

        for cell_num in range(1, role.max_cells + 1):

            # Build messages
            system_content = self._build_system(role, task, prior_context)
            messages       = [Message(role="system", content=system_content)]
            messages.extend(history[-10:])

            # Inject recovery hint if pending
            if recovery:
                messages.append(Message(
                    role    = "user",
                    content = f"Previous error:\n{recovery}\nWrite a corrected cell.",
                ))
                recovery = None

            # Generate
            code   = role.llm(messages)
            output = self.kernel.execute(code, timeout=self.cell_timeout)

            if self.verbose:
                icon = "✗" if output.has_error else "→"
                print(f"  [{role.name}:{cell_num}] {icon} {output.as_text(max_chars=100)}")

            global_cell_num = len(self._all_cells) + len(turn.cells) + 1
            cell = Cell(
                code     = code,
                output   = output,
                cell_num = global_cell_num,
                author   = role.name,
            )
            turn.cells.append(cell)

            history.append(Message(role="assistant", content=code))
            history.append(Message(
                role    = "user",
                content = f"Output:\n{output.as_text(max_chars=500)}"
            ))

            if output.has_error:
                hint, _ = self._recovery.suggest(output.error)
                recovery = hint
                continue

            # Check yield signal
            if role.yield_signal in code:
                # Extract handoff context if agent provided one
                if HANDOFF_SIGNAL in code:
                    idx = code.find(HANDOFF_SIGNAL) + len(HANDOFF_SIGNAL)
                    turn.handoff_context = code[idx:].strip().split("\n")[0]
                break

        turn.summary = self._summarize_turn(role.name, turn.cells)
        return turn

    def _build_system(
        self,
        role:          AgentRole,
        task:          str,
        prior_context: str,
    ) -> str:
        namespace = self.kernel.namespace
        return (
            f"You are the {role.name} agent.\n\n"
            f"{role.system}\n\n"
            f"━━━ TASK ━━━\n{task}\n\n"
            f"━━━ PRIOR AGENTS' WORK ━━━\n"
            f"{prior_context or 'You are the first agent — no prior work.'}\n\n"
            f"━━━ CURRENT KERNEL NAMESPACE ━━━\n"
            f"{namespace}\n\n"
            f"━━━ RULES ━━━\n"
            f"- Write one Python cell per response\n"
            f"- Your writes go to variables prefixed: {role.writes}\n"
            f"- Read any variable freely — the kernel is shared\n"
            f"- Signal your turn is done with: {role.yield_signal}\n"
        )

    def _summarize_prior_turns(self, current_agent: str) -> str:
        """Build a summary of what prior agents did for the current agent's context."""
        if not self._turns:
            return ""
        lines = []
        for turn in self._turns:
            if turn.agent_name == current_agent:
                continue
            lines.append(
                f"{turn.agent_name.upper()}: {turn.summary or '(no summary)'}"
            )
            if turn.handoff_context:
                lines.append(f"  Handoff note: {turn.handoff_context}")
        return "\n".join(lines)

    def _summarize_turn(self, agent_name: str, cells: list[Cell]) -> str:
        """One-line summary of what this agent produced."""
        if not cells:
            return "No cells executed."
        outputs = " | ".join(
            c.output.as_text(max_chars=80)
            for c in cells[-3:]
            if not c.output.is_empty
        )
        return f"{len(cells)} cells. Last outputs: {outputs}"

    def _build_session_summary(self, task: str) -> str:
        lines = [f"Task: {task}", ""]
        for i, turn in enumerate(self._turns):
            lines.append(f"Turn {i+1} ({turn.agent_name}): {turn.summary}")
        return "\n".join(lines)

# kerno/steps/memory.py
"""
Memory steps: inject past context, store session results.
"""

from __future__ import annotations

from kerno.interfaces import AgentState, Memory
from kerno.memory.store import MemoryEntry


class InjectMemoryStep:
    """
    Retrieves relevant memories and injects them into state.summary.
    Runs at session start — gives the LLM context from prior sessions.
    """

    def __init__(
        self,
        memory:     Memory,
        k:          int   = 3,
        min_score:  float = 0.1,
    ):
        self.memory    = memory
        self.k         = k
        self.min_score = min_score

    def run(self, state: AgentState) -> AgentState:
        if not state.summary:   # Only inject at session start
            entries = self.memory.retrieve(
                state.task,
                k         = self.k,
                min_score = self.min_score,
            )
            if entries:
                lines = ["Relevant context from prior sessions:"]
                for e in entries:
                    lines.append("  [{}] {}".format(e.kind, e.content[:300]))
                state.summary = "\n".join(lines)

        return state


class StoreMemoryStep:
    """
    Stores the session result in memory.
    Runs on completion — what this session learned persists.
    """

    def __init__(self, memory: Memory):
        self.memory = memory

    def run(self, state: AgentState) -> AgentState:
        if state.complete and state.summary:
            self.memory.store(MemoryEntry(
                content    = "Task: {}\n\nSummary: {}".format(state.task, state.summary),
                kind       = "result",
                session_id = state.session_id,
                task       = state.task,
            ))
        return state


class StoreInsightStep:
    """
    After each cell, check if output contains a noteworthy finding
    and store it as an insight memory.
    """

    def __init__(
        self,
        memory: Memory,
        llm:    object,            # LLM to judge what's noteworthy
        threshold: float = 0.7,   # Confidence threshold for storing
    ):
        self.memory    = memory
        self.llm       = llm
        self.threshold = threshold

    def run(self, state: AgentState) -> AgentState:
        if not state.history:
            return state

        last = state.history[-1]
        if last.output.has_error or last.output.is_empty:
            return state

        # Ask LLM if this output is worth remembering
        from kerno.types import Message
        judgment = self.llm([Message(
            role    = "user",
            content = (
                "Does this output contain a noteworthy insight worth "
                "remembering for future sessions?\n\n"
                "Output:\n{}\n\n"
                "Reply with JSON: "
                '{{"worth_storing": true/false, '
                '"insight": "one sentence if worth storing"}}'
            ).format(last.output.as_text(max_chars=500))
        )])

        import json, re
        try:
            raw  = re.sub(r'```(?:json)?\s*', '', judgment).strip()
            data = json.loads(raw)
            if data.get("worth_storing") and data.get("insight"):
                self.memory.store(MemoryEntry(
                    content    = data["insight"],
                    kind       = "insight",
                    session_id = state.session_id,
                    task       = state.task,
                ))
        except (json.JSONDecodeError, KeyError):
            pass

        return state

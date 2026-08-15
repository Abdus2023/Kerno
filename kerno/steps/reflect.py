# kerno/steps/reflect.py
"""
ReflectStep: reflect on the last cell output before continuing.
"""

from __future__ import annotations

from kerno.interfaces import AgentState


class ReflectStep:
    """
    Reflect on the last cell's output.
    Adds a reflection message to the context for the next LLM call.
    """

    def __init__(self, llm, context_builder=None):
        self.llm     = llm
        self.builder = context_builder

    def run(self, state: AgentState) -> AgentState:
        if not state.history:
            return state

        last_cell = state.history[-1]
        if self.builder and hasattr(self.builder, 'build_reflection'):
            reflection = self.llm(self.builder.build_reflection(last_cell))
        else:
            from kerno.types import Message
            reflection = self.llm([Message(
                role    = "user",
                content = (
                    "Reflect on this output. Was it successful?\n"
                    "If there was an error, suggest what to try next.\n\n"
                    "Output:\n{}".format(last_cell.output.as_text(max_chars=800))
                ),
            )])

        state.metadata["last_reflection"] = reflection
        return state

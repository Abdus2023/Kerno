# kerno/steps/generate.py
"""
GenerateCodeStep: LLM → code.
The only step that calls the LLM for code generation.
"""

from __future__ import annotations

from kerno.interfaces import AgentState, ContextStrategy, LLM
from kerno.context.builder import PromptBuilder
from kerno.telemetry.tracer import get_tracer


class GenerateCodeStep:
    """
    Calls the LLM to generate the next cell of code.

    The LLM and context builder are injected — fully swappable.
    The step reads AgentState and writes:
      - metadata["last_code"]: the generated code
    """

    def __init__(
        self,
        llm:             LLM,
        context_builder: ContextStrategy = None,
    ):
        self.llm     = llm
        self.builder = context_builder or PromptBuilder()
        self._tracer = get_tracer()

    def run(self, state: AgentState) -> AgentState:
        messages = self.builder.build(
            task      = state.task,
            history   = state.history,
            namespace = state.namespace,
            summary   = state.summary,
        )

        # Inject any pending recovery hint
        hint = state.metadata.pop("recovery_hint", None)
        if hint:
            from kerno.types import Message
            messages.append(Message(
                role    = "user",
                content = "Previous cell raised an error:\n{}\nWrite a recovery cell.".format(hint)
            ))

        with self._tracer.span("step.generate"):
            code = self.llm(messages)

        state.metadata["last_code"] = code
        return state


class ReflectAndGenerateStep:
    """
    Variation: reflects on last output, then generates code.
    Replaces the simple GenerateCodeStep for the reflect loop.
    """

    def __init__(self, llm: LLM, context_builder: ContextStrategy = None):
        self.llm     = llm
        self.builder = context_builder or PromptBuilder()

    def run(self, state: AgentState) -> AgentState:
        # Reflect on last cell if there is one
        if state.history:
            last_cell = state.history[-1]
            reflection = self._reflect(last_cell)
            state.metadata["last_reflection"] = reflection
            state.metadata["reflections"] = (
                state.metadata.get("reflections", []) + [reflection]
            )

        # Generate next code
        messages = self._build_with_reflections(state)
        code     = self.llm(messages)
        state.metadata["last_code"] = code
        return state

    def _reflect(self, cell) -> str:
        prompt = self.builder.build_reflection(cell)
        return self.llm(prompt)

    def _build_with_reflections(self, state: AgentState) -> list:
        reflections = state.metadata.get("reflections", [])
        # Build context preferring reflections over raw outputs
        messages = self.builder.build(
            task      = state.task,
            history   = [],           # Let reflections carry the history
            namespace = state.namespace,
            summary   = state.summary,
        )
        for i, cell in enumerate(state.history[-15:]):
            from kerno.types import Message
            messages.append(Message(role="assistant", content=cell.code))
            if i < len(reflections):
                messages.append(Message(
                    role    = "user",
                    content = "Reflection:\n{}".format(reflections[i])
                ))
            else:
                messages.append(Message(
                    role    = "user",
                    content = "Output:\n{}".format(cell.output.as_text())
                ))
        return messages

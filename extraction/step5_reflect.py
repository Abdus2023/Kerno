# kerno/loop/reflect.py
"""
ReflectReviseLoop: each cell is followed by a reflection.
Reflections are information-dense summaries that survive
context compression better than raw output.

Best for: open-ended exploration, data quality investigations.
"""

from kerno.loop.base import BaseLoop
from kerno.types import Cell, Message


_REFLECT_SYSTEM = """\
You are reviewing your own work in a Jupyter kernel session.
After each cell execution, produce a brief reflection.
"""


class ReflectReviseLoop(BaseLoop):
    """
    Think → Act → Observe → Reflect → Think → ...

    The reflection loop replaces raw output in the LLM's context.
    This gives it higher information density per token.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reflections: list[str] = []

    def _next_cell(self, cell_num: int) -> str:
        messages = self._build_messages_with_reflections()
        return self._call_llm(messages)

    def _on_cell_complete(self, cell: Cell) -> None:
        """After each cell, generate a reflection and store it."""
        reflection = self._reflect(cell)
        self._reflections.append(reflection)

        if self.verbose:
            print(f"  💭 {reflection[:150]}")

    def _reflect(self, cell: Cell) -> str:
        """Generate a reflection on the cell's execution."""
        reflection_messages = self._builder.build_reflection(cell)
        full_messages = (
            [Message(role="system", content=_REFLECT_SYSTEM)]
            + reflection_messages
        )
        return self._call_llm(full_messages)

    def _build_messages_with_reflections(self) -> list[Message]:
        """
        Build messages that include reflections instead of raw outputs.
        Reflections are information-dense: they compress output into insight.
        """
        messages = self._builder.build(
            task      = self._task,
            history   = [],          # We'll add reflections instead
            namespace = self.kernel.namespace,
            summary   = self._summary,
        )

        # Add recent cells — but annotated with their reflections
        recent  = self._history[-15:]
        refls   = self._reflections[-15:]

        for i, cell in enumerate(recent):
            messages.append(Message(role="assistant", content=cell.code))

            # Use reflection if available; raw output for the most recent cell
            if i < len(refls):
                messages.append(Message(
                    role="user",
                    content=f"Reflection:\n{refls[i]}"
                ))
            else:
                messages.append(Message(
                    role="user",
                    content=f"Output:\n{cell.output.as_text()}"
                ))

        return messages

# kerno/loop/reactive.py
"""
ReactiveLoop: the simplest complete loop.
No planning. No lookahead. Pure observe-act.
Best for: short, well-defined tasks.
"""

from kerno.loop.base import BaseLoop
from kerno.types import Message


class ReactiveLoop(BaseLoop):
    """
    Observe current state. Act. Repeat.
    The LLM generates one cell at a time based only on:
    - The task
    - Recent history
    - Live namespace
    """

    def _next_cell(self, cell_num: int) -> str:
        messages = self._build_messages()
        return self._call_llm(messages)

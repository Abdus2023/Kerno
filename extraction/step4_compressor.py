# kerno/context/compressor.py
"""
HistoryCompressor: converts old execution history into dense summaries.

When context fills up, we don't drop history — we compress it.
The compression preserves WHAT EXISTS (state) over WHAT HAPPENED (events).
"""

from __future__ import annotations

from kerno.types import Cell, LLMCallable, Message


_COMPRESSION_PROMPT = """\
These cells were executed in a Jupyter kernel session.
Summarize what was ACCOMPLISHED in 3-5 sentences.

Focus on:
- What data objects were created and what they contain
- What transformations or analyses were performed
- What was discovered or produced
- What variable names to remember

Do NOT describe what to do next.
Do NOT include code.
Be precise about variable names and data shapes.

Cells:
{cells_text}
"""


class HistoryCompressor:
    """
    Compresses old execution history into dense summaries.

    The compressed summary replaces old cells in the context window.
    The kernel namespace acts as the ground truth for what actually exists —
    the summary only needs to capture the narrative of what happened.
    """

    def __init__(self, llm: LLMCallable):
        self.llm = llm

    def compress(self, cells: list[Cell]) -> str:
        """
        Compress a list of cells into a narrative summary.

        Args:
            cells: The cells to compress (older history)

        Returns:
            A plain text summary suitable for the system prompt
        """
        if not cells:
            return ""

        cells_text = "\n\n---\n\n".join(
            f"Cell {c.cell_num}:\n```python\n{c.code}\n```\n"
            f"Output: {c.output.as_text(max_chars=300)}"
            for c in cells
        )

        prompt  = _COMPRESSION_PROMPT.format(cells_text=cells_text)
        summary = self.llm([Message(role="user", content=prompt)])
        return summary.strip()

    def should_compress(
        self,
        history:    list[Cell],
        threshold:  int = 20,
    ) -> bool:
        """
        Heuristic: compress when history grows beyond threshold.
        """
        return len(history) >= threshold

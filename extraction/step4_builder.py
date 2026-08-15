# kerno/context/builder.py
"""
PromptBuilder: assembles the LLM's context from kernel state + history.

The system prompt is not static. It is regenerated every turn
with a live snapshot of the kernel namespace. This is what makes
the agent aware of its own state even after context compression.
"""

from __future__ import annotations

from kerno.types import Cell, Message


class PromptBuilder:
    """
    Builds the message list sent to the LLM on each turn.

    The key design principle: the system prompt carries live kernel state.
    The conversation history carries execution history.
    These are separated so each can be managed independently.
    """

    SYSTEM_TEMPLATE = """\
You are an autonomous Python agent operating inside a Jupyter kernel.
You accomplish tasks by writing and executing Python cells.

━━━ CURRENT KERNEL STATE ━━━
{namespace}

━━━ PRIOR WORK ━━━
{summary}

━━━ ACTIVE TASK ━━━
{task}

━━━ OPERATING RULES ━━━
• Write one focused Python cell per response — no explanations outside code
• All variables from prior cells are available in the namespace above
• Inspect before assuming: if unsure what exists, write `print(df.columns)` first
• Checkpoint important objects: `import joblib; joblib.dump(obj, '_ckpt/obj.joblib')`
• Use descriptive variable names that encode lineage: df_raw, df_clean, df_west
• Never redefine a variable that already exists unless you intend to replace it
• Signal completion with a comment on the last line: # TASK_COMPLETE: <one-line summary>

━━━ CELL FORMAT ━━━
Respond with ONLY Python code. No markdown fences. No prose.
The code will be executed directly in the kernel.
"""

    REFLECT_TEMPLATE = """\
You just executed this cell:

```python
{code}
```

Output:
{output}

Reflect briefly (2-3 sentences):
1. What did this actually produce?
2. Does it change your approach?
3. What is the single most valuable next action?
"""

    def build(
        self,
        task:      str,
        history:   list[Cell],
        namespace: str,
        summary:   str = "",
        max_cells: int = 20,
    ) -> list[Message]:
        """
        Build the full message list for the next LLM call.

        Args:
            task:      The original task description
            history:   Recent execution history (Cell objects)
            namespace: Live JSON snapshot from kernel
            summary:   Compressed summary of older history
            max_cells: How many recent cells to include verbatim

        Returns:
            List of Message objects ready for the LLM
        """
        system_content = self.SYSTEM_TEMPLATE.format(
            namespace=namespace or "{}  (kernel just started)",
            summary=summary or "Session just started — no prior work.",
            task=task,
        )

        messages = [Message(role="system", content=system_content)]

        # Add recent cells to conversation history
        recent = history[-max_cells:]
        for cell in recent:
            # Agent's action
            messages.append(Message(role="assistant", content=cell.code))
            # Kernel's response
            out_text = cell.output.as_text()
            messages.append(Message(
                role="user",
                content=f"Output:\n{out_text}"
            ))

        return messages

    def build_reflection(self, cell: Cell) -> list[Message]:
        """
        Build a message list for a reflection call.
        Used by ReflectReviseLoop after each execution.
        """
        content = self.REFLECT_TEMPLATE.format(
            code=cell.code,
            output=cell.output.as_text(max_chars=1500),
        )
        return [Message(role="user", content=content)]

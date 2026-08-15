"""
Example 9: Resume an interrupted session from a notebook.
Shows: notebook continuation, state restoration.
"""

import sys
import anthropic
from kerno.types   import Message
from kerno.notebook.continuation import continue_from_notebook


def make_claude(model: str = "claude-opus-4-5") -> callable:
    client = anthropic.Anthropic()
    def llm(messages: list[Message]) -> str:
        response = client.messages.create(
            model      = model,
            max_tokens = 4096,
            system     = messages[0].content,
            messages   = [{"role": m.role, "content": m.content} for m in messages[1:]],
        )
        return response.content[0].text
    return llm


if __name__ == "__main__":
    # Get the notebook path from CLI or use the most recent
    if len(sys.argv) > 1:
        notebook_path = sys.argv[1]
    else:
        from pathlib import Path
        sessions = sorted(Path("sessions").glob("*.ipynb"),
                          key=lambda p: p.stat().st_mtime)
        if not sessions:
            print("No sessions found. Run an example first.")
            sys.exit(1)
        notebook_path = str(sessions[-1])
        print(f"Using most recent session: {notebook_path}")

    result = continue_from_notebook(
        path       = notebook_path,
        llm        = make_claude(),
        new_task   = (
            "The prior analysis has been loaded. "
            "Please complete any unfinished work, "
            "then produce a final summary with key findings."
        ),
        re_execute = True,
        verbose    = True,
    )

    print(f"\nStatus:  {result.status.name}")
    print(f"Summary: {result.summary[:300] if result.summary else '(none)'}")

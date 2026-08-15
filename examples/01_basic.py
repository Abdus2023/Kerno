# examples/01_basic.py
"""
Example 1: The simplest possible kerno usage.
One function call. One LLM. One task. One result.
"""

import anthropic
from kerno import run, Message


def make_claude(model: str = "claude-opus-4-5") -> callable:
    client = anthropic.Anthropic()

    def llm(messages: list[Message]) -> str:
        response = client.messages.create(
            model      = model,
            max_tokens = 4096,
            system     = messages[0].content,
            messages   = [
                {"role": m.role, "content": m.content}
                for m in messages[1:]
            ],
        )
        return response.content[0].text

    return llm


if __name__ == "__main__":
    result = run(
        task    = "Create a sample DataFrame with 100 rows of sales data "
                  "(date, region, product, revenue, units). "
                  "Profile it and plot the revenue distribution.",
        llm     = make_claude(),
        verbose = True,
    )

    print(f"\nStatus:  {result.status.name}")
    print(f"Cells:   {result.cells_executed}")
    print(f"Errors:  {result.error_count} ({result.recovery_count} recovered)")
    print(f"Time:    {result.duration:.1f}s")

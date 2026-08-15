"""
Example 7: Cross-session memory.
Run two related tasks. The second task recalls context from the first.
"""

import anthropic
from kerno        import run, Message
from kerno.memory.simple import SimpleMemoryStore


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
    llm    = make_claude()
    memory = SimpleMemoryStore(".kerno/memory.json")

    # ── Session 1: Initial analysis ────────────────────────────────────────────
    print("Session 1: Initial analysis")
    result1 = run(
        task = (
            "Generate monthly sales data for 2023 (12 months, "
            "columns: month, revenue, units, region). "
            "Compute total annual revenue and identify the "
            "best and worst performing months."
        ),
        llm    = llm,
        memory = memory,
        verbose= True,
    )
    print(f"Session 1: {result1.status.name}")

    # ── Session 2: Follow-up using memory from session 1 ───────────────────────
    print("\nSession 2: Follow-up")
    result2 = run(
        task = (
            "Using what you know about our 2023 sales performance, "
            "generate a Q1 2024 forecast. "
            "Apply a 5% growth rate to the best months "
            "and a 10% improvement to the worst months."
        ),
        llm    = llm,
        memory = memory,   # Same store — session 1's results are available
        verbose= True,
    )
    print(f"Session 2: {result2.status.name}")

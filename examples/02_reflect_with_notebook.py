# examples/02_reflect_with_notebook.py
"""
Example 2: ReflectReviseLoop with notebook output.
Shows: richer reasoning, persistent artifact.
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
            messages   = [{"role": m.role, "content": m.content} for m in messages[1:]],
        )
        return response.content[0].text
    return llm


if __name__ == "__main__":
    llm = make_claude()

    result = run(
        task = (
            "Generate a synthetic e-commerce dataset with 500 orders "
            "(order_id, customer_id, product_category, order_value, "
            "discount_pct, return_flag, country). "
            "Investigate: which product categories have the highest return rates? "
            "Is there a relationship between discount percentage and returns? "
            "Produce a clear final conclusion."
        ),
        llm           = llm,
        loop          = "reflect",     # Deeper reasoning
        save_notebook = True,          # Saves to sessions/
        verbose       = True,
    )

    print(f"\n{'═'*60}")
    print(f"Status:    {result.status.name}")
    print(f"Cells:     {result.cells_executed}")
    print(f"Summary:   {result.summary[:200] if result.summary else '(none)'}")

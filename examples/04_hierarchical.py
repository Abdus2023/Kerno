# examples/04_hierarchical.py
"""
Example 4: HierarchicalLoop with separate planner and executor LLMs.
Shows: cost optimization — expensive model for strategy, cheap for execution.
"""

import anthropic
from kerno import run, Message


def make_claude(model: str) -> callable:
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
    # Planner: smart and strategic (expensive, few calls)
    planner  = make_claude("claude-opus-4-5")

    # Executor: fast and cheap (many calls)
    executor = make_claude("claude-haiku-4-5")

    result = run(
        task = (
            "Comprehensive time series analysis: "
            "Generate 3 years of daily sales data with trend, seasonality, and noise. "
            "Decompose the series. Identify anomalies. "
            "Forecast the next 30 days using a simple model. "
            "Produce a summary dashboard with 4 plots."
        ),
        llm          = executor,
        planner_llm  = planner,
        loop         = "hierarchical",
        save_notebook= True,
        verbose      = True,
    )

    print(f"\nStatus:    {result.status.name}")
    print(f"Cells:     {result.cells_executed}")
    print(f"Summary:\n{result.summary}")

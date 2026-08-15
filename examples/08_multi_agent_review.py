"""
Example 8: Multi-agent analysis with analyst + critic + narrator.
Shows: agents communicating through shared kernel namespace.
"""

import anthropic
from kerno import run, analyst_role, critic_role, narrator_role, Message


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
            "Generate a dataset of 500 customer records with columns: "
            "customer_id, age, tenure_months, monthly_spend, "
            "support_tickets, churn_flag. "
            "Build a logistic regression model to predict churn. "
            "Evaluate it and identify the most predictive features."
        ),
        llm  = llm,
        loop = "multi_agent",
        roles = [
            analyst_role(llm),  # Loads data, builds model
            critic_role(llm),   # Reviews methodology
            narrator_role(llm), # Writes executive summary
        ],
        save_notebook = True,
        verbose       = True,
    )

    print(f"\nStatus:  {result.status.name}")
    print(f"Cells:   {result.cells_executed} across all agents")
    print(f"Summary:\n{result.summary}")

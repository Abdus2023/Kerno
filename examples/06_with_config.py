"""
Example 6: Production-ready run using KernoConfig.
Shows: config file, memory, security, telemetry all wired together.
"""

import anthropic
from kerno.config  import KernoConfig
from kerno.runner  import run_with_config
from kerno.types   import Message


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
    # Production config: memory + security + notebook output
    config = KernoConfig.for_production()

    # Override specific settings
    config.llm.model              = "claude-opus-4-5"
    config.kernel.max_cells       = 40
    config.security.profile       = "data_analysis"
    config.security.sanitize_inputs = True

    result = run_with_config(
        task   = (
            "Generate 1000 rows of synthetic e-commerce data "
            "(order_id, customer_id, product, revenue, country, "
            "churn_risk_score). "
            "Identify the top 3 countries by churn risk. "
            "Plot the distribution of churn_risk_score by country."
        ),
        llm    = make_claude(config.llm.model),
        config = config,
        loop   = "reflect",
    )

    print(f"\nStatus:  {result.status.name}")
    print(f"Cells:   {result.cells_executed}")
    print(f"Summary: {result.summary[:300] if result.summary else '(none)'}")

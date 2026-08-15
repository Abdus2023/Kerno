# examples/basic_analysis.py
"""
Minimal working example of kerno.
Requires: an Anthropic API key, a file called 'data.csv' in the working directory.
"""

import anthropic
from kerno import run, Message


def make_llm(model: str = "claude-opus-4-5"):
    client = anthropic.Anthropic()

    def llm(messages: list[Message]) -> str:
        # kerno passes Message objects; Anthropic API wants dicts
        system   = messages[0].content
        history  = [
            {"role": m.role, "content": m.content}
            for m in messages[1:]
        ]
        response = client.messages.create(
            model      = model,
            max_tokens = 4096,
            system     = system,
            messages   = history,
        )
        return response.content[0].text

    return llm


if __name__ == "__main__":
    result = run(
        task    = (
            "Load 'data.csv'. Profile the data — shape, dtypes, null counts. "
            "Identify the numeric columns and plot their distributions. "
            "Report any anomalies you find."
        ),
        llm     = make_llm(),
        verbose = True,
    )

    print(f"\n{'═'*60}")
    print(f"Status : {result.status.name}")
    print(f"Cells  : {result.cells_executed}")
    print(f"Errors : {result.error_count} ({result.recovery_count} recovered)")
    print(f"Time   : {result.duration:.1f}s")
    print(f"State  : {result.final_namespace}")

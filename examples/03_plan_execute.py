# examples/03_plan_execute.py
"""
Example 3: PlanExecuteLoop for a multi-step structured analysis.
Shows: explicit plan, step-by-step execution, step verification.
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
            "Build a complete ML pipeline: "
            "1) Generate synthetic classification data (1000 samples, 10 features, 3 classes). "
            "2) Split into train/test (80/20). "
            "3) Train a RandomForestClassifier. "
            "4) Evaluate: accuracy, confusion matrix, feature importances. "
            "5) Plot feature importances as a horizontal bar chart."
        ),
        llm           = llm,
        loop          = "plan",
        max_cells     = 30,
        save_notebook = True,
        verbose       = True,
    )

    print(f"\nStatus: {result.status.name}")
    print(f"Cells:  {result.cells_executed}")

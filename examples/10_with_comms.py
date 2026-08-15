"""
Example 10: Structured kernel → orchestrator communication.
Shows: real-time progress, anomaly detection, without polluting stdout.
"""

import anthropic
from kerno      import run, Message
from kerno.comms.channel import CommMessage


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


def on_progress(msg: CommMessage) -> None:
    pct  = msg.payload.get("pct", 0)
    step = msg.payload.get("step", "")
    bar  = "█" * int(pct * 20) + "░" * (20 - int(pct * 20))
    print(f"  [{bar}] {pct:.0%}  {step}")


def on_anomaly(msg: CommMessage) -> None:
    severity    = msg.payload.get("severity", "info")
    description = msg.payload.get("description", "")
    icons       = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
    print(f"\n  {icons.get(severity, '?')} ANOMALY: {description}")


if __name__ == "__main__":
    llm = make_claude()

    result = run(
        task = (
            "Generate 2000 rows of financial transaction data "
            "(transaction_id, account_id, amount, category, "
            "is_fraudulent, country). "
            "Use progress() to report each major step. "
            "Use signal_anomaly() if you find anything unexpected. "
            "Build a fraud detection model."
        ),
        llm  = llm,
        comm_handlers = {
            "progress": on_progress,
            "anomaly":  on_anomaly,
        },
        save_notebook = True,
        verbose       = False,   # Comms replace verbose output
    )

    print(f"\nStatus: {result.status.name}")
    print(f"Cells:  {result.cells_executed}")

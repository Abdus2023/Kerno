# examples/05_parallel.py
"""
Example 5: Parallel task execution with KernelPool.
Shows: multiple isolated kernels running simultaneously.
"""

import anthropic
from kerno import run_with_pool, Message


def make_claude(model: str = "claude-haiku-4-5") -> callable:
    client = anthropic.Anthropic()
    def llm(messages: list[Message]) -> str:
        response = client.messages.create(
            model      = model,
            max_tokens = 2048,
            system     = messages[0].content,
            messages   = [{"role": m.role, "content": m.content} for m in messages[1:]],
        )
        return response.content[0].text
    return llm


if __name__ == "__main__":
    llm = make_claude()

    # Three independent analyses run in parallel
    tasks = [
        "Generate 200 rows of sales data for Region A. Compute: total revenue, "
        "top 3 products by revenue, average order value. Print results.",

        "Generate 200 rows of sales data for Region B. Compute: total revenue, "
        "top 3 products by revenue, average order value. Print results.",

        "Generate 200 rows of sales data for Region C. Compute: total revenue, "
        "top 3 products by revenue, average order value. Print results.",
    ]

    import time
    start   = time.time()
    results = run_with_pool(
        tasks          = tasks,
        llm            = llm,
        pool_size      = 3,       # 3 kernels → 3 tasks run simultaneously
        save_notebooks = True,
        verbose        = True,
    )
    elapsed = time.time() - start

    print(f"\n{'═'*60}")
    print(f"Completed {len(results)} tasks in {elapsed:.1f}s")
    for i, result in enumerate(results):
        print(f"  Task {i}: {result.status.name} in {result.cells_executed} cells")

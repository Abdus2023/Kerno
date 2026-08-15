# kerno/__init__.py
"""
kerno: a kernel-native agent runtime.

The minimal public interface. Import from here.
"""

from kerno.kernel.runtime import KernelRuntime
from kerno.loop.reactive  import ReactiveLoop
from kerno.loop.reflect   import ReflectReviseLoop
from kerno.types          import (
    Cell, CellOutput, CellError,
    Message, SessionResult, SessionStatus,
    LLMCallable,
)


def run(
    task:        str,
    llm:         LLMCallable,
    *,
    loop:        str   = "reactive",
    kernel_name: str   = "python3",
    max_cells:   int   = 50,
    skills_path: str   = None,
    verbose:     bool  = False,
) -> SessionResult:
    """
    Run a task in a kernel-agent session.

    This is the one-function API. For production use,
    construct KernelRuntime and loops directly for more control.

    Args:
        task:        Natural language task description
        llm:         Callable(messages: list[Message]) -> str
        loop:        "reactive" | "reflect"
        kernel_name: Jupyter kernel spec name
        max_cells:   Maximum cells before stopping
        skills_path: Path to Python skills bootstrap file
        verbose:     Print execution trace to stdout

    Returns:
        SessionResult

    Example:
        import anthropic
        from kerno import run

        client = anthropic.Anthropic()

        def llm(messages):
            response = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=4096,
                system=messages[0].content,
                messages=[{"role": m.role, "content": m.content}
                          for m in messages[1:]],
            )
            return response.content[0].text

        result = run(
            task="Load data.csv and plot the distribution of each column",
            llm=llm,
            verbose=True,
        )
        print(result.status)
    """
    with KernelRuntime(kernel_name=kernel_name) as kernel:

        # Load skills if provided
        if skills_path:
            from pathlib import Path
            if Path(skills_path).exists():
                code   = Path(skills_path).read_text()
                output = kernel.execute(code, silent=True, timeout=60)
                if output.has_error and verbose:
                    print(f"[kerno] Skills load warning: {output.error.evalue}")

        # Select loop
        loop_cls = {
            "reactive": ReactiveLoop,
            "reflect":  ReflectReviseLoop,
        }.get(loop, ReactiveLoop)

        agent = loop_cls(
            kernel    = kernel,
            llm       = llm,
            max_cells = max_cells,
            verbose   = verbose,
        )

        return agent.run(task)


__all__ = [
    "run",
    "KernelRuntime",
    "ReactiveLoop",
    "ReflectReviseLoop",
    "Cell",
    "CellOutput",
    "CellError",
    "Message",
    "SessionResult",
    "SessionStatus",
]

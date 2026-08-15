# kerno/__init__.py
"""
kerno: a kernel-native agent runtime.
"""

from kerno.kernel.runtime  import KernelRuntime
from kerno.kernel.pool     import KernelPool
from kerno.loop.reactive   import ReactiveLoop
from kerno.loop.reflect    import ReflectReviseLoop
from kerno.loop.plan_execute import PlanExecuteLoop
from kerno.errors.classifier import ErrorClassifier
from kerno.errors.recovery   import RecoveryStrategy
from kerno.skills.registry   import SkillRegistry
from kerno.skills.bootstrap  import bootstrap as load_default_skills
from kerno.audit.notebook    import NotebookAuditTrail
from kerno.types import (
    Cell, CellOutput, CellError,
    Message, SessionResult, SessionStatus,
    ErrorClass, LLMCallable,
)


def run(
    task:          str,
    llm:           LLMCallable,
    *,
    loop:          str          = "reactive",
    kernel_name:   str          = "python3",
    max_cells:     int          = 50,
    skills_path:   str | None   = None,
    save_notebook: bool         = False,
    notebook_dir:  str          = "sessions",
    verbose:       bool         = False,
) -> SessionResult:
    """
    Run a task in a kernel-agent session.

    Args:
        task:          Natural language task description
        llm:           Callable(messages: list[Message]) -> str
        loop:          "reactive" | "reflect" | "plan"
        kernel_name:   Jupyter kernel spec name (default: "python3")
        max_cells:     Maximum cells before stopping (default: 50)
        skills_path:   Path to a Python skills bootstrap file
        save_notebook: If True, save session as a .ipynb file
        notebook_dir:  Directory for saved notebooks (default: "sessions")
        verbose:       Print execution trace to stdout

    Returns:
        SessionResult

    Example:
        import anthropic
        from kerno import run, Message

        client = anthropic.Anthropic()

        def llm(messages: list[Message]) -> str:
            response = client.messages.create(
                model    = "claude-opus-4-5",
                max_tokens = 4096,
                system   = messages[0].content,
                messages = [{"role": m.role, "content": m.content}
                            for m in messages[1:]],
            )
            return response.content[0].text

        result = run(
            task           = "Load data.csv and plot column distributions",
            llm            = llm,
            loop           = "reflect",
            save_notebook  = True,
            verbose        = True,
        )
        print(result.status, result.cells_executed)
    """
    loop_cls = {
        "reactive": ReactiveLoop,
        "reflect":  ReflectReviseLoop,
        "plan":     PlanExecuteLoop,
    }.get(loop, ReactiveLoop)

    with KernelRuntime(kernel_name=kernel_name) as kernel:

        # Load skills
        if skills_path:
            from pathlib import Path
            if Path(skills_path).exists():
                out = kernel.execute(Path(skills_path).read_text(),
                                     silent=True, timeout=60)
                if out.has_error and verbose:
                    print(f"[kerno] Skills warning: {out.error.evalue}")
        else:
            # Load default skills
            load_default_skills(kernel)

        agent  = loop_cls(
            kernel    = kernel,
            llm       = llm,
            max_cells = max_cells,
            verbose   = verbose,
        )
        result = agent.run(task)

    # Optionally persist as notebook
    if save_notebook:
        trail = NotebookAuditTrail.from_result(result)
        path  = trail.save(notebook_dir)
        if verbose:
            print(f"\n[kerno] Notebook saved → {path}")

    return result


__all__ = [
    # Top-level API
    "run",

    # Kernel
    "KernelRuntime",
    "KernelPool",

    # Loops
    "ReactiveLoop",
    "ReflectReviseLoop",
    "PlanExecuteLoop",

    # Errors
    "ErrorClassifier",
    "RecoveryStrategy",

    # Skills
    "SkillRegistry",
    "load_default_skills",

    # Audit
    "NotebookAuditTrail",

    # Types
    "Cell",
    "CellOutput",
    "CellError",
    "Message",
    "SessionResult",
    "SessionStatus",
    "ErrorClass",
    "LLMCallable",
]

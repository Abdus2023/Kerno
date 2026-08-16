# kerno/session.py
"""
Session resume — kernel failure does not imply session failure (K-004).

A session is: identity, task, memory, history, artifacts, policy.
A kernel is: a Python process, namespace, execution state.
They are not the same thing (audit #35).

resume_session() continues a recorded SessionResult on a FRESH kernel:

    1. start a new kernel
    2. re-execute the recorded cells (replay) to restore computational
       state — blocked cells are blocked again by the same policy
    3. seed the loop with the restored history
    4. continue the agent with the LLM until completion

This is the "kernel crash != agent crash" path for a finished-but-
incomplete session, complementing BaseLoop.auto_restart which recovers
a kernel that dies DURING a live run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from kerno.execution.budget    import BudgetedExecutor, ExecutionBudget
from kerno.execution.engine    import ExecutionEngine
from kerno.kernel.runtime      import KernelRuntime
from kerno.loop.plan_execute   import PlanExecuteLoop
from kerno.loop.reactive       import ReactiveLoop
from kerno.loop.reflect        import ReflectReviseLoop
from kerno.security.allowlist  import AllowList
from kerno.security.capabilities import CapabilityBroker
from kerno.types import (
    Cell, CellError, CellOutput, LLMCallable,
    SessionResult, SessionStatus,
)


def resume_session(
    result:              SessionResult,
    llm:                 LLMCallable,
    *,
    loop:                str                 = "reactive",
    allowlist:           Optional[AllowList] = None,
    capability_broker:   Optional[CapabilityBroker] = None,
    capabilities:        Optional[frozenset[str]] = None,
    budget:              Optional[ExecutionBudget] = None,
    max_cells:           int                 = 50,
    cell_timeout:        float               = 120.0,
    auto_restart:        bool                = True,
    kernel_name:         str                 = "python3",
    verbose:             bool                = False,
    task_prefix:         str                 = "[resumed] ",
) -> SessionResult:
    """
    Continue a recorded session on a fresh kernel (audit #36).

    The recorded cells are re-executed to restore the namespace, then the
    agent loop continues from that history — the LLM only writes NEW cells.

    Returns a new SessionResult whose history contains the restored cells
    followed by the continuation cells.
    """
    if not result.cells:
        raise ValueError("Cannot resume a session with no recorded cells")

    with KernelRuntime(kernel_name=kernel_name) as kernel:
        # Trusted host-side setup: install the runtime import hook.
        if allowlist:
            kcode = allowlist.to_kernel_code()
            if kcode:
                kernel.execute(kcode, silent=True, timeout=10)

        # Execution choke point (K-001)
        caps = (
            capabilities if capabilities is not None
            else (frozenset({"kernel.execute"})
                  if capability_broker is not None else frozenset())
        )
        engine = ExecutionEngine(
            kernel,
            allowlist            = allowlist,
            broker               = capability_broker,
            default_capabilities = caps,
        )
        if budget is not None:
            engine = BudgetedExecutor(engine, budget)

        # ── Restore computational state by replaying recorded cells ──────
        # Through the engine with agent origin: policy is re-applied, so
        # cells that were blocked originally are blocked again.
        restored: list[Cell] = []
        for cell in result.cells:
            output = engine.execute(cell.code, timeout=cell_timeout)
            restored.append(Cell(
                code     = cell.code,
                output   = output,
                cell_num = cell.cell_num,
                author   = cell.author,
            ))

        # ── Continue the agent from the restored history ─────────────────
        loop_cls = {
            "reactive": ReactiveLoop,
            "reflect":  ReflectReviseLoop,
            "plan":     PlanExecuteLoop,
        }.get(loop, ReactiveLoop)

        agent = loop_cls(
            kernel       = engine,
            llm          = llm,
            max_cells    = max_cells,
            cell_timeout = cell_timeout,
            verbose      = verbose,
            auto_restart = auto_restart,
        )
        return agent.run(
            task_prefix + result.task,
            initial_history = restored,
            initial_summary = result.summary,
        )


# ── Session serialization (persistence / replay / export) ─────────────────────

def fork_session(
    result:              SessionResult,
    llm:                 LLMCallable,
    *,
    up_to_cell:          int,
    loop:                str                 = "reactive",
    allowlist:           Optional[AllowList] = None,
    capability_broker:   Optional[CapabilityBroker] = None,
    max_cells:           int                 = 50,
    cell_timeout:        float               = 120.0,
    auto_restart:        bool                = True,
    kernel_name:         str                 = "python3",
    verbose:             bool                = False,
) -> SessionResult:
    """
    Fork a session at a cell boundary (audit #59/#60).

    The recorded cells up to `up_to_cell` are re-executed on a FRESH
    kernel (restoring the computational state at that point), then a NEW
    LLM continues from there — like branching a computation at a
    checkpoint and running a different configuration.

        Checkpoint (cell N)
            ├── branch A (LLM A)  ← original session
            └── branch B (LLM B)  ← this fork

    Returns a new SessionResult whose history is the replayed prefix
    followed by the new LLM's continuation cells.
    """
    n = len(result.cells)
    if not 1 <= up_to_cell <= n:
        raise ValueError(
            "up_to_cell must be in [1, {}], got {}".format(n, up_to_cell)
        )

    prefix = SessionResult(
        session_id      = result.session_id + "-fork",
        task            = result.task,
        status          = SessionStatus.COMPLETE,
        cells           = list(result.cells[:up_to_cell]),
        final_namespace = result.final_namespace,
        summary         = result.summary,
        started_at      = result.started_at,
    )
    return resume_session(
        prefix, llm,
        loop               = loop,
        allowlist          = allowlist,
        capability_broker  = capability_broker,
        max_cells          = max_cells,
        cell_timeout       = cell_timeout,
        auto_restart       = auto_restart,
        kernel_name        = kernel_name,
        verbose            = verbose,
        task_prefix        = "[fork] ",
    )


def session_to_dict(result: SessionResult) -> dict:
    """
    Serialize a SessionResult to a plain JSON-serializable dict.

    Every cell's output is preserved (stdout, stderr, result, displays,
    images, error, duration, execution_id) so a saved session can be
    replayed, resumed, or audited in another process.
    """
    cells = []
    for cell in result.cells:
        out = cell.output
        cells.append({
            "code":      cell.code,
            "cell_num":  cell.cell_num,
            "author":    cell.author,
            "timestamp": cell.timestamp,
            "reasoning": cell.reasoning,
            "output": {
                "stdout":        out.stdout,
                "stderr":        out.stderr,
                "result":        out.result,
                "displays":      out.displays,
                "images":        out.images,
                "duration":      out.duration,
                "execution_id":  out.execution_id,
                "error": (
                    None if out.error is None else {
                        "ename":     out.error.ename,
                        "evalue":    out.error.evalue,
                        "traceback": out.error.traceback,
                    }
                ),
            },
        })
    return {
        "session_id":      result.session_id,
        "task":            result.task,
        "status":          result.status.name,
        "summary":         result.summary,
        "final_namespace": result.final_namespace,
        "started_at":      result.started_at,
        "ended_at":        result.ended_at,
        "execution_ids":   list(result.execution_ids),
        "blocked_rules":   list(result.blocked_rules),
        "cells":           cells,
    }


def session_from_dict(data: dict) -> SessionResult:
    """Rebuild a SessionResult from session_to_dict() output."""
    cells = []
    for c in data.get("cells", []):
        o = c.get("output", {})
        err = o.get("error")
        from kerno.types import CellError
        cells.append(Cell(
            code      = c.get("code", ""),
            cell_num  = c.get("cell_num", 0),
            author    = c.get("author", "agent"),
            timestamp = c.get("timestamp", 0.0),
            reasoning = c.get("reasoning"),
            output    = CellOutput(
                stdout       = o.get("stdout", ""),
                stderr       = o.get("stderr", ""),
                result       = o.get("result"),
                displays     = list(o.get("displays", [])),
                images       = list(o.get("images", [])),
                duration     = o.get("duration", 0.0),
                execution_id = o.get("execution_id"),
                error        = (
                    None if err is None else CellError(
                        ename     = err.get("ename", "Error"),
                        evalue    = err.get("evalue", ""),
                        traceback = err.get("traceback", ""),
                    )
                ),
            ),
        ))
    return SessionResult(
        session_id      = data.get("session_id", ""),
        task            = data.get("task", ""),
        status          = SessionStatus[data.get("status", "COMPLETE")],
        cells           = cells,
        final_namespace = data.get("final_namespace", "{}"),
        summary         = data.get("summary", ""),
        started_at      = data.get("started_at", 0.0),
        ended_at        = data.get("ended_at"),
        execution_ids   = list(data.get("execution_ids", [])),
        blocked_rules   = list(data.get("blocked_rules", [])),
    )


def save_session(result: SessionResult, path: str | Path) -> Path:
    """Save a session as JSON (for replay / resume / audit)."""
    import json
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(session_to_dict(result), indent=2))
    return target


def load_session(path: str | Path) -> SessionResult:
    """Load a session saved by save_session()."""
    import json
    return session_from_dict(json.loads(Path(path).read_text()))


# ── Resume from a notebook (audit #56/#96: notebook → session → resume) ──────

def resume_from_notebook(
    path:                str,
    llm:                 LLMCallable,
    *,
    new_task:            Optional[str] = None,
    loop:                str           = "reactive",
    allowlist:           Optional[AllowList] = None,
    capability_broker:   Optional[CapabilityBroker] = None,
    budget:              Optional[object] = None,
    max_cells:           int           = 50,
    cell_timeout:        float         = 120.0,
    auto_restart:        bool          = True,
    kernel_name:         str           = "python3",
    verbose:             bool          = False,
) -> SessionResult:
    """
    Continue a session from a saved notebook, through the choke point.

    The notebook is a human-readable PROJECTION of the execution ledger
    (audit #56); the canonical state is rebuilt by re-executing the
    recorded cells on a FRESH kernel via the ExecutionEngine (policy
    re-applied — blocked cells stay blocked), then the LLM continues.

    Usage:
        result = resume_from_notebook(
            "sessions/20240127_analyze_q3_sales.ipynb",
            llm=my_llm,
            allowlist=AllowList.data_analysis(),
        )
    """
    import nbformat
    from pathlib import Path as _Path

    from kerno.notebook.continuation import load_notebook
    from kerno.types import Cell, CellOutput, SessionStatus as _SS

    nb_path = _Path(path)
    if not nb_path.exists():
        raise FileNotFoundError("Notebook not found: {}".format(path))

    with open(nb_path) as f:
        nb = nbformat.read(f, as_version=4)

    original_task = nb.metadata.get("kerno", {}).get("task", "")

    # Rebuild a SessionResult from the notebook's recorded cells WITHOUT
    # executing them — resume_session() replays them on a fresh kernel
    # through the engine (single choke point, policy enforced).
    prior_cells: list[Cell] = []
    for i, cell in enumerate(nb.cells, start=1):
        if cell.cell_type != "code":
            continue
        outputs = cell.get("outputs", [])
        stdout = "".join(
            o.get("text", "") for o in outputs
            if o.get("output_type") == "stream" and o.get("name") == "stdout"
        )
        error = None
        for o in outputs:
            if o.get("output_type") == "error":
                from kerno.types import CellError
                error = CellError(
                    ename  = o.get("ename", "Error"),
                    evalue = o.get("evalue", ""),
                    traceback = "\n".join(o.get("traceback", [])),
                )
                break
        prior_cells.append(Cell(
            code     = cell.source,
            output   = CellOutput(stdout=stdout, error=error),
            cell_num = i,
            author   = "recorded",
        ))

    prior = SessionResult(
        session_id      = nb.metadata.get("kerno", {}).get("session_id", "nb-" + nb_path.stem),
        task            = original_task or "[notebook]",
        status          = _SS.INTERRUPTED,
        cells           = prior_cells,
        final_namespace = "{}",
        summary         = "",
    )

    task = new_task or (
        "Continue this analysis. Prior work has been loaded from a "
        "notebook. Original task: {}. Resume from where the prior "
        "session ended.".format(original_task)
    )
    return resume_session(
        prior, llm,
        loop               = loop,
        allowlist          = allowlist,
        capability_broker  = capability_broker,
        budget             = budget,
        max_cells          = max_cells,
        cell_timeout       = cell_timeout,
        auto_restart       = auto_restart,
        kernel_name        = kernel_name,
        verbose            = verbose,
        task_prefix        = "",
    )

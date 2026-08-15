# kerno/_run.py
"""
Core run functions: run() and run_with_pool().
Extracted from __init__.py to keep the public surface clean.
"""

from __future__ import annotations

from kerno.audit.notebook      import NotebookAuditTrail
from kerno.comms.channel       import CommMessage, KernoComm
from kerno.config              import KernoConfig
from kerno.errors.classifier   import ErrorClassifier
from kerno.errors.recovery     import RecoveryStrategy
from kerno.kernel.pool         import KernelPool
from kerno.kernel.runtime      import KernelRuntime
from kerno.loop.debate         import DebateLoop
from kerno.loop.hierarchical   import HierarchicalLoop
from kerno.loop.multi_agent    import (
    AgentRole, MultiAgentLoop,
    analyst_role, critic_role, narrator_role,
)
from kerno.loop.plan_execute   import PlanExecuteLoop
from kerno.loop.reactive       import ReactiveLoop
from kerno.loop.reflect        import ReflectReviseLoop
from kerno.memory.simple       import SimpleMemoryStore
from kerno.memory.store        import MemoryEntry, MemoryStore
from kerno.notebook.continuation import continue_from_notebook
from kerno.plugins             import BasePlugin, PluginRegistry
from kerno.plugins.registry    import (
    CostEstimatorPlugin, NotebookPlugin, TimingPlugin,
)
from kerno.runner              import run_with_config
from kerno.security.allowlist  import AllowList, AllowListViolation
from kerno.security.sanitizer  import InputSanitizer
from kerno.skills.bootstrap    import bootstrap as load_default_skills
from kerno.skills.bootstrap    import bootstrap_minimal, bootstrap_ml
from kerno.skills.registry     import SkillRegistry
from kerno.telemetry           import get_logger, get_metrics, get_tracer
from kerno.types import (
    Cell, CellError, CellOutput,
    ErrorClass, LLMCallable,
    Message, SessionResult, SessionStatus,
)


def run(
    task:                 str,
    llm:                  LLMCallable,
    *,
    loop:                 str                    = "reactive",
    planner_llm:          LLMCallable | None      = None,
    roles:                list[AgentRole] | None  = None,
    position:             str                     = "",
    n_rounds:             int                     = 2,
    kernel_name:          str                     = "python3",
    max_cells:            int                     = 50,
    skills_path:          str | None              = None,
    load_default_skills:  bool                    = True,
    skill_modules:        list[str] | None        = None,
    memory:               MemoryStore | None      = None,
    allowlist:            AllowList | None        = None,
    plugins:              PluginRegistry | None   = None,
    save_notebook:        bool                    = False,
    notebook_dir:         str                     = "sessions",
    comm_handlers:        dict | None             = None,
    verbose:              bool                    = False,
) -> SessionResult:
    """
    Run a task in a kernel-agent session.

    Args:
        task:                 Natural language task description
        llm:                  Callable(messages: list[Message]) -> str

        loop:                 "reactive" | "reflect" | "plan" |
                              "hierarchical" | "multi_agent" | "debate"
        planner_llm:          Separate LLM for planning (hierarchical)
        roles:                AgentRole list (multi_agent)
        position:             Hypothesis to debate (debate loop)
        n_rounds:             Number of debate rounds (debate loop)

        kernel_name:          Jupyter kernel spec (default: "python3")
        max_cells:            Maximum cells before stopping

        skills_path:          Path to extra skills file
        load_default_skills:  Load built-in skills (default: True)
        skill_modules:        Subset of built-in skill modules to load

        memory:               MemoryStore for cross-session recall
        allowlist:            Security allowlist
        plugins:              PluginRegistry for lifecycle hooks

        save_notebook:        Save session as .ipynb
        notebook_dir:         Directory for notebooks

        comm_handlers:        {kind: fn} for structured kernel messages
        verbose:              Print execution trace

    Returns:
        SessionResult

    Examples:
        # Minimal
        result = run("Analyze data.csv", llm=my_llm)

        # Full stack
        result = run(
            task      = "Build churn model",
            llm       = my_llm,
            loop      = "reflect",
            memory    = SimpleMemoryStore(),
            allowlist = AllowList.data_analysis(),
            plugins   = PluginRegistry().register(TimingPlugin()),
            save_notebook = True,
        )

        # Debate
        result = run(
            task     = "What drives customer churn?",
            llm      = my_llm,
            loop     = "debate",
            position = "Price sensitivity is the primary churn driver",
            n_rounds = 2,
        )
    """
    from pathlib import Path

    with KernelRuntime(kernel_name=kernel_name) as kernel:

        # ── Skills ────────────────────────────────────────────────────────
        if load_default_skills:
            if skill_modules:
                load_default_skills(kernel, include=skill_modules)
            else:
                load_default_skills(kernel)

            if plugins:
                for name in (skill_modules or [
                    "data_skills", "viz_skills", "introspect_skills",
                    "ml_skills",   "stats_skills",
                ]):
                    plugins.on_skill_load(name)

        if skills_path and Path(skills_path).exists():
            out = kernel.execute(
                Path(skills_path).read_text(), silent=True, timeout=60
            )
            if out.has_error and verbose:
                print("[kerno] Skills warning: {}".format(out.error.evalue))

        # ── Security ──────────────────────────────────────────────────────
        if allowlist:
            kcode = allowlist.to_kernel_code()
            if kcode:
                kernel.execute(kcode, silent=True, timeout=10)

        # ── Comms ─────────────────────────────────────────────────────────
        comm = None
        if comm_handlers:
            comm = KernoComm(kernel).start()
            for kind, handler in comm_handlers.items():
                comm.on(kind, handler)

        # ── Loop ──────────────────────────────────────────────────────────
        common = dict(kernel=kernel, llm=llm, verbose=verbose)

        if loop == "hierarchical":
            if not planner_llm:
                raise ValueError("loop='hierarchical' requires planner_llm=")
            agent = HierarchicalLoop(
                planner_llm  = planner_llm,
                executor_llm = llm,
                **{k: v for k, v in common.items() if k != "llm"},
            )

        elif loop == "multi_agent":
            if not roles:
                raise ValueError("loop='multi_agent' requires roles=[...]")
            agent = MultiAgentLoop(kernel=kernel, roles=roles, verbose=verbose)

        elif loop == "debate":
            agent = DebateLoop(
                kernel     = kernel,
                proposer   = llm,
                challenger = planner_llm or llm,
                judge      = planner_llm or llm,
                position   = position,
                n_rounds   = n_rounds,
                verbose    = verbose,
            )

        else:
            loop_cls = {
                "reactive": ReactiveLoop,
                "reflect":  ReflectReviseLoop,
                "plan":     PlanExecuteLoop,
            }.get(loop, ReactiveLoop)

            loop_kwargs = dict(
                **common,
                max_cells = max_cells,
                memory    = memory,
                plugins   = plugins,
            )

            if allowlist:
                original_execute = kernel.execute
                def guarded_execute(code, **kw):
                    try:
                        allowlist.check(code)
                    except AllowListViolation as e:
                        return CellOutput(
                            error=CellError(
                                ename  = "AllowListViolation",
                                evalue = str(e),
                            )
                        )
                    return original_execute(code, **kw)
                kernel.execute = guarded_execute

            agent = loop_cls(**loop_kwargs)

        result = agent.run(task)

        if comm:
            comm.stop()

    # ── Post-run ──────────────────────────────────────────────────────────
    if save_notebook:
        trail = NotebookAuditTrail.from_result(result)
        path  = trail.save(notebook_dir)
        if verbose:
            print("\n[kerno] Notebook → {}".format(path))

    if memory and result.status == SessionStatus.COMPLETE:
        memory.store_session_result(
            session_id = result.session_id,
            task       = task,
            summary    = result.summary,
            namespace  = result.final_namespace,
        )

    return result


def run_with_pool(
    tasks:           list[str],
    llm:             LLMCallable,
    *,
    pool_size:       int               = 3,
    loop:            str               = "reactive",
    kernel_name:     str               = "python3",
    max_cells:       int               = 50,
    skills_path:     str | None        = None,
    memory:          MemoryStore | None = None,
    allowlist:       AllowList | None   = None,
    save_notebooks:  bool               = False,
    notebook_dir:    str                = "sessions",
    verbose:         bool               = False,
) -> list[SessionResult]:
    """Run multiple tasks in parallel using a KernelPool."""
    import concurrent.futures
    from pathlib import Path

    with KernelPool(size=pool_size, kernel_name=kernel_name,
                    skills_path=skills_path) as pool:

        def run_one(args):
            idx, task = args
            kernel    = pool.acquire("task-{}".format(idx))
            try:
                if not skills_path:
                    load_default_skills(kernel)
                if allowlist:
                    kcode = allowlist.to_kernel_code()
                    if kcode:
                        kernel.execute(kcode, silent=True, timeout=10)

                loop_cls = {
                    "reactive": ReactiveLoop,
                    "reflect":  ReflectReviseLoop,
                    "plan":     PlanExecuteLoop,
                }.get(loop, ReactiveLoop)

                agent  = loop_cls(
                    kernel=kernel, llm=llm,
                    max_cells=max_cells, memory=memory, verbose=verbose
                )
                result = agent.run(task)

                if save_notebooks:
                    NotebookAuditTrail.from_result(result).save(notebook_dir)

                return idx, result
            finally:
                pool.release("task-{}".format(idx), reason="complete")

        results_map: dict[int, SessionResult] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as ex:
            futures = {ex.submit(run_one, (i, t)): i for i, t in enumerate(tasks)}
            for future in concurrent.futures.as_completed(futures):
                try:
                    idx, result = future.result()
                    results_map[idx] = result
                    if verbose:
                        print("[kerno] Task {}: {} "
                              "({} cells)".format(idx, result.status.name,
                              result.cells_executed))
                except Exception as e:
                    if verbose:
                        print("[kerno] Task {} failed: {}".format(futures[future], e))

        return [results_map[i] for i in range(len(tasks)) if i in results_map]

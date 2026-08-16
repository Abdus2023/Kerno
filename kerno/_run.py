# kerno/_run.py
"""
Core run functions: run() and run_with_pool().
Extracted from __init__.py to keep the public surface clean.
"""

from __future__ import annotations

from kerno.audit.notebook      import NotebookAuditTrail
from kerno.comms.channel       import KernoComm
from kerno.approval            import ApprovalGate
from kerno.effects             import EffectLedger
from kerno.execution.budget    import BudgetedExecutor, ExecutionBudget
from kerno.execution.engine    import ExecutionEngine
from kerno.execution.modes     import DryRunExecutor
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
from kerno.memory.store        import MemoryStore
from kerno.plugins             import PluginRegistry
from kerno.plugins.registry    import (
    CostEstimatorPlugin, NotebookPlugin, TimingPlugin,
)
from kerno.reproducibility     import build_manifest
from kerno.runner              import run_with_config
from kerno.security.allowlist  import AllowList
from kerno.security.capabilities import CapabilityBroker
from kerno.skills.bootstrap    import bootstrap as bootstrap_skills
from kerno.types import (
    LLMCallable, Message, SessionResult, SessionStatus,
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
    capability_broker:    CapabilityBroker | None = None,
    capabilities:         frozenset[str] | None   = None,
    budget:               ExecutionBudget | None  = None,
    redactor:             callable | None         = None,
    effect_ledger:        EffectLedger | None     = None,
    approval_gate:        ApprovalGate | None     = None,
    plugins:              PluginRegistry | None   = None,
    save_notebook:        bool                    = False,
    notebook_dir:         str                     = "sessions",
    comm_handlers:        dict | None             = None,
    auto_restart:         bool                    = False,
    model_name:           str                     = "",
    artifact_paths:       list[str] | None        = None,
    isolation:            str                     = "shared",
    mode:                 str                     = "live",   # "live" | "dry_run"
    cancel_token:         object | None           = None,     # audit #83
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
        capability_broker:    CapabilityBroker for authorization (K-008).
                              When set, every agent-origin execution must
                              hold active grants for `capabilities`
                              (default: {"kernel.execute"}).
        capabilities:         Capabilities required for each agent cell.
                              Only enforced when capability_broker is set.
        budget:               ExecutionBudget limiting total cells, wall
                              time, and output bytes across the session.
        redactor:             Redaction function (audit #68) applied to
                              recorded previews/errors (e.g. SecretBroker.redact).
        effect_ledger:        EffectLedger observing declared vs actual
                              filesystem effects (audit #93).
        approval_gate:        ApprovalGate consulted when an execution
                              requires human.approval (audit #90, fail closed).
        plugins:              PluginRegistry for lifecycle hooks

        save_notebook:        Save session as .ipynb
        notebook_dir:         Directory for notebooks

        comm_handlers:        {kind: fn} for structured kernel messages
        auto_restart:         On kernel death, restart the kernel and
                              restore state from history (K-004)
        model_name:           LLM model identifier for the reproducibility
                              manifest (saved with the notebook)
        artifact_paths:       Files to hash into the reproducibility
                              manifest as produced artifacts
        mode:                 "live" (real kernel) | "dry_run" (validate
                              without executing, audit #91). Dry runs
                              apply the allowlist but never start a kernel.
        cancel_token:         CancellationToken (audit #83): checked
                              before every cell and DURING execution
                              (mid-cell kernel interrupt). A cancelled
                              session ends INTERRUPTED. Supported for
                              reactive/reflect/plan/multi_agent loops.
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
    from contextlib import nullcontext
    from pathlib import Path

    if mode not in ("live", "dry_run"):
        raise ValueError("mode must be 'live' or 'dry_run'")
    live = (mode == "live")

    # Audit #91: dry-run mode validates the whole session (policy applied,
    # loops driven, cells produced) WITHOUT ever starting a kernel.
    if live:
        kernel_ctx = KernelRuntime(kernel_name=kernel_name)
    else:
        kernel_ctx = nullcontext(DryRunExecutor(allowlist=allowlist))

    with kernel_ctx as kernel:

        # ── Skills (live only: skills need a real kernel) ────────────────
        if live and load_default_skills:
            if skill_modules:
                bootstrap_skills(kernel, include=skill_modules)
            else:
                bootstrap_skills(kernel)

            if plugins:
                for name in (skill_modules or [
                    "data_skills", "viz_skills", "introspect_skills",
                    "ml_skills",   "stats_skills",
                ]):
                    plugins.on_skill_load(name)

        if live and skills_path and Path(skills_path).exists():
            out = kernel.execute(
                Path(skills_path).read_text(), silent=True, timeout=60
            )
            if out.has_error and verbose:
                print("[kerno] Skills warning: {}".format(out.error.evalue))

        # ── Security ──────────────────────────────────────────────────────
        # Trusted host-side setup: install the runtime import hook directly
        # on the raw kernel (defense-in-depth for anything that runs there).
        if live and allowlist:
            kcode = allowlist.to_kernel_code()
            if kcode:
                kernel.execute(kcode, silent=True, timeout=10)

        # ── Execution choke point (K-001) ─────────────────────────────────
        # ALL agent code — regardless of loop strategy — must pass through
        # the ExecutionEngine, which enforces authorization (K-008) and the
        # allowlist policy, and records an audit trail + event stream.
        # Loops never receive the raw kernel.
        if capability_broker is not None and capabilities is None:
            # Default contract: a session with a broker requires the
            # kernel.execute capability for every agent cell.
            capabilities = frozenset({"kernel.execute"})
        engine = ExecutionEngine(
            kernel,
            allowlist            = allowlist,
            broker               = capability_broker,
            default_capabilities = capabilities or frozenset(),
            redactor             = redactor,
            effect_ledger        = effect_ledger,
            approval_gate        = approval_gate,
        )
        if budget is not None:
            # Budget enforcement wraps the choke point: exhausted budgets
            # refuse further executions before they reach the kernel.
            engine = BudgetedExecutor(engine, budget)

        # ── Comms (live only: needs kernel internals) ────────────────────
        comm = None
        if live and comm_handlers:
            comm = KernoComm(kernel).start()
            for kind, handler in comm_handlers.items():
                comm.on(kind, handler)

        # ── Loop ──────────────────────────────────────────────────────────
        common = dict(kernel=engine, llm=llm, verbose=verbose)

        if loop == "hierarchical":
            if not planner_llm:
                raise ValueError("loop='hierarchical' requires planner_llm=")
            agent = HierarchicalLoop(
                planner_llm  = planner_llm,
                executor_llm = llm,
                cancel_token = cancel_token,
                **{k: v for k, v in common.items() if k != "llm"},
            )

        elif loop == "multi_agent":
            if not roles:
                raise ValueError("loop='multi_agent' requires roles=[...]")
            kwargs: dict = dict(kernel=engine, roles=roles, verbose=verbose,
                               cancel_token=cancel_token)
            if isolation == "isolated":
                # K-009: each agent runs in its own kernel; state crosses
                # boundaries only through explicit shared memory.
                kwargs["isolation"]      = "isolated"
                kwargs["kernel_factory"] = _isolated_kernel_factory(
                    kernel_name, allowlist, capability_broker,
                    capabilities or frozenset(),
                )
                # Audit #86: in isolated mode the run()-level budget is
                # meaningless (turns use fresh kernels), so forward it as
                # the PER-AGENT budget — each agent gets its own share.
                if budget is not None:
                    kwargs["budget"] = budget
            agent = MultiAgentLoop(**kwargs)

        elif loop == "debate":
            agent = DebateLoop(
                kernel       = engine,
                proposer     = llm,
                challenger   = planner_llm or llm,
                judge        = planner_llm or llm,
                position     = position,
                n_rounds     = n_rounds,
                verbose      = verbose,
                cancel_token = cancel_token,
            )

        else:
            loop_cls = {
                "reactive": ReactiveLoop,
                "reflect":  ReflectReviseLoop,
                "plan":     PlanExecuteLoop,
            }.get(loop, ReactiveLoop)

            agent = loop_cls(
                **common,
                max_cells    = max_cells,
                memory       = memory,
                plugins      = plugins,
                auto_restart = auto_restart,
            )

        try:
            # Audit #83: every loop strategy supports cancellation.
            # BaseLoop-family loops take the token at run(); the
            # standalone loops (hierarchical/multi_agent/debate) take it
            # at construction and their run() takes only task.
            if isinstance(agent, (ReactiveLoop, ReflectReviseLoop, PlanExecuteLoop)):
                result = agent.run(task, cancel_token=cancel_token)
            else:
                result = agent.run(task)
        finally:
            # Exception-safe lifecycle: comms must always be torn down,
            # even when the agent loop raises.
            if comm:
                comm.stop()

        kernel_generation = kernel.generation if live else 0

    # ── Execution-ledger correlation (audit #78) ─────────────────────────
    # The caller can cross-reference these execution_ids against the
    # engine's records/events for full provenance.
    result.execution_ids = [
        r.execution_id for r in getattr(engine, "records", ())
    ]
    result.blocked_rules = [
        r.rule for r in getattr(engine, "records", ())
        if not r.allowed and r.rule
    ]

    # ── Post-run ──────────────────────────────────────────────────────────
    if save_notebook:
        trail = NotebookAuditTrail.from_result(result, redactor=redactor)
        manifest = build_manifest(
            result,
            kernel_generation = kernel_generation,
            model_name        = model_name,
            artifact_paths    = artifact_paths,
        )
        path = trail.save(notebook_dir, manifest=manifest.to_dict())
        if verbose:
            print("\n[kerno] Notebook → {}".format(path))
            print("[kerno] Manifest → {}".format(
                path.with_name("{}.manifest.json".format(result.session_id))
            ))

    if memory is not None and result.status == SessionStatus.COMPLETE:
        memory.store_session_result(
            session_id = result.session_id,
            task       = task,
            summary    = result.summary,
            namespace  = result.final_namespace,
        )

    return result


def _isolated_kernel_factory(
    kernel_name:        str,
    allowlist:          AllowList | None,
    capability_broker:  CapabilityBroker | None,
    capabilities:       frozenset[str],
):
    """Factory producing a fresh policy-wrapped kernel per agent (K-009)."""

    def factory():
        k = KernelRuntime(kernel_name=kernel_name)
        k.start()
        if allowlist:
            kcode = allowlist.to_kernel_code()
            if kcode:
                k.execute(kcode, silent=True, timeout=10)
        return ExecutionEngine(
            k,
            allowlist            = allowlist,
            broker               = capability_broker,
            default_capabilities = capabilities,
        )

    return factory


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
    capability_broker: CapabilityBroker | None = None,
    budget:          ExecutionBudget | None = None,
    redactor:        callable | None    = None,
    effect_ledger:   EffectLedger | None = None,
    approval_gate:   ApprovalGate | None = None,
    cancel_token:    object | None      = None,
    save_notebooks:  bool               = False,
    notebook_dir:    str                = "sessions",
    auto_restart:    bool               = False,
    model_name:      str                = "",
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
                    bootstrap_skills(kernel)
                if allowlist:
                    kcode = allowlist.to_kernel_code()
                    if kcode:
                        kernel.execute(kcode, silent=True, timeout=10)

                # Execution choke point (K-001): pool workers also execute
                # agent code exclusively through the engine.
                caps = (
                    frozenset({"kernel.execute"})
                    if capability_broker is not None else frozenset()
                )
                engine = ExecutionEngine(
                    kernel,
                    allowlist            = allowlist,
                    broker               = capability_broker,
                    default_capabilities = caps,
                    redactor             = redactor,
                    effect_ledger        = effect_ledger,
                    approval_gate        = approval_gate,
                )
                if budget is not None:
                    engine = BudgetedExecutor(engine, budget)

                loop_cls = {
                    "reactive": ReactiveLoop,
                    "reflect":  ReflectReviseLoop,
                    "plan":     PlanExecuteLoop,
                }.get(loop, ReactiveLoop)

                agent  = loop_cls(
                    kernel=engine, llm=llm,
                    max_cells=max_cells, memory=memory, verbose=verbose,
                    auto_restart=auto_restart,
                )
                result = agent.run(task, cancel_token=cancel_token)
                result.execution_ids = [
                    r.execution_id for r in getattr(engine, "records", ())
                ]
                result.blocked_rules = [
                    r.rule for r in getattr(engine, "records", ())
                    if not r.allowed and r.rule
                ]

                if save_notebooks:
                    manifest = build_manifest(
                        result,
                        kernel_generation = kernel.generation,
                        model_name        = model_name,
                    )
                    NotebookAuditTrail.from_result(
                        result, redactor=redactor
                    ).save(
                        notebook_dir, manifest=manifest.to_dict()
                    )

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

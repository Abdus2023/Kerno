# kerno/compose.py
"""
Composable session builder.

Instead of a single run() function with 20 parameters,
a builder that makes the composition explicit and readable.

Design:
  Session = LLM + Kernel + Skills + Pipeline + Memory + Security

Each piece is independently swappable.
The builder assembles them, validates dependencies, and runs.

Usage:
    from kerno.compose import Session
    from kerno.llm     import anthropic_llm, CachedLLM, RetryLLM
    from kerno.skills.composer import ml_skills

    result = (
        Session()
        .with_llm(RetryLLM(anthropic_llm("claude-opus-4-5")))
        .with_kernel()
        .with_skills(ml_skills())
        .with_memory(SimpleMemoryStore())
        .with_security(AllowList.data_analysis())
        .with_plugins(TimingPlugin(), CostEstimatorPlugin())
        .with_loop("reflect")
        .run("Build a churn prediction model")
    )

    # Or fully custom pipeline:
    result = (
        Session()
        .with_llm(my_llm)
        .with_kernel()
        .with_skills(analysis_skills())
        .with_pipeline(Pipeline([
            InjectMemoryStep(memory),
            GenerateCodeStep(my_llm),
            TransformCodeStep([AllowListTransformer(allowlist), TimingTransformer()]),
            ExecuteStep(kernel),
            StoreInsightStep(memory, my_llm),
            CompletionCheckStep(),
        ]))
        .run("Analyze sales trends")
    )
"""

from __future__ import annotations

import uuid
from typing import Optional

from kerno.interfaces import AgentState, Executor, LLM, Memory
from kerno.pipeline   import LoopStep, Pipeline
from kerno.types      import SessionResult, SessionStatus


class Session:
    """
    Composable session builder.
    Each .with_*() method returns self — chains freely.
    .run(task) assembles the pieces and executes.
    """

    def __init__(self):
        self._llm:         Optional[LLM]      = None
        self._kernel:      Optional[Executor]  = None
        self._skills       = None
        self._memory:      Optional[Memory]    = None
        self._allowlist    = None
        self._plugins      = None
        self._transformers: list               = []
        self._formatters:   list               = []
        self._pipeline:     Optional[Pipeline] = None
        self._loop_strategy: str               = "reactive"
        self._max_cells:    int                = 50
        self._verbose:      bool               = False
        self._save_notebook: bool              = False
        self._notebook_dir:  str               = "sessions"
        self._comm_handlers: dict              = {}
        self._kernel_name:   str               = "python3"

    # ── Builder methods ───────────────────────────────────────────────────────

    def with_llm(self, llm: LLM) -> "Session":
        self._llm = llm
        return self

    def with_kernel(
        self,
        kernel_name: str   = "python3",
        kernel:      object = None,
    ) -> "Session":
        if kernel:
            self._kernel = kernel
        else:
            self._kernel_name = kernel_name
            self._kernel = None   # Created lazily in run()
        return self

    def with_skills(self, skills) -> "Session":
        """Accept SkillSet, SkillRegistry, or path string."""
        self._skills = skills
        return self

    def with_memory(self, memory: Memory) -> "Session":
        self._memory = memory
        return self

    def with_security(self, allowlist) -> "Session":
        self._allowlist = allowlist
        return self

    def with_plugins(self, *plugins) -> "Session":
        from kerno.plugins import PluginRegistry
        self._plugins = PluginRegistry()
        for p in plugins:
            self._plugins.register(p)
        return self

    def with_transformers(self, *transformers) -> "Session":
        self._transformers.extend(transformers)
        return self

    def with_formatters(self, *formatters) -> "Session":
        self._formatters.extend(formatters)
        return self

    def with_loop(
        self,
        strategy:  str = "reactive",
        max_cells: int = 50,
    ) -> "Session":
        self._loop_strategy = strategy
        self._max_cells     = max_cells
        return self

    def with_pipeline(self, pipeline) -> "Session":
        """Provide a fully custom pipeline. Overrides with_loop()."""
        self._pipeline = pipeline
        return self

    def with_notebook(self, save: bool = True, directory: str = "sessions") -> "Session":
        self._save_notebook = save
        self._notebook_dir  = directory
        return self

    def with_comms(self, *handlers) -> "Session":
        self._comm_handlers = handlers
        return self

    def verbose(self, v: bool = True) -> "Session":
        self._verbose = v
        return self

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, task: str) -> SessionResult:
        """
        Validate configuration, assemble components, execute.
        """
        import time
        from pathlib import Path
        from kerno.kernel.runtime import KernelRuntime

        # ── Validation ────────────────────────────────────────────────────────
        if self._llm is None:
            raise ValueError("No LLM configured. Call .with_llm(my_llm) first.")

        # ── Kernel ────────────────────────────────────────────────────────────
        kernel_name = getattr(self, "_kernel_name", "python3")
        own_kernel  = self._kernel is None
        kernel      = self._kernel or KernelRuntime(kernel_name=kernel_name)

        try:
            if own_kernel:
                kernel.start()

            # ── Security in kernel ────────────────────────────────────────────
            if self._allowlist:
                kcode = self._allowlist.to_kernel_code()
                if kcode:
                    kernel.execute(kcode, silent=True, timeout=10)

            # ── Skills ────────────────────────────────────────────────────────
            self._load_skills(kernel)

            # ── Comms ─────────────────────────────────────────────────────────
            comm = None
            if self._comm_handlers:
                from kerno.comms.channel import KernoComm
                comm = KernoComm(kernel).start()
                for kind, handler in self._comm_handlers.items():
                    comm.on(kind, handler)

            # ── Build pipeline ────────────────────────────────────────────────
            pipeline = self._pipeline or self._build_pipeline(kernel)

            # ── Initial state ─────────────────────────────────────────────────
            session_id = str(uuid.uuid4())
            state      = AgentState(
                task       = task,
                session_id = session_id,
            )

            # ── Plugin: session start ─────────────────────────────────────────
            if self._plugins:
                self._plugins.on_session_start(task, session_id)

            # ── Execute ───────────────────────────────────────────────────────
            started_at = time.time()
            final      = pipeline.run(state)
            ended_at   = time.time()

            # ── Build result ──────────────────────────────────────────────────
            status = (
                SessionStatus.COMPLETE       if final.complete
                else SessionStatus.ERROR_UNHANDLED if final.error
                else SessionStatus.MAX_CELLS
            )
            result = SessionResult(
                session_id      = session_id,
                task            = task,
                status          = status,
                cells           = final.history,
                final_namespace = kernel.namespace,
                summary         = final.summary,
                started_at      = started_at,
                ended_at        = ended_at,
            )

            # ── Plugin: session complete ──────────────────────────────────────
            if self._plugins:
                self._plugins.on_session_complete(result)

            if comm:
                comm.stop()

            # ── Notebook ──────────────────────────────────────────────────────
            if self._save_notebook:
                from kerno.audit.notebook import NotebookAuditTrail
                trail = NotebookAuditTrail.from_result(result)
                path  = trail.save(self._notebook_dir)
                if self._verbose:
                    print("[kerno] Notebook → {}".format(path))

            return result

        finally:
            if own_kernel:
                kernel.shutdown()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _load_skills(self, kernel) -> None:
        if self._skills is None:
            from kerno.skills.bootstrap import bootstrap
            bootstrap(kernel)
        elif isinstance(self._skills, str):
            from pathlib import Path
            kernel.execute(Path(self._skills).read_text(), silent=True, timeout=60)
        elif hasattr(self._skills, "load_into"):
            self._skills.load_into(kernel)
        elif hasattr(self._skills, "load_code"):
            pass   # SkillRegistry — already loaded externally

    def _build_pipeline(self, kernel) -> Pipeline:
        """Build the default pipeline for the selected strategy."""
        from kerno.loop.factory import (
            make_reactive, make_reflect, make_plan_execute,
            is_complete,
        )
        from kerno.steps.transform import NormalizationTransformer

        transformers = [NormalizationTransformer()] + self._transformers
        if self._allowlist:
            from kerno.steps.transform import AllowListTransformer
            transformers.append(AllowListTransformer(self._allowlist))

        strategy_builders = {
            "reactive": lambda: make_reactive(
                kernel       = kernel,
                llm          = self._llm,
                memory       = self._memory,
                transformers = transformers,
                formatters   = self._formatters,
                max_cells    = self._max_cells,
            ),
            "reflect":  lambda: make_reflect(
                kernel    = kernel,
                llm       = self._llm,
                memory    = self._memory,
                max_cells = self._max_cells,
            ),
            "plan":     lambda: make_plan_execute(
                kernel    = kernel,
                llm       = self._llm,
                memory    = self._memory,
                max_cells = self._max_cells,
            ),
        }

        builder = strategy_builders.get(self._loop_strategy)
        if not builder:
            raise ValueError(
                "Unknown loop strategy: {}. "
                "Available: {}".format(self._loop_strategy, list(strategy_builders))
            )

        loop = builder()

        # Wrap in memory injection if needed
        if self._memory:
            from kerno.steps.memory import InjectMemoryStep, StoreMemoryStep
            from kerno.pipeline import Pipeline as P
            return P([
                InjectMemoryStep(self._memory),
                loop,
                StoreMemoryStep(self._memory),
            ])

        return Pipeline([loop])

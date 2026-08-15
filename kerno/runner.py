"""
Config-aware runner: the bridge between KernoConfig and kerno.run().

Separates concerns:
  - __init__.py: low-level, explicit parameters
  - runner.py:   high-level, config-driven
"""

from __future__ import annotations

from typing import Optional

from kerno.config        import KernoConfig
from kerno.memory.simple import SimpleMemoryStore
from kerno.security.allowlist import AllowList
from kerno.types         import LLMCallable, SessionResult


def run_with_config(
    task:   str,
    llm:    LLMCallable,
    config: Optional[KernoConfig] = None,
    *,
    loop:         str                  = "reactive",
    planner_llm:  LLMCallable | None   = None,
    skills_path:  str | None           = None,
    comm_handlers: dict | None         = None,
) -> SessionResult:
    """
    Run a task using a KernoConfig for all settings.

    This is the preferred entry point for production use.
    KernoConfig centralises all tuning in one place.

    Usage:
        config = KernoConfig.from_env()
        result = run_with_config("Analyze data.csv", llm=my_llm, config=config)
    """
    from kerno import run

    cfg = config or KernoConfig.default()

    # Build memory store from config
    memory = None
    if cfg.memory.enabled:
        memory = SimpleMemoryStore(persist_path=cfg.memory.persist_path)

    # Build allowlist from config
    allowlist = None
    if cfg.security.profile != "none":
        allowlist = {
            "permissive":    AllowList.permissive,
            "data_analysis": AllowList.data_analysis,
            "read_only":     AllowList.read_only,
        }.get(cfg.security.profile, AllowList.permissive)()

    return run(
        task                 = task,
        llm                  = llm,
        loop                 = loop,
        planner_llm          = planner_llm,
        kernel_name          = cfg.kernel.name,
        max_cells            = cfg.kernel.max_cells,
        skills_path          = skills_path,
        load_default_skills  = True,
        memory               = memory,
        allowlist            = allowlist,
        save_notebook        = cfg.output.save_notebook,
        notebook_dir         = cfg.output.notebook_dir,
        comm_handlers        = comm_handlers,
        verbose              = cfg.output.verbose,
    )

"""
Example 15: The secure runtime — choke point + authorization + budget.

Every cell passes through ExecutionEngine: capability authorization
(K-008), allowlist policy, audit records, and an event stream. A
capability broker scopes grants to the agent; the budget caps cells.

Runs WITHOUT an API key: ScriptedBrain is a deterministic LLM.
"""

from kerno import (
    AllowList, BudgetedExecutor, Capability, CapabilityBroker,
    CAP_KERNEL_EXECUTE, ExecutionBudget, ExecutionEngine, ScriptedBrain,
    run, SessionStatus,
)


def main() -> None:
    # ── The brain: deterministic, no API key needed ──────────────────────
    brain = ScriptedBrain(
        "x = 21\nprint('x =', x)",
        "y = x * 2\nprint('y =', y)",
        "# TASK_COMPLETE: computed",
    )

    # ── The authorization layer: grants scoped to the agent ──────────────
    broker = CapabilityBroker()
    broker.grant(Capability(CAP_KERNEL_EXECUTE), subject="agent-1")

    result = run(
        "Compute values",
        llm=brain,
        allowlist          = AllowList.data_analysis(),
        capability_broker  = broker,
        budget             = ExecutionBudget(max_executions=5),
        max_cells          = 10,
    )

    print("status:      ", result.status.name)
    print("cells:       ", result.cells_executed)
    print("brain calls: ", brain.call_count)

    # ── Direct engine access: records + event stream ─────────────────────
    from kerno.kernel.runtime import KernelRuntime
    engine = ExecutionEngine(
        KernelRuntime(),
        allowlist            = AllowList.data_analysis(),
        broker               = broker,
        default_capabilities = frozenset({CAP_KERNEL_EXECUTE}),
    )
    print("\nengine created — execute() is the single choke point (K-001)")

    # Violations never reach the kernel: they become error cells
    engine = BudgetedExecutor(engine, ExecutionBudget(max_executions=2))
    print("budgeted engine ready")

    assert result.status in (SessionStatus.COMPLETE, SessionStatus.MAX_CELLS)


if __name__ == "__main__":
    main()

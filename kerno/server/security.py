# kerno/server/security.py
"""
Server-side execution security (audit K-001 through the HTTP surface).

The public HTTP/OpenAI-compatible servers must NOT execute raw kernel
code: every request is wrapped in the ExecutionEngine choke point, so
the allowlist, capability broker, and budget apply to server-driven
sessions exactly as they do to local run() sessions.

    HTTP request
        │
        ▼
    make_server_engine(kernel, profile, broker, budget)
        │
        ▼
    ExecutionEngine (allowlist + broker) → BudgetedExecutor
        │
        ▼
    pipeline / loop
"""

from __future__ import annotations

from typing import Optional

from kerno.execution.budget    import BudgetedExecutor, ExecutionBudget
from kerno.execution.engine    import ExecutionEngine
from kerno.security.allowlist  import AllowList
from kerno.security.capabilities import CapabilityBroker

PROFILES = {
    "permissive":    AllowList.permissive,
    "data_analysis": AllowList.data_analysis,
    "read_only":     AllowList.read_only,
}


def make_server_engine(
    kernel:            object,
    profile:           str = "data_analysis",
    capability_broker: Optional[CapabilityBroker] = None,
    budget:            Optional[ExecutionBudget] = None,
) -> object:
    """
    Wrap a raw kernel in the full choke point (K-001).

    Args:
        kernel:            the acquired KernelRuntime (or any Executor)
        profile:           allowlist profile: "data_analysis" (default),
                           "read_only", "permissive", or "none" (explicit
                           trusted opt-out)
        capability_broker: CapabilityBroker for authorization (K-008)
        budget:            ExecutionBudget capping the session (audit #85)

    Returns an object satisfying the Executor protocol — pass it to any
    loop/pipeline factory as the `kernel` argument.
    """
    allowlist = None
    if profile != "none":
        if profile not in PROFILES:
            raise ValueError(
                f"Unknown security profile: {profile!r}. Available: {sorted(PROFILES.keys())}"
            )
        allowlist = PROFILES[profile]()

    engine = ExecutionEngine(
        kernel,
        allowlist            = allowlist,
        broker               = capability_broker,
        default_capabilities = (
            frozenset({"kernel.execute"})
            if capability_broker is not None else frozenset()
        ),
    )
    if budget is not None:
        engine = BudgetedExecutor(engine, budget)
    return engine

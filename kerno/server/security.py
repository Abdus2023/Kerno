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

PROFILE_RANK = {
    "none": 0,
    "permissive": 1,
    "data_analysis": 2,
    "read_only": 3,
}


def resolve_effective_profile(
    requested:       Optional[str],
    server_default:  str  = "data_analysis",
    allow_downgrade: bool = False,
) -> str:
    """
    Resolve effective security profile preventing client downgrades (K-012).

    If the requested profile is weaker than the server default, the server
    default is enforced. Requests may only select equal or stronger profiles
    (e.g., read_only when server default is data_analysis).
    """
    req = requested or server_default
    if req not in PROFILE_RANK:
        raise ValueError(
            f"Unknown security profile: {req!r}. Available: {sorted(PROFILES.keys())}"
        )
    if server_default not in PROFILE_RANK:
        server_default = "data_analysis"

    if not allow_downgrade and PROFILE_RANK[req] < PROFILE_RANK[server_default]:
        return server_default
    return req


def make_server_engine(
    kernel:            object,
    profile:           str = "data_analysis",
    capability_broker: Optional[CapabilityBroker] = None,
    budget:            Optional[ExecutionBudget] = None,
    server_default:    Optional[str] = None,
    allow_downgrade:   bool = False,
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
        server_default:    authoritative server default profile (K-012)
        allow_downgrade:   whether client may downgrade below server default

    Returns an object satisfying the Executor protocol — pass it to any
    loop/pipeline factory as the `kernel` argument.
    """
    if server_default is not None:
        effective = resolve_effective_profile(profile, server_default=server_default, allow_downgrade=allow_downgrade)
    else:
        effective = profile or "data_analysis"

    allowlist = None
    if effective != "none":
        if effective not in PROFILES:
            raise ValueError(
                f"Unknown security profile: {effective!r}. Available: {sorted(PROFILES.keys())}"
            )
        allowlist = PROFILES[effective]()

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

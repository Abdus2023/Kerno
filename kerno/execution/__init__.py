# kerno/execution/__init__.py
"""
Execution subsystem: the single choke point for code execution.

Everything that executes code — agents, loops, plugins, skills,
checkpoints — must pass through ExecutionEngine (invariant K-001).

Also provides execution modes (SIMULATE / DRY_RUN / LIVE / REPLAY),
replay without the LLM, and execution budgets.
"""

from kerno.execution.engine import (
    ExecutionEngine,
    ExecutionRecord,
    ExecutionEvent,
    ORIGIN_AGENT,
    ORIGIN_RUNTIME,
    EVT_EXECUTION_REQUESTED,
    EVT_CAPABILITY_DENIED,
    EVT_POLICY_BLOCKED,
    EVT_EXECUTION_STARTED,
    EVT_EXECUTION_COMPLETED,
)
from kerno.execution.modes import (
    ExecutionMode, DryRunExecutor, ReplayExecutor, replay_session,
)
from kerno.execution.budget import (
    ExecutionBudget, BudgetExceeded, BudgetTracker, BudgetSnapshot,
    BudgetedExecutor,
)

__all__ = [
    "ExecutionEngine",
    "ExecutionRecord",
    "ExecutionEvent",
    "ORIGIN_AGENT",
    "ORIGIN_RUNTIME",
    "EVT_EXECUTION_REQUESTED",
    "EVT_CAPABILITY_DENIED",
    "EVT_POLICY_BLOCKED",
    "EVT_EXECUTION_STARTED",
    "EVT_EXECUTION_COMPLETED",
    "ExecutionMode",
    "DryRunExecutor",
    "ReplayExecutor",
    "replay_session",
    "ExecutionBudget",
    "BudgetExceeded",
    "BudgetTracker",
    "BudgetSnapshot",
    "BudgetedExecutor",
]

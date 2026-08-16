# kerno/bridge.py
"""
SessionResult ↔ AgentState bridge — one vocabulary across both
execution models (audit #76: Execution is the core abstraction).

Kerno has two loop families:
  - BaseLoop loops (Reactive/Reflect/Plan/Hierarchical/MultiAgent/Debate)
    produce SessionResult.
  - The pipeline system (kerno.pipeline + kerno.steps) consumes and
    produces AgentState.

The bridge converts between them, so a recorded session can feed a
pipeline, and a pipeline outcome can be resumed/replayed as a session:

    SessionResult ──result_to_state()──▶ AgentState
    AgentState    ──state_to_result()──▶ SessionResult
"""

from __future__ import annotations

from typing import Optional

from kerno.interfaces import AgentState
from kerno.types import SessionResult, SessionStatus


def result_to_state(
    result: SessionResult,
    task:   Optional[str] = None,
    *,
    complete_override: Optional[bool] = None,
) -> AgentState:
    """
    Convert a SessionResult into an AgentState for pipeline continuation.

    The history, namespace, summary, and session identity are carried
    over; `complete`/`error` map from the session status so a pipeline
    sees the same terminal outcome.
    """
    complete = (
        complete_override
        if complete_override is not None
        else result.status == SessionStatus.COMPLETE
    )
    return AgentState(
        task          = task or result.task,
        history       = list(result.cells),
        namespace     = result.final_namespace,
        summary       = result.summary,
        session_id    = result.session_id,
        complete      = complete,
        error         = None if complete else result.status.name,
        metadata      = {
            "execution_ids": list(getattr(result, "execution_ids", [])),
            "blocked_rules": list(getattr(result, "blocked_rules", [])),
            "started_at":    result.started_at,
            "ended_at":      result.ended_at,
            "source":        "SessionResult",
        },
        execution_counter = len(getattr(result, "execution_ids", [])),
    )


def state_to_result(
    state: AgentState,
    *,
    status_override: Optional[SessionStatus] = None,
) -> SessionResult:
    """
    Convert an AgentState back into a SessionResult.

    A complete state maps to COMPLETE; an errored state to
    ERROR_UNHANDLED; otherwise MAX_CELLS (the pipeline ran to its limit).
    """
    if status_override is not None:
        status = status_override
    elif state.complete:
        status = SessionStatus.COMPLETE
    elif state.error:
        status = SessionStatus.ERROR_UNHANDLED
    else:
        status = SessionStatus.MAX_CELLS

    return SessionResult(
        session_id      = state.session_id or "pipeline",
        task            = state.task,
        status          = status,
        cells           = list(state.history),
        final_namespace = state.namespace,
        summary         = state.summary,
        execution_ids   = list(state.metadata.get("execution_ids", [])),
        blocked_rules   = list(state.metadata.get("blocked_rules", [])),
    )


def state_history_len(state: AgentState) -> int:
    """Convenience: number of executed cells recorded in the state."""
    return len(state.history)

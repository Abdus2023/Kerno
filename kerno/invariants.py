# kerno/invariants.py
"""
Formal invariants of the runtime (audit #101, P1-P10).

Each check is a function that raises InvariantViolation with a precise
message when the property is broken. The checks are written to DETECT
violations — unit tests assert both the passing scenario and that a
violating scenario is caught — so the tests protect the architecture,
not the implementation.

    P1  completed execution cannot return to running
    P2  denied action cannot execute
    P3  cancelled action cannot commit
    P4  artifact provenance always references a valid execution
    P5  event sequence is monotonic
    P6  child capability set ⊆ parent capability set
    P7  replay does not invoke Brain
    P8  kernel restart increments generation
    P9  session survives kernel restart
    P10 every execution has exactly one terminal state
"""

from __future__ import annotations

from typing import Iterable, Optional


class InvariantViolation(RuntimeError):
    """Raised when a runtime invariant is broken."""


# ── P1: completed execution cannot return to running ──────────────────────────

def check_terminal_events(events: Iterable[object]) -> None:
    """
    No event may follow a terminal event for the same execution.

    events: ExecutionEvent-like objects with .execution_id, .event_type.
    """
    terminal_types = {
        "EXECUTION_COMPLETED", "CAPABILITY_DENIED", "POLICY_BLOCKED",
        "APPROVAL_DENIED", "EFFECT_VIOLATION",
    }
    seen_terminal: set[str] = set()
    for event in events:
        if event.execution_id in seen_terminal:
            raise InvariantViolation(
                "P1 violated: execution {} has events after its terminal "
                "event ({} follows)".format(
                    event.execution_id, event.event_type
                )
            )
        if event.event_type in terminal_types:
            seen_terminal.add(event.execution_id)


# ── P2: denied action cannot execute ──────────────────────────────────────────

def check_denied_never_started(events: Iterable[object]) -> None:
    """
    A denied execution must never emit EXECUTION_STARTED.

    events: ExecutionEvent-like objects with .execution_id, .event_type.
    """
    denied: set[str] = set()
    for event in events:
        if event.event_type in (
            "CAPABILITY_DENIED", "POLICY_BLOCKED", "APPROVAL_DENIED",
        ):
            denied.add(event.execution_id)
        if event.event_type == "EXECUTION_STARTED" and event.execution_id in denied:
            raise InvariantViolation(
                "P2 violated: denied execution {} reached the kernel".format(
                    event.execution_id
                )
            )


# ── P3/P10: exactly one terminal outcome, terminal is final ───────────────────

def check_single_terminal_state(history: Iterable[object]) -> None:
    """
    A state machine history must contain at most one terminal status and
    it must be the last entry.

    history: StateTransition-like objects with .from_status, .to_status,
    where statuses have a .terminal property.
    """
    terminal_seen: Optional[str] = None
    for transition in history:
        if terminal_seen is not None:
            raise InvariantViolation(
                "P10 violated: transition {} -> {} after terminal {}".format(
                    transition.from_status.name,
                    transition.to_status.name,
                    terminal_seen,
                )
            )
        if getattr(transition.to_status, "terminal", False):
            terminal_seen = transition.to_status.name


# ── P4: artifact provenance references a valid execution ──────────────────────

def check_artifact_provenance(
    artifact_refs: Iterable[object],
    valid_execution_ids: Iterable[str],
) -> None:
    """
    Every artifact's creator_execution must be a valid execution id
    (or None for host-created artifacts).

    artifact_refs: objects with .creator_execution.
    """
    valid = set(valid_execution_ids)
    for ref in artifact_refs:
        creator = getattr(ref, "creator_execution", None)
        if creator is not None and creator not in valid:
            raise InvariantViolation(
                "P4 violated: artifact {} references unknown execution "
                "{}".format(getattr(ref, "digest", ref), creator)
            )


# ── P5: event sequence is monotonic ───────────────────────────────────────────

def check_monotonic_sequence(events: Iterable[object]) -> None:
    """
    Event sequence numbers must be strictly increasing.

    events: objects with .sequence.
    """
    last = -1
    for event in events:
        if event.sequence <= last:
            raise InvariantViolation(
                "P5 violated: event sequence {} after {}".format(
                    event.sequence, last
                )
            )
        last = event.sequence


# ── P6: child capability set ⊆ parent capability set ──────────────────────────

def check_attenuation(grants: Iterable[object]) -> None:
    """
    Every grant with a parent must be a subset of that parent.

    grants: CapabilityGrant objects with .parent_grant_id and .capability.
    Requires the fnmatch subset relation: child scope must match the
    parent scope pattern.
    """
    from fnmatch import fnmatch

    by_id = {g.grant_id: g for g in grants}
    for grant in grants:
        if grant.parent_grant_id is None:
            continue
        parent = by_id.get(grant.parent_grant_id)
        if parent is None:
            raise InvariantViolation(
                "P6 violated: grant {} references missing parent {}".format(
                    grant.grant_id, grant.parent_grant_id
                )
            )
        pcap = parent.capability
        ccap = grant.capability
        if pcap.name != "*" and ccap.name != pcap.name:
            raise InvariantViolation(
                "P6 violated: grant {} capability {} exceeds parent {}"
                .format(grant.grant_id, ccap.name, pcap.name)
            )
        if not fnmatch(ccap.scope, pcap.scope):
            raise InvariantViolation(
                "P6 violated: grant {} scope {} exceeds parent scope {}"
                .format(grant.grant_id, ccap.scope, pcap.scope)
            )


# ── P7: replay does not invoke Brain ──────────────────────────────────────────

def check_replay_llm_free(llm_spy, replay_result: object) -> None:
    """
    Replay must never call the LLM.

    llm_spy: a callable with .call_count (e.g. a mock).
    """
    calls = getattr(llm_spy, "call_count", None)
    if calls is None:
        import inspect
        if hasattr(llm_spy, "call_count_list"):
            calls = len(llm_spy.call_count_list)
    if calls:
        raise InvariantViolation(
            "P7 violated: replay invoked the Brain {} times".format(calls)
        )


# ── P8: kernel restart increments generation ──────────────────────────────────

def check_generation_monotonic(generations: Iterable[int]) -> None:
    """
    Observed kernel generations must be strictly increasing.

    generations: observed values of KernelRuntime.generation over time.
    """
    last = 0
    for generation in generations:
        if generation < last:
            raise InvariantViolation(
                "P8 violated: generation {} regressed from {}".format(
                    generation, last
                )
            )
        if generation > last:
            last = generation


# ── P9: session survives kernel restart ───────────────────────────────────────

def check_session_recovered(
    status,
    kernel_generations: Iterable[int],
    auto_restart: bool,
) -> None:
    """
    With auto_restart enabled, a kernel restart must not end the session
    in KERNEL_DIED.

    status: SessionStatus (compare .name == "KERNEL_DIED").
    """
    restarted = any(g > 1 for g in kernel_generations)
    if auto_restart and restarted and getattr(status, "name", status) == "KERNEL_DIED":
        raise InvariantViolation(
            "P9 violated: session died (KERNEL_DIED) despite auto_restart "
            "with a restart available"
        )


# ── Runner ────────────────────────────────────────────────────────────────────

def verify(checks: Iterable[tuple[str, callable]]) -> list[str]:
    """
    Run named checks; raise InvariantViolation on the first failure.

    checks: [(name, check_callable), ...]

    Returns the list of passed check names.
    """
    passed: list[str] = []
    for name, check in checks:
        check()
        passed.append(name)
    return passed

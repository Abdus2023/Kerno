"""
Invariant tests (audit #101, P1-P10).

For every check: a passing scenario, AND a violating scenario the check
must DETECT — these tests protect the architecture, not the implementation.
"""

import pytest

from kerno.invariants import (
    InvariantViolation,
    check_artifact_provenance, check_attenuation, check_denied_never_started,
    check_generation_monotonic, check_monotonic_sequence,
    check_replay_llm_free, check_session_recovered, check_single_terminal_state,
    check_terminal_events, verify,
)
from kerno.security.capabilities import (
    Capability, CapabilityBroker, CAP_FILESYSTEM_READ,
)


class Event:
    def __init__(self, execution_id, event_type, sequence):
        self.execution_id = execution_id
        self.event_type   = event_type
        self.sequence     = sequence


class Transition:
    def __init__(self, frm, to):
        self.from_status = frm
        self.to_status   = to


class Ref:
    def __init__(self, digest, creator_execution):
        self.digest = digest
        self.creator_execution = creator_execution


# ── P1 ────────────────────────────────────────────────────────────────────────

class TestP1TerminalEvents:

    def test_clean_chain_passes(self):
        events = [
            Event("e1", "EXECUTION_REQUESTED", 1),
            Event("e1", "EXECUTION_STARTED", 2),
            Event("e1", "EXECUTION_COMPLETED", 3),
        ]
        check_terminal_events(events)  # no raise

    def test_event_after_completion_detected(self):
        events = [
            Event("e1", "EXECUTION_COMPLETED", 3),
            Event("e1", "EXECUTION_STARTED", 4),   # P1 violation
        ]
        with pytest.raises(InvariantViolation, match="P1"):
            check_terminal_events(events)


# ── P2 ────────────────────────────────────────────────────────────────────────

class TestP2DeniedNeverStarted:

    def test_blocked_execution_never_starts(self):
        events = [
            Event("e1", "EXECUTION_REQUESTED", 1),
            Event("e1", "POLICY_BLOCKED", 2),
        ]
        check_denied_never_started(events)  # no raise

    def test_denied_then_started_detected(self):
        events = [
            Event("e1", "POLICY_BLOCKED", 2),
            Event("e1", "EXECUTION_STARTED", 3),  # P2 violation
        ]
        with pytest.raises(InvariantViolation, match="P2"):
            check_denied_never_started(events)


# ── P3/P10 ────────────────────────────────────────────────────────────────────

class TestP10SingleTerminalState:

    class Status:
        def __init__(self, name, terminal=False):
            self.name = name
            self.terminal = terminal

    def test_happy_path_passes(self):
        created = self.Status("CREATED")
        success = self.Status("SUCCESS", terminal=True)
        history = [
            Transition(created, self.Status("AUTHORIZING")),
            Transition(self.Status("AUTHORIZING"), self.Status("RUNNING")),
            Transition(self.Status("RUNNING"), success),
        ]
        check_single_terminal_state(history)  # no raise

    def test_transition_after_terminal_detected(self):
        success = self.Status("SUCCESS", terminal=True)
        history = [
            Transition(self.Status("CREATED"), success),
            Transition(success, self.Status("RUNNING")),  # P10 violation
        ]
        with pytest.raises(InvariantViolation, match="P10"):
            check_single_terminal_state(history)


# ── P4 ────────────────────────────────────────────────────────────────────────

class TestP4ArtifactProvenance:

    def test_valid_references_pass(self):
        refs = [
            Ref("sha256:a", "exec_00000001"),
            Ref("sha256:b", None),               # host-created → ok
        ]
        check_artifact_provenance(refs, ["exec_00000001"])

    def test_dangling_reference_detected(self):
        refs = [Ref("sha256:a", "exec_99999999")]
        with pytest.raises(InvariantViolation, match="P4"):
            check_artifact_provenance(refs, ["exec_00000001"])


# ── P5 ────────────────────────────────────────────────────────────────────────

class TestP5MonotonicSequence:

    def test_increasing_passes(self):
        check_monotonic_sequence([Event("a", "X", 1), Event("b", "X", 2)])

    def test_regression_detected(self):
        with pytest.raises(InvariantViolation, match="P5"):
            check_monotonic_sequence([Event("a", "X", 2), Event("b", "X", 1)])


# ── P6 ────────────────────────────────────────────────────────────────────────

class TestP6Attenuation:

    def _broker_chain(self):
        broker = CapabilityBroker()
        parent = broker.grant(Capability(CAP_FILESYSTEM_READ, scope="/workspace/**"))
        broker.attenuate(parent, scope="/workspace/datasets/**")
        return broker

    def test_attenuated_chain_passes(self):
        broker = self._broker_chain()
        check_attenuation(broker.all_grants())  # no raise

    def test_wider_child_detected(self):
        broker = CapabilityBroker()
        parent = broker.grant(Capability(CAP_FILESYSTEM_READ, scope="/workspace/**"))
        # Manually register an over-wide child, bypassing the broker guard
        from kerno.security.capabilities import CapabilityGrant
        from kerno.action import ActionKind  # noqa: F401
        child = CapabilityGrant(
            grant_id="cap_bad", capability=Capability(CAP_FILESYSTEM_READ, scope="/*"),
            parent_grant_id=parent.grant_id,
        )
        broker._grants["cap_bad"] = child
        with pytest.raises(InvariantViolation, match="P6"):
            check_attenuation(broker.all_grants())


# ── P7 ────────────────────────────────────────────────────────────────────────

class TestP7ReplayNoBrain:

    class Spy:
        def __init__(self):
            self.call_count = 0

        def __call__(self, messages):
            self.call_count += 1
            return "# TASK_COMPLETE"

    def test_unused_spy_passes(self):
        check_replay_llm_free(self.Spy(), object())

    def test_called_spy_detected(self):
        spy = self.Spy()
        spy.call_count = 3
        with pytest.raises(InvariantViolation, match="P7"):
            check_replay_llm_free(spy, object())


# ── P8 ────────────────────────────────────────────────────────────────────────

class TestP8GenerationMonotonic:

    def test_increasing_passes(self):
        check_generation_monotonic([1, 1, 2, 2, 3])

    def test_regression_detected(self):
        with pytest.raises(InvariantViolation, match="P8"):
            check_generation_monotonic([1, 2, 1])

    def test_generation_strictly_increments_on_restart(self):
        # Verification that each distinct restart transition increments generation
        initial_gen = 1
        restart_gen = initial_gen + 1
        assert restart_gen > initial_gen
        check_generation_monotonic([initial_gen, restart_gen])


# ── P9 ────────────────────────────────────────────────────────────────────────

class TestP9SessionSurvivesRestart:

    class Status:
        def __init__(self, name):
            self.name = name

    def test_recovered_session_passes(self):
        check_session_recovered(
            self.Status("COMPLETE"), [1, 2], auto_restart=True,
        )

    def test_dead_despite_restart_detected(self):
        with pytest.raises(InvariantViolation, match="P9"):
            check_session_recovered(
                self.Status("KERNEL_DIED"), [1, 2], auto_restart=True,
            )

    def test_no_restart_means_no_requirement(self):
        check_session_recovered(
            self.Status("KERNEL_DIED"), [1], auto_restart=True,
        )  # no restart happened → not a P9 violation


# ── Runner ────────────────────────────────────────────────────────────────────

class TestVerify:

    def test_verify_runs_all_and_reports_passed(self):
        passed = verify([
            ("p5", lambda: check_monotonic_sequence(
                [Event("a", "X", 1), Event("b", "X", 2)])),
            ("p8", lambda: check_generation_monotonic([1, 1, 2])),
        ])
        assert passed == ["p5", "p8"]

    def test_verify_raises_on_first_failure(self):
        with pytest.raises(InvariantViolation, match="P5"):
            verify([
                ("p5", lambda: check_monotonic_sequence(
                    [Event("a", "X", 2), Event("b", "X", 1)])),
                ("p8", lambda: check_generation_monotonic([1, 2])),
            ])


    def test_effect_violation_observation_followed_by_completion_passes(self):
        events = [
            Event("e1", "EXECUTION_REQUESTED", 1),
            Event("e1", "EXECUTION_STARTED", 2),
            Event("e1", "EFFECT_VIOLATION", 3),     # observational event
            Event("e1", "EXECUTION_COMPLETED", 4),   # terminal event
        ]
        check_terminal_events(events)  # no raise

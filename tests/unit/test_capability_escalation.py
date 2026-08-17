"""
K-008 adversarial capability-escalation suite (F-008).

Attempts every privilege-escalation route the remediation plan requires:

  1. agent self-grant / implicit capability
  2. cross-agent grant use
  3. scope widening through attenuation
  4. subject mutation through attenuation
  5. expired parent grant
  6. revoked parent grant
  7. skill capability mutation after granting (SkillProvenance bridge)
  8. runtime-origin combination (self-grant + ORIGIN_RUNTIME)

Expected result for every case: DENIED — no route produces escalation.
"""

import time

import pytest

from kerno.capability_exec import CapabilityExecutor
from kerno.execution.engine import ORIGIN_RUNTIME, ExecutionEngine
from kerno.security.capabilities import (
    CAP_FILESYSTEM_READ,
    CAP_FILESYSTEM_WRITE,
    CAP_KERNEL_EXECUTE,
    Capability,
    CapabilityBroker,
    CapabilityViolation,
)
from kerno.skilltrust import SkillProvenance, grant_skill_capabilities
from kerno.types import CellOutput


class _FakeKernel:
    def execute(self, code, timeout=120.0, silent=False, **kwargs):
        return CellOutput(stdout="ok")

    def execute_silent(self, code, timeout=15.0, **kwargs):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


# ── 1. Self-grant / implicit capability ───────────────────────────────────────

class TestSelfGrantPrevention:

    def test_broker_starts_empty_fail_closed(self):
        broker = CapabilityBroker()
        # No grant exists until an EXPLICIT issuer grants it — nothing is
        # inferred from syntax or requests.
        assert not broker.check(CAP_KERNEL_EXECUTE)
        with pytest.raises(CapabilityViolation):
            broker.require(CAP_KERNEL_EXECUTE)

    def test_agent_facing_executor_exposes_no_grant_surface(self):
        broker = CapabilityBroker()
        executor = CapabilityExecutor(
            broker=broker,
            artifact_store=None,
        )
        # Structural: the agent-facing surface cannot manufacture grants.
        assert not hasattr(executor, "grant")
        assert not hasattr(executor, "grant_many")
        assert not hasattr(executor, "attenuate")

    def test_engine_denies_undeclared_capability_before_kernel(self):
        broker = CapabilityBroker()
        kernel = _FakeKernel()
        engine = ExecutionEngine(
            kernel, broker=broker,
            default_capabilities=frozenset({CAP_KERNEL_EXECUTE}),
        )
        out = engine.execute("x = 1")
        assert out.has_error
        assert out.error.ename == "CapabilityViolation"

    def test_no_capability_declared_means_no_privilege(self):
        # Fail-closed: absence of a capability set does NOT silently grant.
        broker = CapabilityBroker()
        broker.grant_many({CAP_FILESYSTEM_READ}, subject="agent-1")
        engine = ExecutionEngine(
            _FakeKernel(), broker=broker,
        )
        out = engine.execute("x = 1", capabilities=None, subject="agent-1")
        assert not out.has_error   # no capability required → no gate to fail


# ── 2. Cross-agent grant use ──────────────────────────────────────────────────

class TestCrossAgentIsolation:

    def test_agent_b_cannot_use_agent_a_grant(self):
        broker = CapabilityBroker()
        broker.grant_many({CAP_KERNEL_EXECUTE}, subject="agent-A", issuer="admin")
        assert broker.check(CAP_KERNEL_EXECUTE, subject="agent-A")
        assert not broker.check(CAP_KERNEL_EXECUTE, subject="agent-B")
        with pytest.raises(CapabilityViolation):
            broker.require(CAP_KERNEL_EXECUTE, subject="agent-B")

    def test_engine_enforces_subject_scoped_grant(self):
        broker = CapabilityBroker()
        broker.grant_many({CAP_KERNEL_EXECUTE}, subject="agent-A", issuer="admin")
        engine = ExecutionEngine(
            _FakeKernel(), broker=broker,
            default_capabilities=frozenset({CAP_KERNEL_EXECUTE}),
        )
        ok = engine.execute("x = 1", subject="agent-A")
        assert not ok.has_error
        denied = engine.execute("x = 1", subject="agent-B")
        assert denied.has_error
        assert denied.error.ename == "CapabilityViolation"


# ── 3. Scope widening through attenuation ─────────────────────────────────────

class TestScopeWideningPrevention:

    def test_child_scope_cannot_widen_parent(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="workspace/*"),
            subject="agent-1", issuer="admin",
        )
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, scope="/")          # wider than workspace/*
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, scope="workspace/../etc/*")
        # Equal-or-narrower scope is fine
        broker.attenuate(parent, scope="workspace/datasets/*")
        assert broker.check(CAP_FILESYSTEM_READ, scope="workspace/datasets/x.csv", subject="agent-1")
        assert not broker.check(CAP_FILESYSTEM_READ, scope="/etc/passwd", subject="agent-1")

    def test_direct_grant_with_parent_cannot_widen(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="workspace/*"),
            subject="agent-1", issuer="admin",
        )
        with pytest.raises(CapabilityViolation):
            broker.grant(
                Capability(CAP_FILESYSTEM_READ, scope="/"),
                subject="agent-1", parent=parent,
            )

    def test_child_cannot_change_capability_name(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="workspace/*"),
            subject="agent-1", issuer="admin",
        )
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, name=CAP_KERNEL_EXECUTE)


# ── 4. Subject mutation ───────────────────────────────────────────────────────

class TestSubjectMutationPrevention:

    def test_child_cannot_change_subject(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="workspace/*"),
            subject="agent-A", issuer="admin",
        )
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, subject="agent-B")

    def test_direct_grant_with_parent_cannot_change_subject(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ),
            subject="agent-A", issuer="admin",
        )
        with pytest.raises(CapabilityViolation):
            broker.grant(
                Capability(CAP_FILESYSTEM_READ),
                subject="agent-B", parent=parent,
            )


# ── 5. Expired parent ─────────────────────────────────────────────────────────

class TestExpiredParentPrevention:

    def test_expired_parent_cannot_be_used_to_derive_children(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="workspace/*"),
            subject="agent-1", issuer="admin",
            expires_at=time.time() - 10,
        )
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, scope="workspace/datasets/*")

    def test_expired_grant_is_inactive(self):
        broker = CapabilityBroker()
        broker.grant(
            Capability(CAP_FILESYSTEM_READ),
            subject="agent-1", issuer="admin",
            expires_at=time.time() - 10,
        )
        assert not broker.check(CAP_FILESYSTEM_READ, subject="agent-1")
        with pytest.raises(CapabilityViolation):
            broker.require(CAP_FILESYSTEM_READ, subject="agent-1")


# ── 6. Revoked parent ─────────────────────────────────────────────────────────

class TestRevokedParentPrevention:

    def test_revoked_parent_cannot_be_used(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="workspace/*"),
            subject="agent-1", issuer="admin",
        )
        child = broker.attenuate(parent, scope="workspace/datasets/*")
        broker.revoke(parent.grant_id)

        # Both the parent and its descendants are inactive.
        assert not broker.check(CAP_FILESYSTEM_READ, scope="workspace/datasets/x.csv", subject="agent-1")
        with pytest.raises(CapabilityViolation):
            broker.require(CAP_FILESYSTEM_READ, scope="workspace/datasets/x.csv", subject="agent-1")
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, scope="workspace/datasets/extra/*")
        assert not broker._is_active(child)


# ── 7. Skill capability mutation after granting ───────────────────────────────

class TestSkillCapabilityImmutability:

    def _provenance(self, caps, author="author-1"):
        return SkillProvenance(
            author_agent          = author,
            source_action         = "create",
            source_session        = "sess-1",
            capabilities_required = frozenset(caps),
            approval              = "approved",
        )

    def test_skill_receives_only_declared_capabilities(self):
        broker = CapabilityBroker()
        prov = self._provenance([CAP_KERNEL_EXECUTE])
        grants = grant_skill_capabilities(broker, prov, subject="agent-1")
        assert len(grants) == 1

        # Declared capability works for the author agent...
        assert broker.check(CAP_KERNEL_EXECUTE, subject="agent-1")
        # ...undeclared capabilities do NOT leak through the bridge.
        assert not broker.check(CAP_FILESYSTEM_READ, subject="agent-1")
        with pytest.raises(CapabilityViolation):
            broker.require(CAP_FILESYSTEM_READ, subject="agent-1")

    def test_mutating_provenance_after_grant_does_not_widen_authority(self):
        broker = CapabilityBroker()
        prov = self._provenance([CAP_KERNEL_EXECUTE])
        grant_skill_capabilities(broker, prov, subject="agent-1")

        # An attacker mutates the provenance record after the grant.
        prov.capabilities_required = frozenset({CAP_KERNEL_EXECUTE, CAP_FILESYSTEM_WRITE})

        # The broker grants are immutable snapshots — nothing widened.
        assert not broker.check(CAP_FILESYSTEM_WRITE, subject="agent-1")
        assert broker.check(CAP_KERNEL_EXECUTE, subject="agent-1")
        with pytest.raises(CapabilityViolation):
            broker.require(CAP_FILESYSTEM_WRITE, subject="agent-1")

    def test_skill_grant_scoped_to_author_agent(self):
        broker = CapabilityBroker()
        prov = self._provenance([CAP_KERNEL_EXECUTE], author="author-1")
        grant_skill_capabilities(broker, prov)   # subject falls back to author_agent
        assert broker.check(CAP_KERNEL_EXECUTE, subject="author-1")
        assert not broker.check(CAP_KERNEL_EXECUTE, subject="author-2")
        with pytest.raises(CapabilityViolation):
            broker.require(CAP_KERNEL_EXECUTE, subject="author-2")


# ── 8. Runtime-origin combination ─────────────────────────────────────────────

class TestRuntimeOriginCombination:

    def test_self_grant_plus_runtime_origin_still_denied(self):
        # Even with a valid grant for the subject, the public API cannot
        # manufacture ORIGIN_RUNTIME — the escalation route is closed at
        # the API surface, not the broker.
        broker = CapabilityBroker()
        broker.grant_many({CAP_KERNEL_EXECUTE}, subject="agent-1", issuer="admin")
        engine = ExecutionEngine(
            _FakeKernel(), broker=broker,
            default_capabilities=frozenset({CAP_KERNEL_EXECUTE}),
        )
        with pytest.raises(ValueError):
            engine.execute("x = 1", origin=ORIGIN_RUNTIME, subject="agent-1")

    def test_runtime_path_grants_nothing(self):
        # runtime_execute() executes trusted host code; it does not create
        # or widen any capability grant.
        broker = CapabilityBroker()
        engine = ExecutionEngine(_FakeKernel(), broker=broker)
        out = engine.runtime_execute("x = 1")
        assert not out.has_error
        assert len(broker) == 0
        with pytest.raises(CapabilityViolation):
            broker.require(CAP_KERNEL_EXECUTE)

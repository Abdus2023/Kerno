"""
Unit tests for the CapabilityBroker — capability-oriented authorization
(audit #21, #31, #87, #88; invariants K-008, P6).
"""

import time

import pytest

from kerno.security.capabilities import (
    Capability, CapabilityBroker, CapabilityViolation,
    CAP_FILESYSTEM_READ, CAP_KERNEL_EXECUTE, CAP_NETWORK_CONNECT,
    WILDCARD,
    PROFILE_READ_ONLY, PROFILE_DATA_ANALYSIS, PROFILE_RESEARCH,
    PROFILE_TRUSTED, grant_profile,
)


class TestGrantAndCheck:

    def test_grant_then_check_ok(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        assert broker.check(CAP_KERNEL_EXECUTE) is True

    def test_missing_capability_denied(self):
        broker = CapabilityBroker()
        assert broker.check(CAP_KERNEL_EXECUTE) is False

    def test_require_raises_with_name(self):
        broker = CapabilityBroker()
        with pytest.raises(CapabilityViolation) as exc:
            broker.require(CAP_KERNEL_EXECUTE)
        assert exc.value.name == CAP_KERNEL_EXECUTE
        assert "no active grant" in exc.value.reason

    def test_different_name_denied(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        assert broker.check(CAP_FILESYSTEM_READ) is False

    def test_wildcard_grant_covers_everything(self):
        broker = CapabilityBroker()
        broker.grant(Capability(WILDCARD))
        assert broker.check(CAP_FILESYSTEM_READ) is True
        assert broker.check(CAP_NETWORK_CONNECT) is True


class TestScopes:

    def test_scope_matches_subpath(self):
        broker = CapabilityBroker()
        broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="/workspace/datasets/**")
        )
        assert broker.check(
            CAP_FILESYSTEM_READ, scope="/workspace/datasets/x.csv"
        ) is True
        assert broker.check(
            CAP_FILESYSTEM_READ, scope="/workspace/datasets/sub/y.csv"
        ) is True

    def test_scope_denies_outside(self):
        broker = CapabilityBroker()
        broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="/workspace/datasets/**")
        )
        assert broker.check(
            CAP_FILESYSTEM_READ, scope="/etc/passwd"
        ) is False

    def test_unscoped_grant_covers_any_scope(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_FILESYSTEM_READ))
        assert broker.check(
            CAP_FILESYSTEM_READ, scope="/anything/at/all"
        ) is True


class TestSubjects:

    def test_grant_to_subject_denies_others(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE), subject="alice")
        assert broker.check(CAP_KERNEL_EXECUTE, subject="alice") is True
        assert broker.check(CAP_KERNEL_EXECUTE, subject="bob") is False

    def test_anonymous_grant_serves_any_subject(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        assert broker.check(CAP_KERNEL_EXECUTE, subject="bob") is True


class TestExpiryAndRevocation:

    def test_expired_grant_denied(self):
        broker = CapabilityBroker()
        broker.grant(
            Capability(CAP_KERNEL_EXECUTE),
            expires_at=time.time() - 10,
        )
        assert broker.check(CAP_KERNEL_EXECUTE) is False

    def test_future_expiry_allowed(self):
        broker = CapabilityBroker()
        broker.grant(
            Capability(CAP_KERNEL_EXECUTE),
            expires_at=time.time() + 3600,
        )
        assert broker.check(CAP_KERNEL_EXECUTE) is True

    def test_revoke_denies(self):
        broker = CapabilityBroker()
        grant = broker.grant(Capability(CAP_KERNEL_EXECUTE))
        assert broker.check(CAP_KERNEL_EXECUTE) is True
        broker.revoke(grant.grant_id)
        assert broker.check(CAP_KERNEL_EXECUTE) is False

    def test_revoke_cascades_to_children(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="/workspace/**")
        )
        child = broker.attenuate(
            parent, scope="/workspace/datasets/**"
        )
        broker.revoke(parent.grant_id)
        assert broker.check(CAP_FILESYSTEM_READ, scope="/workspace/datasets/x.csv") is False
        assert child.grant_id in broker._revoked


class TestAttenuation:
    """Invariant P6: child capability set ⊆ parent capability set."""

    def test_attenuate_narrower_scope_ok(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="/workspace/**"),
            subject="agent-1",
        )
        child = broker.attenuate(parent, scope="/workspace/datasets/**")
        assert child.parent_grant_id == parent.grant_id
        assert broker.check(
            CAP_FILESYSTEM_READ, scope="/workspace/datasets/x.csv",
            subject="agent-1",
        ) is True

    def test_attenuate_wider_scope_denied(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="/workspace/datasets/**")
        )
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, scope="/etc/**")

    def test_attenuate_different_capability_denied(self):
        broker = CapabilityBroker()
        parent = broker.grant(Capability(CAP_KERNEL_EXECUTE))
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, name=CAP_FILESYSTEM_READ)

    def test_attenuate_wider_subject_denied(self):
        broker = CapabilityBroker()
        parent = broker.grant(
            Capability(CAP_KERNEL_EXECUTE), subject="alice"
        )
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, subject="bob")

    def test_attenuate_keeps_parent_alive_requirement(self):
        broker = CapabilityBroker()
        parent = broker.grant(Capability(CAP_KERNEL_EXECUTE))
        broker.revoke(parent.grant_id)
        with pytest.raises(CapabilityViolation, match="parent grant"):
            broker.attenuate(parent)

    def test_constraint_attenuation(self):
        broker = CapabilityBroker()
        parent = broker.grant(Capability(
            CAP_FILESYSTEM_READ, constraints={"path_prefix": "/workspace"}
        ))
        # same constraint → ok
        child = broker.attenuate(parent, constraints={"path_prefix": "/workspace"})
        assert child is not None
        # adding a new constraint → not a subset → denied
        with pytest.raises(CapabilityViolation):
            broker.attenuate(parent, constraints={
                "path_prefix": "/workspace", "extra": "x"
            })

    def test_constraint_check_requires_request_values(self):
        broker = CapabilityBroker()
        broker.grant(Capability(
            CAP_FILESYSTEM_READ, constraints={"path_prefix": "/workspace"}
        ))
        assert broker.check(
            CAP_FILESYSTEM_READ, constraints={"path_prefix": "/workspace"}
        ) is True
        assert broker.check(
            CAP_FILESYSTEM_READ, constraints={"path_prefix": "/etc"}
        ) is False


class TestProfiles:

    def test_profile_grants_work(self):
        broker = CapabilityBroker()
        grants = grant_profile(broker, PROFILE_DATA_ANALYSIS, subject="agent-1")
        assert len(grants) == len(PROFILE_DATA_ANALYSIS)
        assert broker.check(CAP_KERNEL_EXECUTE, subject="agent-1") is True
        assert broker.check(CAP_FILESYSTEM_READ, subject="agent-1") is True
        assert broker.check(CAP_NETWORK_CONNECT, subject="agent-1") is False

    def test_profile_relationships(self):
        # research ⊇ read_only; data_analysis ⊇ read_only; trusted ⊇ all
        assert PROFILE_READ_ONLY <= PROFILE_DATA_ANALYSIS
        assert PROFILE_READ_ONLY <= PROFILE_RESEARCH
        assert WILDCARD in PROFILE_TRUSTED

    def test_active_grants_filter_by_subject(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE), subject="alice")
        broker.grant(Capability(CAP_KERNEL_EXECUTE), subject="bob")
        assert len(broker.active_grants(subject="alice")) == 1
        assert len(broker.active_grants(subject="carol")) == 0

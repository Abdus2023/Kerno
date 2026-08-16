"""
Unit tests for skill trust levels and approval (audit #64/#65).
"""

import pytest

from kerno.skilltrust import (
    SkillApprovalError, SkillApprover, SkillPolicy, SkillProvenance,
    SkillReview, TrustLevel, can_load, provenance,
)
from kerno.evolution import SkillProposal


def make_proposal(code="def helper(x):\n    return x * 2", name="helper"):
    return SkillProposal(name=name, code=code, description="A helper")


class TestCanLoad:
    """Policy → minimum trust matrix (audit #65)."""

    def test_untrusted_loads_nowhere(self):
        for policy in SkillPolicy:
            assert can_load(TrustLevel.UNTRUSTED, policy) is False

    def test_system_loads_everywhere(self):
        for policy in SkillPolicy:
            assert can_load(TrustLevel.SYSTEM, policy) is True

    def test_policy_matrix(self):
        assert can_load(TrustLevel.EXPERIMENTAL, SkillPolicy.SANDBOX) is True
        assert can_load(TrustLevel.EXPERIMENTAL, SkillPolicy.RESEARCH) is False
        assert can_load(TrustLevel.EXPERIMENTAL, SkillPolicy.PRODUCTION) is False
        assert can_load(TrustLevel.VALIDATED, SkillPolicy.RESEARCH) is True
        assert can_load(TrustLevel.VALIDATED, SkillPolicy.PRODUCTION) is False
        assert can_load(TrustLevel.TRUSTED, SkillPolicy.PRODUCTION) is True


class TestSkillApprover:

    def test_tests_pass_validates(self):
        review = SkillApprover().review(
            make_proposal(), test_results=["ok", "ok"]
        )
        assert review.approved
        assert review.level == TrustLevel.VALIDATED

    def test_approval_promotes_to_trusted(self):
        review = SkillApprover().review(
            make_proposal(), test_results=["ok"], approved_by="lead"
        )
        assert review.approved
        assert review.level == TrustLevel.TRUSTED
        assert "approved by lead" in review.reasons

    def test_failed_tests_reject(self):
        review = SkillApprover().review(
            make_proposal(), test_results=["ok", "FAIL: edge case"]
        )
        assert not review.approved
        assert review.level == TrustLevel.UNTRUSTED
        assert "tests failed" in review.summary

    def test_no_tests_reject(self):
        review = SkillApprover().review(make_proposal())
        assert not review.approved
        assert "no automated tests" in review.summary

    def test_forbidden_builtins_reject(self):
        # Audit #66: a generated skill must not smuggle capabilities
        for banned_code in (
            "def f():\n    eval(user_input)",
            "exec('import os')",
            "compile('x=1', '<s>', 'exec')",
        ):
            review = SkillApprover().review(make_proposal(code=banned_code))
            assert not review.approved, f"should reject: {banned_code}"
            assert any("forbidden" in r for r in review.reasons)

    def test_empty_code_reject(self):
        review = SkillApprover().review(make_proposal(code="   "))
        assert not review.approved
        assert "empty code" in review.reasons


class TestProvenance:

    def test_provenance_carries_full_trace(self):
        proposal = make_proposal()
        prov = provenance(
            proposal,
            author_agent="analyst",
            source_action="act_0047",
            source_session="sess-1",
            parent_skill="load_v1",
            capabilities=frozenset({"kernel.execute"}),
            version=2,
            approval="review-9",
        )
        assert prov.author_agent == "analyst"
        assert prov.source_action == "act_0047"
        assert prov.source_session == "sess-1"
        assert prov.parent_skill == "load_v1"
        assert prov.capabilities_required == frozenset({"kernel.execute"})
        assert prov.version == 2
        assert prov.approval == "review-9"

    def test_provenance_defaults(self):
        prov = provenance(make_proposal())
        assert prov.version == 1
        assert prov.approval == ""
        assert prov.capabilities_required == frozenset()


class TestSkillCapabilityBridging:
    """Audit #65/#66: bridging skill provenance capabilities into CapabilityBroker."""

    def test_grant_skill_capabilities_registers_grants(self):
        from kerno.security.capabilities import CapabilityBroker
        from kerno.skilltrust import grant_skill_capabilities

        broker = CapabilityBroker()
        prov = provenance(
            make_proposal(),
            author_agent="analyst",
            capabilities=frozenset({"filesystem.read", "dataframe.compute"}),
            approval="audit-gate",
        )

        grants = grant_skill_capabilities(broker, prov)
        assert len(grants) == 2

        # Check broker now has active grants for analyst
        assert broker.check("filesystem.read", subject="analyst")
        assert broker.check("dataframe.compute", subject="analyst")

        # Other subjects still denied
        assert not broker.check("filesystem.read", subject="critic")

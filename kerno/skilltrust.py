# kerno/skilltrust.py
"""
Skill trust levels and approval policy (audit #64/#65).

A generated skill must never silently replace a trusted skill. Every
skill proposal carries provenance (parent_skill, author_agent,
source_action, test_results, capabilities_required, version, approval)
and a trust level:

    UNTRUSTED      — freshly extracted, unverified
    EXPERIMENTAL   — runs in sandbox only
    VALIDATED      — passed automated tests
    TRUSTED        — reviewed/approved by a human or policy
    SYSTEM         — ships with the runtime

Policies decide what may load where:

    production:  SYSTEM, TRUSTED
    research:    + VALIDATED
    sandbox:     + EXPERIMENTAL
    never:       UNTRUSTED → privileged capabilities
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class TrustLevel(Enum):
    UNTRUSTED    = auto()
    EXPERIMENTAL = auto()
    VALIDATED    = auto()
    TRUSTED      = auto()
    SYSTEM       = auto()


class SkillPolicy(Enum):
    """Execution policies for loading skills (audit #65)."""

    PRODUCTION = auto()   # SYSTEM, TRUSTED
    RESEARCH   = auto()   # + VALIDATED
    SANDBOX    = auto()   # + EXPERIMENTAL


# Minimum trust allowed per policy
_POLICY_MINIMUM: dict[SkillPolicy, TrustLevel] = {
    SkillPolicy.PRODUCTION: TrustLevel.TRUSTED,
    SkillPolicy.RESEARCH:   TrustLevel.VALIDATED,
    SkillPolicy.SANDBOX:    TrustLevel.EXPERIMENTAL,
}


def can_load(level: TrustLevel, policy: SkillPolicy) -> bool:
    """
    May a skill with this trust level load under this policy?

    UNTRUSTED never loads anywhere. SYSTEM always loads.
    """
    if level == TrustLevel.SYSTEM:
        return True
    if level == TrustLevel.UNTRUSTED:
        return False
    order = [
        TrustLevel.EXPERIMENTAL,
        TrustLevel.VALIDATED,
        TrustLevel.TRUSTED,
    ]
    return order.index(level) >= order.index(_POLICY_MINIMUM[policy])


@dataclass
class SkillProvenance:
    """Provenance of a skill (audit #64)."""

    parent_skill:        str   = ""
    author_agent:        str   = ""
    source_action:       str   = ""          # action_id that created it
    source_session:      str   = ""
    capabilities_required: frozenset[str] = frozenset()
    version:             int   = 1
    approval:            str   = ""          # approver / approval id
    created_at:          float = field(default_factory=__import__("time").time)


class SkillApprovalError(RuntimeError):
    """Raised when a skill proposal fails review."""


@dataclass
class SkillReview:
    """Result of reviewing a skill proposal."""

    approved:    bool
    level:       TrustLevel
    reasons:     list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.approved:
            return "approved as {}".format(self.level.name)
        return "rejected: " + "; ".join(self.reasons)


class SkillApprover:
    """
    Reviews skill proposals → VALIDATED (automated tests pass) or
    TRUSTED (explicit approval). UNTRUSTED without tests → rejected.

    Usage:
        approver = SkillApprover()
        review = approver.review(proposal, test_results=["ok"], approved_by="")
        if review.approved:
            register(proposal, level=review.level)
    """

    def review(
        self,
        proposal:       object,
        *,
        test_results:   Optional[list[str]] = None,
        approved_by:    str = "",
        capabilities:   Optional[frozenset[str]] = None,
        parent_skill:   str = "",
        source_action:  str = "",
    ) -> SkillReview:
        """
        Review a SkillProposal-like object (name, code, description).

        Rules:
          - missing code → rejected
          - code containing exec/eval/compile → rejected (capability
            smuggling through generated skills, audit #66)
          - automated test_results containing "FAIL" → rejected
          - approved_by set → TRUSTED
          - passing tests, no approval → VALIDATED
          - otherwise → UNTRUSTED (loadable in no policy)
        """
        code = getattr(proposal, "code", "") or ""
        if not code.strip():
            return SkillReview(False, TrustLevel.UNTRUSTED, ["empty code"])

        reasons: list[str] = []
        for banned in ("eval(", "exec(", "compile("):
            if banned in code:
                reasons.append("forbidden builtin: " + banned.rstrip("("))

        if test_results:
            failed = [r for r in test_results if "FAIL" in r.upper()]
            if failed:
                reasons.append("automated tests failed: " + ", ".join(failed))
        else:
            reasons.append("no automated tests")

        if reasons:
            return SkillReview(False, TrustLevel.UNTRUSTED, reasons)

        if approved_by:
            return SkillReview(True, TrustLevel.TRUSTED,
                               ["approved by " + approved_by])
        return SkillReview(True, TrustLevel.VALIDATED, ["tests passed"])


def provenance(
    proposal:     object,
    *,
    author_agent: str = "",
    source_action: str = "",
    source_session: str = "",
    parent_skill: str = "",
    capabilities: Optional[frozenset[str]] = None,
    version:      int = 1,
    approval:     str = "",
) -> SkillProvenance:
    """Build provenance for a proposal (audit #64)."""
    return SkillProvenance(
        parent_skill          = parent_skill,
        author_agent          = author_agent,
        source_action         = source_action,
        source_session        = source_session or getattr(proposal, "source_session", ""),
        capabilities_required = frozenset(capabilities or ()),
        version               = version,
        approval              = approval,
    )

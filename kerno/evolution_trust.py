# kerno/evolution_trust.py
"""
Skill evolution + trust integration (audit #64/#65).

Bridges CapabilityExtractor (evolution.py) with SkillApprover
(skilltrust.py): extracted proposals are reviewed under a policy and
given full provenance before they may be registered. A generated skill
never silently replaces a trusted skill.

Usage:
    reviewer = EvolutionReviewer(policy=SkillPolicy.RESEARCH)
    proposals = CapabilityExtractor().extract(result)
    accepted = reviewer.review_all(proposals, author_agent="analyst")
    # accepted: [(SkillProposal, SkillReview, SkillProvenance), ...]
"""

from __future__ import annotations

from typing import Optional

from kerno.skilltrust import (
    SkillApprover, SkillPolicy, SkillProvenance,
    can_load, provenance,
)


class EvolutionReviewer:
    """
    Reviews extracted skill proposals under a trust policy.

    Rules:
      - proposals whose review is not approved → rejected
      - approved proposals must be loadable under the policy
        (VALIDATED loads in research/sandbox; TRUSTED in production)
      - rejected proposals carry their reasons for the agent to fix
    """

    def __init__(
        self,
        policy:      SkillPolicy = SkillPolicy.SANDBOX,
        approver:    Optional[SkillApprover] = None,
        test_hook:   Optional[callable] = None,
    ):
        self.policy   = policy
        self.approver = approver or SkillApprover()
        # test_hook: (SkillProposal) -> list[str] | None — runs automated
        # tests for a proposal; None means "no tests" (rejected unless
        # explicitly approved).
        self.test_hook = test_hook

    def review_all(
        self,
        proposals:    list,
        *,
        author_agent: str = "",
        source_action: str = "",
        source_session: str = "",
        approved_by:  str = "",
    ) -> list:
        """
        Review every proposal.

        Returns: [(proposal, SkillReview, SkillProvenance)] for the
        ACCEPTED proposals only (rejected ones are skipped).
        """
        accepted = []
        for proposal in proposals:
            review = self.approver.review(
                proposal,
                test_results = self._run_tests(proposal),
                approved_by  = approved_by,
            )
            if not review.approved:
                continue
            if not can_load(review.level, self.policy):
                continue
            prov = provenance(
                proposal,
                author_agent   = author_agent,
                source_action  = source_action,
                source_session = source_session,
            )
            accepted.append((proposal, review, prov))
        return accepted

    def _run_tests(self, proposal) -> Optional[list[str]]:
        if self.test_hook is None:
            return None
        results = self.test_hook(proposal)
        return list(results) if results else None

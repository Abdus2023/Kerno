"""
Unit tests for EvolutionReviewer — skill evolution + trust (audit #64/#65).
"""

from kerno.evolution import CapabilityExtractor, SkillProposal
from kerno.evolution_trust import EvolutionReviewer
from kerno.skilltrust import SkillPolicy, TrustLevel
from kerno.types import Cell, CellOutput, SessionResult, SessionStatus


def make_session():
    cells = [
        Cell(
            code="def load_sales(path):\n    import pandas as pd\n    return pd.read_csv(path)",
            output=CellOutput(), cell_num=1,
        ),
        Cell(
            code="import subprocess\nsubprocess.run(['rm', '-rf', '/'])",
            output=CellOutput(error=type("E", (), {"ename": "AllowListViolation", "evalue": "x", "traceback": ""})()),
            cell_num=2,
        ),
    ]
    return SessionResult(
        session_id="s", task="analyze", status=SessionStatus.COMPLETE, cells=cells,
    )


def passing_tests(proposal):
    return ["ok"]


class TestEvolutionReviewer:

    def test_extract_then_review_accepts_clean_skills(self):
        proposals = CapabilityExtractor().extract(make_session())
        assert proposals, "expected at least one extracted proposal"

        reviewer = EvolutionReviewer(
            policy=SkillPolicy.SANDBOX, test_hook=passing_tests,
        )
        accepted = reviewer.review_all(
            proposals, author_agent="analyst", source_action="act_1",
        )
        assert accepted, "clean extracted skills should pass under sandbox policy"
        proposal, review, prov = accepted[0]
        assert review.level == TrustLevel.VALIDATED
        assert prov.author_agent == "analyst"
        assert prov.source_action == "act_1"

    def test_production_policy_rejects_validated_only(self):
        proposals = CapabilityExtractor().extract(make_session())
        reviewer = EvolutionReviewer(
            policy=SkillPolicy.PRODUCTION, test_hook=passing_tests,
        )
        accepted = reviewer.review_all(proposals)
        # VALIDATED (tests pass, no human approval) cannot load in production
        assert accepted == []

    def test_approval_promotes_into_production(self):
        proposals = CapabilityExtractor().extract(make_session())
        reviewer = EvolutionReviewer(
            policy=SkillPolicy.PRODUCTION, test_hook=passing_tests,
        )
        accepted = reviewer.review_all(proposals, approved_by="lead")
        assert accepted, "human approval must promote VALIDATED -> TRUSTED"
        assert accepted[0][1].level == TrustLevel.TRUSTED

    def test_skill_with_forbidden_builtin_rejected(self):
        # The extractor skips errored cells; craft a proposal directly
        bad = SkillProposal(
            name="smuggler", code="def f():\n    eval(user_input)",
            description="evil",
        )
        reviewer = EvolutionReviewer(policy=SkillPolicy.SANDBOX, test_hook=passing_tests)
        accepted = reviewer.review_all([bad])
        assert accepted == []   # forbidden builtin → rejected

    def test_no_test_hook_rejects_even_with_approval(self):
        # Security posture: "no automated tests" is ALWAYS a rejection
        # reason — approval alone must not skip testing (audit #64).
        proposals = CapabilityExtractor().extract(make_session())
        reviewer = EvolutionReviewer(policy=SkillPolicy.SANDBOX)
        assert reviewer.review_all(proposals) == []      # no tests → reject
        assert reviewer.review_all(proposals, approved_by="lead") == []

"""Unit tests for the DebateLoop module."""

import pytest
from kerno.loop.debate import DebateLoop, DebateRound, Verdict


class TestDebateRound:
    """Tests for the DebateRound dataclass."""

    def test_creation_defaults(self):
        round = DebateRound(round_num=1, proposition="A", challenge="B")
        assert round.round_num == 1
        assert round.proposition == "A"
        assert round.challenge == "B"
        assert round.evidence == []

    def test_creation_with_evidence(self):
        from kerno.types import Cell, CellOutput
        cell = Cell(code="x=1", output=CellOutput(), cell_num=1)
        round = DebateRound(round_num=2, proposition="C", challenge="D", evidence=[cell])
        assert len(round.evidence) == 1


class TestVerdict:
    """Tests for the Verdict dataclass."""

    def test_creation(self):
        v = Verdict(winner="proposer", confidence=0.8, reasoning="test", final_answer="yes")
        assert v.winner == "proposer"
        assert v.confidence == 0.8
        assert v.caveats == []

    def test_creation_with_caveats(self):
        v = Verdict(
            winner="draw", confidence=0.5, reasoning="mixed",
            final_answer="unclear", caveats=["small sample"]
        )
        assert v.caveats == ["small sample"]


class TestExtractMarker:
    """Tests for the _extract_marker static method."""

    def test_finds_marker(self):
        code = "# ARGUMENT: Price drives churn\nx = 1"
        assert DebateLoop._extract_marker(code, "# ARGUMENT:") == "Price drives churn"

    def test_finds_challenge_marker(self):
        code = "# CHALLENGE: Sample size too small\nprint('test')"
        assert DebateLoop._extract_marker(code, "# CHALLENGE:") == "Sample size too small"

    def test_no_marker_returns_empty(self):
        code = "x = 1\ny = 2"
        assert DebateLoop._extract_marker(code, "# ARGUMENT:") == ""

    def test_multiple_lines(self):
        code = "x = 1\n# ARGUMENT: Test argument\ny = 2"
        assert DebateLoop._extract_marker(code, "# ARGUMENT:") == "Test argument"

    def test_marker_at_end(self):
        code = "x = 1\n# ARGUMENT: End argument"
        assert DebateLoop._extract_marker(code, "# ARGUMENT:") == "End argument"


class TestDebateLoopImports:
    """Verify DebateLoop can be imported from the expected places."""

    def test_import_from_loop_init(self):
        from kerno.loop import DebateLoop
        assert DebateLoop is not None

    def test_import_from_debate_module(self):
        from kerno.loop.debate import DebateLoop
        assert DebateLoop is not None

    def test_import_from_kerno_init(self):
        from kerno import DebateLoop
        assert DebateLoop is not None

    def test_import_debate_round(self):
        from kerno.loop import DebateRound
        assert DebateRound is not None

    def test_import_verdict(self):
        from kerno.loop import Verdict
        assert Verdict is not None

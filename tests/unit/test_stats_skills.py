"""Unit tests for the Statistics skills module."""

import ast
import pytest


class TestStatsSkillsSyntax:
    """Verify the Stats skills code string is valid Python."""

    def test_stats_module_syntax(self):
        with open("kerno/skills/builtins/stats.py") as f:
            ast.parse(f.read())

    def test_stats_code_string_syntax(self):
        """The _STATS_SKILLS_CODE string itself should be valid Python."""
        from kerno.skills.builtins.stats import get_code
        code = get_code()
        ast.parse(code)

    def test_get_code_returns_string(self):
        from kerno.skills.builtins.stats import get_code
        result = get_code()
        assert isinstance(result, str)
        assert len(result) > 100


class TestStatsSkillsDefinitions:
    """Verify key function definitions exist in the Stats skills code."""

    def test_has_describe_distribution(self):
        from kerno.skills.builtins.stats import get_code
        assert "def describe_distribution" in get_code()

    def test_has_ttest(self):
        from kerno.skills.builtins.stats import get_code
        assert "def ttest" in get_code()

    def test_has_anova(self):
        from kerno.skills.builtins.stats import get_code
        assert "def anova" in get_code()

    def test_has_chi_square(self):
        from kerno.skills.builtins.stats import get_code
        assert "def chi_square" in get_code()

    def test_has_bootstrap_ci(self):
        from kerno.skills.builtins.stats import get_code
        assert "def bootstrap_ci" in get_code()

    def test_has_correlate(self):
        from kerno.skills.builtins.stats import get_code
        assert "def correlate" in get_code()


class TestStatsSkillsImports:
    """Verify stats skills module can be imported."""

    def test_import_stats_module(self):
        from kerno.skills.builtins import stats
        assert stats is not None

    def test_import_get_code(self):
        from kerno.skills.builtins.stats import get_code
        assert callable(get_code)

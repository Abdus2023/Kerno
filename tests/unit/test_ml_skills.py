"""Unit tests for the ML skills module."""

import ast
import pytest


class TestMLSkillsSyntax:
    """Verify the ML skills code string is valid Python."""

    def test_ml_module_syntax(self):
        with open("kerno/skills/builtins/ml.py") as f:
            ast.parse(f.read())

    def test_ml_code_string_syntax(self):
        """The _ML_SKILLS_CODE string itself should be valid Python."""
        from kerno.skills.builtins.ml import get_code
        code = get_code()
        ast.parse(code)

    def test_get_code_returns_string(self):
        from kerno.skills.builtins.ml import get_code
        result = get_code()
        assert isinstance(result, str)
        assert len(result) > 100


class TestMLSkillsDefinitions:
    """Verify key function definitions exist in the ML skills code."""

    def test_has_split_function(self):
        from kerno.skills.builtins.ml import get_code
        assert "def split" in get_code()

    def test_has_train_classifier(self):
        from kerno.skills.builtins.ml import get_code
        assert "def train_classifier" in get_code()

    def test_has_train_regressor(self):
        from kerno.skills.builtins.ml import get_code
        assert "def train_regressor" in get_code()

    def test_has_evaluate_classifier(self):
        from kerno.skills.builtins.ml import get_code
        assert "def evaluate_classifier" in get_code()

    def test_has_evaluate_regressor(self):
        from kerno.skills.builtins.ml import get_code
        assert "def evaluate_regressor" in get_code()

    def test_has_cross_validate_model(self):
        from kerno.skills.builtins.ml import get_code
        assert "def cross_validate_model" in get_code()

    def test_has_feature_importance(self):
        from kerno.skills.builtins.ml import get_code
        assert "def feature_importance" in get_code()

    def test_has_preprocess(self):
        from kerno.skills.builtins.ml import get_code
        assert "def preprocess" in get_code()


class TestMLSkillsImports:
    """Verify ml skills module can be imported."""

    def test_import_ml_module(self):
        from kerno.skills.builtins import ml
        assert ml is not None

    def test_import_get_code(self):
        from kerno.skills.builtins.ml import get_code
        assert callable(get_code)

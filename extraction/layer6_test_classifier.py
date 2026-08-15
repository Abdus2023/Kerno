# tests/unit/test_error_classifier.py
"""Unit tests for error classification — no kernel required."""

import pytest
from kerno.errors.classifier import ErrorClassifier
from kerno.types import CellError, ErrorClass


@pytest.fixture
def clf():
    return ErrorClassifier()


class TestErrorClassifier:

    def test_classifies_key_error(self, clf):
        error      = CellError("KeyError", "'profit'")
        classified = clf.classify(error)
        assert classified.error_class == ErrorClass.WRONG_COLUMN
        assert "profit" in classified.recovery_hint
        assert "columns" in classified.recovery_code

    def test_classifies_module_not_found(self, clf):
        error      = CellError("ModuleNotFoundError", "No module named 'plotly'")
        classified = clf.classify(error)
        assert classified.error_class == ErrorClass.MODULE_NOT_FOUND
        assert "pip" in classified.recovery_code
        assert "plotly" in classified.recovery_code

    def test_classifies_name_error(self, clf):
        error      = CellError("NameError", "name 'df_clean' is not defined")
        classified = clf.classify(error)
        assert classified.error_class == ErrorClass.UNDEFINED_VARIABLE
        assert "df_clean" in classified.recovery_hint
        assert "globals" in classified.recovery_code

    def test_classifies_syntax_error(self, clf):
        error      = CellError("SyntaxError", "invalid syntax")
        classified = clf.classify(error)
        assert classified.error_class == ErrorClass.SYNTAX_ERROR

    def test_classifies_file_not_found(self, clf):
        error      = CellError("FileNotFoundError", "[Errno 2] No such file or directory: 'data.csv'")
        classified = clf.classify(error)
        assert classified.error_class == ErrorClass.FILE_NOT_FOUND
        assert "data.csv" in classified.recovery_hint

    def test_unclassified_error(self, clf):
        error      = CellError("WeirdCustomError", "something very unusual")
        classified = clf.classify(error)
        assert classified.error_class == ErrorClass.UNCLASSIFIED
        assert classified.is_retryable  # Unknown errors are retryable by default

    def test_format_for_llm_contains_class_name(self, clf):
        error      = CellError("KeyError", "'missing_col'")
        classified = clf.classify(error)
        formatted  = clf.format_for_llm(classified)
        assert "WRONG_COLUMN" in formatted
        assert "missing_col" in formatted

    def test_memory_error_not_retryable(self, clf):
        error      = CellError("MemoryError", "")
        classified = clf.classify(error)
        assert classified.error_class == ErrorClass.OUT_OF_MEMORY
        assert classified.requires_replan

    def test_zero_division(self, clf):
        error      = CellError("ZeroDivisionError", "division by zero")
        classified = clf.classify(error)
        assert classified.error_class == ErrorClass.DIVISION_BY_ZERO
        assert "np.where" in classified.recovery_code

# kerno/errors/__init__.py
"""Errors subpackage: error classification and recovery strategies."""

from kerno.errors.classifier import ErrorClassifier, ClassifiedError
from kerno.errors.recovery import RecoveryStrategy

__all__ = [
    "ErrorClassifier",
    "ClassifiedError",
    "RecoveryStrategy",
]

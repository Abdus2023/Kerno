# kerno/errors/classifier.py
"""
ErrorClassifier: maps raw kernel errors to structured error classes
and suggests recovery code.

Why this matters:
  A LLM receiving a raw traceback can recover.
  A LLM receiving a classified error + recovery template recovers faster,
  more consistently, and with less wasted context.

The classifier is a rule-based filter in front of the LLM,
not a replacement for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from kerno.types import CellError, ErrorClass


@dataclass
class ClassifiedError:
    """
    A kernel error with classification and recovery guidance.
    """
    original:         CellError
    error_class:      ErrorClass
    recovery_hint:    str          # One-line human description
    recovery_code:    str          # Python code template to try next
    is_retryable:     bool         = True
    requires_replan:  bool         = False


# ── Classification Rules ──────────────────────────────────────────────────
#
# Each rule is: (pattern, error_class, hint_fn, recovery_fn)
# Patterns match against "ename: evalue".
# hint_fn and recovery_fn receive the Match object.

_RULES: list[tuple] = [

    # ── Semantic ──────────────────────────────────────────────────────────────

    (
        re.compile(r"KeyError: ['\"](\w+)['\"]"),
        ErrorClass.WRONG_COLUMN,
        lambda m: f"Column '{m.group(1)}' does not exist",
        lambda m: (
            f"# Column '{m.group(1)}' not found — inspect available columns\n"
            f"print('Available columns:', df.columns.tolist())\n"
            f"# Then use the correct column name"
        ),
    ),

    (
        re.compile(r"AttributeError: '(\w+)' object has no attribute '(\w+)'"),
        ErrorClass.WRONG_API,
        lambda m: f"'{m.group(1)}' has no attribute '{m.group(2)}'",
        lambda m: (
            f"# '{m.group(1)}' has no '{m.group(2)}' — inspect available attributes\n"
            f"# Check: [a for a in dir(obj) if not a.startswith('_')]"
        ),
    ),

    (
        re.compile(r"TypeError: .*argument.*"),
        ErrorClass.WRONG_API,
        lambda m: "Wrong argument type or count for a function call",
        lambda m: (
            "# Wrong arguments — check the function signature\n"
            "# import inspect; print(inspect.signature(the_function))"
        ),
    ),

    (
        re.compile(r"ValueError: could not convert string to float"),
        ErrorClass.WRONG_TYPE,
        lambda m: "Tried to do arithmetic on a string column",
        lambda m: (
            "# String column where numeric expected\n"
            "# df['col'] = pd.to_numeric(df['col'], errors='coerce')"
        ),
    ),

    # ── Resource ─────────────────────────────────────────────────────────────

    (
        re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'"),
        ErrorClass.MODULE_NOT_FOUND,
        lambda m: f"Module '{m.group(1)}' is not installed",
        lambda m: (
            f"import subprocess\n"
            f"subprocess.run(['pip', 'install', '{m.group(1)}'], "
            f"capture_output=True)\n"
            f"import {m.group(1).split('.')[0]}"
        ),
    ),

    (
        re.compile(r"FileNotFoundError: \[Errno 2\].*'(.+)'"),
        ErrorClass.FILE_NOT_FOUND,
        lambda m: f"File not found: '{m.group(1)}'",
        lambda m: (
            f"import pathlib\n"
            f"# File '{m.group(1)}' not found — check what's available\n"
            f"print(sorted(pathlib.Path('.').glob('**/*'))[:20])"
        ),
    ),

    (
        re.compile(r"MemoryError"),
        ErrorClass.OUT_OF_MEMORY,
        lambda m: "Ran out of memory — data too large for current approach",
        lambda m: (
            "# Out of memory — try working with a sample first\n"
            "df_sample = df.sample(min(10_000, len(df)), random_state=42)\n"
            "# Validate approach on sample, then apply to full dataset"
        ),
    ),

    (
        re.compile(r"TimeoutError"),
        ErrorClass.TIMEOUT,
        lambda m: "Cell timed out — computation too slow",
        lambda m: (
            "# Operation timed out — sample down or optimize\n"
            "# For DataFrames: use df.sample(1000) first\n"
            "# For loops: vectorize with pandas/numpy instead"
        ),
    ),

    # ── Logic ─────────────────────────────────────────────────────────────────

    (
        re.compile(r"ValueError: operands could not be broadcast together"),
        ErrorClass.DIMENSION_MISMATCH,
        lambda m: "Array dimensions do not match for the operation",
        lambda m: (
            "# Dimension mismatch — print shapes before operating\n"
            "# print(a.shape, b.shape)"
        ),
    ),

    (
        re.compile(r"IndexError: (index \d+ is out of bounds|list index out of range)"),
        ErrorClass.INDEX_OUT_OF_BOUNDS,
        lambda m: "Index out of bounds — check the length of the sequence",
        lambda m: (
            "# Index out of bounds — check lengths\n"
            "# print(len(the_sequence))"
        ),
    ),

    (
        re.compile(r"ZeroDivisionError"),
        ErrorClass.DIVISION_BY_ZERO,
        lambda m: "Division by zero — guard or filter zero values",
        lambda m: (
            "# Division by zero — use np.where or filter\n"
            "# result = np.where(denominator != 0, numerator / denominator, np.nan)"
        ),
    ),

    # ── Syntax ────────────────────────────────────────────────────────────────

    (
        re.compile(r"SyntaxError: (.+)"),
        ErrorClass.SYNTAX_ERROR,
        lambda m: f"Syntax error: {m.group(1)}",
        lambda m: (
            "# Syntax error in generated code — rewrite the cell\n"
            "# Common causes: missing colon, mismatched brackets, f-string issues"
        ),
    ),

    (
        re.compile(r"IndentationError"),
        ErrorClass.SYNTAX_ERROR,
        lambda m: "Indentation error",
        lambda m: (
            "# Indentation error — rewrite with consistent 4-space indentation"
        ),
    ),

    # ── State ─────────────────────────────────────────────────────────────────

    (
        re.compile(r"NameError: name '(\w+)' is not defined"),
        ErrorClass.UNDEFINED_VARIABLE,
        lambda m: f"Variable '{m.group(1)}' is not defined in the kernel namespace",
        lambda m: (
            f"# '{m.group(1)}' not in namespace — check what's available\n"
            f"similar = [k for k in globals() "
            f"           if '{m.group(1)[:3].lower()}' in k.lower()]\n"
            f"print('Similar names:', similar)"
        ),
    ),

    (
        re.compile(r"NotFittedError|sklearn.*not fitted"),
        ErrorClass.WRONG_API,
        lambda m: "Model has not been fitted — call .fit() first",
        lambda m: (
            "# Model not fitted — fit before predict\n"
            "# model.fit(X_train, y_train)\n"
            "# Then: model.predict(X_test)"
        ),
    ),
]


class ErrorClassifier:
    """
    Classifies CellError objects and returns structured recovery guidance.
    """

    def classify(self, error: CellError) -> ClassifiedError:
        """
        Match an error against known patterns and return classification.

        Args:
            error: The CellError from kernel output

        Returns:
            ClassifiedError with class, hint, and recovery code
        """
        error_str = f"{error.ename}: {error.evalue}"

        for pattern, error_class, hint_fn, recovery_fn in self._iter_rules():
            match = pattern.search(error_str)
            if match:
                is_retryable    = error_class not in (ErrorClass.OUT_OF_MEMORY,)
                requires_replan = error_class in (
                    ErrorClass.OUT_OF_MEMORY,
                    ErrorClass.TIMEOUT,
                )
                return ClassifiedError(
                    original        = error,
                    error_class     = error_class,
                    recovery_hint   = hint_fn(match),
                    recovery_code   = recovery_fn(match),
                    is_retryable    = is_retryable,
                    requires_replan = requires_replan,
                )

        # No match — unclassified
        return ClassifiedError(
            original      = error,
            error_class   = ErrorClass.UNCLASSIFIED,
            recovery_hint = f"Unclassified error: {error.ename}",
            recovery_code = (
                f"# Unclassified error: {error.ename}: {error.evalue}\n"
                f"# Traceback:\n"
                + "\n".join(
                    f"# {line}"
                    for line in (error.traceback or "").split("\n")[-5:]
                )
            ),
            is_retryable  = True,
        )

    def format_for_llm(self, classified: ClassifiedError) -> str:
        """
        Format a classified error for injection into LLM context.
        Structured to be more information-dense than a raw traceback.
        """
        return (
            f"[{classified.error_class.name}] "
            f"{classified.recovery_hint}\n\n"
            f"Suggested recovery:\n"
            f"```python\n{classified.recovery_code}\n```\n\n"
            f"Original error:\n"
            f"{classified.original.ename}: {classified.original.evalue}"
        )

    def _iter_rules(self):
        """Yield rules, unpacking optional flags."""
        for rule in _RULES:
            pattern, error_class, hint_fn, recovery_fn = rule[:4]
            yield pattern, error_class, hint_fn, recovery_fn

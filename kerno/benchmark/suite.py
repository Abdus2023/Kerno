# kerno/benchmark/suite.py
"""
BenchmarkSuite: a collection of benchmark cases.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib     import Path
from typing      import Callable, Optional


@dataclass
class BenchmarkCase:
    """
    One benchmark task with evaluation criteria.
    """
    id:            str
    task:          str
    category:      str  = "general"

    # Evaluation criteria
    expected_status:  str            = "COMPLETE"
    max_cells:        int            = 50
    max_duration_s:   float          = 300.0
    min_quality:      float          = 3.0    # LLM judge score (1-5)

    # Optional: keyword checks on final output
    must_contain:     list[str]      = field(default_factory=list)
    must_not_contain: list[str]      = field(default_factory=list)

    # Optional: programmatic verification
    verify_fn:        Optional[Callable] = None

    # Metadata
    tags:             list[str]      = field(default_factory=list)
    difficulty:       str            = "medium"   # easy | medium | hard


class BenchmarkSuite:
    """
    A collection of benchmark cases.

    Usage:
        suite = BenchmarkSuite("data_analysis")
        suite.add(BenchmarkCase(
            id   = "basic_profiling",
            task = "Create a 100-row DataFrame and profile it",
            must_contain = ["shape", "dtype"],
        ))
        suite.save("benchmarks/data_analysis.json")
    """

    def __init__(self, name: str, description: str = ""):
        self.name        = name
        self.description = description
        self._cases:     list[BenchmarkCase] = []

    def add(self, case: BenchmarkCase) -> "BenchmarkSuite":
        self._cases.append(case)
        return self

    def add_all(self, cases: list[BenchmarkCase]) -> "BenchmarkSuite":
        self._cases.extend(cases)
        return self

    def filter(
        self,
        category:   str = None,
        difficulty: str = None,
        tags:       list[str] = None,
    ) -> "BenchmarkSuite":
        cases = self._cases
        if category:
            cases = [c for c in cases if c.category == category]
        if difficulty:
            cases = [c for c in cases if c.difficulty == difficulty]
        if tags:
            cases = [c for c in cases if any(t in c.tags for t in tags)]

        sub       = BenchmarkSuite("{}_{}".format(self.name, category or "filtered"))
        sub._cases = cases
        return sub

    def __len__(self) -> int:
        return len(self._cases)

    def __iter__(self):
        return iter(self._cases)

    def save(self, path: str) -> None:
        data = {
            "name":        self.name,
            "description": self.description,
            "cases": [
                {
                    "id":               c.id,
                    "task":             c.task,
                    "category":         c.category,
                    "expected_status":  c.expected_status,
                    "max_cells":        c.max_cells,
                    "max_duration_s":   c.max_duration_s,
                    "min_quality":      c.min_quality,
                    "must_contain":     c.must_contain,
                    "must_not_contain": c.must_not_contain,
                    "tags":             c.tags,
                    "difficulty":       c.difficulty,
                }
                for c in self._cases
            ]
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: str) -> "BenchmarkSuite":
        data  = json.loads(Path(path).read_text())
        suite = cls(data["name"], data.get("description", ""))
        for c in data["cases"]:
            suite.add(BenchmarkCase(**{k: v for k, v in c.items()
                                       if k != "verify_fn"}))
        return suite


# ── Built-in suites ───────────────────────────────────────────────────────────

def standard_suite() -> BenchmarkSuite:
    """
    The kerno standard benchmark suite.
    Tests core capabilities across difficulty levels.
    """
    suite = BenchmarkSuite(
        name        = "kerno_standard",
        description = "Standard benchmark for kerno agent capabilities",
    )

    # ── Easy: basic operations ─────────────────────────────────────────────────
    suite.add(BenchmarkCase(
        id           = "hello_world",
        task         = "Print 'Hello, kerno!' and assign the string to a variable called greeting",
        category     = "basic",
        difficulty   = "easy",
        max_cells    = 5,
        must_contain = ["Hello, kerno!"],
        tags         = ["smoke_test"],
    ))
    suite.add(BenchmarkCase(
        id           = "dataframe_create",
        task         = (
            "Create a pandas DataFrame with 50 rows and columns: "
            "id (int), name (str), value (float). Print its shape."
        ),
        category     = "data",
        difficulty   = "easy",
        max_cells    = 10,
        must_contain = ["50", "3"],
        tags         = ["pandas"],
    ))
    suite.add(BenchmarkCase(
        id           = "error_recovery",
        task         = (
            "Try to access column 'nonexistent' on a DataFrame. "
            "Catch the error and print the available columns instead."
        ),
        category     = "error_handling",
        difficulty   = "easy",
        max_cells    = 8,
        tags         = ["error", "recovery"],
    ))

    # ── Medium: analysis tasks ─────────────────────────────────────────────────
    suite.add(BenchmarkCase(
        id           = "data_profiling",
        task         = (
            "Generate 500 rows of sales data (date, region, revenue, units). "
            "Profile it: shape, dtypes, nulls, and numeric summary."
        ),
        category     = "analysis",
        difficulty   = "medium",
        max_cells    = 15,
        must_contain = ["500", "region", "revenue"],
        tags         = ["pandas", "profiling"],
    ))
    suite.add(BenchmarkCase(
        id           = "visualization",
        task         = (
            "Generate 200 rows of data with columns: x (float), y (float), "
            "group (A/B/C). Create a scatter plot colored by group."
        ),
        category     = "visualization",
        difficulty   = "medium",
        max_cells    = 15,
        tags         = ["matplotlib", "scatter"],
    ))
    suite.add(BenchmarkCase(
        id           = "statistical_test",
        task         = (
            "Generate two groups of 100 random values each from different distributions. "
            "Run a t-test and report whether the difference is significant."
        ),
        category     = "statistics",
        difficulty   = "medium",
        max_cells    = 10,
        must_contain = ["p", "significant"],
        tags         = ["scipy", "hypothesis_test"],
    ))

    # ── Hard: multi-step tasks ─────────────────────────────────────────────────
    suite.add(BenchmarkCase(
        id         = "ml_pipeline",
        task       = (
            "Generate a binary classification dataset (1000 samples, 10 features). "
            "Split train/test. Train a RandomForest. Evaluate with accuracy, "
            "precision, recall, F1. Plot feature importances."
        ),
        category   = "machine_learning",
        difficulty = "hard",
        max_cells  = 25,
        must_contain = ["accuracy", "precision", "recall"],
        tags         = ["sklearn", "classification"],
    ))
    suite.add(BenchmarkCase(
        id         = "time_series",
        task       = (
            "Generate 2 years of daily revenue data with trend and seasonality. "
            "Decompose the series. Identify the 3 highest and 3 lowest months. "
            "Forecast the next 30 days using linear extrapolation."
        ),
        category   = "time_series",
        difficulty = "hard",
        max_cells  = 30,
        must_contain = ["trend", "seasonal", "forecast"],
        tags         = ["time_series", "decomposition"],
    ))

    return suite

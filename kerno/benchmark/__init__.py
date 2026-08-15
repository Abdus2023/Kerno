# kerno/benchmark/__init__.py
"""
kerno benchmarking: measure agent performance.

A benchmark is a collection of tasks with expected outcomes.
The runner executes each task with one or more configurations
and compares results.

Metrics tracked:
  - Task completion rate
  - Cells per task (efficiency)
  - Error rate and recovery rate
  - Wall time per task
  - Token cost estimate
  - LLM-as-judge quality scores
"""

from kerno.benchmark.suite  import BenchmarkSuite, BenchmarkCase
from kerno.benchmark.runner import BenchmarkRunner
from kerno.benchmark.report import BenchmarkReport

__all__ = ["BenchmarkSuite", "BenchmarkCase", "BenchmarkRunner", "BenchmarkReport"]

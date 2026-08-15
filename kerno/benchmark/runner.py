# kerno/benchmark/runner.py
"""
BenchmarkRunner: executes a suite and collects results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing      import Callable, Optional

from kerno.benchmark.suite import BenchmarkCase, BenchmarkSuite


@dataclass
class CaseResult:
    """Result of running one benchmark case."""
    case_id:        str
    task:           str
    status:         str
    cells_executed: int
    duration_s:     float
    error_count:    int
    recovery_count: int

    # Evaluation outcomes
    status_pass:    bool  = False
    cells_pass:     bool  = False
    duration_pass:  bool  = False
    content_pass:   bool  = False
    quality_score:  float = 0.0
    quality_pass:   bool  = False
    verify_pass:    Optional[bool] = None

    # Derived
    @property
    def overall_pass(self) -> bool:
        checks = [self.status_pass, self.cells_pass,
                  self.duration_pass, self.content_pass]
        if self.verify_pass is not None:
            checks.append(self.verify_pass)
        return all(checks)

    @property
    def score(self) -> float:
        """0.0 – 1.0 composite score."""
        passed = sum([
            self.status_pass, self.cells_pass,
            self.duration_pass, self.content_pass,
        ])
        total = 4
        base = passed / total

        # Incorporate quality score if available
        if self.quality_score > 0:
            quality_component = (self.quality_score - 1) / 4   # Normalize 1-5 → 0-1
            return (base + quality_component) / 2

        return base


class BenchmarkRunner:
    """
    Runs a BenchmarkSuite against one or more configurations.

    Usage:
        runner = BenchmarkRunner(llm=my_llm)
        report = runner.run(standard_suite())
        print(report.summary())

        # Compare configurations
        report = runner.compare(
            suite    = standard_suite(),
            configs  = {
                "reactive": {"loop": "reactive"},
                "reflect":  {"loop": "reflect"},
            }
        )
    """

    def __init__(
        self,
        llm,
        judge_llm:    object  = None,
        verbose:      bool    = False,
        save_notebooks: bool  = False,
    ):
        self.llm            = llm
        self.judge_llm      = judge_llm or llm
        self.verbose        = verbose
        self.save_notebooks = save_notebooks

    def run(
        self,
        suite:     BenchmarkSuite,
        loop:      str = "reactive",
        max_cells: int = None,
    ) -> "BenchmarkReport":
        """
        Run all cases in the suite with a single configuration.
        """
        from kerno.benchmark.report import BenchmarkReport

        results: list[CaseResult] = []
        total   = len(suite)

        print("\nBenchmark: {}  ({} cases, loop={})".format(suite.name, total, loop))
        print("─" * 60)

        for i, case in enumerate(suite):
            if self.verbose:
                print("\n[{}/{}] {}: {}...".format(i+1, total, case.id, case.task[:60]))
            else:
                print("  [{}/{}] {}... ".format(i+1, total, case.id), end="", flush=True)

            result = self._run_case(case, loop=loop, max_cells=max_cells)
            results.append(result)

            if not self.verbose:
                icon = "✓" if result.overall_pass else "✗"
                print("{} ({}, {:.1f}s)".format(icon, result.cells_executed, result.duration_s))

        return BenchmarkReport(
            suite_name    = suite.name,
            config        = {"loop": loop},
            case_results  = results,
        )

    def compare(
        self,
        suite:   BenchmarkSuite,
        configs: dict[str, dict],
    ) -> "BenchmarkReport":
        """
        Run the suite with multiple configurations and compare.

        Args:
            suite:   Benchmark suite to run
            configs: {config_name: {loop: ..., max_cells: ...}}

        Returns:
            BenchmarkReport with all configurations compared
        """
        from kerno.benchmark.report import BenchmarkReport

        all_results: dict[str, list[CaseResult]] = {}

        for config_name, config_params in configs.items():
            print("\nConfiguration: {}".format(config_name))
            report = self.run(suite, **config_params)
            all_results[config_name] = report.case_results

        # Return multi-config report
        return BenchmarkReport(
            suite_name      = suite.name,
            config          = configs,
            case_results    = all_results.get(list(configs.keys())[0], []),
            all_config_results = all_results,
        )

    def _run_case(
        self,
        case:      BenchmarkCase,
        loop:      str = "reactive",
        max_cells: int = None,
    ) -> CaseResult:
        """Execute one benchmark case and evaluate it."""
        from kerno.compose  import Session
        from kerno.llm.wrappers import RetryLLM

        max_c  = max_cells or case.max_cells
        start  = time.time()

        result = CaseResult(
            case_id        = case.id,
            task           = case.task,
            status         = "ERROR",
            cells_executed = 0,
            duration_s     = 0.0,
            error_count    = 0,
            recovery_count = 0,
        )

        try:
            session_result = (
                Session()
                .with_llm(RetryLLM(self.llm, max_retries=2))
                .with_kernel()
                .with_loop(loop, max_cells=max_c)
                .run(case.task)
            )

            result.status         = session_result.status.name
            result.cells_executed = session_result.cells_executed
            result.duration_s     = round(session_result.duration, 2)
            result.error_count    = session_result.error_count
            result.recovery_count = session_result.recovery_count

        except Exception as e:
            result.status     = "EXCEPTION"
            result.duration_s = round(time.time() - start, 2)
            if self.verbose:
                print("  Exception: {}".format(e))
            return result

        # ── Evaluation ────────────────────────────────────────────────────────

        result.status_pass   = result.status == case.expected_status
        result.cells_pass    = result.cells_executed <= case.max_cells
        result.duration_pass = result.duration_s   <= case.max_duration_s

        # Content check
        all_text = " ".join(
            c.output.stdout
            for c in session_result.cells
        ).lower()

        must_contain_pass    = all(kw.lower() in all_text for kw in case.must_contain)
        must_not_contain_pass = not any(kw.lower() in all_text for kw in case.must_not_contain)
        result.content_pass  = must_contain_pass and must_not_contain_pass

        # Quality score (LLM judge)
        if self.judge_llm and result.status == "COMPLETE":
            result.quality_score = self._judge_quality(case, session_result)
            result.quality_pass  = result.quality_score >= case.min_quality

        # Custom verification
        if case.verify_fn:
            try:
                result.verify_pass = bool(case.verify_fn(session_result))
            except Exception:
                result.verify_pass = False

        if self.verbose:
            icon = "✓" if result.overall_pass else "✗"
            print("  {} status={} cells={} content={} quality={:.1f}".format(
                icon, result.status_pass,
                result.cells_pass, result.content_pass,
                result.quality_score))

        return result

    def _judge_quality(self, case: BenchmarkCase, session) -> float:
        """Use LLM-as-judge to score the session output."""
        from kerno.types import Message

        # Build a compact summary of what happened
        cells_summary = "\n".join(
            "Cell {}: {}".format(c.cell_num, c.output.as_text(max_chars=200))
            for c in session.cells[-5:]   # Last 5 cells
        )

        prompt = (
            "Rate this agent's response on a scale of 1-5.\n\n"
            "Task: {}\n"
            "Expected outcome: complete and correct answer\n\n"
            "Last {} cells of output:\n{}\n\n"
            "Final namespace: {}\n\n"
            "Rate on:\n"
            "  1 = Failed completely\n"
            "  2 = Partially completed, significant issues\n"
            "  3 = Completed but with notable problems\n"
            "  4 = Completed well with minor issues\n"
            "  5 = Excellent, complete, clean\n\n"
            "Reply with only a number (1-5).\n"
        ).format(
            case.task,
            min(5, len(session.cells)),
            cells_summary,
            session.final_namespace[:300],
        )

        try:
            response = self.judge_llm([Message(role="user", content=prompt)])
            score    = float(response.strip().split()[0])
            return max(1.0, min(5.0, score))
        except Exception:
            return 0.0

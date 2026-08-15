# kerno/benchmark/report.py
"""
BenchmarkReport: aggregates and presents benchmark results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib     import Path
from typing      import Optional

from kerno.benchmark.runner import CaseResult


@dataclass
class BenchmarkReport:
    """Aggregated benchmark results."""
    suite_name:          str
    config:              dict
    case_results:        list[CaseResult]
    all_config_results:  dict[str, list[CaseResult]] = field(default_factory=dict)

    # ── Statistics ────────────────────────────────────────────────────────────

    @property
    def pass_rate(self) -> float:
        if not self.case_results:
            return 0.0
        return sum(r.overall_pass for r in self.case_results) / len(self.case_results)

    @property
    def avg_cells(self) -> float:
        if not self.case_results:
            return 0.0
        return sum(r.cells_executed for r in self.case_results) / len(self.case_results)

    @property
    def avg_duration_s(self) -> float:
        if not self.case_results:
            return 0.0
        return sum(r.duration_s for r in self.case_results) / len(self.case_results)

    @property
    def avg_quality(self) -> float:
        scored = [r.quality_score for r in self.case_results if r.quality_score > 0]
        return sum(scored) / len(scored) if scored else 0.0

    @property
    def by_category(self) -> dict:
        """Group results by category."""
        # Note: CaseResult doesn't carry category; need to match by case_id
        # This is a placeholder that returns an empty dict since
        # we don't have the suite's cases directly
        return {}

    # ── Display ───────────────────────────────────────────────────────────────

    def summary(self) -> str:
        """Single-string summary suitable for CI output."""
        n      = len(self.case_results)
        passed = sum(r.overall_pass for r in self.case_results)
        lines  = [
            "Benchmark: {}".format(self.suite_name),
            "  Pass rate:    {}/{} ({:.0%})".format(passed, n, self.pass_rate),
            "  Avg cells:    {:.1f}".format(self.avg_cells),
            "  Avg duration: {:.1f}s".format(self.avg_duration_s),
        ]
        if self.avg_quality > 0:
            lines.append("  Avg quality:  {:.2f}/5.0".format(self.avg_quality))

        # Failures
        failures = [r for r in self.case_results if not r.overall_pass]
        if failures:
            lines.append("\n  Failed cases ({}):".format(len(failures)))
            for r in failures[:5]:
                reasons = []
                if not r.status_pass:    reasons.append("status={}".format(r.status))
                if not r.cells_pass:     reasons.append("cells={}".format(r.cells_executed))
                if not r.duration_pass:  reasons.append("time={:.1f}s".format(r.duration_s))
                if not r.content_pass:   reasons.append("content missing")
                lines.append("    {}: {}".format(r.case_id, ", ".join(reasons)))

        return "\n".join(lines)

    def table(self) -> str:
        """Tabular view of all case results."""
        header = (
            "{:<25} {:<10} {:>6} "
            "{:>8} {:>8} {:>5}"
        ).format("ID", "Status", "Cells", "Time(s)", "Quality", "Pass")
        sep    = "─" * len(header)
        rows   = [header, sep]

        for r in self.case_results:
            icon    = "✓" if r.overall_pass else "✗"
            quality = "{:.1f}".format(r.quality_score) if r.quality_score > 0 else "  -"
            rows.append(
                "{:<25} {:<10} {:>6} "
                "{:>8.1f} {:>8} {:>5}".format(
                    r.case_id, r.status, r.cells_executed,
                    r.duration_s, quality, icon
                )
            )

        rows.append(sep)
        rows.append(
            "{:<25} {:<10} {:>6.1f} "
            "{:>8.1f} {:>8.2f} "
            "{:>4.0%}".format(
                "TOTAL", "", self.avg_cells,
                self.avg_duration_s, self.avg_quality,
                self.pass_rate
            )
        )
        return "\n".join(rows)

    def compare_table(self) -> str:
        """
        Compare results across configurations.
        Only valid when all_config_results is populated.
        """
        if not self.all_config_results:
            return "No comparison data available."

        configs = list(self.all_config_results.keys())
        header  = "{:<25} ".format("Case") + " ".join("{:<12}".format(c) for c in configs)
        sep     = "─" * len(header)
        rows    = [header, sep]

        # Collect all case IDs
        all_ids = list(dict.fromkeys(
            r.case_id
            for results in self.all_config_results.values()
            for r in results
        ))

        for case_id in all_ids:
            row = "{:<25} ".format(case_id)
            for config in configs:
                r = next(
                    (r for r in self.all_config_results[config]
                     if r.case_id == case_id),
                    None
                )
                if r:
                    icon = "✓" if r.overall_pass else "✗"
                    row += "{} {:>3}c {:>5.1f}s  ".format(icon, r.cells_executed, r.duration_s)
                else:
                    row += "{:<12} ".format("N/A")
            rows.append(row)

        return "\n".join(rows)

    def save(self, path: str) -> None:
        """Save report as JSON."""
        data = {
            "suite_name":   self.suite_name,
            "config":       self.config,
            "pass_rate":    self.pass_rate,
            "avg_cells":    self.avg_cells,
            "avg_duration": self.avg_duration_s,
            "avg_quality":  self.avg_quality,
            "cases": [
                {
                    "id":             r.case_id,
                    "status":         r.status,
                    "cells":          r.cells_executed,
                    "duration_s":     r.duration_s,
                    "quality_score":  r.quality_score,
                    "overall_pass":   r.overall_pass,
                    "status_pass":    r.status_pass,
                    "cells_pass":     r.cells_pass,
                    "content_pass":   r.content_pass,
                }
                for r in self.case_results
            ]
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))

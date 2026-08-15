"""Session quality summary plugin."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from kerno.plugins.registry import BasePlugin


@dataclass
class QualityReport:
    cells: int = 0
    errors: int = 0
    recoveries: int = 0
    images: int = 0
    displays: int = 0
    total_duration: float = 0.0
    error_classes: Counter = field(default_factory=Counter)

    @property
    def success_rate(self) -> float:
        if self.cells == 0:
            return 1.0
        return 1 - (self.errors / self.cells)


class SessionQualityPlugin(BasePlugin):
    """Aggregate execution quality signals and print a final report."""

    name = "session_quality"

    def __init__(self):
        self.report = QualityReport()

    def on_session_start(self, task: str, session_id: str) -> None:
        self.report = QualityReport()

    def on_cell_complete(self, cell) -> None:
        output = cell.output
        self.report.cells += 1
        self.report.total_duration += float(getattr(output, "duration", 0.0) or 0.0)
        self.report.images += len(getattr(output, "images", []) or [])
        self.report.displays += len(getattr(output, "displays", []) or [])

    def on_error(self, cell, classified_error) -> None:
        # BaseLoop dispatches on_cell_complete before on_error; avoid double count.
        output = getattr(cell, "output", None)
        already_counted = bool(getattr(output, "has_error", False))
        if not already_counted:
            self.report.cells += 1
            self.report.total_duration += float(getattr(output, "duration", 0.0) or 0.0)
            self.report.images += len(getattr(output, "images", []) or [])
            self.report.displays += len(getattr(output, "displays", []) or [])
        self.report.errors += 1
        label = getattr(getattr(classified_error, "error_class", None), "name", "UNKNOWN")
        self.report.error_classes[label] += 1
        if self.report.cells >= 2 and self.report.errors == 1:
            self.report.recoveries += 1

    def on_session_complete(self, result) -> None:
        rpt = self.report
        top_errors = ", ".join(
            f"{name}={count}" for name, count in rpt.error_classes.most_common(3)
        ) or "none"
        print(
            "[quality] success={:.0%} cells={} errors={} recoveries={} "
            "images={} displays={} duration={:.2f}s top_errors=[{}]".format(
                rpt.success_rate, rpt.cells, rpt.errors, rpt.recoveries,
                rpt.images, rpt.displays, rpt.total_duration, top_errors,
            ),
            flush=True,
        )

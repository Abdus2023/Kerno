# kerno/dev/inspect.py
"""
SessionInspector: post-hoc analysis of a completed session.
"""

from __future__ import annotations

from kerno.types import SessionResult, Cell


class SessionInspector:
    """
    Inspect and analyze a completed SessionResult.

    Usage:
        result = Session()...run("analyze data.csv")
        inspector = SessionInspector(result)
        inspector.summary()
        inspector.cell_timeline()
        inspector.error_report()
        inspector.efficiency_report()
    """

    def __init__(self, result: SessionResult):
        self.result = result

    def summary(self) -> str:
        r = self.result
        return (
            "Session: {}...\n"
            "  Task:      {}\n"
            "  Status:    {}\n"
            "  Cells:     {}\n"
            "  Errors:    {} ({})\n"
            "  Duration:  {:.1f}s  "
            "({:.1f}s/cell avg)\n"
        ).format(
            r.session_id[:8],
            r.task[:60],
            r.status.name,
            r.cells_executed,
            r.error_count,
            "{} recovered".format(r.recovery_count),
            r.duration,
            r.duration / max(r.cells_executed, 1),
        )

    def cell_timeline(self) -> str:
        """Visual timeline of cells with timing and error markers."""
        lines = ["Cell timeline ({})".format(len(self.result.cells))]
        for cell in self.result.cells:
            icon    = "✗" if cell.output.has_error else "→"
            dur     = "{:.0f}ms".format(cell.output.duration * 1000)
            preview = cell.code[:40].replace("\n", " ")
            lines.append("  [{:3d}] {} {:>6}  {}".format(cell.cell_num, icon, dur, preview))
            if cell.output.has_error:
                lines.append(
                    "             ↳ {}: {}".format(
                        cell.output.error.ename,
                        cell.output.error.evalue[:40]
                    )
                )
        return "\n".join(lines)

    def error_report(self) -> str:
        """Detailed analysis of all errors."""
        from kerno.errors.classifier import ErrorClassifier
        clf    = ErrorClassifier()
        errors = [c for c in self.result.cells if c.output.has_error]

        if not errors:
            return "No errors in this session. ✓"

        lines = ["Error report ({})".format(len(errors))]
        for cell in errors:
            classified = clf.classify(cell.output.error)
            lines.append("\n  Cell {}: {}".format(cell.cell_num, classified.error_class.name))
            lines.append("    {}".format(classified.recovery_hint))
            lines.append("    Retryable: {}".format(classified.is_retryable))

        return "\n".join(lines)

    def efficiency_report(self) -> str:
        """Identify efficiency issues: slow cells, repeated errors, etc."""
        cells   = self.result.cells
        lines   = ["Efficiency report:"]

        if not cells:
            return "No cells to analyze."

        # Slow cells (> 10x average)
        durations = [c.output.duration for c in cells]
        avg_dur   = sum(durations) / len(durations) if durations else 0
        slow      = [c for c in cells if c.output.duration > avg_dur * 10 and
                     c.output.duration > 5.0]
        if slow:
            threshold = avg_dur * 10
            lines.append("\n  Slow cells (>{}s threshold):".format("{:.1f}".format(threshold)))
            for c in slow:
                lines.append("    Cell {}: {:.1f}s".format(c.cell_num, c.output.duration))

        # Repeated error patterns
        error_classes: list[str] = []
        for c in cells:
            if c.output.has_error:
                error_classes.append(c.output.error.ename)

        from collections import Counter
        repeated = {e: n for e, n in Counter(error_classes).items() if n > 1}
        if repeated:
            lines.append("\n  Repeated errors:")
            for ename, count in repeated.items():
                lines.append("    {}: {} times".format(ename, count))

        # Empty outputs (cells that produced nothing)
        empty = [c for c in cells if c.output.is_empty and not c.output.has_error]
        if empty:
            lines.append("\n  Cells with no output: {}".format(len(empty)))

        if len(lines) == 1:
            lines.append("  No efficiency issues detected. ✓")

        return "\n".join(lines)

    def find_cells(
        self,
        containing: str = None,
        with_error: bool = None,
        author: str = None,
    ) -> list[Cell]:
        """Search cells by content or attributes."""
        cells = self.result.cells
        if containing:
            cells = [c for c in cells if containing.lower() in c.code.lower()
                     or containing.lower() in c.output.stdout.lower()]
        if with_error is not None:
            cells = [c for c in cells if c.output.has_error == with_error]
        if author:
            cells = [c for c in cells if c.author == author]
        return cells

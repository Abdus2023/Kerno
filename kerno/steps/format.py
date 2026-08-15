# kerno/steps/format.py
"""
FormatOutputStep: CellOutput → str for LLM consumption.
Applies output formatters to control information density.
"""

from __future__ import annotations

from kerno.interfaces import AgentState, OutputFormatter


class FormatOutputStep:
    """
    Format the last cell's output for injection into LLM context.
    By default, uses CellOutput.as_text() — override with custom formatters.
    """

    def __init__(
        self,
        formatters: list[OutputFormatter] = None,
        max_chars:  int = 2000,
    ):
        self.formatters = formatters or []
        self.max_chars  = max_chars

    def run(self, state: AgentState) -> AgentState:
        if not state.history:
            return state

        last_cell = state.history[-1]
        text      = last_cell.output.as_text(max_chars=self.max_chars)

        for formatter in self.formatters:
            text = formatter.format(last_cell.output, text=text)

        state.metadata["last_output_formatted"] = text
        return state


# ── Built-in formatters ───────────────────────────────────────────────────────

class AnomalyFlagFormatter:
    """Prepends anomaly warnings to the formatted output."""

    ANOMALY_THRESHOLDS = {
        "null_rate":     0.20,   # > 20% nulls
        "skew":          3.0,    # |skew| > 3
        "outlier_rate":  0.05,   # > 5% outliers
    }

    def format(self, output, **kwargs) -> str:
        text   = kwargs.get("text", output.as_text())
        flags  = []

        # Check for known anomaly patterns in stdout
        stdout = output.stdout
        if "nan" in stdout.lower() or "null" in stdout.lower():
            flags.append("⚠️ Null/NaN values detected in output")
        if "inf" in stdout.lower():
            flags.append("⚠️ Infinite values detected")
        if "warning" in stdout.lower():
            flags.append("⚠️ Warnings in output — inspect carefully")

        if flags:
            header = "\n".join(flags)
            return "{}\n\n{}".format(header, text)
        return text


class DataShapeFormatter:
    """
    Extracts and highlights shape information from DataFrame outputs.
    Makes it easier for the LLM to track data dimensions.
    """

    def format(self, output, **kwargs) -> str:
        import re
        text = kwargs.get("text", output.as_text())

        # Find shape patterns like "(1234, 56)"
        shapes = re.findall(r'\((\d+),\s*(\d+)\)', text)
        if shapes:
            shape_str = ", ".join("{}×{}".format(r, c) for r, c in shapes[:3])
            return "[shapes: {}]\n{}".format(shape_str, text)

        return text

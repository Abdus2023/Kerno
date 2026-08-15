# kerno/steps/execute.py
"""
ExecuteStep: code → CellOutput.
The only step that touches the kernel.
"""

from __future__ import annotations

from kerno.errors.classifier import ErrorClassifier
from kerno.interfaces        import AgentState, Executor
from kerno.telemetry.tracer  import get_tracer
from kerno.types             import Cell


class ExecuteStep:
    """
    Executes the code in metadata["last_code"] in the kernel.
    Writes the resulting Cell to state.history.
    Writes error classification to metadata["recovery_hint"] if error.
    """

    def __init__(
        self,
        kernel:      Executor,
        timeout:     float = 120.0,
        classifier:  ErrorClassifier = None,
    ):
        self.kernel     = kernel
        self.timeout    = timeout
        self.classifier = classifier or ErrorClassifier()
        self._tracer    = get_tracer()

    def run(self, state: AgentState) -> AgentState:
        code = state.metadata.get("last_code", "")
        if not code:
            return state

        with self._tracer.span(
            "step.execute",
            {"code.preview": code[:60].replace("\n", " ")}
        ):
            output = self.kernel.execute(code, timeout=self.timeout)

        cell_num = len(state.history) + 1
        cell     = Cell(
            code     = code,
            output   = output,
            cell_num = cell_num,
            author   = "agent",
        )
        state.history.append(cell)
        state.namespace = self.kernel.namespace

        if output.has_error:
            classified                   = self.classifier.classify(output.error)
            state.metadata["recovery_hint"] = (
                "[{}] "
                "{}\n\n"
                "Suggested recovery:\n{}".format(
                    classified.error_class.name,
                    classified.recovery_hint,
                    classified.recovery_code
                )
            )
            state.metadata["consecutive_errors"] = (
                state.metadata.get("consecutive_errors", 0) + 1
            )
        else:
            state.metadata["consecutive_errors"] = 0

        return state


class DryRunExecuteStep:
    """
    Executes nothing. Prints the code and returns a fake success output.
    Useful for testing pipelines without a running kernel.
    """

    def run(self, state: AgentState) -> AgentState:
        code     = state.metadata.get("last_code", "")
        print("[dry-run] Would execute:\n{}".format(code[:200]))

        from kerno.types import Cell, CellOutput
        cell = Cell(
            code     = code,
            output   = CellOutput(stdout="[dry-run: not executed]\n"),
            cell_num = len(state.history) + 1,
            author   = "dry-run",
        )
        state.history.append(cell)
        return state

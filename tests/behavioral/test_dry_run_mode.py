"""
Behavioral tests for run(mode="dry_run") — audit #91: the session is
validated end-to-end WITHOUT ever starting a kernel.
"""

import pytest

from kerno import run
from kerno.security.allowlist import AllowList
from kerno.types import Message, SessionStatus


def make_llm(*responses):
    responses = list(responses)
    state = {"i": 0}

    def llm(messages: list[Message]) -> str:
        i = state["i"]
        state["i"] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: done"

    return llm


@pytest.mark.integration
class TestDryRunMode:

    def test_dry_run_completes_without_kernel(self):
        # The tell: this test is FAST — a real kernel takes ~2-4s to
        # start; dry run never starts one.
        result = run(
            "Compute values",
            llm=make_llm(
                "x = 21\nprint('x =', x)",
                "# TASK_COMPLETE: done",
            ),
            allowlist=AllowList.data_analysis(),
            mode="dry_run",
            max_cells=5,
        )

        assert result.status == SessionStatus.COMPLETE
        assert result.cells_executed == 2
        # Cells are validated, not executed
        assert "[dry_run]" in result.cells[0].output.stdout
        assert "would execute" in result.cells[0].output.stdout

    def test_dry_run_still_applies_allowlist(self):
        result = run(
            "Attempt",
            llm=make_llm("import subprocess", "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            mode="dry_run",
            max_cells=5,
        )
        # The violating cell is blocked even in dry run
        blocked = [
            c for c in result.cells
            if "subprocess" in c.code and c.output.has_error
        ]
        assert blocked
        assert blocked[0].output.error.ename == "AllowListViolation"

    def test_dry_run_never_starts_kernel(self, monkeypatch):
        """The strongest guarantee: KernelRuntime.start is never called."""
        started = []
        import kerno._run as run_module

        original_start = run_module.KernelRuntime.start
        def spy_start(self):
            started.append(self)
            return original_start(self)

        monkeypatch.setattr(run_module.KernelRuntime, "start", spy_start)

        run(
            "Compute",
            llm=make_llm("# TASK_COMPLETE: done"),
            mode="dry_run",
            max_cells=3,
        )
        assert started == [], "dry_run must never start a kernel"

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError, match="mode"):
            run(
                "Compute",
                llm=make_llm(),
                mode="simulate",   # not implemented at the facade
            )

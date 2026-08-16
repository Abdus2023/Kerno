"""
Behavioral tests for fork_session (audit #59/#60): branch an interrupted
session at a cell boundary and continue with a DIFFERENT LLM on a fresh
kernel — computational Git for agent state.
"""

import pytest

from kerno import fork_session, run
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
class TestForkSession:

    def test_fork_continues_from_cell_boundary_with_new_llm(self):
        # Original session: interrupted at MAX_CELLS after computing x
        def never_done(messages):
            return "x = 21\nprint('x =', x)"

        original = run(
            "Analyze values",
            llm=never_done,
            allowlist=AllowList.data_analysis(),
            max_cells=2,
        )
        assert original.status == SessionStatus.MAX_CELLS
        assert original.cells_executed == 2

        # Fork at cell 2 with a DIFFERENT LLM that completes the work
        forked = fork_session(
            original,
            make_llm(
                "y = x * 2\nprint('y =', y)",     # reads restored x
                "# TASK_COMPLETE: done",
            ),
            up_to_cell=2,
            allowlist=AllowList.data_analysis(),
            max_cells=5,
        )

        # The fork replayed the 2-cell prefix, then continued (the new
        # LLM's computation cell + its completion cell)
        assert len(forked.cells) == 4
        assert forked.cells[0].code == original.cells[0].code
        assert forked.cells[1].code == original.cells[1].code
        # The new LLM's continuation sees the restored state
        y_cell = forked.cells[2]
        assert "y = x * 2" in y_cell.code
        assert not y_cell.output.has_error
        assert "y = 42" in y_cell.output.stdout
        assert forked.status == SessionStatus.COMPLETE

    def test_fork_at_different_boundaries_branch_differently(self):
        def never_done(messages):
            return "x = 21\nprint('x =', x)"

        original = run(
            "Branch test",
            llm=never_done,
            allowlist=AllowList.data_analysis(),
            max_cells=2,
        )

        # Branch A: fork at cell 1, redefine x entirely
        branch_a = fork_session(
            original,
            make_llm(
                "x = 100\nprint('branch A x =', x)",
                "# TASK_COMPLETE: done",
            ),
            up_to_cell=1,
            allowlist=AllowList.data_analysis(),
            max_cells=3,
        )
        assert "branch A x = 100" in branch_a.cells[1].output.stdout

        # Branch B: fork at cell 2, keep the original x=21
        branch_b = fork_session(
            original,
            make_llm(
                "print('branch B x =', x)",
                "# TASK_COMPLETE: done",
            ),
            up_to_cell=2,
            allowlist=AllowList.data_analysis(),
            max_cells=3,
        )
        assert "branch B x = 21" in branch_b.cells[2].output.stdout

        # Same baseline, divergent outcomes — the branches differ
        assert branch_a.cells[1].output.stdout != branch_b.cells[2].output.stdout

    def test_fork_validates_cell_boundary(self):
        from kerno.types import SessionResult
        r = SessionResult(
            session_id="s", task="t", status=SessionStatus.INTERRUPTED,
            cells=[],  # empty
        )
        try:
            fork_session(r, make_llm(), up_to_cell=1)
            assert False, "expected ValueError"
        except ValueError:
            pass

        # up_to_cell beyond the recorded cells
        original = run(
            "t", llm=make_llm("# TASK_COMPLETE: done"),
            max_cells=2, load_default_skills=False,
        )
        try:
            fork_session(original, make_llm(), up_to_cell=99)
            assert False, "expected ValueError"
        except ValueError:
            pass

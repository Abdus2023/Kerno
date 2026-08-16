"""
End-to-end: a live session saved as a notebook can be resumed through
the same code path the `kerno resume` CLI command uses — on a real
kernel, with policy re-applied.
"""

import pytest

from kerno import run
from kerno.security.allowlist import AllowList
from kerno.session import resume_from_notebook
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
class TestCliResumePath:

    def test_save_then_resume_through_cli_path(self, tmp_path):
        # Session 1: compute x, save the notebook
        original = run(
            "Compute values",
            llm=make_llm(
                "x = 21\nprint('x =', x)",
                "# TASK_COMPLETE: done",
            ),
            allowlist=AllowList.data_analysis(),
            max_cells=3,
            save_notebook=True,
            notebook_dir=str(tmp_path / "sessions"),
            load_default_skills=False,
        )
        assert original.status == SessionStatus.COMPLETE

        nb_files = list((tmp_path / "sessions").glob("*.ipynb"))
        assert nb_files, "expected a saved notebook"

        # The `kerno resume` command calls resume_from_notebook with an
        # allowlist — exercise exactly that path.
        allowlist = AllowList.data_analysis()
        resumed = resume_from_notebook(
            str(nb_files[0]),
            make_llm(
                "y = x * 2\nprint('y =', y)",
                "# TASK_COMPLETE: done",
            ),
            allowlist=allowlist,
            max_cells=5,
        )

        assert resumed.status == SessionStatus.COMPLETE
        # Restored state x=21 visible to the continuation
        assert any(
            not c.output.has_error and "y = 42" in c.output.stdout
            for c in resumed.cells
        )
        # The resumed session's history includes the replayed prefix
        assert resumed.cells[0].code == original.cells[0].code

    def test_resume_cli_path_reapplies_policy(self, tmp_path):
        # A session that was interrupted by a policy block
        original = run(
            "Attempt",
            llm=make_llm("import subprocess", "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            max_cells=3,
            save_notebook=True,
            notebook_dir=str(tmp_path / "sessions"),
            load_default_skills=False,
        )
        assert any(
            c.output.has_error and c.output.error.ename == "AllowListViolation"
            for c in original.cells
        )

        nb_files = list((tmp_path / "sessions").glob("*.ipynb"))
        resumed = resume_from_notebook(
            str(nb_files[0]),
            make_llm("print('ok')", "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
        )
        # The violating cell is blocked AGAIN on resume
        assert any(
            "subprocess" in c.code
            and c.output.has_error
            and c.output.error.ename == "AllowListViolation"
            for c in resumed.cells
        )

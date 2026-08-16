"""
Behavioral tests for resume_from_notebook — notebook → session → resume
through the choke point (audit #56/#96).
"""

import nbformat
import pytest

from kerno import resume_from_notebook, run
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


def make_notebook(path, session_id="sess-nb", task="Analyze sales"):
    """A notebook with two recorded code cells."""
    nb = nbformat.v4.new_notebook()
    nb.metadata["kerno"] = {
        "session_id": session_id,
        "task":       task,
        "framework":  "kerno",
    }
    nb.cells.append(nbformat.v4.new_code_cell("x = 21"))
    nb.cells.append(nbformat.v4.new_code_cell("print('x =', x)"))
    nb.cells[1].outputs = [
        nbformat.v4.new_output("stream", name="stdout", text="x = 21\n"),
    ]
    nbformat.write(nb, path)
    return nb


@pytest.mark.integration
class TestResumeFromNotebook:

    def test_resume_continues_after_recorded_cells(self, tmp_path):
        nb_path = tmp_path / "prior.ipynb"
        make_notebook(nb_path)

        result = resume_from_notebook(
            nb_path,
            make_llm(
                "y = x * 2\nprint('y =', y)",     # reads restored x=21
                "# TASK_COMPLETE: done",
            ),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
        )

        # The 2 recorded cells were replayed (state restored), then the
        # LLM's continuation cell + completion cell
        assert len(result.cells) == 4
        assert result.cells[0].code == "x = 21"
        assert result.cells[1].code == "print('x =', x)"
        # Restored state is visible to the continuation
        y_cell = result.cells[2]
        assert not y_cell.output.has_error
        assert "y = 42" in y_cell.output.stdout
        assert result.status == SessionStatus.COMPLETE

    def test_policy_reapplied_during_resume(self, tmp_path):
        # A notebook containing a violating cell
        nb_path = tmp_path / "bad.ipynb"
        nb = nbformat.v4.new_notebook()
        nb.metadata["kerno"] = {"session_id": "s", "task": "t"}
        nb.cells.append(nbformat.v4.new_code_cell("import subprocess"))
        nbformat.write(nb, nb_path)

        result = resume_from_notebook(
            nb_path,
            make_llm("print('ok')", "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
        )

        # The violating cell was blocked AGAIN during restore
        blocked = [
            c for c in result.cells
            if "subprocess" in c.code and c.output.has_error
        ]
        assert blocked
        assert blocked[0].output.error.ename == "AllowListViolation"

    def test_missing_notebook_raises(self, tmp_path):
        try:
            resume_from_notebook(str(tmp_path / "ghost.ipynb"), make_llm())
            assert False, "expected FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_end_to_end_save_then_resume(self, tmp_path):
        """Full loop: live run → notebook → resume → continue."""
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

        resumed = resume_from_notebook(
            str(nb_files[0]),
            make_llm(
                "y = x * 2\nprint('y =', y)",
                "# TASK_COMPLETE: done",
            ),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
        )
        assert resumed.status == SessionStatus.COMPLETE
        # The resumed continuation reads the state the original computed
        assert any(
            not c.output.has_error and "y = 42" in c.output.stdout
            for c in resumed.cells
        )

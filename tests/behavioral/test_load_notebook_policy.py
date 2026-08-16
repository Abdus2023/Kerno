"""
K-001 completeness: load_notebook's re-execution goes through the
choke point when an engine is provided — recorded LLM cells are
subject to policy; raw re-execution is an explicit opt-in.
"""

import nbformat
import pytest

from kerno.execution.engine import ExecutionEngine
from kerno.kernel.runtime import KernelRuntime
from kerno.notebook.continuation import load_notebook
from kerno.security.allowlist import AllowList


def make_notebook(path, cells=("x = 21", "import subprocess")):
    nb = nbformat.v4.new_notebook()
    nb.metadata["kerno"] = {"session_id": "s", "task": "t"}
    for code in cells:
        nb.cells.append(nbformat.v4.new_code_cell(code))
    nbformat.write(nb, path)


@pytest.mark.integration
class TestLoadNotebookPolicy:

    def test_engine_path_blocks_violating_cells(self, tmp_path):
        nb_path = tmp_path / "prior.ipynb"
        make_notebook(nb_path)

        kernel = KernelRuntime()
        kernel.start()
        try:
            engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
            cells, _ = load_notebook(
                str(nb_path), kernel, re_execute=True, engine=engine,
            )

            # The violating cell was re-executed through the engine and
            # blocked by policy
            blocked = [c for c in cells if "subprocess" in c.code]
            assert blocked
            assert blocked[0].output.has_error
            assert blocked[0].output.error.ename == "AllowListViolation"
        finally:
            kernel.shutdown()

    def test_raw_path_executes_without_policy(self, tmp_path):
        """Documented opt-in: without an engine, raw re-execution runs."""
        nb_path = tmp_path / "prior.ipynb"
        make_notebook(nb_path, cells=("import subprocess",))

        kernel = KernelRuntime()
        kernel.start()
        try:
            cells, _ = load_notebook(
                str(nb_path), kernel, re_execute=True,
            )
            executed = [c for c in cells if "subprocess" in c.code]
            assert executed
            assert not executed[0].output.has_error  # raw path ran it
        finally:
            kernel.shutdown()

    def test_no_reexecute_loads_history_only(self, tmp_path):
        nb_path = tmp_path / "prior.ipynb"
        make_notebook(nb_path)

        kernel = KernelRuntime()
        kernel.start()
        try:
            cells, _ = load_notebook(
                str(nb_path), kernel, re_execute=False,
            )
            assert len(cells) == 2
            # No kernel execution happened at all
            assert kernel.cells_executed == 0
        finally:
            kernel.shutdown()

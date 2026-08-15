# tests/behavioral/test_runtime.py
"""
Behavioral tests for KernelRuntime.
These tests require a running Python kernel — they use real kernel processes.
Marked with @pytest.mark.integration for optional exclusion.
"""

import pytest
from kerno.kernel.runtime import KernelRuntime


@pytest.fixture
def kernel():
    """A fresh kernel for each test prevents state/IPython magic from leaking."""
    with KernelRuntime() as k:
        yield k


@pytest.mark.integration
class TestKernelRuntime:

    def test_starts_and_is_alive(self, kernel):
        assert kernel.is_alive

    def test_execute_returns_stdout(self, kernel):
        output = kernel.execute("print('hello kerno')")
        assert "hello kerno" in output.stdout
        assert not output.has_error

    def test_execute_captures_error(self, kernel):
        output = kernel.execute("raise ValueError('test error')")
        assert output.has_error
        assert output.error.ename == "ValueError"
        assert "test error" in output.error.evalue

    def test_state_persists_between_cells(self, kernel):
        kernel.execute("x_persist_test = 42")
        output = kernel.execute("print(x_persist_test)")
        assert "42" in output.stdout

    def test_error_does_not_corrupt_state(self, kernel):
        kernel.execute("safe_var = 'still here'")
        kernel.execute("raise RuntimeError('kaboom')")   # Error
        output = kernel.execute("print(safe_var)")        # State survives
        assert "still here" in output.stdout
        assert not output.has_error

    def test_namespace_snapshot_reflects_state(self, kernel):
        import json
        kernel.execute("snap_test_df = __import__('pandas').DataFrame({'a': [1,2,3]})")
        snapshot = json.loads(kernel.namespace)
        assert "snap_test_df" in snapshot
        assert "DataFrame" in snapshot["snap_test_df"]

    def test_namespace_snapshot_is_json(self, kernel):
        import json
        snap = kernel.namespace
        parsed = json.loads(snap)  # Should not raise
        assert isinstance(parsed, dict)

    def test_execute_silent_no_side_effects(self, kernel):
        # Silent execution should not appear in cell history
        before_count = kernel.cells_executed
        kernel.execute_silent("x = 1 + 1")
        after_count = kernel.cells_executed
        assert after_count == before_count

    def test_timeout_raises_gracefully(self, kernel):
        output = kernel.execute("import time; time.sleep(100)", timeout=1.0)
        assert output.has_error
        assert "Timeout" in output.error.ename

    def test_rich_output_captured(self, kernel):
        kernel.execute("import pandas as pd")
        output = kernel.execute(
            "pd.DataFrame({'a': [1,2], 'b': [3,4]})"
        )
        assert output.displays or output.result  # DataFrame renders to HTML or repr

    def test_image_output_captured(self, kernel):
        setup = (
            "%matplotlib inline\n"
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1,2,3])\n"
            "plt.show()"
        )
        output = kernel.execute(setup)
        assert len(output.images) > 0

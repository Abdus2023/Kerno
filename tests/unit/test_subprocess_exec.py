"""
Unit tests for SubprocessExecutor (audit #97): process-level isolation
with clean namespaces and hard timeouts.
"""

import time

from kerno.subprocess_exec import SubprocessExecutor


class TestSubprocessExecutor:

    def test_executes_code(self):
        ex = SubprocessExecutor()
        out = ex.execute("print(1 + 1)")
        assert not out.has_error
        assert out.stdout.strip() == "2"

    def test_clean_namespace_per_execution(self):
        ex = SubprocessExecutor()
        ex.execute("x = 42")
        out = ex.execute("print(x)")
        assert out.has_error          # fresh process → no leaked state
        assert "NameError" in out.error.evalue

    def test_error_surfaces_stderr(self):
        ex = SubprocessExecutor()
        out = ex.execute("raise ValueError('boom')")
        assert out.has_error
        assert out.error.ename == "SubprocessExecutionError"
        assert "ValueError" in out.error.evalue

    def test_timeout_kills_hung_code(self):
        ex = SubprocessExecutor(timeout=1)
        start = time.monotonic()
        out = ex.execute("import time\nwhile True: time.sleep(1)")
        elapsed = time.monotonic() - start
        assert out.has_error
        assert out.error.ename == "TimeoutError"
        assert elapsed < 15           # hard kill, not a long hang

    def test_memory_limit_applied(self):
        ex = SubprocessExecutor(memory_limit_mb=64)
        out = ex.execute("x = [0] * 10_000_000")   # ~80 MB → should fail
        assert out.has_error

    def test_executor_protocol(self):
        ex = SubprocessExecutor()
        assert ex.is_alive is True
        assert ex.namespace == "{}"
        assert ex.execute_silent("print('silent')") == "silent"

    def test_stdout_captured(self):
        ex = SubprocessExecutor()
        out = ex.execute("print('line1')\nprint('line2')")
        assert out.stdout == "line1\nline2\n"

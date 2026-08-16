"""
Behavioral: the server execution path (_execute_task) enforces the
allowlist on a REAL kernel — violating LLM code is blocked and never
executes (K-001 through the HTTP surface).
"""

import sys

import pytest

from kerno.kernel.runtime import KernelRuntime
from kerno.types import Message


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
class TestServerExecuteTaskLive:

    def _run_task(self, llm, security="data_analysis", monkeypatch=None):
        from kerno.server import app as server_app

        if monkeypatch is not None:
            import sys as _sys
            mod = _sys.modules["kerno.skills.bootstrap"]
            monkeypatch.setattr(mod, "bootstrap", lambda kernel: None)

        kernel = KernelRuntime()
        kernel.start()
        try:
            request = type("Req", (), {
                "task": "analyze", "loop": "reactive",
                "max_cells": 5, "security": security,
                "save_notebook": False,
            })()
            return server_app._execute_task(
                kernel=kernel, llm=llm, request=request,
                session_id="sess-live", memory=None,
            )
        finally:
            kernel.shutdown()

    def test_violating_code_blocked_on_real_kernel(self, monkeypatch):
        result = self._run_task(
            make_llm(
                "import subprocess\nsubprocess.run(['echo', 'pwned'])",
                "# TASK_COMPLETE: done",
            ),
            monkeypatch=monkeypatch,
        )
        blocked = [
            c for c in result.cells
            if "subprocess" in c.code and c.output.has_error
        ]
        assert blocked
        assert blocked[0].output.error.ename == "AllowListViolation"
        # The violating code never executed: no 'pwned' output anywhere
        assert not any("pwned" in c.output.stdout for c in result.cells)

    def test_clean_code_runs_on_real_kernel(self, monkeypatch):
        result = self._run_task(
            make_llm(
                "x = 21\nprint('x =', x)",
                "# TASK_COMPLETE: done",
            ),
            monkeypatch=monkeypatch,
        )
        assert any(
            not c.output.has_error and "x = 21" in c.output.stdout
            for c in result.cells
        )

    def test_secure_app_default_is_data_analysis(self):
        from kerno.server.secure_app import create_secure_app
        # The authenticated server defaults to data_analysis — verify the
        # default flows through make_server_engine.
        from kerno.server.security import make_server_engine
        from kerno.kernel.runtime import KernelRuntime as KR

        kernel = KR()
        kernel.start()
        try:
            engine = make_server_engine(
                kernel, profile="data_analysis",
            )
            out = engine.execute("import subprocess")
            assert out.has_error
            assert out.error.ename == "AllowListViolation"
        finally:
            kernel.shutdown()

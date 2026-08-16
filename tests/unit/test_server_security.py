"""
Unit tests for server-side execution security — the HTTP/OpenAI surfaces
must go through the choke point (K-001), never raw kernel code.
"""

import pytest

from kerno.execution.budget import ExecutionBudget
from kerno.server.security import make_server_engine
from kerno.security.allowlist import AllowList
from kerno.security.capabilities import CapabilityBroker
from kerno.types import CellOutput, Message


class FakeKernel:
    def __init__(self):
        self.calls = []

    def execute(self, code, timeout=120.0, silent=False, **kwargs):
        self.calls.append(code)
        return CellOutput(stdout="ok")

    def execute_silent(self, code, timeout=15.0, **kwargs):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


class TestMakeServerEngine:

    def test_profile_applies_allowlist(self):
        engine = make_server_engine(FakeKernel(), profile="data_analysis")
        out = engine.execute("import subprocess\nsubprocess.run(['x'])")
        assert out.has_error
        assert out.error.ename == "AllowListViolation"

    def test_none_profile_opts_out(self):
        engine = make_server_engine(FakeKernel(), profile="none")
        out = engine.execute("import subprocess\nsubprocess.run(['x'])")
        assert not out.has_error        # no policy — explicit opt-out

    def test_read_only_profile(self):
        engine = make_server_engine(FakeKernel(), profile="read_only")
        out = engine.execute("open('/etc/passwd')")
        assert out.has_error
        assert out.error.ename == "AllowListViolation"

    def test_broker_enforces_default_capability(self):
        broker = CapabilityBroker()     # no grants
        engine = make_server_engine(
            FakeKernel(), profile="none", capability_broker=broker,
        )
        out = engine.execute("x = 1")
        assert out.has_error
        assert out.error.ename == "CapabilityViolation"

    def test_budget_wraps(self):
        engine = make_server_engine(
            FakeKernel(), profile="none",
            budget=ExecutionBudget(max_executions=1),
        )
        assert not engine.execute("x = 1").has_error
        out = engine.execute("y = 2")
        assert out.has_error
        assert out.error.ename == "BudgetExceeded"

    def test_unknown_profile_falls_back_to_permissive(self):
        engine = make_server_engine(FakeKernel(), profile="banana")
        out = engine.execute("eval('1+1')")
        assert out.has_error


class TestExecuteTaskChokePoint:
    """_execute_task (the /run endpoint) must block violating code."""

    def _call(self, llm, security="data_analysis", monkeypatch=None):
        from kerno.server import app as server_app

        if monkeypatch is not None:
            # The package re-exports the function, shadowing the submodule
            # attribute — patch through sys.modules directly.
            import sys
            mod = sys.modules["kerno.skills.bootstrap"]
            monkeypatch.setattr(mod, "bootstrap", lambda kernel: None)

        kernel = FakeKernel()
        request = type("Req", (), {
            "task": "analyze", "loop": "reactive",
            "max_cells": 5, "security": security, "save_notebook": False,
        })()
        return server_app._execute_task(
            kernel=kernel, llm=llm, request=request,
            session_id="sess-1", memory=None,
        ), kernel

    def _llm(self, *responses):
        responses = list(responses)
        state = {"i": 0}
        def llm(messages: list[Message]) -> str:
            i = state["i"]
            state["i"] += 1
            if i < len(responses):
                return responses[i]
            return "# TASK_COMPLETE: done"
        return llm

    def test_violating_code_blocked(self, monkeypatch):
        result, kernel = self._call(
            self._llm("import subprocess\nsubprocess.run(['rm', '-rf', '/'])"),
            monkeypatch=monkeypatch,
        )
        blocked = [
            c for c in result.cells
            if "subprocess" in c.code and c.output.has_error
        ]
        assert blocked, "the server path must block violating code"
        assert blocked[0].output.error.ename == "AllowListViolation"
        # The violating code never reached the kernel
        assert not any("subprocess" in c for c in kernel.calls)

    def test_clean_code_runs(self, monkeypatch):
        result, kernel = self._call(
            self._llm("x = 21\nprint('x =', x)"),
            monkeypatch=monkeypatch,
        )
        assert result.cells
        assert any(
            not c.output.has_error for c in result.cells
        )

    def test_none_security_allows(self, monkeypatch):
        result, kernel = self._call(
            self._llm("import subprocess\nsubprocess.run(['echo', 'hi'])"),
            security="none",
            monkeypatch=monkeypatch,
        )
        # With profile="none" the code executes
        assert any(
            not c.output.has_error and "subprocess" in c.code
            for c in result.cells
        )


class TestPerRequestBudget:
    """RunRequest.budget_cells caps the session (audit #85)."""

    def _call(self, llm, budget_cells=None, security="none", monkeypatch=None):
        from kerno.server import app as server_app
        if monkeypatch is not None:
            import sys
            mod = sys.modules["kerno.skills.bootstrap"]
            monkeypatch.setattr(mod, "bootstrap", lambda kernel: None)

        kernel = FakeKernel()
        request = type("Req", (), {
            "task": "analyze", "loop": "reactive",
            "max_cells": 10, "security": security,
            "save_notebook": False, "budget_cells": budget_cells,
        })()
        return server_app._execute_task(
            kernel=kernel, llm=llm, request=request,
            session_id="sess-1", memory=None,
        )

    def _never_done_llm(self):
        from kerno.types import Message
        def llm(messages):
            return "x = 1"
        return llm

    def test_budget_cells_caps_session(self, monkeypatch):
        result = self._call(
            self._never_done_llm(), budget_cells=2, monkeypatch=monkeypatch,
        )
        succeeded = sum(
            1 for c in result.cells if not c.output.has_error
        )
        assert succeeded == 2, "per-request budget must cap cells at 2"
        assert any(
            c.output.has_error and c.output.error.ename == "BudgetExceeded"
            for c in result.cells
        )


class TestAPIKeyStoreHardening:
    """Hardened PBKDF2 API key store with constant-time matching (Phase D)."""

    def test_key_validation_success_and_failure(self):
        from kerno.server.auth import APIKeyStore

        store = APIKeyStore(iterations=1000)
        store.add_key("test-token-xyz", "user-42", "prod-key", rate_limit=250)

        # Valid key resolves
        info = store.validate("test-token-xyz")
        assert info is not None
        assert info["user_id"] == "user-42"
        assert info["rate_limit"] == 250

        # Invalid key rejected
        assert store.validate("test-token-wrong") is None
        assert store.validate("") is None

    def test_keys_stored_with_unique_salts(self):
        from kerno.server.auth import APIKeyStore

        store = APIKeyStore(iterations=1000)
        store.add_key("same-secret", "user-1")
        store.add_key("same-secret", "user-2")

        # Two identical keys should have different derived hashes due to unique salts
        entries = list(store._keys.values())
        assert len(entries) == 2
        assert entries[0]["salt_hex"] != entries[1]["salt_hex"]


    @pytest.mark.asyncio
    async def test_auth_fails_closed_when_auth_enabled_and_no_keys(self, monkeypatch):
        import os
        from kerno.server.auth import verify_api_key

        # Simulate production / auth_enabled with no keys set
        monkeypatch.setenv("KERNO_ENABLE_AUTH", "true")
        monkeypatch.delenv("KERNO_API_KEYS", raising=False)

        try:
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(None)
            assert exc_info.value.status_code == 401
            assert "fail closed" in exc_info.value.detail
        except ImportError:
            pass

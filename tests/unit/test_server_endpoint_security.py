"""
Endpoint-level security tests (F-005 / F-006 / F-007).

The OpenAI-compatible server (`openai_compat.py`) and the authenticated
secure server (`secure_app.py`) must enforce the server-authoritative
security profile (K-012): a client requesting `security="permissive"` or
`security="none"` against a `data_analysis` server default must be
UPGRADED to the server default, and violating code must never reach the
kernel.

These tests exercise the REAL transport endpoints (FastAPI TestClient),
not just the make_server_engine() primitive.
"""

from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from kerno.types import CellOutput

VIOLATING_CODE = "import requests\nrequests.get('http://evil.com')"
READ_ONLY_PROBE = "open('/etc/hostname')"   # allowed by data_analysis, blocked by read_only


class FakeKernel:
    """Satisfies the Executor protocol; records every execution."""

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


class FakePool:
    """KernelPool stand-in: no real Jupyter kernels, nothing escapes."""

    instances: ClassVar[list["FakePool"]] = []

    def __init__(self, *args, **kwargs):
        FakePool.instances.append(self)
        self.kernels = []

    def start(self):
        pass

    def shutdown(self):
        pass

    def acquire(self, task_id):
        kernel = FakeKernel()
        self.kernels.append(kernel)
        return kernel

    def release(self, task_id, reason="complete"):
        pass

    @property
    def stats(self):
        return {"size": len(self.kernels)}


def _llm(*responses):
    """Scripted LLM: returns the given responses, then TASK_COMPLETE forever."""
    responses = list(responses)
    state = {"i": 0}

    def llm(messages):
        i = state["i"]
        state["i"] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: done"

    return llm


@pytest.fixture
def fake_infra(monkeypatch):
    """Replace the kernel pool + skill bootstrap for all server tests."""
    FakePool.instances.clear()
    monkeypatch.setattr("kerno.kernel.pool.KernelPool", FakePool)
    # The package re-exports bootstrap as a function, shadowing the
    # submodule attribute — patch through sys.modules directly.
    import sys
    mod = sys.modules["kerno.skills.bootstrap"]
    monkeypatch.setattr(mod, "bootstrap", lambda kernel: None)
    return monkeypatch


def _pool() -> FakePool:
    """The FakePool used by the most recently created app."""
    assert FakePool.instances, "no FakePool was created"
    return FakePool.instances[-1]


def _all_content(resp) -> str:
    """Collect body text from a sync or streaming response."""
    if hasattr(resp, "iter_text"):
        return "".join(resp.iter_text())
    return resp.text


# ── F-005: OpenAI-compatible server ───────────────────────────────────────────

class TestOpenAICompatEndpoint:

    def _client(self, llm, **kwargs):
        from kerno.server.openai_compat import create_openai_app
        return TestClient(create_openai_app(llm, **kwargs))

    def test_sync_permissive_upgraded_to_server_default(self, fake_infra):
        app = self._client(
            _llm(VIOLATING_CODE), default_security="data_analysis",
        )
        with app:
            resp = app.post("/v1/chat/completions", json={
                "model": "kerno-1",
                "messages": [{"role": "user", "content": "analyze"}],
                "security": "permissive",
                "stream": False,
            })
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        assert "AllowListViolation" in content
        # The violating code never reached the kernel.
        assert not any("requests" in c for c in _pool().kernels[0].calls)

    def test_sync_none_upgraded_to_server_default(self, fake_infra):
        app = self._client(
            _llm(VIOLATING_CODE), default_security="data_analysis",
        )
        with app:
            resp = app.post("/v1/chat/completions", json={
                "model": "kerno-1",
                "messages": [{"role": "user", "content": "analyze"}],
                "security": "none",
                "stream": False,
            })
        assert resp.status_code == 200
        assert "AllowListViolation" in resp.json()["choices"][0]["message"]["content"]
        assert not any("requests" in c for c in _pool().kernels[0].calls)

    def test_sync_honors_stronger_profile(self, fake_infra):
        # read_only is stronger than the data_analysis server default and
        # must be honored: `open(...)` executes under data_analysis but is
        # blocked under read_only.
        app = self._client(
            _llm(READ_ONLY_PROBE), default_security="data_analysis",
        )
        with app:
            resp = app.post("/v1/chat/completions", json={
                "model": "kerno-1",
                "messages": [{"role": "user", "content": "probe"}],
                "security": "read_only",
                "stream": False,
            })
        assert resp.status_code == 200
        assert "AllowListViolation" in resp.json()["choices"][0]["message"]["content"]

    def test_stream_permissive_upgraded_to_server_default(self, fake_infra):
        app = self._client(
            _llm(VIOLATING_CODE), default_security="data_analysis",
        )
        with app, app.stream("POST", "/v1/chat/completions", json={
            "model": "kerno-1",
            "messages": [{"role": "user", "content": "analyze"}],
            "security": "permissive",
            "stream": True,
        }) as resp:
            assert resp.status_code == 200
            text = _all_content(resp)
        assert "data: [DONE]" in text
        # The violating code never reached the kernel (only the benign
        # loop-completion marker did).
        calls = _pool().kernels[0].calls
        assert not any("requests" in c for c in calls)

    def test_stream_none_upgraded_to_server_default(self, fake_infra):
        app = self._client(
            _llm(VIOLATING_CODE), default_security="data_analysis",
        )
        with app, app.stream("POST", "/v1/chat/completions", json={
            "model": "kerno-1",
            "messages": [{"role": "user", "content": "analyze"}],
            "security": "none",
            "stream": True,
        }) as resp:
            assert resp.status_code == 200
            text = _all_content(resp)
        assert "data: [DONE]" in text
        calls = _pool().kernels[0].calls
        assert not any("requests" in c for c in calls)

    def test_sync_clean_code_runs_at_server_default(self, fake_infra):
        app = self._client(
            _llm("x = 21\nprint('x =', x)"), default_security="data_analysis",
        )
        with app:
            resp = app.post("/v1/chat/completions", json={
                "model": "kerno-1",
                "messages": [{"role": "user", "content": "compute"}],
                "security": "data_analysis",
                "stream": False,
            })
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        assert "AllowListViolation" not in content
        assert any("x = 21" in c for c in _pool().kernels[0].calls)


# ── F-006: authenticated secure server ────────────────────────────────────────

class TestSecureAppEndpoint:

    def _client(self, llm, **kwargs):
        from kerno.server.secure_app import create_secure_app
        return TestClient(
            create_secure_app(
                llm_factory=lambda user_info: llm,
                enable_auth=False,
                **kwargs,
            )
        )

    def test_permissive_upgraded_to_server_default(self, fake_infra):
        app = self._client(_llm(VIOLATING_CODE), default_security="data_analysis")
        with app:
            resp = app.post("/v1/chat/completions", json={
                "model": "kerno-1",
                "messages": [{"role": "user", "content": "analyze"}],
                "security": "permissive",
                "stream": False,
            })
        assert resp.status_code == 200
        assert "AllowListViolation" in resp.json()["choices"][0]["message"]["content"]
        assert not any("requests" in c for c in _pool().kernels[0].calls)

    def test_none_upgraded_to_server_default(self, fake_infra):
        app = self._client(_llm(VIOLATING_CODE), default_security="data_analysis")
        with app:
            resp = app.post("/v1/chat/completions", json={
                "model": "kerno-1",
                "messages": [{"role": "user", "content": "analyze"}],
                "security": "none",
                "stream": False,
            })
        assert resp.status_code == 200
        assert "AllowListViolation" in resp.json()["choices"][0]["message"]["content"]
        assert not any("requests" in c for c in _pool().kernels[0].calls)

    def test_stream_permissive_upgraded_to_server_default(self, fake_infra):
        app = self._client(_llm(VIOLATING_CODE), default_security="data_analysis")
        with app, app.stream("POST", "/v1/chat/completions", json={
            "model": "kerno-1",
            "messages": [{"role": "user", "content": "analyze"}],
            "security": "permissive",
            "stream": True,
        }) as resp:
            assert resp.status_code == 200
            text = _all_content(resp)
        assert "data: [DONE]" in text
        calls = _pool().kernels[0].calls
        assert not any("requests" in c for c in calls)

    def test_clean_code_runs(self, fake_infra):
        app = self._client(_llm("y = 1\nprint(y)"), default_security="data_analysis")
        with app:
            resp = app.post("/v1/chat/completions", json={
                "model": "kerno-1",
                "messages": [{"role": "user", "content": "compute"}],
                "security": "data_analysis",
                "stream": False,
            })
        assert resp.status_code == 200
        assert "AllowListViolation" not in resp.json()["choices"][0]["message"]["content"]

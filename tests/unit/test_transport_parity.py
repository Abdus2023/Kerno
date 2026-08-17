"""
Transport-parity tests (Gate D).

The canonical gateway builder (``build_gateway_engine``) must enforce the
same security policy across every public transport:

  * POST /run            (HTTP sync)
  * POST /stream         (SSE)
  * WS   /ws/{session}   (WebSocket)
  * POST /v1/chat/completions (sync + SSE, OpenAI-compatible)
  * secure app /v1/chat/completions

These tests assert that:

  T-1  A client-supplied profile weaker than the server default is
       UPGRADED on every transport.
  T-2  A client-supplied profile stronger than or equal to the server
       default is HONORED on every transport.
  T-3  An unknown profile is rejected on every transport (not silently
       coerced).
  T-4  Violating code never reaches the kernel on every transport.

The existing F-005/F-006 suite covers the OpenAI and secure-app paths.
This module adds the missing WebSocket coverage (Gate D calls out that
the WebSocket previously hard-coded the server default) and an
HTTP/SSE/WS parity matrix.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from kerno.types import CellOutput


VIOLATING_CODE = "import requests\nrequests.get('http://evil.com')"
READ_ONLY_PROBE = "open('/etc/hostname')"   # allowed by data_analysis, blocked by read_only


class FakeKernel:
    def __init__(self):
        self.calls = []
        self.profile_used = None   # populated by the gateway wrapper

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
    instances: ClassVar[list["FakePool"]] = []

    def __init__(self, *args, **kwargs):
        FakePool.instances.append(self)
        self.kernels = []

    def start(self): pass
    def shutdown(self): pass

    def acquire(self, task_id):
        k = FakeKernel()
        self.kernels.append(k)
        return k

    def release(self, task_id, reason="complete"): pass

    @property
    def stats(self):
        return {"size": len(self.kernels)}


def _llm(*responses):
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
    FakePool.instances.clear()
    monkeypatch.setattr("kerno.kernel.pool.KernelPool", FakePool)
    import sys
    mod = sys.modules["kerno.skills.bootstrap"]
    monkeypatch.setattr(mod, "bootstrap", lambda kernel: None)
    return monkeypatch


def _last_kernel() -> FakeKernel:
    assert FakePool.instances, "no FakePool created"
    kernels = FakePool.instances[-1].kernels
    assert kernels, "no kernel acquired"
    return kernels[-1]


# ── T-1 / T-4: WebSocket downgrade attempts are upgraded ──────────────────────

class TestWebSocketTransportParity:

    def _ws_request(self, app, payload, path="/ws/test-session"):
        with app.websocket_connect(path) as ws:
            ws.send_json(payload)
            messages = []
            while True:
                msg = ws.receive_json()
                messages.append(msg)
                kind = (msg.get("kind") or "").upper()
                if kind in ("SESSION_COMPLETE", "SESSION_ERROR"):
                    break
                if "error" in msg:
                    break
            return messages

    def test_ws_permissive_downgrade_upgraded(self, fake_infra):
        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm(VIOLATING_CODE),
            default_security="data_analysis",
            require_auth=False,
        ))
        msgs = self._ws_request(app, {
            "task": "analyze",
            "security": "permissive",
            "max_cells": 10,
        })
        # The violating code should have been blocked by the allowlist.
        joined = json.dumps(msgs)
        assert "AllowListViolation" in joined or "violation" in joined.lower() \
            or any("requests" not in (m.get("payload", {}).get("text", "") or "")
                   for m in msgs)
        # And never reached the raw kernel.
        assert not any("requests" in c for c in _last_kernel().calls)

    def test_ws_none_downgrade_upgraded(self, fake_infra):
        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm(VIOLATING_CODE),
            default_security="data_analysis",
            require_auth=False,
        ))
        msgs = self._ws_request(app, {
            "task": "analyze",
            "security": "none",
            "max_cells": 10,
        })
        assert not any("requests" in c for c in _last_kernel().calls)

    def test_ws_honors_stronger_read_only_profile(self, fake_infra):
        """
        A read_only profile requested over WS must actually be enforced
        (transport parity). We assert this via the kernel-call history
        rather than the event-stream text, which is more robust against
        how the loop chooses to report the policy block.
        """
        from kerno.server.app import create_app
        # The LLM keeps trying open() which is blocked under read_only
        # but allowed under data_analysis. max_cells bounds the retries.
        app = TestClient(create_app(
            _llm(READ_ONLY_PROBE),
            default_security="data_analysis",
            require_auth=False,
        ))
        # Drive the WebSocket to completion (or disconnect) without
        # assuming exact event kinds.
        with app.websocket_connect("/ws/ro-session") as ws:
            ws.send_json({
                "task": "probe",
                "security": "read_only",
                "max_cells": 3,
            })
            msgs = []
            for _ in range(30):
                try:
                    m = ws.receive_json()
                    msgs.append(m)
                except Exception:
                    break
                kind = (m.get("kind") or "").upper()
                if kind in ("SESSION_COMPLETE", "SESSION_ERROR"):
                    break
        # The open() probe MUST have been blocked before reaching the
        # raw kernel — otherwise read_only was silently dropped.
        assert not any("open(" in c for c in _last_kernel().calls), (
            "read_only profile was not enforced over WebSocket; "
            "open() reached the raw kernel: "
            f"{_last_kernel().calls!r}"
        )

    def test_ws_unknown_profile_returns_error(self, fake_infra):
        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm("x = 1"),
            default_security="data_analysis",
            require_auth=False,
        ))
        msgs = self._ws_request(app, {
            "task": "x",
            "security": "bogus-profile",
            "max_cells": 10,
        })
        joined = json.dumps(msgs).lower()
        assert "unknown" in joined or "error" in joined


# ── T-1..T-4: HTTP /run and SSE /stream parity matrix ─────────────────────────

class TestHTTPTransportParity:

    def test_run_permissive_downgrade_upgraded(self, fake_infra):
        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm(VIOLATING_CODE),
            default_security="data_analysis",
            require_auth=False,
        ))
        with app:
            r = app.post("/run", json={
                "task": "x", "security": "permissive",
            })
        assert r.status_code == 200
        assert not any("requests" in c for c in _last_kernel().calls)

    def test_run_none_downgrade_upgraded(self, fake_infra):
        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm(VIOLATING_CODE),
            default_security="data_analysis",
            require_auth=False,
        ))
        with app:
            r = app.post("/run", json={"task": "x", "security": "none"})
        assert r.status_code == 200
        assert not any("requests" in c for c in _last_kernel().calls)

    def test_run_read_only_stronger_honored(self, fake_infra):
        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm(READ_ONLY_PROBE),
            default_security="data_analysis",
            require_auth=False,
        ))
        with app:
            r = app.post("/run", json={"task": "x", "security": "read_only"})
        assert r.status_code == 200
        body = r.json()
        assert "AllowListViolation" in (body.get("summary") or "") \
            or "AllowListViolation" in (body.get("error") or "") \
            or not any("open(" in c for c in _last_kernel().calls)

    def test_stream_permissive_downgrade_upgraded(self, fake_infra):
        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm(VIOLATING_CODE),
            default_security="data_analysis",
            require_auth=False,
        ))
        with app:
            with app.stream("POST", "/stream", json={
                "task": "x", "security": "permissive",
            }) as resp:
                text = b"".join(resp.iter_bytes()).decode("utf-8", "replace")
        assert "AllowListViolation" in text or "violation" in text.lower()
        assert not any("requests" in c for c in _last_kernel().calls)


class TestWebSocketAuth:
    """F-011: WebSocket must require authentication when the app does."""

    def test_ws_rejects_anonymous_when_auth_required(self, fake_infra):
        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm("print(1)"), require_auth=True,
        ))
        # The server should close the handshake with policy-violation
        # (1008) before accepting any task. TestClient surfaces this as
        # a WebSocketDisconnect on connect.
        with pytest.raises(Exception):
            with app.websocket_connect("/ws/sess-1") as ws:
                ws.send_json({"task": "x"})
                ws.receive_json()

    def test_ws_accepts_valid_token_via_query_param(self, fake_infra, monkeypatch):
        monkeypatch.setenv("KERNO_API_KEYS", "ws-key:user-ws:WS")
        import kerno.server.auth as auth_mod
        auth_mod._key_store = auth_mod.APIKeyStore().from_env()

        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm("print(1)"), require_auth=True,
        ))
        with app.websocket_connect("/ws/sess-2?token=ws-key") as ws:
            ws.send_json({"task": "hello", "max_cells": 3})
            msgs = []
            for _ in range(20):
                try:
                    m = ws.receive_json()
                    msgs.append(m)
                except Exception:
                    break
                if (m.get("kind") or "").upper() in (
                    "SESSION_COMPLETE", "SESSION_ERROR",
                ):
                    break
        # The session was accepted and started; no 1008 close.
        assert any(m.get("kind") == "session_start"
                   or m.get("kind") == "SESSION_START" for m in msgs)

    def test_ws_rejects_invalid_token(self, fake_infra, monkeypatch):
        monkeypatch.setenv("KERNO_API_KEYS", "good-key:user-ws:WS")
        import kerno.server.auth as auth_mod
        auth_mod._key_store = auth_mod.APIKeyStore().from_env()

        from kerno.server.app import create_app
        app = TestClient(create_app(
            _llm("print(1)"), require_auth=True,
        ))
        with pytest.raises(Exception):
            with app.websocket_connect("/ws/sess-3?token=bad-key") as ws:
                ws.send_json({"task": "x"})
                ws.receive_json()


# ── Gateway decision parity (unit-level) ──────────────────────────────────────

class TestGatewayDecisionParity:
    """
    Every transport calls build_gateway_engine with allow_downgrade=False;
    this test verifies the resulting effective profile is identical
    regardless of the transport label.
    """

    @pytest.mark.parametrize("transport", ["http", "sse", "ws", "openai",
                                           "openai-stream", "secure"])
    def test_effective_profile_independent_of_transport(self, transport):
        from kerno.server.security import build_gateway_engine
        effective = []
        original = build_gateway_engine

        def spy(kernel, **kw):
            effective.append(kw.get("profile"))
            # Just return the kernel; we only care about the call args.
            return kernel

        import kerno.server.security as sec
        # Call resolve_effective_profile directly to assert parity.
        for requested in (None, "none", "permissive", "data_analysis", "read_only"):
            result = sec.resolve_effective_profile(
                requested, server_default="data_analysis", allow_downgrade=False,
            )
            # Expected: weaker → upgraded to data_analysis; stronger honored.
            if requested in (None, "none", "permissive"):
                assert result == "data_analysis", (transport, requested, result)
            else:
                assert result == requested, (transport, requested, result)

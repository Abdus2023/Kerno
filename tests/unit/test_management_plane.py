"""
Management-plane authorization tests (F-011 / Gate C).

The data-plane endpoints (/run, /stream, /ws, /v1/chat/completions) are
already governed by the gateway engine. These tests cover a *separate*
security boundary:

  * /health              — operational state, pool stats
  * /metrics             — telemetry snapshot
  * /sessions            — recent session list
  * /sessions/{id}       — task text, generated code, stdout
  * /sessions/{id}/cancel — cancellation (denial-of-service vector)
  * /v1/models           — catalog (existence oracle in auth deployments)
  * /usage               — per-user usage log (secure app)

Invariants asserted:

  I-M1  /health/live is public with minimal disclosure (no pool stats).
  I-M2  When auth is enabled, management endpoints require a valid API
        key — anonymous callers get 401/403.
  I-M3  Authenticated user A cannot read user B's sessions (returns 404
        to avoid existence disclosure).
  I-M4  Authenticated user A cannot cancel user B's sessions.
  I-M5  /sessions lists only the caller's own sessions.
  I-M6  When auth is disabled (default development mode), endpoints are
        reachable anonymously but ownership still defaults to the
        anonymous principal, so an authenticated caller cannot reach
        anonymous sessions.
  I-M7  assert_session_owner returns 404 (not 403) on mismatch.
"""

from __future__ import annotations

import os
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from kerno.types import CellOutput


VIOLATING_CODE = "import requests\nrequests.get('http://evil.com')"


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


class FakePool:
    instances: ClassVar[list["FakePool"]] = []

    def __init__(self, *args, **kwargs):
        FakePool.instances.append(self)
        self.kernels = []

    def start(self):
        pass

    def shutdown(self):
        pass

    def acquire(self, task_id):
        k = FakeKernel()
        self.kernels.append(k)
        return k

    def release(self, task_id, reason="complete"):
        pass

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


# ── I-M1: /health/live is public with minimal disclosure ──────────────────────

class TestHealthLivePublic:

    def test_main_app_health_live_is_public(self, fake_infra):
        from kerno.server.app import create_app
        # Force require_auth=True — /health/live must remain public.
        app = TestClient(create_app(_llm(), require_auth=True))
        with app:
            resp = app.get("/health/live")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"status": "ok"}
        # No pool/session information leaked.
        assert "pool_stats" not in body
        assert "sessions" not in body

    def test_openai_health_live_is_public(self, fake_infra):
        from kerno.server.openai_compat import create_openai_app
        app = TestClient(create_openai_app(_llm()))
        with app:
            resp = app.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_secure_app_health_live_is_public(self, fake_infra):
        from kerno.server.secure_app import create_secure_app
        app = TestClient(create_secure_app(
            llm_factory=lambda info: _llm(), enable_auth=True,
        ))
        with app:
            resp = app.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ── I-M2: management endpoints require auth when enabled ──────────────────────

class TestManagementEndpointsRequireAuth:

    def _app(self, fake_infra):
        # Re-import management to pick up monkeypatched env. The
        # dependency is resolved at import time, so we force the
        # require_auth path explicitly via create_app(...).
        from kerno.server.app import create_app
        return TestClient(create_app(_llm(), require_auth=True))

    def test_health_requires_auth(self, fake_infra):
        with self._app(fake_infra) as app:
            resp = app.get("/health")
        assert resp.status_code in (401, 403)

    def test_metrics_requires_auth(self, fake_infra):
        with self._app(fake_infra) as app:
            resp = app.get("/metrics")
        assert resp.status_code in (401, 403)

    def test_sessions_list_requires_auth(self, fake_infra):
        with self._app(fake_infra) as app:
            resp = app.get("/sessions")
        assert resp.status_code in (401, 403)

    def test_sessions_detail_requires_auth(self, fake_infra):
        with self._app(fake_infra) as app:
            resp = app.get("/sessions/abc-123")
        assert resp.status_code in (401, 403, 404)

    def test_cancel_requires_auth(self, fake_infra):
        with self._app(fake_infra) as app:
            resp = app.post("/sessions/abc-123/cancel")
        assert resp.status_code in (401, 403)

    def test_run_requires_auth_when_enabled(self, fake_infra):
        with self._app(fake_infra) as app:
            resp = app.post("/run", json={"task": "x"})
        assert resp.status_code in (401, 403)


# ── I-M3 / I-M4 / I-M5: ownership isolation ───────────────────────────────────

class TestOwnershipIsolation:
    """
    With auth enabled and two users configured, user A must not be able
    to read, list, or cancel user B's sessions.
    """

    @pytest.fixture
    def configured_app(self, fake_infra, monkeypatch):
        # Two distinct API keys for two distinct users.
        monkeypatch.setenv(
            "KERNO_API_KEYS",
            "key-a:user-a:Alice,key-b:user-b:Bob",
        )
        monkeypatch.setenv("KERNO_ENABLE_AUTH", "true")
        # Force the key store to reload from env.
        import kerno.server.auth as auth_mod
        auth_mod._key_store = auth_mod.APIKeyStore().from_env()
        # Reset the management_principal closure to require auth.
        import importlib
        import kerno.server.management as mgmt
        importlib.reload(mgmt)
        # Rebuild app after reload so it binds the new dependency.
        from kerno.server.app import create_app
        app = TestClient(create_app(_llm("print('hello-a')"), require_auth=True))
        return app

    def _auth(self, key):
        return {"Authorization": f"Bearer {key}"}

    def test_user_a_cannot_read_user_b_session(self, configured_app):
        with configured_app as app:
            # User A creates a session.
            r1 = app.post("/run", json={"task": "from a"}, headers=self._auth("key-a"))
            assert r1.status_code == 200, r1.text
            sid_a = r1.json()["session_id"]

            # User B tries to read it.
            r2 = app.get(f"/sessions/{sid_a}", headers=self._auth("key-b"))
            assert r2.status_code == 404  # existence hidden

            # User A can read it.
            r3 = app.get(f"/sessions/{sid_a}", headers=self._auth("key-a"))
            assert r3.status_code == 200

    def test_sessions_list_scoped_to_owner(self, configured_app):
        with configured_app as app:
            app.post("/run", json={"task": "a-1"}, headers=self._auth("key-a"))
            app.post("/run", json={"task": "a-2"}, headers=self._auth("key-a"))
            app.post("/run", json={"task": "b-1"}, headers=self._auth("key-b"))

            r_a = app.get("/sessions", headers=self._auth("key-a"))
            r_b = app.get("/sessions", headers=self._auth("key-b"))
            assert r_a.status_code == 200
            assert r_b.status_code == 200
            tasks_a = {s["task"] for s in r_a.json()}
            tasks_b = {s["task"] for s in r_b.json()}
            assert tasks_a == {"a-1", "a-2"}
            assert tasks_b == {"b-1"}

    def test_cannot_cancel_other_users_session(self, configured_app):
        with configured_app as app:
            # User A starts a session; we cannot easily hold one open,
            # but we can verify the ownership gate returns 404 for a
            # session owned by A when queried by B even if no active
            # token exists. The cancel endpoint first checks ownership
            # before looking up the token for a *recorded* owner.
            r = app.post("/run", json={"task": "x"}, headers=self._auth("key-a"))
            sid = r.json()["session_id"]
            # Completed session has no active token; B should still
            # receive 404 rather than 200 + cancel info.
            r2 = app.post(
                f"/sessions/{sid}/cancel", headers=self._auth("key-b"),
            )
            assert r2.status_code == 404


# ── I-M6: anonymous mode still works ──────────────────────────────────────────

class TestAnonymousMode:

    def test_management_endpoints_reachable_when_auth_disabled(self, fake_infra):
        from kerno.server.app import create_app
        app = TestClient(create_app(_llm(), require_auth=False))
        with app:
            assert app.get("/health").status_code == 200
            assert app.get("/metrics").status_code == 200
            assert app.get("/sessions").status_code == 200

    def test_anonymous_run_records_anonymous_owner(self, fake_infra):
        """
        A session created by an anonymous caller is recorded with the
        anonymous principal; an authenticated user cannot reach it even
        in the same app instance if auth is later toggled on.
        """
        from kerno.server.app import create_app

        # Build one app with auth OFF and create a session.
        app = TestClient(create_app(_llm("print(1)"), require_auth=False))
        with app:
            r = app.post("/run", json={"task": "anon-task"})
            assert r.status_code == 200
            sid = r.json()["session_id"]
            # Anonymous caller can read it back.
            assert app.get(f"/sessions/{sid}").status_code == 200

        # Build a second app with auth ON but point it at the same
        # session store via a shared in-memory dict. In production
        # ownership is enforced per-process; this exercises the
        # assert_session_owner helper directly for the cross-principal
        # case.
        from fastapi import HTTPException
        from kerno.server.management import (
            ANONYMOUS_PRINCIPAL, assert_session_owner,
        )
        with pytest.raises(HTTPException) as exc:
            assert_session_owner(
                ANONYMOUS_PRINCIPAL, {"user_id": "user-a"},
                session_id=sid,
            )
        assert exc.value.status_code == 404


# ── I-M7: assert_session_owner returns 404 on mismatch ────────────────────────

class TestAssertSessionOwner:

    def test_mismatch_raises_404(self):
        from fastapi import HTTPException
        from kerno.server.management import assert_session_owner

        with pytest.raises(HTTPException) as exc:
            assert_session_owner(
                "user-a", {"user_id": "user-b"}, session_id="sid-1",
            )
        assert exc.value.status_code == 404
        assert "sid-1" in exc.value.detail

    def test_match_passes(self):
        from kerno.server.management import assert_session_owner
        # Should not raise.
        assert_session_owner("user-a", {"user_id": "user-a"})

    def test_anonymous_owner_consistent(self):
        from fastapi import HTTPException
        from kerno.server.management import (
            ANONYMOUS_PRINCIPAL, assert_session_owner,
        )
        # None owner is treated as anonymous; an authenticated caller
        # cannot reach it.
        with pytest.raises(HTTPException) as exc:
            assert_session_owner(None, {"user_id": "user-a"})
        assert exc.value.status_code == 404
        # Anonymous caller can reach an anonymous session.
        assert_session_owner(None, {"user_id": ANONYMOUS_PRINCIPAL})


# ── Secure-app /usage ownership scoping ───────────────────────────────────────

class TestSecureAppUsageScoping:

    def test_usage_only_returns_callers_sessions(self, fake_infra, monkeypatch):
        monkeypatch.setenv(
            "KERNO_API_KEYS",
            "ua:user-a:Alice,ub:user-b:Bob",
        )
        monkeypatch.setenv("KERNO_ENABLE_AUTH", "true")
        import kerno.server.auth as auth_mod
        auth_mod._key_store = auth_mod.APIKeyStore().from_env()

        from kerno.server.secure_app import create_secure_app
        app = TestClient(create_secure_app(
            llm_factory=lambda info: _llm("print(1)"), enable_auth=True,
        ))
        with app:
            app.post("/v1/chat/completions",
                     json={"model": "k", "messages": [{"role": "user", "content": "a"}]},
                     headers={"Authorization": "Bearer ua"})
            app.post("/v1/chat/completions",
                     json={"model": "k", "messages": [{"role": "user", "content": "b"}]},
                     headers={"Authorization": "Bearer ub"})

            r_a = app.get("/usage", headers={"Authorization": "Bearer ua"})
            r_b = app.get("/usage", headers={"Authorization": "Bearer ub"})
            assert r_a.status_code == 200
            assert r_b.status_code == 200
            assert r_a.json()["user_id"] == "user-a"
            assert r_b.json()["user_id"] == "user-b"
            assert r_a.json()["sessions"] == 1
            assert r_b.json()["sessions"] == 1

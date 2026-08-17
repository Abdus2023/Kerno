"""
Management-plane authorization (F-011 / Phase 6).

The data plane (``/run``, ``/stream``, ``/ws``, ``/v1/chat/completions``)
is execution-governed by the gateway engine. The *management plane* is a
separate security boundary: it exposes operational state (``/health``,
``/metrics``, ``/sessions``, ``/sessions/{id}``, ``/usage``, the
``/v1/models`` catalog, and the cancellation endpoint). Unauthenticated
disclosure of this surface can leak pool/session statistics, task text,
generated code, and stdout — and an unauthenticated cancellation lets an
attacker deny service by guessing session IDs.

This module provides:

* :func:`management_auth_required` — the fail-closed production policy
  shared by every server surface; evaluated per-request so tests and
  deployments can toggle it without restarting the process.
* :func:`management_principal` — a FastAPI dependency returning the
  authenticated user, or the anonymous principal when auth is not
  required.
* :func:`assert_session_owner` — a uniform ownership check so that user A
  cannot read, list, or cancel user B's sessions.

The data-plane authenticator in :mod:`kerno.server.auth` is reused so a
single API-key store governs both planes.
"""

from __future__ import annotations

import os
from typing import Optional

try:
    from fastapi import Depends, HTTPException
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    HAS_FASTAPI = True
except ImportError:                                          # pragma: no cover
    HAS_FASTAPI = False

from kerno.server.auth import _key_store, _rate_limiter


# Principal recorded on sessions/resources when no authentication is in
# use. Ownership checks treat anonymous resources as reachable only by
# anonymous callers.
ANONYMOUS_PRINCIPAL = "anonymous"

_TRUTHY = ("true", "1", "yes", "on")

# Process-wide override used by tests / callers that construct apps with
# an explicit ``require_auth`` value. None means "defer to the
# environment policy". This is a simple boolean override because Kerno
# runs a single server per process in production.
_REQUIRE_AUTH_OVERRIDE: Optional[bool] = None


def set_management_auth_required(value: Optional[bool]) -> None:
    """
    Force management-plane authentication on or off for this process.

    Pass ``None`` to revert to environment policy. Used by
    ``create_app(require_auth=...)`` and by tests that need deterministic
    behaviour without mutating the process environment.
    """
    global _REQUIRE_AUTH_OVERRIDE
    _REQUIRE_AUTH_OVERRIDE = value


def management_auth_required() -> bool:
    """
    Return whether the management plane must require authentication.

    Policy (fail-closed for production):

    * An explicit override set via :func:`set_management_auth_required`
      takes precedence (used by ``create_app(require_auth=...)``).
    * ``KERNO_ENABLE_AUTH`` truthy → require auth.
    * ``KERNO_RUNTIME_MODE == production`` → require auth even if no
      keys are configured (the caller then gets a clear 401 — a
      production deployment must not silently expose operations data).
    * Otherwise auth is optional (development / local single-user mode).

    The check reads the environment on every call so deployments and
    tests can toggle the policy without re-importing the module.
    """
    if _REQUIRE_AUTH_OVERRIDE is not None:
        return _REQUIRE_AUTH_OVERRIDE
    auth_enabled = os.environ.get("KERNO_ENABLE_AUTH", "").lower() in _TRUTHY
    is_production = os.environ.get(
        "KERNO_RUNTIME_MODE", "",
    ).lower() == "production"
    return auth_enabled or is_production


if HAS_FASTAPI:
    _bearer = HTTPBearer(auto_error=False)

    def _validate_credentials(
        credentials: Optional[HTTPAuthorizationCredentials],
    ) -> dict:
        """Validate a bearer credential against the shared key store."""
        if not os.environ.get("KERNO_API_KEYS"):
            raise HTTPException(
                status_code=401,
                detail=(
                    "Authentication is enabled (or running in production "
                    "mode) but no API keys are configured on server "
                    "(fail closed)"
                ),
            )
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="API key required. Pass as: Authorization: Bearer <key>",
            )
        info = _key_store.validate(credentials.credentials)
        if not info:
            raise HTTPException(status_code=401, detail="Invalid API key")

        allowed, remaining = _rate_limiter.check(
            info["user_id"], info["rate_limit"],
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Resets in 1 hour.",
                headers={"Retry-After": "3600"},
            )
        info = dict(info)
        info["rate_limit_remaining"] = remaining
        return info

    def make_principal_dependency(require_auth: bool):
        """
        Build a FastAPI dependency that resolves the management principal.

        ``require_auth`` decides whether the dependency enforces API-key
        auth or returns the anonymous principal. A factory (rather than a
        single module-level dependency) lets two apps in the same process
        use different policies — important for tests and for embedding
        multiple Kerno servers in one host.
        """
        async def _dependency(
            credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
        ) -> dict:
            if require_auth:
                return _validate_credentials(credentials)
            return {
                "user_id": ANONYMOUS_PRINCIPAL,
                "max_cells": 50,
                "rate_limit": 1000,
            }
        return _dependency

    async def management_principal(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    ) -> dict:
        """
        Default management principal — resolves policy from the
        environment on every request. Use
        :func:`make_principal_dependency` when constructing an app with
        an explicit ``require_auth`` value.
        """
        if management_auth_required():
            return _validate_credentials(credentials)
        return {
            "user_id": ANONYMOUS_PRINCIPAL,
            "max_cells": 50,
            "rate_limit": 1000,
        }


def assert_session_owner(
    session_owner: Optional[str],
    principal: dict,
    *,
    session_id: str = "",
) -> None:
    """
    Raise 404 (not 403) if ``principal`` does not own ``session_owner``.

    404 is used rather than 403 to avoid disclosing the *existence* of
    another principal's sessions — an attacker should not be able to
    enumerate valid session IDs. When the session has no recorded owner
    it is treated as owned by the anonymous principal, so an
    authenticated user can never reach an anonymous session and vice
    versa.
    """
    if not HAS_FASTAPI:
        # Allow use in non-FastAPI contexts as a plain ownership check.
        caller = (principal or {}).get("user_id", ANONYMOUS_PRINCIPAL)
        owner = session_owner or ANONYMOUS_PRINCIPAL
        if owner != caller:
            raise LookupError(
                f"Session {session_id} not owned by {caller}"
                if session_id else "Session not owned by caller"
            )
        return

    caller = (principal or {}).get("user_id", ANONYMOUS_PRINCIPAL)
    owner = session_owner or ANONYMOUS_PRINCIPAL
    if owner != caller:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found" if session_id
            else "Session not found",
        )

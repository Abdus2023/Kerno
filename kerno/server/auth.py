"""
Authentication and rate limiting for the Kerno server.

In production, you want:
  - API key validation (who can use the server)
  - Per-user rate limiting (how much they can use)
  - Per-user kernel isolation (sessions don't cross contaminate)
  - Usage tracking (for billing or quotas)
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from typing      import Optional

try:
    from fastapi             import Depends, HTTPException, Security
    from fastapi.security    import HTTPAuthorizationCredentials, HTTPBearer
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


# ── API Key Management ────────────────────────────────────────────────────────


class APIKeyStore:
    """
    Hardened API key store with salted PBKDF2-HMAC-SHA256 key derivation
    and constant-time comparison (audit #16 / Phase D).
    """

    def __init__(self, iterations: int = 100_000):
        self._keys: dict[str, dict] = {}
        self.iterations = iterations

    def _derive(self, key: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", key.encode("utf-8"), salt, self.iterations
        ).hex()

    def add_key(
        self,
        key:        str,
        user_id:    str,
        name:       str       = "",
        rate_limit: int       = 100,    # Requests per hour
        max_cells:  int       = 50,     # Max cells per session
        salt:       Optional[str] = None,
    ) -> None:
        import secrets

        # 16-byte random salt per key
        salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
        derived    = self._derive(key, salt_bytes)

        self._keys[derived] = {
            "user_id":     user_id,
            "name":        name,
            "rate_limit":  rate_limit,
            "max_cells":   max_cells,
            "created_at":  time.time(),
            "active":      True,
            "salt_hex":    salt_bytes.hex(),
        }

    def validate(self, key: str) -> Optional[dict]:
        """
        Validate an API key using constant-time comparison.
        Returns user info on match, or None.
        """
        import hmac

        if not key:
            return None

        # Check against salted derivations in constant time
        for derived_hash, info in self._keys.items():
            if not info.get("active"):
                continue
            salt_bytes = bytes.fromhex(info["salt_hex"])
            candidate = self._derive(key, salt_bytes)
            if hmac.compare_digest(derived_hash, candidate):
                return info

        return None

    def from_env(self) -> "APIKeyStore":
        """Load keys from KERNO_API_KEYS environment variable."""
        import os
        keys_str = os.environ.get("KERNO_API_KEYS", "")
        # Format: "key1:user1:name1,key2:user2:name2"
        for entry in keys_str.split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 2:
                self.add_key(key=parts[0], user_id=parts[1],
                             name=parts[2] if len(parts) > 2 else "")
        return self


# ── Rate Limiter ──────────────────────────────────────────────────────────────


class RateLimiter:
    """
    Sliding window rate limiter per user.
    """

    def __init__(self, window_seconds: float = 3600.0):
        self.window   = window_seconds
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, user_id: str, limit: int) -> tuple[bool, int]:
        """
        Check if user is within rate limit.
        Returns (allowed, remaining).
        """
        now      = time.time()
        cutoff   = now - self.window
        window   = self._windows[user_id]

        # Remove expired entries
        self._windows[user_id] = [t for t in window if t > cutoff]

        current  = len(self._windows[user_id])
        allowed  = current < limit
        remaining = max(0, limit - current)

        if allowed:
            self._windows[user_id].append(now)

        return allowed, remaining

    def reset(self, user_id: str) -> None:
        self._windows.pop(user_id, None)


# ── FastAPI Integration ───────────────────────────────────────────────────────

_key_store   = APIKeyStore().from_env()
_rate_limiter = RateLimiter()

if HAS_FASTAPI:
    _bearer = HTTPBearer(auto_error=False)

    async def verify_api_key(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer)
    ) -> dict:
        """
        FastAPI dependency: validate API key from Authorization header.
        Returns user info on success, raises 401/429 on failure.
        """
        import os

        # If auth is explicitly enabled or in production mode, fail closed when no keys are configured
        auth_enabled  = os.environ.get("KERNO_ENABLE_AUTH", "").lower() in ("true", "1", "yes")
        is_production = os.environ.get("KERNO_RUNTIME_MODE", "").lower() == "production"

        if not os.environ.get("KERNO_API_KEYS"):
            if auth_enabled or is_production:
                raise HTTPException(
                    status_code = 401,
                    detail      = "Authentication is enabled (or running in production mode) but no API keys are configured on server (fail closed)",
                )
            return {"user_id": "anonymous", "rate_limit": 1000, "max_cells": 50}

        if not credentials:
            raise HTTPException(
                status_code = 401,
                detail      = "API key required. Pass as: Authorization: Bearer <key>",
            )

        user_info = _key_store.validate(credentials.credentials)
        if not user_info:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Rate limit check
        allowed, remaining = _rate_limiter.check(
            user_info["user_id"],
            user_info["rate_limit"],
        )
        if not allowed:
            raise HTTPException(
                status_code = 429,
                detail      = "Rate limit exceeded. Resets in 1 hour.",
                headers     = {"Retry-After": "3600"},
            )

        user_info["rate_limit_remaining"] = remaining
        return user_info

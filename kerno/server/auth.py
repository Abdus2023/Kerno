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
    Simple in-memory API key store.
    Replace with a database in production.
    """

    def __init__(self):
        self._keys: dict[str, dict] = {}

    def add_key(
        self,
        key:       str,
        user_id:   str,
        name:      str       = "",
        rate_limit: int      = 100,    # Requests per hour
        max_cells:  int      = 50,     # Max cells per session
    ) -> None:
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        self._keys[key_hash] = {
            "user_id":    user_id,
            "name":       name,
            "rate_limit": rate_limit,
            "max_cells":  max_cells,
            "created_at": time.time(),
            "active":     True,
        }

    def validate(self, key: str) -> Optional[dict]:
        """Validate an API key. Returns user info or None."""
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        info     = self._keys.get(key_hash)
        if info and info.get("active"):
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

        # If no keys configured, allow all (development mode)
        if not os.environ.get("KERNO_API_KEYS"):
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

# kerno/security/secrets.py
"""
SecretBroker — dedicated secret management (audit #67, #68).

Principles:
    1. Secrets are NEVER exposed to the kernel wholesale (no os.environ
       dumps). A subject requests exactly one secret and must hold a
       grant for it.
    2. Secrets are NEVER stored in notebooks or event payloads. The
       broker provides redaction so any recorded text (code previews,
       error values, outputs) can be scrubbed before it reaches the
       event store:  Execution → Observation → Redaction → Event Store.

Usage:
    broker = SecretBroker()
    broker.register("db_password", "s3cr3t!")
    broker.grant("db_password", subject="agent-1")

    value = broker.request("db_password", subject="agent-1")   # "s3cr3t!"
    broker.redact("password is s3cr3t!")                        # "password is [REDACTED]"
"""

from __future__ import annotations

import time
from typing import Optional

REDACTED = "[REDACTED]"


class SecretNotFound(KeyError):
    """Raised when requesting an unknown secret."""


class SecretDenied(PermissionError):
    """Raised when the subject holds no valid grant for the secret."""


class SecretBroker:
    """Registers secrets, grants scoped access, and redacts values."""

    def __init__(self):
        self._secrets: dict[str, str] = {}
        # (secret_id, subject) → expiry (None = never)
        self._grants: dict[tuple[str, str], Optional[float]] = {}

    # ── Registration ──────────────────────────────────────────────────────

    def register(self, secret_id: str, value: str) -> None:
        if not secret_id:
            raise ValueError("secret_id must not be empty")
        self._secrets[secret_id] = value

    def unregister(self, secret_id: str) -> None:
        self._secrets.pop(secret_id, None)
        self._grants = {
            k: v for k, v in self._grants.items() if k[0] != secret_id
        }

    # ── Grants ─────────────────────────────────────────────────────────────

    def grant(
        self,
        secret_id: str,
        subject:   str = "",
        expires_at: Optional[float] = None,
    ) -> None:
        """Grant a subject access to a secret (subject "" = any)."""
        if secret_id not in self._secrets:
            raise SecretNotFound(secret_id)
        self._grants[(secret_id, subject)] = expires_at

    def revoke(self, secret_id: str, subject: str = "") -> None:
        """Revoke a grant (subject "" revokes the anonymous grant only)."""
        self._grants.pop((secret_id, subject), None)

    def revoke_all(self, secret_id: str) -> None:
        """Revoke every grant for a secret."""
        self._grants = {
            k: v for k, v in self._grants.items() if k[0] != secret_id
        }

    # ── Access ─────────────────────────────────────────────────────────────

    def request(self, secret_id: str, subject: str = "") -> str:
        """
        Return the secret value if the subject holds a valid grant.

        Raises SecretNotFound / SecretDenied otherwise.
        """
        if secret_id not in self._secrets:
            raise SecretNotFound(secret_id)
        if not self._is_granted(secret_id, subject):
            raise SecretDenied(
                f"subject '{subject or '<anonymous>'}' has no grant "
                f"for secret '{secret_id}'"
            )
        return self._secrets[secret_id]

    def _is_granted(self, secret_id: str, subject: str) -> bool:
        now = time.time()
        for key, expiry in self._grants.items():
            sid, subj = key
            if sid != secret_id:
                continue
            if subj and subject and subj != subject:
                continue
            if expiry is not None and now >= expiry:
                continue
            return True
        return False

    # ── Redaction (audit #68) ──────────────────────────────────────────────

    def redact(self, text: str) -> str:
        """
        Replace every registered secret value in `text` with [REDACTED].

        Values are matched longest-first so overlapping secrets are all
        covered and shorter secrets inside longer ones don't leave residue.
        """
        if not text:
            return text
        values = sorted(
            (v for v in self._secrets.values() if v),
            key=len, reverse=True,
        )
        for value in values:
            if value in text:
                text = text.replace(value, REDACTED)
        return text

    def redact_many(self, texts: list[str]) -> list[str]:
        return [self.redact(t) for t in texts]

    def __contains__(self, secret_id: str) -> bool:
        return secret_id in self._secrets

    def __len__(self) -> int:
        return len(self._secrets)

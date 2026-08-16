# kerno/capability_exec.py
"""
CapabilityExecutor — capability execution separated from code execution
(audit #31, #48).

The two-plane architecture:

    CONTROL PLANE                    DATA PLANE
    ┌──────────────────┐   ┌──────────────────────────┐
    │ Agent             │   │ filesystem               │
    │   └ Capability    │   │ artifact store           │
    │      request      │──▶│ secrets                  │
    │         └ broker  │   │ kernel (compute backend) │
    └──────────────────┘   └──────────────────────────┘

The LLM produces INTENT, not Python: instead of generating
`open("/workspace/data.csv")`, it requests
`filesystem.read` scope="/workspace/data.csv". The broker authorizes
the request against capability grants (K-008) and performs it HOST-SIDE —
no Python is executed for these operations at all.

Supported capabilities:
    filesystem.read   — read a file within the granted scope
    artifact.create   — store content into the ArtifactStore (audit #95)
    artifact.read     — read an artifact by digest
    secret.read       — retrieve a granted secret via SecretBroker (#67)
    kernel.execute    — delegate to the ExecutionEngine (the Python path)

Every invocation is audited in `records` (name, scope, subject, ok).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from kerno.artifacts import ArtifactStore
from kerno.security.capabilities import (
    CAP_ARTIFACT_CREATE, CAP_FILESYSTEM_READ, CAP_SECRET_READ,
    CapabilityBroker,
)

CAP_ARTIFACT_READ = "artifact.read"
CAP_KERNEL_EXECUTE_CAP = "kernel.execute"

DEFAULT_MAX_READ_BYTES = 1_000_000   # 1 MB


class CapabilityError(RuntimeError):
    """Raised by CapabilityExecutor when an operation fails."""


@dataclass
class CapabilityRecord:
    """One audited capability invocation."""

    name:      str
    scope:     str          = "*"
    subject:   str          = ""
    ok:        bool         = False
    error:     str          = ""
    timestamp: float        = field(default_factory=__import__("time").time)

    def to_dict(self) -> dict:
        return {
            "name":    self.name,
            "scope":   self.scope,
            "subject": self.subject,
            "ok":      self.ok,
            "error":   self.error,
            "time":    self.timestamp,
        }


@dataclass
class CapabilityResult:
    """Outcome of one capability invocation."""

    name:  str
    ok:    bool
    value: Any       = None
    error: str       = ""

    @property
    def denied(self) -> bool:
        return not self.ok and "denied" in self.error


class CapabilityExecutor:
    """
    Performs authorized capability operations host-side (no Python).

    Usage:
        ex = CapabilityExecutor(broker, artifact_store=store)
        result = ex.invoke(
            "filesystem.read", scope="/workspace/data.csv", subject="agent-1"
        )
        if result.ok:
            text = result.value
    """

    def __init__(
        self,
        broker:          CapabilityBroker,
        artifact_store:  Optional[ArtifactStore] = None,
        secret_broker:   Optional[object] = None,     # SecretBroker
        engine:          Optional[object] = None,     # ExecutionEngine
        max_read_bytes:  int = DEFAULT_MAX_READ_BYTES,
        workspace_root:  Optional[str | Path] = None,  # default: grant scope base
    ):
        self._broker         = broker
        self._artifacts      = artifact_store
        self._secrets        = secret_broker
        self._engine         = engine
        self._max_read_bytes = max_read_bytes
        self._workspace_root = Path(workspace_root) if workspace_root else None
        self._records: list[CapabilityRecord] = []

    # ── Public API ───────────────────────────────────────────────────────

    def invoke(
        self,
        name:      str,
        *,
        scope:     str    = "*",
        subject:   str    = "",
        params:    Optional[dict] = None,
    ) -> CapabilityResult:
        """Authorize and perform one capability operation."""
        params = dict(params or {})

        # ── Authorization (K-008) ────────────────────────────────────────
        if not self._broker.check(name, scope=scope, subject=subject):
            self._record(name, scope, subject, False,
                         "denied: no active grant")
            return CapabilityResult(name, False, error="denied: no active grant")

        # ── Dispatch ─────────────────────────────────────────────────────
        try:
            if name == CAP_FILESYSTEM_READ:
                result = self._read_file(scope)
            elif name == CAP_ARTIFACT_CREATE:
                result = self._create_artifact(scope, params)
            elif name == CAP_ARTIFACT_READ:
                result = self._read_artifact(scope)
            elif name == CAP_SECRET_READ:
                result = self._read_secret(scope, subject)
            elif name == CAP_KERNEL_EXECUTE_CAP:
                result = self._kernel_execute(params)
            else:
                result = CapabilityResult(
                    name, False, error="unknown capability: " + name
                )
        except CapabilityError as exc:
            result = CapabilityResult(name, False, error=str(exc))

        self._record(name, scope, subject, result.ok, result.error)
        return result

    @property
    def records(self) -> tuple[CapabilityRecord, ...]:
        """Immutable audit trail of every invocation."""
        return tuple(self._records)

    # ── Capability implementations (host-side, no Python) ────────────────

    def _read_file(self, path: str) -> CapabilityResult:
        resolved = self._resolve_path(path)
        if not resolved.exists():
            raise CapabilityError("file not found: " + path)
        if not resolved.is_file():
            raise CapabilityError("not a file: " + path)
        size = resolved.stat().st_size
        if size > self._max_read_bytes:
            raise CapabilityError(
                "file too large: {} bytes > {} limit".format(
                    size, self._max_read_bytes
                )
            )
        try:
            text = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise CapabilityError("file is not utf-8 text")
        return CapabilityResult("filesystem.read", True, value=text)

    def _create_artifact(self, scope: str, params: dict) -> CapabilityResult:
        if self._artifacts is None:
            raise CapabilityError("no artifact store configured")
        data = params.get("data")
        if not isinstance(data, str):
            raise CapabilityError("artifact.create requires params['data'] str")
        ref = self._artifacts.store_text(
            data,
            media_type        = params.get("media_type", "text/plain"),
            creator_execution = params.get("creator_execution"),
            metadata          = params.get("metadata"),
        )
        return CapabilityResult(
            "artifact.create", True, value=ref.to_dict()
        )

    def _read_artifact(self, digest: str) -> CapabilityResult:
        if self._artifacts is None:
            raise CapabilityError("no artifact store configured")
        if not digest.startswith("sha256:"):
            raise CapabilityError("artifact.read requires a sha256: digest")
        if not self._artifacts.exists(digest):
            raise CapabilityError("artifact not found: " + digest)
        return CapabilityResult(
            "artifact.read", True, value=self._artifacts.read_text(digest)
        )

    def _read_secret(self, secret_id: str, subject: str) -> CapabilityResult:
        if self._secrets is None:
            raise CapabilityError("no secret broker configured")
        try:
            value = self._secrets.request(secret_id, subject=subject)
        except Exception as exc:
            raise CapabilityError("secret denied: " + str(exc)[:120])
        return CapabilityResult("secret.read", True, value=value)

    def _kernel_execute(self, params: dict) -> CapabilityResult:
        if self._engine is None:
            raise CapabilityError("no compute engine configured")
        code = params.get("code", "")
        if not isinstance(code, str) or not code.strip():
            raise CapabilityError("kernel.execute requires params['code']")
        output = self._engine.execute(
            code,
            timeout = float(params.get("timeout", 120.0)),
            subject = params.get("subject", ""),
        )
        if output.has_error:
            return CapabilityResult(
                "kernel.execute", False,
                error="{}: {}".format(
                    output.error.ename, output.error.evalue[:200]
                ),
            )
        return CapabilityResult(
            "kernel.execute", True,
            value={"stdout": output.stdout, "stderr": output.stderr},
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _resolve_path(self, path: str) -> Path:
        """
        Resolve the requested path and verify it stays inside the granted
        scope (audit #31: no traversal out of the authorization scope).
        """
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            if self._workspace_root is None:
                raise CapabilityError("relative path requires workspace_root")
            candidate = self._workspace_root / candidate
        resolved = candidate.resolve()

        # Traversal guard: when a workspace root is configured, the
        # resolved path must stay inside it — '..' sequences that escape
        # are rejected even if the raw string matched the scope pattern.
        if self._workspace_root is not None:
            root = self._workspace_root.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                raise CapabilityError(
                    "path escapes workspace: " + path
                )
        return resolved

    def _record(
        self,
        name:    str,
        scope:   str,
        subject: str,
        ok:      bool,
        error:   str,
    ) -> None:
        self._records.append(CapabilityRecord(
            name=name, scope=scope, subject=subject, ok=ok, error=error,
        ))

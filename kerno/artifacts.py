# kerno/artifacts.py
"""
Content-addressed, immutable artifact store (audit #94/#95).

Artifacts are identified by their SHA-256 digest (sha256:<hex>), never
by filename: deduplication is free, and mutation is impossible — writing
the same bytes yields the same ref; writing different bytes yields a
different artifact with its own provenance.

    ArtifactRef
    ├── digest            — content address
    ├── media_type
    ├── size
    ├── creator_execution — execution_id that produced it (K-006)
    └── metadata

The notebook is just another artifact (audit #96): sessions store
notebooks through the same store.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MEDIA_TYPE_JSON    = "application/json"
MEDIA_TYPE_IPYNB   = "application/x-ipynb+json"
MEDIA_TYPE_CSV     = "text/csv"
MEDIA_TYPE_PLAIN   = "text/plain"
MEDIA_TYPE_BYTES   = "application/octet-stream"


@dataclass(frozen=True)
class ArtifactRef:
    """Immutable reference to one stored artifact."""

    digest:            str
    media_type:        str                = MEDIA_TYPE_BYTES
    size:              int                = 0
    creator_execution: Optional[str]      = None
    created_at:        float              = field(default_factory=time.time)
    metadata:          dict               = field(default_factory=dict)

    @property
    def key(self) -> str:
        return self.digest

    def to_dict(self) -> dict:
        return {
            "digest":            self.digest,
            "media_type":        self.media_type,
            "size":              self.size,
            "creator_execution": self.creator_execution,
            "created_at":        self.created_at,
            "metadata":          dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ArtifactRef":
        return cls(**d)


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ArtifactIntegrityError(RuntimeError):
    """Raised when stored bytes do not match their content address."""


class ArtifactStore:
    """
    Directory-backed content-addressed store.

    Layout: <root>/sha256:<hex>  (flat, content-addressed)
    """

    def __init__(self, root: str | Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # ── Writing (immutable: same digest → same bytes) ─────────────────────

    def store_bytes(
        self,
        data:              bytes,
        media_type:        str              = MEDIA_TYPE_BYTES,
        creator_execution: Optional[str]    = None,
        metadata:          Optional[dict]   = None,
    ) -> ArtifactRef:
        """Store bytes; returns a ref keyed by their digest."""
        digest = sha256_bytes(data)
        ref = ArtifactRef(
            digest            = digest,
            media_type        = media_type,
            size              = len(data),
            creator_execution = creator_execution,
            metadata          = dict(metadata or {}),
        )
        path = self._root / digest
        if path.exists():
            # Content-addressed invariant: the file must match its digest.
            # If a hostile mutation changed the bytes, restore the
            # canonical content (self-heal) so the address stays true.
            if path.read_bytes() != data:
                path.write_bytes(data)
        else:
            path.write_bytes(data)
        return ref

    def store_text(
        self,
        text:              str,
        media_type:        str              = MEDIA_TYPE_PLAIN,
        creator_execution: Optional[str]    = None,
        metadata:          Optional[dict]   = None,
    ) -> ArtifactRef:
        return self.store_bytes(
            text.encode("utf-8"), media_type, creator_execution, metadata
        )

    def store_file(
        self,
        path:              str | Path,
        media_type:        str              = MEDIA_TYPE_BYTES,
        creator_execution: Optional[str]    = None,
        metadata:          Optional[dict]   = None,
    ) -> ArtifactRef:
        """Copy a file into the store (the store copy is immutable)."""
        data = Path(path).read_bytes()
        return self.store_bytes(data, media_type, creator_execution, metadata)

    # ── Reading ────────────────────────────────────────────────────────────

    def path_for(self, ref: ArtifactRef | str) -> Path:
        """The on-disk path for a ref (or digest string)."""
        digest = ref if isinstance(ref, str) else ref.digest
        return self._root / digest

    def read_bytes(self, ref: ArtifactRef | str) -> bytes:
        """Read the artifact, verifying its content address (audit #94)."""
        digest = ref if isinstance(ref, str) else ref.digest
        path   = self.path_for(digest)
        data   = path.read_bytes()
        if sha256_bytes(data) != digest:
            raise ArtifactIntegrityError(
                "artifact {} failed integrity check (tampered?)".format(digest)
            )
        return data

    def read_text(self, ref: ArtifactRef | str) -> str:
        return self.read_bytes(ref).decode("utf-8")

    def exists(self, ref: ArtifactRef | str) -> bool:
        return self.path_for(ref).exists()

    def size(self, ref: ArtifactRef | str) -> int:
        return self.path_for(ref).stat().st_size

    # ── Views ──────────────────────────────────────────────────────────────

    def list_digests(self) -> list[str]:
        return sorted(p.name for p in self._root.iterdir() if p.is_file())

    def __len__(self) -> int:
        return len(self.list_digests())

    def __contains__(self, digest: str) -> bool:
        return (self._root / digest).exists()

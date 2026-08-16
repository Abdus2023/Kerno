# kerno/reproducibility.py
"""
Reproducibility manifests (audit #57, #14, P1).

Artifact reproducibility ("here is the notebook") is easy.
Execution reproducibility ("this session can be reproduced under a
declared environment") requires recording:

    Python version · platform · kernel spec · package versions
    environment variable NAMES (never values) · task hash
    input hashes · artifact hashes · kernel generation · model name

The ReproducibilityManifest is saved alongside the notebook as
`<session_id>.manifest.json`, and a light environment summary is embedded
in the notebook metadata itself.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


def hash_text(text: str) -> str:
    """SHA-256 of arbitrary text (task, config, ...)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: str | Path, chunk_size: int = 65536) -> str:
    """SHA-256 of a file's contents (streamed)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _installed_packages() -> dict[str, str]:
    """{package_name: version} from the current environment."""
    try:
        from importlib import metadata
        packages: dict[str, str] = {}
        for dist in metadata.distributions():
            name = (dist.metadata.get("Name") or "").strip().lower()
            version = (dist.metadata.get("Version") or "").strip()
            if name:
                packages[name] = version
        return dict(sorted(packages.items()))
    except Exception:
        return {}


@dataclass
class EnvironmentSnapshot:
    """The execution environment at capture time."""

    python_version: str
    platform:       str
    kernel_spec:    str
    packages:       dict           = field(default_factory=dict)   # name → version
    env_var_names:  list           = field(default_factory=list)   # NAMES ONLY
    captured_at:    float          = field(default_factory=time.time)

    @classmethod
    def capture(cls, kernel_name: str = "python3") -> "EnvironmentSnapshot":
        """Snapshot the current host environment."""
        return cls(
            python_version = sys.version.split()[0],
            platform       = platform.platform(),
            kernel_spec    = kernel_name,
            packages       = _installed_packages(),
            # Audit #67: names only — values are never recorded.
            env_var_names  = sorted(os.environ.keys()),
        )

    def summary(self) -> dict:
        """A light view safe to embed in notebook metadata."""
        return {
            "python":    self.python_version,
            "platform":  self.platform,
            "kernel":    self.kernel_spec,
            "packages":  len(self.packages),
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EnvironmentSnapshot":
        return cls(**d)


@dataclass
class ReproducibilityManifest:
    """The full reproducibility record for one session (audit #57)."""

    session_id:         str
    task_hash:          str
    environment:        EnvironmentSnapshot
    input_hashes:       dict          = field(default_factory=dict)
    artifact_hashes:    dict          = field(default_factory=dict)
    kernel_generation:  int           = 0
    model_name:         str           = ""
    random_seeds:       dict          = field(default_factory=dict)
    created_at:         float         = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "session_id":        self.session_id,
            "task_hash":         self.task_hash,
            "environment":       self.environment.to_dict(),
            "input_hashes":      dict(self.input_hashes),
            "artifact_hashes":   dict(self.artifact_hashes),
            "kernel_generation": self.kernel_generation,
            "model_name":        self.model_name,
            "random_seeds":      dict(self.random_seeds),
            "created_at":        self.created_at,
        }

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "ReproducibilityManifest":
        env = EnvironmentSnapshot.from_dict(d["environment"])
        return cls(
            session_id        = d["session_id"],
            task_hash         = d["task_hash"],
            environment       = env,
            input_hashes      = d.get("input_hashes", {}),
            artifact_hashes   = d.get("artifact_hashes", {}),
            kernel_generation = d.get("kernel_generation", 0),
            model_name        = d.get("model_name", ""),
            random_seeds      = d.get("random_seeds", {}),
            created_at        = d.get("created_at", time.time()),
        )


def build_manifest(
    result:            object,
    *,
    kernel_name:       str                 = "python3",
    kernel_generation: int                 = 0,
    model_name:        str                 = "",
    artifact_paths:    Optional[list[str]] = None,
    input_hashes:      Optional[dict]      = None,
    random_seeds:      Optional[dict]      = None,
) -> ReproducibilityManifest:
    """
    Build the reproducibility manifest for a finished session.

    Args:
        result:            SessionResult (uses session_id + task)
        kernel_name:       kernel spec used
        kernel_generation: KernelRuntime.generation at session end
        model_name:        LLM model identifier, if known
        artifact_paths:    files to hash as produced artifacts
        input_hashes:      {name: sha256} of external inputs used
        random_seeds:      {name: seed} if the session set explicit seeds
    """
    artifact_hashes = {}
    for path in artifact_paths or []:
        try:
            artifact_hashes[str(path)] = hash_file(path)
        except OSError:
            artifact_hashes[str(path)] = "unavailable"

    return ReproducibilityManifest(
        session_id        = result.session_id,
        task_hash         = hash_text(result.task),
        environment       = EnvironmentSnapshot.capture(kernel_name),
        input_hashes      = dict(input_hashes or {}),
        artifact_hashes   = artifact_hashes,
        kernel_generation = kernel_generation,
        model_name        = model_name,
        random_seeds      = dict(random_seeds or {}),
    )


def save_manifest(
    manifest:  ReproducibilityManifest,
    directory: str,
) -> Path:
    """Write `<session_id>.manifest.json` into `directory`."""
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{manifest.session_id}.manifest.json"
    path.write_text(manifest.to_json())
    return path


# ── Environment lock (Phase E) ────────────────────────────────────────────────

def export_lock(environment: EnvironmentSnapshot) -> str:
    """
    Export the environment as a requirements-lock file (Phase E).

    `name==version` per line, sorted — the pinned environment needed to
    reproduce a session's executions.
    """
    lines = []
    for name, version in environment.packages.items():
        if version:
            lines.append("{}=={}".format(name, version))
    return "\n".join(lines) + "\n"


def save_lock(
    environment: EnvironmentSnapshot,
    path:        str | Path,
) -> Path:
    """Write the environment lock to `path`."""
    target = Path(path)
    target.write_text(export_lock(environment))
    return target

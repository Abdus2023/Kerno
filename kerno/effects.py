# kerno/effects.py
"""
Effect ledger — declared ⊇ observed enforcement (audit #92/#93).

Actions declare their side effects BEFORE execution:

    effects:
      filesystem.write
      network.connect

After execution, an observer diffs the workspace: any filesystem write
that was NOT declared is an unexpected effect → SECURITY VIOLATION.

This is defense-in-depth: even if the allowlist misses a write method
(Path.write_text, df.to_csv, ...), the effect ledger catches the
undeclared filesystem mutation.

Network/process effects cannot be observed host-side without OS hooks;
they are covered by the allowlist and (in production) by container
network policy (DockerExecutor). The ledger documents this boundary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Effect names
EFFECT_FILESYSTEM_WRITE = "filesystem.write"
EFFECT_NETWORK_CONNECT  = "network.connect"
EFFECT_PROCESS_SPAWN    = "process.spawn"

EFFECTS_WRITE = frozenset({EFFECT_FILESYSTEM_WRITE})
EFFECTS_NONE  = frozenset()


def _file_digest(path: Path, chunk_size: int = 65536) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class WorkspaceObserver:
    """
    Snapshots a workspace directory and diffs between snapshots.

    A snapshot maps relative path → (exists, sha256). The diff reports
    created / modified / deleted files — i.e. observed filesystem writes.
    """

    def __init__(self, workspace: str | Path):
        self._workspace = Path(workspace)
        self._workspace.mkdir(parents=True, exist_ok=True)

    @property
    def workspace(self) -> Path:
        return self._workspace

    def snapshot(self) -> dict[str, str]:
        """{relpath: sha256} for every file under the workspace."""
        result: dict[str, str] = {}
        for path in self._workspace.rglob("*"):
            if path.is_file():
                rel = path.relative_to(self._workspace).as_posix()
                try:
                    result[rel] = _file_digest(path)
                except OSError:
                    continue
        return result

    @staticmethod
    def diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
        """
        Files that were created, modified, or deleted between snapshots.

        Returns relative paths in a stable order.
        """
        created  = [k for k in after if k not in before]
        modified = [k for k in before if k in after and before[k] != after[k]]
        deleted  = [k for k in before if k not in after]
        return sorted(set(created) | set(modified) | set(deleted))


@dataclass(frozen=True)
class EffectViolation:
    """An observed effect that was not declared."""

    execution_id: str
    declared:     frozenset[str]
    observed:     list[str]          # file paths changed
    timestamp:    float = field(default_factory=__import__("time").time)


class EffectLedger:
    """
    Records declared effects per execution and compares them against
    observed workspace changes.

    Usage:
        ledger = EffectLedger(workspace="/workspace")
        ledger.declare("exec_1", effects=frozenset({EFFECT_FILESYSTEM_WRITE}))
        ... execute ...
        violations = ledger.observe("exec_1")   # [EffectViolation] if any
    """

    def __init__(self, workspace: Optional[str | Path] = None):
        self._observer = WorkspaceObserver(workspace) if workspace else None
        self._declared: dict[str, frozenset[str]] = {}
        self._before:   dict[str, dict[str, str]] = {}
        self._violations: list[EffectViolation] = []

    def declare(self, execution_id: str, effects: frozenset[str]) -> None:
        """Record the declared effects and snapshot the workspace."""
        self._declared[execution_id] = frozenset(effects)
        if self._observer is not None:
            self._before[execution_id] = self._observer.snapshot()

    def observe(self, execution_id: str) -> list[EffectViolation]:
        """
        Compare observed workspace changes against the declared effects.

        A filesystem change is a violation iff the execution did not
        declare EFFECT_FILESYSTEM_WRITE. Returns (and records) the
        violations for this execution.
        """
        if self._observer is None:
            return []
        declared = self._declared.get(execution_id, frozenset())
        before   = self._before.get(execution_id)
        if before is None:
            return []

        changed = self._observer.diff(before, self._observer.snapshot())
        if not changed:
            return []
        if EFFECT_FILESYSTEM_WRITE in declared:
            return []          # declared → allowed

        violation = EffectViolation(
            execution_id = execution_id,
            declared     = declared,
            observed     = changed,
        )
        self._violations.append(violation)
        return [violation]

    @property
    def violations(self) -> tuple[EffectViolation, ...]:
        """All violations so far (immutable view)."""
        return tuple(self._violations)

    @property
    def declared(self) -> dict[str, frozenset[str]]:
        return dict(self._declared)

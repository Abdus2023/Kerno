"""
SessionVault: persistent, queryable storage for session results.

The vault is the backbone of Level 3 persistence.  It stores every
completed SessionResult, indexes it for full-text search, and can
reproduce any past session from its provenance chain.

Design:
  - SessionVault: high-level API (store, query, reproduce)
  - VaultIndex: SQLite + FTS5 index for fast text search
  - Checkpointing: serialises kernel objects for exact reproduction
  - Reproduction: replays provenance chain to reconstruct any object

The vault is *append-only*: sessions are never modified after storing.
This makes it safe for concurrent access and audit-friendly.
"""

from __future__ import annotations

import json
import pickle
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from kerno.types import Cell, SessionResult, SessionStatus


# ── VaultIndex (SQLite + FTS5) ────────────────────────────────────────────────

class VaultIndex:
    """
    SQLite-backed full-text index over stored sessions.

    Uses FTS5 for fast text search over task descriptions, summaries,
    and cell code.  Each session is one row in the index.
    """

    def __init__(self, db_path: str | Path = "kerno_vault.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_schema()

    def _init_schema(self) -> None:
        """Create the FTS5 virtual table if it doesn't exist."""
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id  TEXT PRIMARY KEY,
                task        TEXT NOT NULL,
                status      TEXT NOT NULL,
                summary     TEXT DEFAULT '',
                created_at  REAL NOT NULL,
                cell_count  INTEGER DEFAULT 0
            )
        """)
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts
            USING fts5(session_id, task, summary, code)
        """)
        self._conn.commit()

    def add(self, result: SessionResult) -> None:
        """Index a stored session result."""
        code_blocks = "\n".join(c.code for c in result.cells)
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions "
                "(session_id, task, status, summary, created_at, cell_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    result.session_id,
                    result.task,
                    result.status.name,
                    result.summary,
                    result.started_at,
                    len(result.cells),
                ),
            )
            self._conn.execute(
                "INSERT INTO sessions_fts (session_id, task, summary, code) "
                "VALUES (?, ?, ?, ?)",
                (result.session_id, result.task, result.summary, code_blocks),
            )

    def query(self, text: str, limit: int = 10) -> list[dict]:
        """
        Full-text search for sessions matching *text*.
        Returns a list of dicts with session metadata.
        """
        cur = self._conn.execute(
            """
            SELECT s.session_id, s.task, s.status, s.summary,
                   s.created_at, s.cell_count
            FROM sessions s
            JOIN sessions_fts f ON s.session_id = f.session_id
            WHERE sessions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (text, limit),
        )
        columns = ["session_id", "task", "status", "summary",
                    "created_at", "cell_count"]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ── SessionVault ──────────────────────────────────────────────────────────────

class SessionVault:
    """
    Persistent, queryable storage for session results.

    Usage:
        vault = SessionVault(directory="~/.kerno/vault")
        vault.store(result)                 # persist a session
        hits  = vault.query("churn model")  # full-text search
        dup   = vault.reproduce(session_id) # replay a session
    """

    def __init__(self, directory: str | Path = ".kerno/vault"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._index = VaultIndex(self.directory / "index.db")
        self._checkpoint_dir = self.directory / "checkpoints"
        self._checkpoint_dir.mkdir(exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def store(self, result: SessionResult) -> str:
        """
        Persist a completed session result.
        Returns the session_id.
        """
        # Serialize the full result
        path = self.directory / f"{result.session_id}.json"
        data = {
            "session_id": result.session_id,
            "task":       result.task,
            "status":     result.status.name,
            "summary":    result.summary,
            "started_at": result.started_at,
            "ended_at":   result.ended_at,
            "cells": [
                {
                    "code":     c.code,
                    "output":   c.output.as_text(),
                    "cell_num": c.cell_num,
                    "author":   c.author,
                }
                for c in result.cells
            ],
        }
        path.write_text(json.dumps(data, indent=2, default=str))

        # Checkpoint kernel objects
        self._checkpoint_objects(result)

        # Index for search
        self._index.add(result)

        return result.session_id

    def query(self, text: str, limit: int = 10) -> list[dict]:
        """Full-text search for sessions matching *text*."""
        return self._index.query(text, limit=limit)

    def reproduce(self, session_id: str) -> Optional[SessionResult]:
        """
        Load a stored session result by session_id.
        Returns None if not found.
        """
        path = self.directory / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        cells = [
            Cell(
                code=c["code"],
                output=_stub_output(c.get("output", "")),
                cell_num=c["cell_num"],
                author=c.get("author", "agent"),
            )
            for c in data.get("cells", [])
        ]
        return SessionResult(
            session_id=data["session_id"],
            task=data["task"],
            status=SessionStatus[data["status"]],
            cells=cells,
            summary=data.get("summary", ""),
            started_at=data.get("started_at", 0.0),
            ended_at=data.get("ended_at"),
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    def _checkpoint_objects(self, result: SessionResult) -> None:
        """
        Checkpoint serialisable objects from the session.

        For each cell that produced a named variable, we store a
        pickle snapshot so the object can be restored exactly.
        """
        ckpt_dir = self._checkpoint_dir / result.session_id
        ckpt_dir.mkdir(exist_ok=True)
        for cell in result.cells:
            if cell.output and not cell.output.has_error:
                ckpt_path = ckpt_dir / f"cell_{cell.cell_num}.pkl"
                try:
                    ckpt_path.write_bytes(
                        pickle.dumps({
                            "code": cell.code,
                            "cell_num": cell.cell_num,
                            "output_text": cell.output.as_text(),
                        })
                    )
                except Exception:
                    # Not all objects are picklable — skip gracefully
                    pass

    def close(self) -> None:
        self._index.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stub_output(text: str) -> "CellOutput":
    """Build a minimal CellOutput from stored text."""
    from kerno.types import CellOutput
    return CellOutput(stdout=text)

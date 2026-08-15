"""
MemoryStore: the abstract interface for cross-session agent memory.

A MemoryStore answers one question:
  "Given what I'm doing now, what from past sessions is relevant?"

This is different from the kernel namespace (active session state)
and different from checkpoints (full object serialization).
Memory is semantic — it stores *meaning*, not *data*.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
import time
import uuid


@dataclass
class MemoryEntry:
    """
    One unit of stored memory.

    content:    The actual text or structured content
    kind:       "result" | "error" | "insight" | "skill" | "plan"
    session_id: Which session produced this
    task:       The task that was being executed
    score:      Relevance score (set during retrieval)
    metadata:   Arbitrary structured data
    """
    content:    str
    kind:       str
    session_id: str           = field(default_factory=lambda: "")
    task:       str           = ""
    entry_id:   str           = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float         = field(default_factory=time.time)
    score:      float         = 0.0
    metadata:   dict[str, Any] = field(default_factory=dict)


class MemoryStore(ABC):
    """
    Abstract interface for memory storage.

    Implement this to plug in:
      - SimpleMemoryStore (built-in, keyword search)
      - ChromaMemoryStore (semantic search via ChromaDB)
      - PineconeMemoryStore (managed vector search)
      - SQLiteMemoryStore (persistent, no ML required)
    """

    @abstractmethod
    def store(self, entry: MemoryEntry) -> str:
        """
        Persist a memory entry.
        Returns: entry_id
        """
        ...

    @abstractmethod
    def retrieve(
        self,
        query:   str,
        k:       int   = 5,
        kind:    Optional[str] = None,
        min_score: float = 0.0,
    ) -> list[MemoryEntry]:
        """
        Retrieve the k most relevant entries for a query.
        Optionally filter by kind.
        Returns entries sorted by relevance (highest first).
        """
        ...

    @abstractmethod
    def list(
        self,
        kind:       Optional[str] = None,
        session_id: Optional[str] = None,
        limit:      int           = 50,
    ) -> list[MemoryEntry]:
        """
        List entries, optionally filtered.
        Returns entries sorted by creation time (newest first).
        """
        ...

    @abstractmethod
    def delete(self, entry_id: str) -> bool:
        """Delete an entry. Returns True if found and deleted."""
        ...

    def store_session_result(
        self,
        session_id: str,
        task:       str,
        summary:    str,
        namespace:  str,
        metadata:   dict = None,
    ) -> str:
        """
        Convenience: store the result of a completed session.
        This is the primary way kerno populates memory.
        """
        content = (
            f"Task: {task}\n\n"
            f"Summary: {summary}\n\n"
            f"Final state: {namespace[:500]}"
        )
        entry = MemoryEntry(
            content    = content,
            kind       = "result",
            session_id = session_id,
            task       = task,
            metadata   = {
                **(metadata or {}),
                "has_summary":   bool(summary),
                "namespace_len": len(namespace),
            },
        )
        return self.store(entry)

    def store_error_pattern(
        self,
        error_class: str,
        context:     str,
        recovery:    str,
        session_id:  str = "",
    ) -> str:
        """Store a successful error recovery for future reference."""
        entry = MemoryEntry(
            content    = f"Error: {error_class}\nContext: {context}\nRecovery: {recovery}",
            kind       = "error",
            session_id = session_id,
            metadata   = {"error_class": error_class},
        )
        return self.store(entry)

    def store_insight(
        self,
        insight:    str,
        task:       str       = "",
        session_id: str       = "",
        metadata:   dict      = None,
    ) -> str:
        """Store a discovered insight for cross-session knowledge."""
        entry = MemoryEntry(
            content    = insight,
            kind       = "insight",
            session_id = session_id,
            task       = task,
            metadata   = metadata or {},
        )
        return self.store(entry)

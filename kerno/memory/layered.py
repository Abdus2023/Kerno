# kerno/memory/layered.py
"""
LayeredMemory — three distinct memory layers (audit #62/#63).

    Working memory   — current task context (minutes / current execution)
    Session memory   — persistent for the current agent/session (hours/days)
    Long-term memory — reusable knowledge (weeks/months)

The layers must NOT collapse into one generic "memory": each has a
different retention policy, retrieval weight, and purpose.

Kernel state is NOT memory (audit #63): `df`, `model`, `x` are
computational state held by the kernel. LayeredMemory stores SEMANTIC
entries only — results, insights, errors, skills, plans.

Usage:
    mem = LayeredMemory(
        working=MemoryStore(), session=SimpleMemoryStore(), long_term=...
    )
    # Same MemoryStore interface: store()/retrieve()/store_session_result()
    # Retrieval merges layers with the given weights.
"""

from __future__ import annotations

from typing import Optional

from kerno.memory.store import MemoryEntry, MemoryStore


class LayeredMemory(MemoryStore):
    """
    Composes three MemoryStores into one MemoryStore interface.

    - store() writes to ALL layers (each decides its own persistence).
    - retrieve() queries each layer and merges results, respecting the
      layer weights.
    - Working memory may be None → skip that layer entirely.
    """

    def __init__(
        self,
        working:   Optional[MemoryStore] = None,
        session:   Optional[MemoryStore] = None,
        long_term: Optional[MemoryStore] = None,
        *,
        working_weight:   float = 1.0,
        session_weight:   float = 1.0,
        long_term_weight: float = 0.5,   # older knowledge weighs less
    ):
        self.working   = working
        self.session   = session
        self.long_term = long_term
        self._weights = {
            "working":   working_weight,
            "session":   session_weight,
            "long_term": long_term_weight,
        }

    @property
    def layers(self) -> dict[str, Optional[MemoryStore]]:
        return {
            "working":   self.working,
            "session":   self.session,
            "long_term": self.long_term,
        }

    # ── MemoryStore interface ────────────────────────────────────────────

    def store(self, entry: MemoryEntry) -> str:
        """Write the entry to every configured layer."""
        entry_id = ""
        for layer in (self.working, self.session, self.long_term):
            if layer is not None:
                entry_id = layer.store(entry)
        return entry_id

    def store_session_result(
        self,
        session_id: str,
        task:       str,
        summary:    str,
        namespace:  str = "",
    ) -> None:
        """Store a completed session into session + long-term layers."""
        entry = MemoryEntry(
            content    = summary or "[no summary]",
            kind       = "result",
            session_id = session_id,
            task       = task,
            metadata   = {"namespace": namespace[:200]},
        )
        if self.session is not None:
            self.session.store(entry)
        if self.long_term is not None:
            self.long_term.store(entry)

    def retrieve(
        self,
        query:     str,
        k:         int  = 3,
        min_score: float = 0.0,
    ) -> list[MemoryEntry]:
        """
        Retrieve from every layer; merge with layer weights applied to
        each entry's score (so working/session context surfaces before
        long-term knowledge at equal relevance).
        """
        merged: list[MemoryEntry] = []
        for name, layer in self.layers.items():
            if layer is None:
                continue
            weight = self._weights.get(name, 1.0)
            for entry in layer.retrieve(query, k=k, min_score=min_score):
                entry.score = entry.score * weight
                merged.append(entry)
        merged.sort(key=lambda e: e.score, reverse=True)
        return merged[:k]

    def list(self) -> list[MemoryEntry]:
        """All entries across layers (working first)."""
        result: list[MemoryEntry] = []
        for layer in (self.working, self.session, self.long_term):
            if layer is not None:
                result.extend(layer.list())
        return result

    def delete(self, entry_id: str) -> bool:
        """Delete from every layer; True if any layer removed it."""
        removed = False
        for layer in (self.working, self.session, self.long_term):
            if layer is not None:
                removed = layer.delete(entry_id) or removed
        return removed

    def __len__(self) -> int:
        return sum(len(l) for l in (self.working, self.session, self.long_term) if l)

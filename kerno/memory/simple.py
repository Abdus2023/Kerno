"""
SimpleMemoryStore: keyword-based memory. No ML required.

Uses TF-IDF-like scoring for retrieval.
Fast, zero-dependency, good enough for development and small deployments.
For production semantic search, use a vector store.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from kerno.memory.store import MemoryEntry, MemoryStore


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r'\b[a-zA-Z0-9_]{2,}\b', text.lower())


class SimpleMemoryStore(MemoryStore):
    """
    In-memory store with keyword search and optional JSON persistence.

    Scoring uses TF-IDF with cosine similarity.
    O(n) retrieval — suitable for up to ~10,000 entries.

    Usage:
        store = SimpleMemoryStore(persist_path=".kerno/memory.json")
        store.store(MemoryEntry(content="...", kind="result", ...))
        results = store.retrieve("churn prediction accuracy", k=3)
    """

    def __init__(self, persist_path: Optional[str] = ".kerno/memory.json"):
        self._entries:  dict[str, MemoryEntry] = {}
        self._inverted: dict[str, set[str]]    = defaultdict(set)
        self._lock      = threading.Lock()
        self._persist_path = Path(persist_path) if persist_path else None

        if self._persist_path and self._persist_path.exists():
            self._load()

    # ── MemoryStore interface ──────────────────────────────────────────────────

    def store(self, entry: MemoryEntry) -> str:
        tokens = _tokenize(entry.content + " " + entry.task)

        with self._lock:
            self._entries[entry.entry_id] = entry
            for token in set(tokens):
                self._inverted[token].add(entry.entry_id)

        self._save()
        return entry.entry_id

    def retrieve(
        self,
        query:     str,
        k:         int   = 5,
        kind:      Optional[str] = None,
        min_score: float = 0.0,
    ) -> list[MemoryEntry]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        with self._lock:
            entries = dict(self._entries)
            inverted = dict(self._inverted)

        # Candidate selection via inverted index
        candidate_ids: set[str] = set()
        for token in query_tokens:
            candidate_ids.update(inverted.get(token, set()))

        # Score candidates
        n_docs    = len(entries) or 1
        query_tf  = Counter(query_tokens)
        scored    = []

        for eid in candidate_ids:
            entry = entries.get(eid)
            if not entry:
                continue
            if kind and entry.kind != kind:
                continue

            doc_tokens = _tokenize(entry.content + " " + entry.task)
            doc_tf     = Counter(doc_tokens)
            doc_len    = len(doc_tokens) or 1

            score = 0.0
            for token, qtf in query_tf.items():
                df  = len(inverted.get(token, set())) or 1
                idf = math.log(n_docs / df + 1)
                tf  = doc_tf.get(token, 0) / doc_len
                score += qtf * tf * idf

            if score >= min_score:
                entry_copy       = MemoryEntry(**entry.__dict__)
                entry_copy.score = round(score, 4)
                scored.append(entry_copy)

        scored.sort(key=lambda e: e.score, reverse=True)
        return scored[:k]

    def list(
        self,
        kind:       Optional[str] = None,
        session_id: Optional[str] = None,
        limit:      int           = 50,
    ) -> list[MemoryEntry]:
        with self._lock:
            entries = list(self._entries.values())

        if kind:
            entries = [e for e in entries if e.kind == kind]
        if session_id:
            entries = [e for e in entries if e.session_id == session_id]

        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            if entry_id not in self._entries:
                return False
            entry  = self._entries.pop(entry_id)
            tokens = _tokenize(entry.content + " " + entry.task)
            for token in set(tokens):
                self._inverted[token].discard(entry_id)

        self._save()
        return True

    # ── Persistence ────────────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self._persist_path:
            return

        self._persist_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            data = [
                {
                    "content":    e.content,
                    "kind":       e.kind,
                    "session_id": e.session_id,
                    "task":       e.task,
                    "entry_id":   e.entry_id,
                    "created_at": e.created_at,
                    "metadata":   e.metadata,
                }
                for e in self._entries.values()
            ]

        with open(self._persist_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        with open(self._persist_path) as f:
            data = json.load(f)

        for item in data:
            entry = MemoryEntry(
                content    = item["content"],
                kind       = item["kind"],
                session_id = item.get("session_id", ""),
                task       = item.get("task", ""),
                entry_id   = item.get("entry_id", ""),
                created_at = item.get("created_at", 0.0),
                metadata   = item.get("metadata", {}),
            )
            tokens = _tokenize(entry.content + " " + entry.task)
            self._entries[entry.entry_id] = entry
            for token in set(tokens):
                self._inverted[token].add(entry.entry_id)

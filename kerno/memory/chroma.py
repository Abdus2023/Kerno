"""
ChromaMemoryStore: semantic vector search using ChromaDB.

Drop-in replacement for SimpleMemoryStore when you need:
  - Semantic similarity (not just keyword matching)
  - Large memory stores (thousands of entries)
  - Cross-domain recall ("this is similar to a task I did 6 months ago")

Requires: pip install chromadb
"""

from __future__ import annotations

from typing import Optional

from kerno.memory.store import MemoryEntry, MemoryStore


class ChromaMemoryStore(MemoryStore):
    """
    Semantic memory store backed by ChromaDB.

    Usage:
        store = ChromaMemoryStore(
            collection_name = "kerno_memory",
            persist_path    = ".kerno/chroma",
        )
        store.store(MemoryEntry(content="...", kind="result"))
        results = store.retrieve("churn prediction", k=3)
    """

    def __init__(
        self,
        collection_name: str          = "kerno_memory",
        persist_path:    Optional[str] = ".kerno/chroma",
        embedding_fn:    Optional[callable] = None,
    ):
        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "ChromaDB is required for ChromaMemoryStore. "
                "Install with: pip install chromadb"
            )

        import chromadb

        if persist_path:
            self._client = chromadb.PersistentClient(path=persist_path)
        else:
            self._client = chromadb.EphemeralClient()

        # Use default embedding function (all-MiniLM-L6-v2 via sentence-transformers)
        # or a custom one provided by the caller
        chroma_kwargs = {}
        if embedding_fn:
            chroma_kwargs["embedding_function"] = embedding_fn

        self._collection = self._client.get_or_create_collection(
            name     = collection_name,
            metadata = {"hnsw:space": "cosine"},
            **chroma_kwargs,
        )

    # ── MemoryStore interface ──────────────────────────────────────────────────

    def store(self, entry: MemoryEntry) -> str:
        self._collection.add(
            documents  = [entry.content + " " + entry.task],
            metadatas  = [{
                "kind":       entry.kind,
                "session_id": entry.session_id,
                "task":       entry.task,
                "created_at": entry.created_at,
                **{k: str(v) for k, v in entry.metadata.items()
                   if isinstance(v, (str, int, float, bool))},
            }],
            ids = [entry.entry_id],
        )
        return entry.entry_id

    def retrieve(
        self,
        query:     str,
        k:         int            = 5,
        kind:      Optional[str]  = None,
        min_score: float          = 0.0,
    ) -> list[MemoryEntry]:
        if not query:
            return []

        where = {"kind": kind} if kind else None

        try:
            results = self._collection.query(
                query_texts = [query],
                n_results   = min(k, max(1, self._collection.count())),
                where       = where,
            )
        except Exception:
            return []

        entries = []
        if not results["ids"] or not results["ids"][0]:
            return []

        for i, entry_id in enumerate(results["ids"][0]):
            meta      = results["metadatas"][0][i]
            doc       = results["documents"][0][i]
            # ChromaDB returns distance (lower = better); convert to similarity score
            distance  = results.get("distances", [[]])[0][i] if results.get("distances") else 0.0
            score     = max(0.0, 1.0 - distance)

            if score < min_score:
                continue

            entry = MemoryEntry(
                content    = doc,
                kind       = meta.get("kind", "unknown"),
                session_id = meta.get("session_id", ""),
                task       = meta.get("task", ""),
                entry_id   = entry_id,
                created_at = float(meta.get("created_at", 0)),
                score      = round(score, 4),
            )
            entries.append(entry)

        entries.sort(key=lambda e: e.score, reverse=True)
        return entries

    def list(
        self,
        kind:       Optional[str] = None,
        session_id: Optional[str] = None,
        limit:      int           = 50,
    ) -> list[MemoryEntry]:
        where = {}
        if kind:
            where["kind"] = kind
        if session_id:
            where["session_id"] = session_id

        results = self._collection.get(
            where = where or None,
            limit = limit,
        )

        entries = []
        for i, entry_id in enumerate(results["ids"]):
            meta  = results["metadatas"][i]
            doc   = results["documents"][i]
            entry = MemoryEntry(
                content    = doc,
                kind       = meta.get("kind", "unknown"),
                session_id = meta.get("session_id", ""),
                task       = meta.get("task", ""),
                entry_id   = entry_id,
                created_at = float(meta.get("created_at", 0)),
            )
            entries.append(entry)

        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    def delete(self, entry_id: str) -> bool:
        try:
            self._collection.delete(ids=[entry_id])
            return True
        except Exception:
            return False

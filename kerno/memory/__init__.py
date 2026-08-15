# kerno/memory/__init__.py
from kerno.memory.store  import MemoryStore, MemoryEntry
from kerno.memory.simple import SimpleMemoryStore

__all__ = ["MemoryStore", "MemoryEntry", "SimpleMemoryStore"]

# Optional: ChromaDB-backed semantic memory
try:
    from kerno.memory.chroma import ChromaMemoryStore
    __all__.append("ChromaMemoryStore")
except ImportError:
    pass

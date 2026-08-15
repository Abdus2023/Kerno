"""
RAG bridge: connect Open WebUI's document store to the Kerno kernel.

Open WebUI sends RAG context in a specific format.
We extract it and materialize documents into the kernel.

Also provides direct RAG capability for Kerno sessions
independent of Open WebUI.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing      import Optional


@dataclass
class RAGDocument:
    """A document retrieved from the RAG store."""
    content:  str
    source:   str
    score:    float
    metadata: dict


class OpenWebUIRAGBridge:
    """
    Extracts RAG context injected by Open WebUI into messages
    and makes it available in the kernel namespace.

    Open WebUI injects RAG context as a system message like:
        "Use the following context to answer the question:
        [DOCUMENT 1]
        Source: filename.pdf
        Content: ...
        [DOCUMENT 2]
        ..."
    """

    DOC_PATTERN = re.compile(
        r'\[DOCUMENT \d+\]\s*'
        r'(?:Source:\s*(?P<source>[^\n]+)\n)?'
        r'(?:Content:\s*)?(?P<content>.+?)(?=\[DOCUMENT|\Z)',
        re.DOTALL
    )

    def __init__(self, kernel):
        self.kernel = kernel

    def extract_and_load(self, messages: list[dict]) -> list[RAGDocument]:
        """
        Find RAG context in messages and load it into the kernel.
        Returns the list of loaded documents.
        """
        docs = self._extract_documents(messages)
        if docs:
            self._load_into_kernel(docs)
        return docs

    def _extract_documents(self, messages: list[dict]) -> list[RAGDocument]:
        """Parse Open WebUI's RAG injection format."""
        docs = []
        for msg in messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content", "")
            if "DOCUMENT" not in content and "context" not in content.lower():
                continue

            for match in self.DOC_PATTERN.finditer(content):
                docs.append(RAGDocument(
                    content  = match.group("content").strip(),
                    source   = match.group("source") or "unknown",
                    score    = 1.0,
                    metadata = {},
                ))

        return docs

    def _load_into_kernel(self, docs: list[RAGDocument]) -> None:
        """Load RAG documents into kernel as a searchable list."""
        docs_repr = json.dumps([
            {"content": d.content[:2000], "source": d.source, "score": d.score}
            for d in docs
        ], indent=2)

        load_code = (
            f"import json as _json\n\n"
            f"# RAG documents loaded from conversation context\n"
            f"rag_documents = _json.loads({docs_repr!r})\n\n"
            f"def search_docs(query: str, top_k: int = 3) -> list:\n"
            f"    \"\"\"Search the loaded RAG documents by keyword.\"\"\"\n"
            f"    query_words = set(query.lower().split())\n"
            f"    scored = []\n"
            f"    for doc in rag_documents:\n"
            f"        doc_words = set(doc['content'].lower().split())\n"
            f"        overlap   = len(query_words & doc_words)\n"
            f"        scored.append((overlap, doc))\n"
            f"    scored.sort(key=lambda x: x[0], reverse=True)\n"
            f"    return [doc for _, doc in scored[:top_k]]\n\n"
            f"print(f'✓ Loaded {{len(rag_documents)}} RAG document(s)')\n"
            f"print(f'  Sources: {{[d[\"source\"] for d in rag_documents]}}')\n"
            f"print(f'  Use search_docs(\"query\") to retrieve relevant passages')\n"
        )
        self.kernel.execute(load_code, silent=False, timeout=10)

    def build_context_note(self, docs: list[RAGDocument]) -> str:
        """Tell the LLM about the available documents."""
        if not docs:
            return ""
        sources = [d.source for d in docs]
        return (
            f"\n\nRAG context loaded: {len(docs)} document(s) from "
            f"{sources}. "
            f"Use `rag_documents` to access them or `search_docs('query')` "
            f"to search."
        )

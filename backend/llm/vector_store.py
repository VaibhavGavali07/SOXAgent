"""ChromaDB-backed persistent vector store for SOX Agent.

Replaces the SQLite linear-scan approach with HNSW approximate nearest-
neighbour search.  At 10 k tickets the old approach loaded every row into
Python memory for every query; ChromaDB handles this in microseconds.

Falls back gracefully to a no-op store if ChromaDB is unavailable so the
rest of the application still starts.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "sox_violations"
_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")


class VectorStore:
    """Persistent ChromaDB-backed vector store."""

    def __init__(self) -> None:
        self._collection = None
        self._enabled = os.getenv("ENABLE_EMBEDDINGS", "true").lower() == "true"
        if self._enabled:
            self._init()

    def _init(self) -> None:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=_PERSIST_DIR)
            self._collection = client.get_or_create_collection(
                name=_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "VectorStore: ChromaDB ready at '%s' (%d docs)", _PERSIST_DIR, self._collection.count()
            )
        except Exception as exc:
            logger.warning("VectorStore: ChromaDB init failed (%s) — similarity search disabled", exc)
            self._enabled = False

    @property
    def available(self) -> bool:
        return self._enabled and self._collection is not None

    # ------------------------------------------------------------------

    def upsert(
        self,
        doc_id: str,
        vector: list[float],
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add or replace a document."""
        if not self.available or not vector:
            return
        try:
            self._collection.upsert(
                ids=[doc_id],
                embeddings=[vector],
                documents=[text[:1000]],
                metadatas=[metadata or {}],
            )
        except Exception as exc:
            logger.warning("VectorStore upsert failed for '%s': %s", doc_id, exc)

    def query(
        self,
        vector: list[float],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return top-N similar documents with similarity scores.

        ChromaDB returns cosine *distance* (0 = identical, 2 = opposite).
        We convert to similarity: ``1 - distance / 2``.
        """
        if not self.available or not vector:
            return []
        try:
            count = self._collection.count()
            if count == 0:
                return []
            kwargs: dict[str, Any] = {
                "query_embeddings": [vector],
                "n_results": min(n_results, count),
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                kwargs["where"] = where
            results = self._collection.query(**kwargs)
            output: list[dict[str, Any]] = []
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i]
                similarity = round(1.0 - distance / 2.0, 4)
                if similarity < 0.5:
                    continue
                output.append(
                    {
                        "id": doc_id,
                        "similarity": similarity,
                        "text": results["documents"][0][i],
                        "metadata": (results["metadatas"][0][i] if results["metadatas"] else {}),
                    }
                )
            return output
        except Exception as exc:
            logger.warning("VectorStore query failed: %s", exc)
            return []

    def delete(self, doc_id: str) -> None:
        if not self.available:
            return
        try:
            self._collection.delete(ids=[doc_id])
        except Exception as exc:
            logger.warning("VectorStore delete failed for '%s': %s", doc_id, exc)

    def count(self) -> int:
        if not self.available:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def clear(self) -> None:
        """Remove all documents (called by data-clear endpoint)."""
        if not self.available:
            return
        try:
            import chromadb
            client = chromadb.PersistentClient(path=_PERSIST_DIR)
            client.delete_collection(_COLLECTION_NAME)
            self._collection = client.get_or_create_collection(
                name=_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("VectorStore: collection cleared")
        except Exception as exc:
            logger.warning("VectorStore clear failed: %s", exc)


# Module-level singleton — shared across all AnalyzerService instances.
_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store

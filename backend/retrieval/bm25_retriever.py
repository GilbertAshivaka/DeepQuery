"""
Deep Query — BM25 Sparse Retriever

In-memory BM25 index rebuilt from ChromaDB chunk texts.
Used alongside dense vector retrieval for hybrid search.
"""

import logging
from typing import Dict, List

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


class BM25Retriever:
    """In-memory BM25 index for sparse keyword retrieval.

    The index is built from all chunk texts stored in ChromaDB.
    It is rebuilt on demand (startup, or when documents change).
    """

    def __init__(self):
        self._index: BM25Okapi | None = None
        self._corpus: List[Dict] = []
        self._tokenized_corpus: List[List[str]] = []

    def build_index(self, chunks: List[Dict]) -> None:
        """Build the BM25 index from chunk data.

        Args:
            chunks: List of dicts with 'id', 'text', 'collection', 'metadata'.
        """
        self._corpus = chunks
        self._tokenized_corpus = [
            self._tokenize(chunk.get("text", "")) for chunk in chunks
        ]

        if self._tokenized_corpus:
            self._index = BM25Okapi(self._tokenized_corpus)
            logger.info(f"BM25 index built with {len(chunks)} documents")
        else:
            self._index = None
            logger.warning("BM25 index is empty — no documents to index")

    def rebuild_from_chroma(self, collection_names: List[str]) -> None:
        """Rebuild the BM25 index from ChromaDB collections."""
        try:
            from vectorstore.chroma_store import chroma_store

            chunks = chroma_store.get_all_chunk_texts(collection_names)
            self.build_index(chunks)
        except Exception as e:
            logger.error(f"Failed to rebuild BM25 index: {e}")

    def search(
        self,
        query: str,
        allowed_collections: List[str],
        top_k: int = 20,
    ) -> List[Dict]:
        """Search the BM25 index.

        Args:
            query: Raw query string.
            allowed_collections: Only return results from these collections.
            top_k: Number of results to return.

        Returns:
            List of dicts with 'id', 'text', 'metadata', 'bm25_score'.
        """
        if self._index is None or not self._corpus:
            # Try to rebuild
            self.rebuild_from_chroma(allowed_collections)
            if self._index is None:
                return []

        tokenized_query = self._tokenize(query)
        scores = self._index.get_scores(tokenized_query)

        # Pair scores with corpus items and filter by collection
        scored_items = []
        for i, score in enumerate(scores):
            if score > 0 and i < len(self._corpus):
                item = self._corpus[i]
                if item.get("collection", "") in allowed_collections:
                    scored_items.append({
                        "id": item.get("id", ""),
                        "text": item.get("text", ""),
                        "document": item.get("text", ""),
                        "metadata": item.get("metadata", {}),
                        "bm25_score": float(score),
                        "collection": item.get("collection", ""),
                    })

        # Sort by BM25 score descending
        scored_items.sort(key=lambda x: x["bm25_score"], reverse=True)

        return scored_items[:top_k]

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace tokenization with lowercasing.

        For a production system, this could use NLTK or spaCy,
        but simple tokenization works well for BM25.
        """
        return text.lower().split()

    def add_document(self, chunk: Dict) -> None:
        """Add a single document to the index (incremental update)."""
        self._corpus.append(chunk)
        tokenized = self._tokenize(chunk.get("text", ""))
        self._tokenized_corpus.append(tokenized)

        # Rebuild the BM25 index (BM25Okapi doesn't support incremental adds)
        if self._tokenized_corpus:
            self._index = BM25Okapi(self._tokenized_corpus)


# ── Module-level singleton ───────────────────────────────────
bm25_retriever = BM25Retriever()

"""
Deep Query — BM25 Sparse Retriever

In-memory BM25 index rebuilt from ChromaDB chunk texts.
Maintains one index per collection for RBAC compliance.
Updated incrementally via Redis pub/sub.
"""

import logging
from typing import Dict, List

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


class BM25Retriever:
    """In-memory BM25 index for sparse keyword retrieval.

    Maintains one index per collection (academic, departmental, administrative, management).
    Indexes are built at server startup and updated incrementally via Redis pub/sub.
    """

    def __init__(self):
        # Per-collection indexes
        self._indexes: Dict[str, BM25Okapi] = {}
        self._corpuses: Dict[str, List[Dict]] = {}
        self._tokenized_corpuses: Dict[str, List[List[str]]] = {}

    def build_index_for_collection(self, collection_name: str, chunks: List[Dict]) -> None:
        """Build the BM25 index for a specific collection.

        Args:
            collection_name: Collection name (academic, departmental, etc.)
            chunks: List of dicts with 'id', 'text', 'metadata'.
        """
        self._corpuses[collection_name] = chunks
        self._tokenized_corpuses[collection_name] = [
            self._tokenize(chunk.get("text", "")) for chunk in chunks
        ]

        if self._tokenized_corpuses[collection_name]:
            self._indexes[collection_name] = BM25Okapi(self._tokenized_corpuses[collection_name])
            logger.info(f"BM25 index built for '{collection_name}' with {len(chunks)} documents")
        else:
            self._indexes[collection_name] = None
            logger.warning(f"BM25 index for '{collection_name}' is empty — no documents to index")

    def build_all_indexes(self) -> None:
        """Build BM25 indexes for all collections at startup."""
        try:
            from vectorstore.chroma_store import chroma_store
            from core.constants import Collection

            for collection in Collection:
                try:
                    chunks = chroma_store.get_all_chunk_texts([collection.value])
                    self.build_index_for_collection(collection.value, chunks)
                except Exception as e:
                    print(f"  ✗ ERROR building index for '{collection.value}': {e}")
                    logger.error(f"Failed to build BM25 index for '{collection.value}': {e}")

            logger.info("All BM25 indexes built successfully")
        except Exception as e:
            print(f"  ✗ FATAL ERROR building BM25 indexes: {e}")
            logger.error(f"Failed to build BM25 indexes: {e}")
            import traceback
            traceback.print_exc()

    def search(
        self,
        query: str,
        allowed_collections: List[str],
        top_k: int = 20,
    ) -> List[Dict]:
        """Search BM25 indexes across allowed collections.

        Args:
            query: Raw query string.
            allowed_collections: Only return results from these collections.
            top_k: Number of results to return.

        Returns:
            List of dicts with 'id', 'text', 'metadata', 'bm25_score'.
        """
        tokenized_query = self._tokenize(query)
        all_scored_items = []

        # Search each allowed collection's index
        for collection_name in allowed_collections:
            if collection_name not in self._indexes or self._indexes[collection_name] is None:
                logger.warning(f"BM25 index for '{collection_name}' not available")
                continue

            corpus = self._corpuses.get(collection_name, [])
            if not corpus:
                continue

            scores = self._indexes[collection_name].get_scores(tokenized_query)

            # Pair scores with corpus items
            for i, score in enumerate(scores):
                if score > 0 and i < len(corpus):
                    item = corpus[i]
                    all_scored_items.append({
                        "id": item.get("id", ""),
                        "text": item.get("text", ""),
                        "document": item.get("text", ""),
                        "metadata": item.get("metadata", {}),
                        "bm25_score": float(score),
                        "collection": collection_name,
                    })

        # Sort by BM25 score descending
        all_scored_items.sort(key=lambda x: x["bm25_score"], reverse=True)

        return all_scored_items[:top_k]

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace tokenization with lowercasing.

        For a production system, this could use NLTK or spaCy,
        but simple tokenization works well for BM25.
        """
        return text.lower().split()

    def add_chunks_to_collection(self, collection_name: str, chunks: List[Dict]) -> None:
        """Add chunks to a collection's index (incremental update).

        Args:
            collection_name: Collection to update.
            chunks: List of new chunks to add.
        """
        if collection_name not in self._corpuses:
            self._corpuses[collection_name] = []
            self._tokenized_corpuses[collection_name] = []

        for chunk in chunks:
            self._corpuses[collection_name].append(chunk)
            tokenized = self._tokenize(chunk.get("text", ""))
            self._tokenized_corpuses[collection_name].append(tokenized)

        # Rebuild the collection's BM25 index (BM25Okapi doesn't support incremental adds)
        if self._tokenized_corpuses[collection_name]:
            self._indexes[collection_name] = BM25Okapi(self._tokenized_corpuses[collection_name])
            logger.info(f"Updated BM25 index for '{collection_name}' (+{len(chunks)} chunks)")


# ── Module-level singleton ───────────────────────────────────
bm25_retriever = BM25Retriever()

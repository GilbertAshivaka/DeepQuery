"""
Deep Query — Cross-Encoder Reranker

Uses a lightweight cross-encoder model (ms-marco-MiniLM) to rerank
retrieval candidates by true relevance to the query.
"""

import logging
from typing import Dict, List

from core.config import settings

logger = logging.getLogger(__name__)


class Reranker:
    """Cross-encoder reranker for retrieval result refinement."""

    def __init__(self):
        self._model = None

    def _load_model(self):
        """Lazy-load the cross-encoder model."""
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    settings.reranker_model,
                    device=settings.reranker_device,
                )
                logger.info(
                    f"Reranker loaded: {settings.reranker_model} on {settings.reranker_device}"
                )
            except Exception as e:
                logger.error(f"Failed to load reranker model: {e}")
                self._model = None

    def rerank(
        self,
        query: str,
        candidates: List[Dict],
        top_n: int = 8,
    ) -> List[Dict]:
        """Rerank candidate results using the cross-encoder.

        Args:
            query: User's query string.
            candidates: List of retrieval result dicts (from RRF fusion).
            top_n: Number of top results to return after reranking.

        Returns:
            Reranked list of result dicts, sorted by relevance.
        """
        if not candidates:
            return []

        self._load_model()

        if self._model is None:
            # Fallback: return candidates sorted by existing score
            logger.warning("Reranker not available, returning candidates as-is")
            return candidates[:top_n]

        # Prepare query-document pairs
        pairs = []
        for item in candidates:
            text = item.get("document", item.get("text", ""))
            if not text:
                text = item.get("metadata", {}).get("summary", "")
            pairs.append((query, text[:512]))  # Truncate to 512 chars for cross-encoder

        try:
            # Score all pairs
            scores = self._model.predict(pairs)

            # Attach scores to candidates
            for i, score in enumerate(scores):
                candidates[i]["rerank_score"] = float(score)

            # Sort by rerank score (descending)
            candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

            return candidates[:top_n]

        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return candidates[:top_n]


# ── Module-level singleton ───────────────────────────────────
reranker = Reranker()

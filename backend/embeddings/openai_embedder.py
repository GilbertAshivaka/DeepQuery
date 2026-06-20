"""
Deep Query — OpenAI Embedder (text-only)

Wraps OpenAI / OpenAI-compatible embedding models (e.g. ``text-embedding-3-small`` /
``-large``) via ``langchain_openai.OpenAIEmbeddings``. Text-only — image and multimodal
chunks fall back to the text-only defaults in :class:`~embeddings.base.Embedder`.

``task_type`` is ignored (OpenAI has no task-type concept). ``dimensions`` is passed
through for the text-embedding-3 family, which supports output truncation.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from embeddings.base import Embedder

logger = logging.getLogger(__name__)


class OpenAIEmbedder(Embedder):
    provider = "openai"
    supports_multimodal = False

    def __init__(
        self,
        model: str,
        dimensions: int,
        api_key: str,
        base_url: Optional[str] = None,
    ):
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:  # optional dependency
            raise RuntimeError(
                "Provider 'openai' embedding selected but langchain-openai is not "
                "installed. Run: pip install langchain-openai"
            ) from exc

        self.model = model
        self.dimensions = int(dimensions)
        kwargs = dict(model=model, api_key=api_key)
        if base_url:
            kwargs["base_url"] = base_url
        # text-embedding-3 supports a configurable output dimension; older models don't.
        if "text-embedding-3" in model:
            kwargs["dimensions"] = self.dimensions
        self._client = OpenAIEmbeddings(**kwargs)

    def embed_text(
        self, text: str, task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> Optional[List[float]]:
        if not text or not text.strip():
            return None
        try:
            return self._client.embed_query(text)
        except Exception as e:
            logger.warning("OpenAI embed_text failed: %s", e)
            return None

    def embed_texts_batch(
        self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> List[Optional[List[float]]]:
        if not texts:
            return []
        try:
            return self._client.embed_documents(texts)
        except Exception as e:
            logger.warning("OpenAI embed_texts_batch failed: %s", e)
            return [None] * len(texts)

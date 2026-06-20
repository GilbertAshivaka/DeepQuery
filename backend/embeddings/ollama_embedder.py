"""
Deep Query — Ollama Embedder (local, text-only)

Wraps local Ollama embedding models (e.g. ``nomic-embed-text``, ``mxbai-embed-large``)
via ``langchain_ollama.OllamaEmbeddings``. The only embedding provider permitted in
air-gapped deployments. Text-only — image/multimodal chunks use the text-only fallbacks.

Output dimension is fixed by the model; the configured ``dimensions`` is recorded as the
collection identity and should match the model's actual output.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from core.config import settings
from embeddings.base import Embedder

logger = logging.getLogger(__name__)


class OllamaEmbedder(Embedder):
    provider = "ollama"
    supports_multimodal = False

    def __init__(self, model: str, dimensions: int, base_url: Optional[str] = None):
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError as exc:  # optional dependency
            raise RuntimeError(
                "Provider 'ollama' embedding selected but langchain-ollama is not "
                "installed. Run: pip install langchain-ollama"
            ) from exc

        self.model = model
        self.dimensions = int(dimensions)
        self._client = OllamaEmbeddings(
            model=model, base_url=base_url or settings.ollama_base_url
        )

    def embed_text(
        self, text: str, task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> Optional[List[float]]:
        if not text or not text.strip():
            return None
        try:
            return self._client.embed_query(text)
        except Exception as e:
            logger.warning("Ollama embed_text failed: %s", e)
            return None

    def embed_texts_batch(
        self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> List[Optional[List[float]]]:
        if not texts:
            return []
        try:
            return self._client.embed_documents(texts)
        except Exception as e:
            logger.warning("Ollama embed_texts_batch failed: %s", e)
            return [None] * len(texts)

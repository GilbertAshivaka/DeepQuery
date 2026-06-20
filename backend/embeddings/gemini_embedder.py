"""
Deep Query — Gemini Embedding 2 Wrapper

Handles text, image, and interleaved multimodal embedding via the
Google GenAI SDK (google-genai).

Model: gemini-embedding-2-preview
Output dimension: 3072 (default, highest quality)
"""

import logging
import time
from typing import List, Optional

from google import genai
from google.genai import types

from core.config import settings
from embeddings.base import Embedder

logger = logging.getLogger(__name__)


class GeminiEmbedder(Embedder):
    """Gemini Embedding 2 — text, native image, and interleaved multimodal embedding.

    The reference (and default) embedder. ``api_key`` / ``model`` / ``dimensions`` are
    injected by the factory so the same class serves any Gemini embedding config."""

    MAX_RETRIES = 3
    BASE_BACKOFF = 2.0  # seconds

    provider = "google"
    supports_multimodal = True

    def __init__(self, api_key: str = "", model: str = "", dimensions: int = 0):
        self.client = genai.Client(api_key=api_key or settings.google_api_key)
        self.model = model or settings.embedding_model
        self.model_name = self.model  # back-compat alias
        self.dimensions = dimensions or settings.embedding_dimensions

    def _embed_config(
        self, task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> types.EmbedContentConfig:
        """Build an EmbedContentConfig with standard settings."""
        return types.EmbedContentConfig(
            output_dimensionality=self.dimensions,
            task_type=task_type,
        )

    # ── Text ──────────────────────────────────────────────────

    def embed_text(
        self, text: str, task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> Optional[List[float]]:
        """Embed a single text string.

        Args:
            text: Plain text to embed (max 8192 tokens).
            task_type: Embedding task type (RETRIEVAL_DOCUMENT, RETRIEVAL_QUERY, etc.).

        Returns:
            Float vector, or None on failure.
        """
        if not text.strip():
            return None

        for attempt in range(self.MAX_RETRIES):
            try:
                result = self.client.models.embed_content(
                    model=self.model_name,
                    contents=text,
                    config=self._embed_config(task_type),
                )
                return result.embeddings[0].values

            except Exception as e:
                wait = self.BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    f"Gemini text embed attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)

        logger.error(f"Failed to embed text after {self.MAX_RETRIES} attempts.")
        return None

    def embed_texts_batch(
        self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> List[Optional[List[float]]]:
        """Embed multiple text strings in a batch request.

        Args:
            texts: List of text strings to embed.
            task_type: Embedding task type.

        Returns:
            List of embedding vectors (or None for failures).
        """
        if not texts:
            return []

        for attempt in range(self.MAX_RETRIES):
            try:
                result = self.client.models.embed_content(
                    model=self.model_name,
                    contents=texts,
                    config=self._embed_config(task_type),
                )
                return [emb.values for emb in result.embeddings]

            except Exception as e:
                wait = self.BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    f"Gemini batch embed attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)

        logger.error(f"Failed to batch embed {len(texts)} texts.")
        return [None] * len(texts)

    # ── Image ─────────────────────────────────────────────────

    def embed_image(
        self, image_bytes: bytes, image_format: str = "png"
    ) -> Optional[List[float]]:
        """Embed an image natively (no OCR required).

        Args:
            image_bytes: Raw PNG or JPEG bytes.
            image_format: 'png' or 'jpeg'.

        Returns:
            Float vector, or None on failure.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                mime_type = f"image/{image_format}"
                image_part = types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type,
                )

                result = self.client.models.embed_content(
                    model=self.model_name,
                    contents=[image_part],
                    config=self._embed_config(),
                )
                return result.embeddings[0].values

            except Exception as e:
                wait = self.BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    f"Gemini image embed attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)

        logger.error(f"Failed to embed image after {self.MAX_RETRIES} attempts.")
        return None

    # ── Multimodal ────────────────────────────────────────────

    def embed_multimodal(
        self, text: str, image_bytes: bytes, image_format: str = "png"
    ) -> Optional[List[float]]:
        """Embed interleaved text + image as a single aggregated vector.

        Used when a chunk contains both a figure caption and the figure itself.

        Args:
            text: Caption or descriptive text.
            image_bytes: Raw PNG/JPEG bytes.
            image_format: 'png' or 'jpeg'.

        Returns:
            Float vector, or None on failure.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                mime_type = f"image/{image_format}"
                content = types.Content(
                    parts=[
                        types.Part(text=text),
                        types.Part.from_bytes(
                            data=image_bytes,
                            mime_type=mime_type,
                        ),
                    ]
                )

                result = self.client.models.embed_content(
                    model=self.model_name,
                    contents=[content],
                    config=self._embed_config(),
                )
                return result.embeddings[0].values

            except Exception as e:
                wait = self.BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    f"Gemini multimodal embed attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)

        logger.error(f"Failed to embed multimodal content after {self.MAX_RETRIES} attempts.")
        return None

    # embed_chunks() is inherited from Embedder (the dispatcher is provider-agnostic).

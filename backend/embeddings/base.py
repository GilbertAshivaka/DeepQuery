"""
Deep Query — Embedder Interface

A provider-agnostic embedding contract. Concrete embedders (Gemini, OpenAI, Ollama)
implement ``embed_text`` / ``embed_texts_batch``; multimodal support is optional and
defaults to a text-only fallback so a text-only embedder degrades gracefully:

    - ``embed_image``      → None  (image-only chunks are skipped on text-only embedders)
    - ``embed_multimodal`` → embeds the caption text only (no native image vector)

Every embedder exposes its ``identity()`` — the ``(provider, model, dimensions)`` triple
bound to a Chroma collection and asserted on read (MODEL_VENDOR_PICKING_PLAN.md §7).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Mirrors Gemini's batch ceiling; small enough for every provider we support.
_BATCH_SIZE = 100


class Embedder(ABC):
    """Provider-agnostic embedding interface."""

    #: provider id (e.g. "google", "openai", "ollama")
    provider: str = ""
    #: provider-native model id
    model: str = ""
    #: output vector dimension
    dimensions: int = 0
    #: whether the embedder can natively embed images / interleaved image+text
    supports_multimodal: bool = False

    # ── Required ──────────────────────────────────────────────

    @abstractmethod
    def embed_text(
        self, text: str, task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> Optional[List[float]]:
        """Embed a single string. ``task_type`` is honored by providers that support it
        (Gemini) and ignored by those that don't."""

    @abstractmethod
    def embed_texts_batch(
        self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> List[Optional[List[float]]]:
        """Embed a batch of strings, returning one vector (or None) per input."""

    # ── Optional (text-only fallbacks) ───────────────────────

    def embed_image(
        self, image_bytes: bytes, image_format: str = "png"
    ) -> Optional[List[float]]:
        """Native image embedding. Text-only embedders return None — the chunk is then
        skipped at upsert (no vector). Override for multimodal providers."""
        return None

    def embed_multimodal(
        self, text: str, image_bytes: bytes, image_format: str = "png"
    ) -> Optional[List[float]]:
        """Interleaved image+text embedding. Text-only embedders fall back to embedding
        the caption text alone. Override for multimodal providers."""
        return self.embed_text(text)

    # ── Chunk dispatcher (provider-agnostic) ─────────────────

    def embed_chunks(self, chunks) -> List[Optional[List[float]]]:
        """Embed a list of DocumentChunk objects, routing each to the right modality:
        text → batched, image → embed_image, mixed → embed_multimodal."""
        embeddings: List[Optional[List[float]]] = []
        text_indices: List[int] = []
        text_contents: List[str] = []

        for i, chunk in enumerate(chunks):
            if chunk.chunk_type == "image" and chunk.image_bytes:
                embeddings.append(self.embed_image(chunk.image_bytes, chunk.image_format))
            elif chunk.chunk_type == "mixed" and chunk.image_bytes and chunk.text:
                embeddings.append(
                    self.embed_multimodal(chunk.text, chunk.image_bytes, chunk.image_format)
                )
            elif chunk.text.strip():
                text_indices.append(i)
                text_contents.append(chunk.text)
                embeddings.append(None)  # placeholder, filled below
            else:
                embeddings.append(None)

        for start in range(0, len(text_contents), _BATCH_SIZE):
            batch_texts = text_contents[start : start + _BATCH_SIZE]
            batch_indices = text_indices[start : start + _BATCH_SIZE]
            for idx, emb in zip(batch_indices, self.embed_texts_batch(batch_texts)):
                embeddings[idx] = emb

        return embeddings

    # ── Identity ─────────────────────────────────────────────

    def identity(self) -> Dict[str, object]:
        """The (provider, model, dimensions) triple recorded on a collection."""
        from embeddings.identity import KEY_DIMENSIONS, KEY_MODEL, KEY_PROVIDER

        return {
            KEY_PROVIDER: self.provider,
            KEY_MODEL: self.model,
            KEY_DIMENSIONS: int(self.dimensions),
        }

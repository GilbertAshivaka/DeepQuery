"""Deep Query — Embeddings package."""

from embeddings.base import Embedder
from embeddings.factory import (
    EmbedderError,
    build_embedder,
    clear_embedder_cache,
    get_embedder,
)

__all__ = [
    "Embedder",
    "get_embedder",
    "build_embedder",
    "clear_embedder_cache",
    "EmbedderError",
]

"""
Deep Query — Embedder Factory

Resolves the active embedding provider/model from the DB-backed config (role
``embedding``), falling back to env settings, and builds the matching
:class:`~embeddings.base.Embedder`. Keys resolve BYOK-first then managed env. The active
embedder is cached and rebuilt when the config version bumps (same cross-worker
invalidation bus as the LLM factory).

Air-gapped deployments may use only a local embedding provider (ollama).

``build_embedder`` builds an embedder from an explicit config without touching the cache
or the active selection — used by the re-index job to construct the *target* embedder
while the current one keeps serving live traffic.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.config import settings
from embeddings.base import Embedder

logger = logging.getLogger(__name__)

EMBEDDING_PROVIDERS = {"google", "openai", "ollama", "qwen"}
EMBEDDING_LOCAL_PROVIDERS = {"ollama"}


class EmbedderError(RuntimeError):
    """Raised when the embedder cannot be built (bad config, missing key/dependency, or
    a deployment-mode violation)."""


def _assert_deployment_allows(provider: str) -> None:
    mode = settings.deployment_mode.lower().strip()
    if mode == "air-gapped" and provider not in EMBEDDING_LOCAL_PROVIDERS:
        raise EmbedderError(
            f"Deployment mode 'air-gapped' forbids embedding provider '{provider}'. "
            f"Use a local provider ({', '.join(sorted(EMBEDDING_LOCAL_PROVIDERS))})."
        )
    if provider not in EMBEDDING_PROVIDERS:
        raise EmbedderError(
            f"Unknown embedding provider '{provider}'. "
            f"Supported: {', '.join(sorted(EMBEDDING_PROVIDERS))}."
        )


def build_embedder(
    provider: str,
    model: str,
    dimensions: int,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Embedder:
    """Build an embedder from an explicit config (uncached). Enforces deployment rules."""
    from agents.models import provider_keys

    provider = (provider or "").lower().strip()
    _assert_deployment_allows(provider)

    if provider == "google":
        # Don't hard-fail on a missing key at build time: GeminiEmbedder constructs fine
        # and fails lazily at call (returning None), preserving the existing behavior the
        # ingestion/retrieval paths rely on.
        key = api_key or provider_keys.resolve_api_key("google") or ""
        from embeddings.gemini_embedder import GeminiEmbedder

        return GeminiEmbedder(api_key=key, model=model, dimensions=dimensions)

    if provider == "openai":
        key = api_key or provider_keys.resolve_api_key("openai")
        if not key:
            raise EmbedderError("No API key for embedding provider 'openai'.")
        from embeddings.openai_embedder import OpenAIEmbedder

        return OpenAIEmbedder(
            model=model,
            dimensions=dimensions,
            api_key=key,
            base_url=base_url or settings.openai_base_url or None,
        )

    if provider == "ollama":
        from embeddings.ollama_embedder import OllamaEmbedder

        return OllamaEmbedder(
            model=model, dimensions=dimensions, base_url=base_url or settings.ollama_base_url
        )

    if provider == "qwen":
        # Qwen embeddings (DashScope text-embedding-v*) via the OpenAI-compatible endpoint.
        key = api_key or provider_keys.resolve_api_key("qwen")
        if not key:
            raise EmbedderError("No API key for embedding provider 'qwen'.")
        from embeddings.openai_embedder import OpenAIEmbedder

        return OpenAIEmbedder(
            model=model,
            dimensions=dimensions,
            api_key=key,
            base_url=base_url or settings.qwen_base_url,
        )

    raise EmbedderError(f"Unknown embedding provider '{provider}'.")


def _active_config() -> tuple[str, str, int, Optional[str]]:
    """(provider, model, dimensions, base_url) of the active embedding config — DB row
    if present, else env settings."""
    try:
        from agents.models import config_store

        row = config_store.resolve_role("embedding")
        if row and row.get("provider") and row.get("model"):
            params = row.get("params") or {}
            dims = int(params.get("dimensions", settings.embedding_dimensions))
            return row["provider"], row["model"], dims, row.get("base_url")
    except Exception as exc:
        logger.debug("active embedding config fell back to env (%s)", exc)
    return (
        settings.embedding_provider,
        settings.embedding_model,
        int(settings.embedding_dimensions),
        None,
    )


# Single cached active embedder, keyed on the config version.
_CACHE: dict = {}


def get_embedder() -> Embedder:
    """The active embedder for live ingest/query. Cached; rebuilt on a config change."""
    from agents.models import config_store

    version = config_store.current_version()
    cached = _CACHE.get(version)
    if cached is not None:
        return cached

    _CACHE.clear()  # only ever one active embedder
    provider, model, dims, base_url = _active_config()
    embedder = build_embedder(provider, model, dims, base_url=base_url)
    _CACHE[version] = embedder
    logger.info(
        "Resolved embedder → provider=%s model=%s dims=%s (v=%s)",
        provider,
        model,
        dims,
        version,
    )
    return embedder


def clear_embedder_cache() -> None:
    """Drop the cached active embedder (after a config change in-process, or in tests)."""
    _CACHE.clear()

"""
Deep Query — Embedding Identity

The triple ``(provider, model, dimensions)`` that uniquely identifies the vector space a
set of embeddings lives in. It is recorded in each Chroma collection's metadata and
asserted on every read/write so a vendor/model switch can never silently query the wrong
space — a mismatch fails loud instead (see MODEL_VENDOR_PICKING_PLAN.md §7.1).

This is intentionally tiny and dependency-free (reads ``settings`` only) so both the
embedder layer and the vector store can use it without an import cycle.
"""

from __future__ import annotations

from typing import Dict

from core.config import settings

# Chroma metadata keys for the recorded identity (kept distinct from hnsw:* keys).
KEY_PROVIDER = "embedding_provider"
KEY_MODEL = "embedding_model"
KEY_DIMENSIONS = "embedding_dimensions"

IDENTITY_KEYS = (KEY_PROVIDER, KEY_MODEL, KEY_DIMENSIONS)


def active_embedding_identity() -> Dict[str, object]:
    """The embedding identity currently in force — the active DB-backed embedding config
    if present, else env settings. Values are Chroma-metadata-safe (str/int), so this can
    be merged straight into a collection's metadata."""
    try:
        from agents.models import config_store

        row = config_store.resolve_role("embedding")
        if row and row.get("provider") and row.get("model"):
            params = row.get("params") or {}
            return {
                KEY_PROVIDER: row["provider"],
                KEY_MODEL: row["model"],
                KEY_DIMENSIONS: int(params.get("dimensions", settings.embedding_dimensions)),
            }
    except Exception:
        pass
    return {
        KEY_PROVIDER: settings.embedding_provider,
        KEY_MODEL: settings.embedding_model,
        KEY_DIMENSIONS: int(settings.embedding_dimensions),
    }


def extract_identity(metadata: Dict | None) -> Dict[str, object] | None:
    """Pull a recorded identity out of a collection's metadata, or ``None`` if the
    collection predates the guardrail (legacy collection, no identity recorded)."""
    if not metadata:
        return None
    if not all(k in metadata for k in IDENTITY_KEYS):
        return None
    return {
        KEY_PROVIDER: metadata[KEY_PROVIDER],
        KEY_MODEL: metadata[KEY_MODEL],
        KEY_DIMENSIONS: int(metadata[KEY_DIMENSIONS]),
    }


def identity_matches(recorded: Dict[str, object], active: Dict[str, object]) -> bool:
    """Whether a recorded identity matches the active one across all three fields."""
    return all(recorded.get(k) == active.get(k) for k in IDENTITY_KEYS)


def describe(identity: Dict[str, object] | None) -> str:
    """Human-readable one-liner for logs/errors."""
    if not identity:
        return "<none>"
    return (
        f"{identity.get(KEY_PROVIDER)}/{identity.get(KEY_MODEL)}"
        f"@{identity.get(KEY_DIMENSIONS)}d"
    )

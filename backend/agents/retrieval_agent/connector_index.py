"""
Deep Query — Connector Semantic Index (scalable connector resolution)

The connector pre-selection step (live.py) decides which connectors to even open for a
query. Showing the model the full connector list works for a handful of connectors but
does not scale: a deployment with thousands of registered MCP servers cannot fit its
catalog in a prompt. This module is the scale path — instead of the model picking from a
shown list, the model emits *what it wants* (intent phrases + name guesses) and we resolve
that against the catalog here, so prompt size never depends on connector count.

Resolution is two-layered (cheap → semantic):
  1. Name/alias fast-path — exact/substring match on connector names (free, no embedding).
  2. Semantic search — embed the intent and rank connectors by cosine similarity over their
     name+summary embeddings (the same Gemini embedder the corpus uses).

Embeddings are *persisted* in a dedicated Chroma collection so they survive restarts: a
connector is embedded only when it is new or its name/summary changed. On a cold cache the
index hydrates from Chroma (no embedding calls); only genuinely new/changed connectors hit
the embedder. The per-query cost is then one query embedding plus cosine over the cached
vectors. Everything degrades gracefully — if Chroma is unreachable the resolver falls back
to a purely in-process cache, and if the embedder is unavailable ``resolve`` returns None
and the caller falls back to the lexical path. No connector routing ever hard-depends on
either being up.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any, Optional

from core.config import settings

logger = logging.getLogger(__name__)

# connector_id -> (source_text, vector). Keyed by id; re-embedded when source_text changes.
# Hydrated from the persistent Chroma collection on a cold cache.
_VECTORS: dict[str, tuple[str, list[float]]] = {}
_lock = threading.Lock()

_EMBED_BATCH = 100             # Gemini batch limit (mirrors ingestion.embed_chunks)
_COLLECTION = "connector_index"  # Chroma collection holding the persisted vectors


def clear_connector_index() -> None:
    """Drop the in-process cache (e.g. after a manifest/summary change). Persisted vectors
    in Chroma are kept and re-hydrated on next use; a connector whose text actually changed
    is detected and re-embedded then, so the persisted copy self-heals."""
    with _lock:
        _VECTORS.clear()


def _connector_text(c: dict[str, Any]) -> str:
    """The text we embed for a connector: its name plus its control-plane summary."""
    return f"{c['connector']}. {c.get('summary', '')}".strip()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def name_matches(guess: str, connectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Name fast-path: connectors whose name matches a model's name guess (case-insensitive
    exact or substring either way, so "Gmail" matches "Gmail (Google Workspace)")."""
    g = (guess or "").strip().lower()
    if not g:
        return []
    out = []
    for c in connectors:
        n = c["connector"].strip().lower()
        if g == n or g in n or n in g:
            out.append(c)
    return out


def _hydrate_from_store(ids: list[str]) -> None:
    """Load persisted (text, vector) for the given connector ids into the in-process cache,
    so a cold cache after restart costs a single Chroma read instead of re-embedding.
    Best-effort: a Chroma miss/error just leaves those ids to be (re)embedded."""
    if not ids:
        return
    try:
        from vectorstore.chroma_store import chroma_store
        coll = chroma_store.get_collection(_COLLECTION)
        res = coll.get(ids=ids, include=["embeddings", "metadatas"])
    except Exception as exc:
        logger.warning("Connector index hydrate skipped (Chroma unavailable): %s", exc)
        return
    # Explicit None checks: Chroma may return embeddings as a NumPy array, and
    # `array or []` raises on the array's ambiguous truth value.
    got_ids = res.get("ids")
    embeds = res.get("embeddings")
    metas = res.get("metadatas")
    got_ids = list(got_ids) if got_ids is not None else []
    embeds = embeds if embeds is not None else []
    metas = metas if metas is not None else []
    with _lock:
        for i, cid in enumerate(got_ids):
            vec = embeds[i] if i < len(embeds) else None
            text = (metas[i] or {}).get("text", "") if i < len(metas) else ""
            if vec is not None and cid not in _VECTORS:
                _VECTORS[cid] = (text, list(vec))


def _persist_to_store(items: list[tuple[str, str, list[float]]]) -> None:
    """Upsert newly embedded connectors into the persistent Chroma collection."""
    if not items:
        return
    try:
        from vectorstore.chroma_store import chroma_store
        coll = chroma_store.get_collection(_COLLECTION)
        coll.upsert(
            ids=[cid for cid, _, _ in items],
            embeddings=[vec for _, _, vec in items],
            documents=[text for _, text, _ in items],
            metadatas=[{"text": text} for _, text, _ in items],
        )
    except Exception as exc:
        logger.warning("Connector index persist skipped (Chroma unavailable): %s", exc)


def _ensure_embedded(connectors: list[dict[str, Any]]) -> bool:
    """Make sure every connector has a current embedding. Hydrates from the persistent store
    first (no embedding cost), then embeds only the new/changed ones (batched) and persists
    them. Returns False if the embedder is needed but unavailable, so the caller can fall
    back to a non-semantic path."""
    # 1. Warm the cache from Chroma for anything we don't already hold in-process.
    if settings.agent_connector_index_persist:
        with _lock:
            cold = [c["connector_id"] for c in connectors if c["connector_id"] not in _VECTORS]
        _hydrate_from_store(cold)

    # 2. What still needs embedding: genuinely new connectors or ones whose text changed.
    pending: list[tuple[str, str]] = []
    with _lock:
        for c in connectors:
            cid, text = c["connector_id"], _connector_text(c)
            cached = _VECTORS.get(cid)
            if cached is None or cached[0] != text:
                pending.append((cid, text))
    if not pending:
        return True

    try:
        from embeddings import get_embedder
        embedder = get_embedder()
    except Exception as exc:  # embedder not importable/buildable (e.g. SDK/key missing)
        logger.warning("Connector semantic index unavailable (embedder unavailable): %s", exc)
        return False

    for start in range(0, len(pending), _EMBED_BATCH):
        chunk = pending[start:start + _EMBED_BATCH]
        try:
            vectors = embedder.embed_texts_batch(
                [t for _, t in chunk], task_type="RETRIEVAL_DOCUMENT"
            )
        except Exception as exc:
            logger.warning("Connector embedding batch failed: %s", exc)
            return False
        fresh: list[tuple[str, str, list[float]]] = []
        with _lock:
            for (cid, text), vec in zip(chunk, vectors):
                if vec:
                    _VECTORS[cid] = (text, vec)
                    fresh.append((cid, text, vec))
        if settings.agent_connector_index_persist:
            _persist_to_store(fresh)
    return True


def resolve(
    intent_phrases: list[str],
    connectors: list[dict[str, Any]],
    *,
    top_k: int,
    min_score: float,
) -> Optional[list[dict[str, Any]]]:
    """Rank connectors by semantic similarity to the intent phrases. Returns the top_k
    above ``min_score`` (cosine), or None if the embedder is unavailable (→ caller falls
    back). An empty list means "nothing cleared the threshold" — a real, honored answer."""
    phrases = [p for p in (intent_phrases or []) if p and p.strip()]
    if not phrases:
        return []
    if not _ensure_embedded(connectors):
        return None

    try:
        from embeddings import get_embedder
        qvec = get_embedder().embed_text(" ; ".join(phrases), task_type="RETRIEVAL_QUERY")
    except Exception as exc:
        logger.warning("Connector intent embedding failed: %s", exc)
        return None
    if not qvec:
        return None

    scored: list[tuple[float, dict[str, Any]]] = []
    with _lock:
        for c in connectors:
            cached = _VECTORS.get(c["connector_id"])
            if cached is not None:
                scored.append((_cosine(qvec, cached[1]), c))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [c for score, c in scored if score >= min_score][:top_k]

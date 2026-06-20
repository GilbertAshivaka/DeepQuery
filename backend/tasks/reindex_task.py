"""
Deep Query — Embedding Re-index Celery Task

Switching the embedding vendor/model invalidates the entire vector index (a new model =
a new vector space). This task performs a safe **blue-green re-index** (MODEL_VENDOR_
PICKING_PLAN.md §7.3):

  1. Build the *target* embedder (the active one keeps serving live traffic untouched).
  2. Re-embed every chunk's stored text into shadow collections (``{name}__{version}``).
     Re-embed ONLY — no re-parse, no OCR, no entity/metadata, no Neo4j (those are
     embedding-independent; re-running them would mutate the graph for no benefit).
  3. On success, atomically promote: write the target as the active embedding config
     with the new ``collection_version``. Old collections are left in place for rollback.

Image/mixed chunks are re-embedded from their stored caption/OCR text (text-only target
embedders have no native image vector — see the Embedder fallbacks).

Progress is published to Redis (``reindex:status``) for the admin UI to poll.
"""

import logging
from datetime import datetime, timezone

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

STATUS_KEY = "reindex:status"
_STATUS_TTL = 24 * 3600
_BATCH = 100


def _set_status(payload: dict) -> None:
    try:
        from core.redis_client import redis_client

        redis_client.set_json(STATUS_KEY, payload, ttl_seconds=_STATUS_TTL)
    except Exception as exc:
        logger.debug("reindex status write failed (%s)", exc)


def get_status() -> dict:
    try:
        from core.redis_client import redis_client

        return redis_client.get_json(STATUS_KEY) or {"state": "idle"}
    except Exception:
        return {"state": "unknown"}


@celery_app.task(
    name="tasks.reindex_embeddings",
    bind=True,
    max_retries=0,
    soft_time_limit=3 * 3600,
    time_limit=3 * 3600 + 300,
)
def reindex_embeddings(self, provider: str, model: str, dimensions: int, base_url: str = None) -> dict:
    """Re-embed all collections with the target embedder, then promote it active."""
    from core.constants import Collection
    from embeddings import build_embedder
    from embeddings.identity import describe
    from vectorstore.chroma_store import chroma_store

    started = datetime.now(timezone.utc)
    new_version = "v" + started.strftime("%Y%m%d%H%M%S")
    base = {
        "state": "running",
        "job_id": self.request.id,
        "target": {"provider": provider, "model": model, "dimensions": dimensions},
        "new_version": new_version,
        "started_at": started.isoformat(),
        "collections": {},
    }
    _set_status(base)

    # 1. Build the target embedder (fail fast on bad key/dependency/config).
    try:
        target = build_embedder(provider, model, int(dimensions), base_url=base_url)
        identity = target.identity()
    except Exception as exc:
        logger.error("Re-index aborted — target embedder build failed: %s", exc)
        base.update(state="failed", error=str(exc))
        _set_status(base)
        return base

    logger.info("Re-index → %s (version %s)", describe(identity), new_version)

    total_written = 0
    try:
        for col in Collection:
            logical = col.value
            chunks = chroma_store.get_all_chunk_texts([logical])  # from ACTIVE collections
            base["collections"][logical] = {"total": len(chunks), "written": 0}
            _set_status(base)

            shadow = chroma_store.get_physical_collection(
                f"{logical}__{new_version}", identity=identity
            )

            for start in range(0, len(chunks), _BATCH):
                batch = chunks[start : start + _BATCH]
                texts = [c.get("text") or "" for c in batch]
                vectors = target.embed_texts_batch(texts)

                ids, embs, docs, metas = [], [], [], []
                for c, v in zip(batch, vectors):
                    if v is None:
                        continue
                    ids.append(c["id"])
                    embs.append(v)
                    docs.append(c.get("text") or "")
                    metas.append(c.get("metadata") or {})

                if ids:
                    shadow.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)
                    total_written += len(ids)
                    base["collections"][logical]["written"] += len(ids)
                    _set_status(base)

        # 2. Promote: make the target the active embedding config + flip the pointer.
        from agents.models import config_store

        config_store.set_role(
            role="embedding",
            provider=provider,
            model=model,
            base_url=base_url,
            params={"dimensions": int(dimensions), "collection_version": new_version},
        )

        base.update(
            state="complete",
            written=total_written,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        _set_status(base)
        logger.info("Re-index complete: %d vectors → version %s (promoted)", total_written, new_version)
        return base

    except Exception as exc:
        logger.error("Re-index failed during embedding: %s", exc, exc_info=True)
        base.update(state="failed", error=str(exc))
        _set_status(base)
        return base

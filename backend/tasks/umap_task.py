"""
Deep Query — UMAP Similarity Map Celery Task

Fetches all document-level embeddings from ChromaDB, runs UMAP to project
them to 2-D, and persists the coordinates back to the documents table.

The task is:
  • Triggered automatically by celery beat (nightly via settings.celery_beat_schedule)
  • Triggered manually via POST /api/admin/recompute-similarity-map
"""

import logging
from datetime import datetime, timezone

import numpy as np
from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_MIN_DOCS_FOR_UMAP = 5


@celery_app.task(
    name="tasks.compute_umap_coordinates",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=600,
    time_limit=900,
)
def compute_umap_coordinates(self) -> dict:
    """Compute 2-D UMAP projections for all non-deleted documents.

    Returns:
        dict with 'processed', 'skipped', 'error' counts.
    """
    logger.info("UMAP task started")

    try:
        import umap
    except ImportError:
        logger.error("umap-learn is not installed — run: pip install umap-learn")
        return {"processed": 0, "skipped": 0, "error": "umap-learn not installed"}

    from core.database import SessionLocal
    from models.database import Document
    from vectorstore.chroma_store import chroma_store

    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(Document.is_deleted == False)
            .all()
        )

        if len(docs) < _MIN_DOCS_FOR_UMAP:
            logger.warning(
                f"Only {len(docs)} documents — need at least {_MIN_DOCS_FOR_UMAP} for UMAP"
            )
            return {"processed": 0, "skipped": len(docs), "error": None}

        # ── Fetch one embedding per document from ChromaDB ────────────
        doc_ids: list[str] = []
        embeddings: list[list[float]] = []

        for doc in docs:
            try:
                # Use the collection that owns this document
                collection = chroma_store.client.get_collection(doc.collection)
                results = collection.get(
                    where={"source_document_id": doc.id},
                    include=["embeddings"],
                    limit=1,
                )
                # ChromaDB returns embeddings as a numpy ndarray, so test
                # length explicitly — `if ndarray` raises "ambiguous truth value".
                embs = results["embeddings"]
                if embs is not None and len(embs) > 0:
                    emb = embs[0]
                    doc_ids.append(doc.id)
                    embeddings.append(emb)
            except Exception as e:
                logger.warning(f"Could not fetch embedding for doc {doc.id}: {e}")

        if len(doc_ids) < _MIN_DOCS_FOR_UMAP:
            logger.warning(f"Only {len(doc_ids)} embeddings retrieved — skipping UMAP")
            return {"processed": 0, "skipped": len(docs), "error": None}

        logger.info(f"Running UMAP on {len(doc_ids)} document embeddings")

        # ── Run UMAP ──────────────────────────────────────────────────
        emb_matrix = np.array(embeddings, dtype=np.float32)
        n_neighbors = min(15, len(doc_ids) - 1)

        reducer = umap.UMAP(
            n_components=2,
            n_neighbors=n_neighbors,
            min_dist=0.1,
            metric="cosine",
            random_state=42,
            low_memory=True,
        )
        coords_2d = reducer.fit_transform(emb_matrix)

        # ── Persist coordinates ───────────────────────────────────────
        now = datetime.now(timezone.utc)
        doc_map = {d.id: d for d in docs}

        for doc_id, (x, y) in zip(doc_ids, coords_2d):
            doc = doc_map.get(doc_id)
            if doc:
                doc.umap_x = float(x)
                doc.umap_y = float(y)
                doc.umap_computed_at = now

        db.commit()
        logger.info(f"UMAP task completed — {len(doc_ids)} documents updated")
        return {"processed": len(doc_ids), "skipped": len(docs) - len(doc_ids), "error": None}

    except Exception as exc:
        logger.error(f"UMAP task failed: {exc}", exc_info=True)
        db.rollback()
        self.retry(exc=exc)
    finally:
        db.close()

"""
Deep Query — Skill Synchronization Task

Fires when a document finishes ingesting (enqueued by the ingestion task). The
Skill Sync Agent (Phase 4 / Sprint 8) resolves which skill files depend on the
changed document and proposes admin-reviewable diffs. Driven by ingestion events,
never by user queries (guide §11).
"""

import logging

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.skill_sync_on_ingest",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def skill_sync_on_ingest(self, document_id: str, job_id: str | None = None) -> dict:
    """Handle a 'document fully ingested' event: resolve dependent skills and propose
    grounded, admin-gated edits to their corpus-fact sections."""
    logger.info("Skill-sync event: document %s fully ingested", document_id)
    try:
        # Sprint 8 provides the resolver/proposer; absent until then.
        from agents.skill_sync import run_sync_for_document
    except Exception:
        run_sync_for_document = None

    if run_sync_for_document is None:
        return {"document_id": document_id, "status": "received", "proposals": 0}
    try:
        return run_sync_for_document(document_id)
    except Exception as exc:  # never let sync failure affect ingestion
        logger.error("Skill sync failed for document %s: %s", document_id, exc, exc_info=True)
        return {"document_id": document_id, "status": "error", "error": str(exc)}

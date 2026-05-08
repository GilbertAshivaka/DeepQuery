"""
Deep Query — Ingestion Celery Task

Async task that runs the full document ingestion pipeline.
"""

import logging

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.run_ingestion_pipeline",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def run_ingestion_pipeline(self, document_id: str, job_id: str) -> dict:
    """Run the full ingestion pipeline for a document.

    This task is enqueued when an admin uploads a document.
    It runs asynchronously via Celery so the upload API returns immediately.

    Args:
        document_id: UUID of the Document record.
        job_id: UUID of the IngestionJob record.

    Returns:
        dict with pipeline results.
    """
    logger.info(f"Starting ingestion task for document={document_id}, job={job_id}")

    try:
        # Ensure backend/ is on sys.path for the worker process
        import os, sys
        _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _backend_dir not in sys.path:
            sys.path.insert(0, _backend_dir)

        from ingestion.pipeline import IngestionPipeline

        pipeline = IngestionPipeline()
        result = pipeline.run(document_id=document_id, job_id=job_id)

        logger.info(f"Ingestion task complete for document={document_id}: {result}")
        return result

    except Exception as exc:
        logger.error(
            f"Ingestion task failed for document={document_id}: {exc}",
            exc_info=True,
        )
        # Retry on transient failures
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        raise


# Alias for the import in documents.py
run_ingestion = run_ingestion_pipeline

"""
Deep Query — Ingestion Celery Task

Async task that runs the full document ingestion pipeline.
"""

import logging

from celery.exceptions import SoftTimeLimitExceeded
from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.run_ingesticd on_pipeline",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=2400,   # 40 min
    time_limit=2700,        # 45 min hard kill
)
def run_ingestion_pipeline(self, document_id: str, job_id: str) -> dict:
    logger.info(f"Starting ingestion task for document={document_id}, job={job_id}")

    try:
        import os, sys
        _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _backend_dir not in sys.path:
            sys.path.insert(0, _backend_dir)

        from ingestion.pipeline import IngestionPipeline

        pipeline = IngestionPipeline()
        result = pipeline.run(document_id=document_id, job_id=job_id)

        logger.info(f"Ingestion task complete for document={document_id}: {result}")

        try:
            from tasks.skill_sync_task import skill_sync_on_ingest
            skill_sync_on_ingest.delay(document_id, job_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to enqueue skill-sync event for {document_id}: {e}")

        return result

    except SoftTimeLimitExceeded:
        logger.error(
            f"Ingestion task exceeded soft time limit for document={document_id}, job={job_id}"
        )
        raise  # not retried — see note below

    except Exception as exc:
        logger.error(
            f"Ingestion task failed for document={document_id}: {exc}",
            exc_info=True,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        raise

# Alias for the import in documents.py
run_ingestion = run_ingestion_pipeline

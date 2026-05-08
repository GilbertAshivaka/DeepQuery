"""Re-queue ingestion jobs to Celery.

Usage:
    python requeue_pending.py          # re-queue PENDING, FAILED, and PROCESSING jobs
    python requeue_pending.py --all    # re-queue ALL jobs (including COMPLETE ones)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database import SessionLocal
from models.database import IngestionJob, Document
from core.constants import JobStatus
from tasks.ingestion_task import run_ingestion_pipeline

requeue_all = "--all" in sys.argv

db = SessionLocal()

if requeue_all:
    jobs = db.query(IngestionJob).all()
    print(f"Re-queuing ALL {len(jobs)} jobs (including completed)")
else:
    jobs = db.query(IngestionJob).filter(
        IngestionJob.status.in_([
            JobStatus.PENDING,
            JobStatus.FAILED,
            JobStatus.PROCESSING,
        ])
    ).all()
    print(f"Found {len(jobs)} non-complete jobs to re-queue")

for job in jobs:
    doc = db.query(Document).filter(Document.id == job.document_id).first()
    if doc:
        job.status = JobStatus.PENDING
        job.error_message = None
        task = run_ingestion_pipeline.delay(str(doc.id), str(job.id))
        job.celery_task_id = task.id
        print(f"  Re-queued: {doc.original_filename:50s} (was {job.status}) -> task {task.id[:8]}")
    else:
        print(f"  Skipped job {job.id}: no document found")

db.commit()
db.close()
print("Done!")

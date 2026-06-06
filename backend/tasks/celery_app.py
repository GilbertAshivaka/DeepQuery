"""
Deep Query — Celery Application Configuration
"""

import os
import sys

# Ensure the backend/ directory is on sys.path so sibling packages
# (ingestion, core, models, etc.) are importable by the worker process.
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from celery import Celery

from core.config import settings

celery_app = Celery(
    "deep_query",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,   # 10 minutes
    task_time_limit=900,         # 15 minutes hard limit
)

# Auto-discover tasks from the tasks package
celery_app.autodiscover_tasks(["tasks"])

# Explicit imports to ensure task registration
import tasks.ingestion_task  # noqa: F401, E402
import tasks.umap_task       # noqa: F401, E402

# ── Beat schedule (periodic tasks) ──────────────────────────
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    # Recompute UMAP coordinates nightly at 02:00 UTC
    "umap-nightly": {
        "task": "tasks.compute_umap_coordinates",
        "schedule": crontab(hour=2, minute=0),
    },
}

"""
Deep Query — Agent run sweeper task (RESUMABLE_AGENT_SPEC_V2 §6)

Periodic cleanup of on-disk artifact directories for runs whose Redis state has expired.
Scheduled via Celery beat (see ``tasks/celery_app.py``). Redis keys self-expire via TTL;
this handles the disk artifacts that don't.
"""

import asyncio
import logging

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.sweep_agent_runs")
def sweep_agent_runs() -> dict:
    """Delete artifact directories for expired agent runs. Best-effort."""
    try:
        from agents.orchestrator.sweeper import sweep_artifacts
        removed = asyncio.run(sweep_artifacts())
        return {"removed": removed}
    except Exception as exc:
        logger.warning("sweep_agent_runs failed: %s", exc)
        return {"removed": 0, "error": str(exc)}

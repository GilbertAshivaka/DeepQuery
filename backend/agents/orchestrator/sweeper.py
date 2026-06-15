"""
Deep Query — Agent run TTL sweeper (RESUMABLE_AGENT_SPEC_V2 §6)

Redis keys (checkpoints, event streams, snapshots, mailboxes, pending records) all carry a
TTL and self-expire. The on-DISK artifact store does NOT — so this sweeper deletes artifact
directories whose run state has expired out of Redis (the run is gone; its raw payloads are
orphaned). Run periodically via Celery beat (``tasks.sweep_agent_runs``).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def sweep_artifacts() -> int:
    """Delete artifact directories for runs whose Redis snapshot has expired. Returns the
    number of run directories removed."""
    from agents.orchestrator import artifacts, event_bus

    root = artifacts._root()
    if not root.exists():
        return 0
    try:
        live = {artifacts._safe(t) for t in await event_bus.iter_run_threads()}
    except Exception as exc:
        logger.warning("sweeper: could not list live runs (skipping): %s", exc)
        return 0

    removed = 0
    for d in root.iterdir():
        if not d.is_dir() or d.name in live:
            continue
        artifacts.delete_thread(d.name)  # snapshot gone → run state expired → orphaned
        removed += 1
    if removed:
        logger.info("sweeper: removed %s expired agent-run artifact dir(s)", removed)
    return removed

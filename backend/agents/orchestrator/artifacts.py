"""
Deep Query — Artifact store (RESUMABLE_AGENT_SPEC_V2 §2.7, phase R5)

Raw read payloads are large and don't belong in the run's working context or its
checkpoint — only their *distillations* (one-line findings + citations) do. This store
holds the raw forms on disk behind a thin ``put/get/exists/delete`` interface, keyed
``{root}/{thread_id}/{step_id}/{artifact_id}``, so a long run keeps a small curated
digest in state while the full evidence stays retrievable (re-read on demand; the basis
for compaction). First adapter = local disk (a persistent volume is required in
deployment); a multi-host swap to S3/MinIO later is one adapter, zero call-site changes.

Sync (disk IO) — async callers use ``asyncio.to_thread``. The TTL sweeper cleans a whole
thread's directory via ``delete_thread`` alongside the expired Redis keys (spec §6).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Optional

from core.config import settings

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _root() -> Path:
    root = Path(settings.agent_artifact_root) if settings.agent_artifact_root else (
        settings.document_store_dir / "agent_artifacts")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe(component: str) -> str:
    """Sanitize one path component — no separators, no traversal."""
    cleaned = _SAFE.sub("_", str(component or "")).strip("._") or "x"
    return cleaned[:128]


def _path(thread_id: str, step_id: str, artifact_id: str) -> Path:
    return _root() / _safe(thread_id) / _safe(step_id) / f"{_safe(artifact_id)}.json"


def put(thread_id: str, step_id: str, artifact_id: str, data: Any) -> str:
    """Persist ``data`` (JSON-serializable) and return its ref ``thread/step/artifact``.
    Best-effort: a disk failure logs and returns an empty ref (the run continues; only
    the durable re-read of this payload is lost)."""
    try:
        p = _path(thread_id, step_id, artifact_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, default=str), encoding="utf-8")
        return f"{_safe(thread_id)}/{_safe(step_id)}/{_safe(artifact_id)}"
    except Exception as exc:
        logger.warning("artifact put failed (%s/%s/%s): %s", thread_id, step_id, artifact_id, exc)
        return ""


def get(ref: str) -> Optional[Any]:
    """Load an artifact by ref, or None if missing/unreadable."""
    if not ref:
        return None
    try:
        p = _root() / f"{ref}.json"
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("artifact get failed (%s): %s", ref, exc)
        return None


def exists(ref: str) -> bool:
    return bool(ref) and (_root() / f"{ref}.json").is_file()


def delete(ref: str) -> None:
    try:
        p = _root() / f"{ref}.json"
        if p.is_file():
            p.unlink()
    except Exception as exc:
        logger.warning("artifact delete failed (%s): %s", ref, exc)


def delete_thread(thread_id: str) -> None:
    """Remove a whole run's artifact directory (TTL sweeper, spec §6)."""
    try:
        d = _root() / _safe(thread_id)
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    except Exception as exc:
        logger.warning("artifact delete_thread failed (%s): %s", thread_id, exc)

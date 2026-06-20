"""
Deep Query — Per-user agent preferences

User-tunable knobs for the agent's retrieval behavior, stored as JSON on the user row
(``User.preferences_json``). Each value falls back to the deployment default in
``settings`` and is clamped to a fixed [min, max] range, so a bad/forged value can never
push the agent outside safe bounds.

Knobs (Settings → Agent):
  - ``max_parallel_reads``    : how many sub-reads a single read step may fan out into.
  - ``whole_doc_min_chunks``  : ≥ this many chunks from one document before its full text
                                is pulled in.
  - ``whole_doc_max_docs``    : how many distinct documents one read may expand to full text.
  - ``whole_doc_max_pages``   : per-document length cap, in pages (chars = pages ×
                                ``settings.agent_whole_doc_page_chars``). The per-run token
                                budget still bounds the total.

Sync (DB IO) — async callers use ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)

# Inclusive [min, max] bounds per knob. The defaults come from settings (deployment-level),
# clamped into these bounds. Surfaced to the UI so sliders render the right ranges.
BOUNDS: dict[str, tuple[int, int]] = {
    "max_parallel_reads": (1, 5),
    "whole_doc_min_chunks": (2, 5),
    "whole_doc_max_docs": (1, 5),
    "whole_doc_max_pages": (2, 30),
}


def _clamp(key: str, value: Any) -> int:
    lo, hi = BOUNDS[key]
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = defaults()[key]
    return max(lo, min(hi, v))


def defaults() -> dict[str, int]:
    """Deployment-level defaults (from settings), clamped into bounds."""
    raw = {
        "max_parallel_reads": settings.agent_max_parallel_reads,
        "whole_doc_min_chunks": settings.agent_whole_doc_min_chunks,
        "whole_doc_max_docs": settings.agent_whole_doc_max_docs,
        "whole_doc_max_pages": settings.agent_whole_doc_max_pages,
    }
    return {k: _clamp(k, v) for k, v in raw.items()}


def _merge(stored: dict[str, Any] | None) -> dict[str, int]:
    """Overlay a user's stored values on the defaults, clamping each known knob and
    ignoring anything unknown."""
    out = defaults()
    if isinstance(stored, dict):
        for k in BOUNDS:
            if k in stored and stored[k] is not None:
                out[k] = _clamp(k, stored[k])
    return out


def _load_raw(db, user_id: str) -> dict[str, Any]:
    from models.database import User
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.preferences_json:
        return {}
    try:
        data = json.loads(user.preferences_json)
        return data.get("agent", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def get(db, user_id: str) -> dict[str, int]:
    """A user's effective agent prefs (defaults overlaid with their stored overrides)."""
    return _merge(_load_raw(db, user_id))


def update(db, user_id: str, patch: dict[str, Any]) -> dict[str, int]:
    """Persist a partial update (only known, clamped knobs) and return the effective prefs.
    Preserves any non-agent sections already in ``preferences_json``."""
    from models.database import User
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise KeyError("user not found")
    try:
        blob = json.loads(user.preferences_json) if user.preferences_json else {}
        if not isinstance(blob, dict):
            blob = {}
    except Exception:
        blob = {}
    agent = blob.get("agent", {}) if isinstance(blob.get("agent"), dict) else {}
    for k in BOUNDS:
        if k in (patch or {}) and patch[k] is not None:
            agent[k] = _clamp(k, patch[k])
    blob["agent"] = agent
    user.preferences_json = json.dumps(blob)
    db.commit()
    return _merge(agent)


def resolve_for_run(user_id: str) -> dict[str, int]:
    """Effective prefs for a run, opening its own session (used by the controller's
    hydrate). Falls back to deployment defaults on any error — never fails a run."""
    if not user_id:
        return defaults()
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        return get(db, user_id)
    except Exception as exc:
        logger.warning("user_prefs.resolve_for_run failed for %s: %s", user_id, exc)
        return defaults()
    finally:
        db.close()


def whole_doc_max_chars(prefs: dict[str, int]) -> int:
    """Convert the user's page cap to a character cap for the retrieval layer."""
    pages = prefs.get("whole_doc_max_pages", defaults()["whole_doc_max_pages"])
    return max(1, pages) * max(500, settings.agent_whole_doc_page_chars)

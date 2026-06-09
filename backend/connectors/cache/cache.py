"""The ephemeral Redis read-cache (guide §7).

The *only* place live data briefly resides — to avoid redundant identical calls
within a short window. It is not a system of record, not searchable, not part of
ranking; when the TTL expires the content is gone. Rules enforced here / by the
gateway:

- **Reads only.** Actions are never cached (the gateway never calls this for an
  action; an action's preview/execute always re-runs).
- **Per-connector TTL**, short by default; volatile connectors set 0 to opt out.
- **Scoped to user (and conversation)** so one user's authorized data never leaks
  into another user's results.
- **Degrades gracefully**: if Redis is unavailable, get/set quietly no-op so a
  cache outage never breaks a read.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from core.redis_client import redis_client

_PREFIX = "dq:conn:cache:"


def cache_key(
    *,
    connector: str,
    capability: str,
    arguments: dict[str, Any] | None,
    user_id: Optional[str],
    conversation_id: Optional[str],
) -> str:
    """Stable key over connector + capability + normalized args + user + conversation."""
    norm_args = json.dumps(arguments or {}, sort_keys=True, default=str)
    raw = "|".join([connector, capability, norm_args, user_id or "-", conversation_id or "-"])
    return _PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_get(
    *,
    connector: str,
    capability: str,
    arguments: dict[str, Any] | None,
    user_id: Optional[str],
    conversation_id: Optional[str],
) -> Optional[dict[str, Any]]:
    """Return a cached read result, or None on miss / cache unavailable."""
    key = cache_key(
        connector=connector, capability=capability, arguments=arguments,
        user_id=user_id, conversation_id=conversation_id,
    )
    return redis_client.get_json(key)  # returns None on any Redis error


def cache_set(
    *,
    connector: str,
    capability: str,
    arguments: dict[str, Any] | None,
    user_id: Optional[str],
    conversation_id: Optional[str],
    value: dict[str, Any],
    ttl_seconds: int,
) -> None:
    """Store a read result with the connector's TTL. ttl<=0 disables caching."""
    if ttl_seconds <= 0:
        return
    key = cache_key(
        connector=connector, capability=capability, arguments=arguments,
        user_id=user_id, conversation_id=conversation_id,
    )
    redis_client.set_json(key, value, ttl_seconds=ttl_seconds)  # no-ops on Redis error

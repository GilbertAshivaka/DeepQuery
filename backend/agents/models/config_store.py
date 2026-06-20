"""
Deep Query — DB-backed Model Config Store

Runtime source of truth for which vendor/model each role uses. The model factory
(``slots.py``) reads the active ``ModelConfig`` row for a role, falling back to env
settings when no row exists — so env remains the bootstrap floor and the system is never
left without a configuration. See MODEL_VENDOR_PICKING_PLAN.md §3.3 / §4.

Cross-worker cache invalidation: every write bumps a Redis counter
(``model_config:version``); the factory keys its model cache on that version, so the API
process and Celery workers rebuild together on the next call after a change.

Resilience: every DB/Redis access is defensive. A missing table, a DB error, or an
unreachable Redis degrades to "no override / version 0" — i.e. pure-env behavior — rather
than breaking model resolution.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from core.config import settings

logger = logging.getLogger(__name__)

# Redis key holding a monotonically increasing config version. Lives in the shared
# broker DB (db 0); namespaced, never flushed.
VERSION_KEY = "model_config:version"

# The roles the store manages. The six LLM slots are driven by the factory; 'embedding'
# is stored/edited here but consumed by the embedding layer (Phase 4).
LLM_ROLES = (
    "orchestration",
    "generation",
    "verification",
    "chat",
    "self_correction",
    "extraction",
)
EMBEDDING_ROLE = "embedding"
ALL_ROLES = LLM_ROLES + (EMBEDDING_ROLE,)


# ── Version counter (cross-worker cache invalidation) ────────────


def current_version() -> int:
    """The current config version (0 if unset or Redis unreachable)."""
    try:
        from core.redis_client import redis_client

        raw = redis_client.get(VERSION_KEY)
        return int(raw) if raw is not None else 0
    except Exception as exc:  # Redis down / bad value → stable fallback
        logger.debug("model-config version read failed (%s); defaulting to 0", exc)
        return 0


def bump_version() -> int:
    """Increment the config version so all workers rebuild cached models. Best-effort."""
    try:
        from core.redis_client import redis_client

        return int(redis_client.sync_client.incr(VERSION_KEY))
    except Exception as exc:
        logger.warning("model-config version bump failed (%s)", exc)
        return current_version()


# ── App settings (deployment-global runtime flags) ───────────────


def get_flag(key: str, default: object = None) -> object:
    """Read a deployment-global runtime flag from the ``app_settings`` table, returning
    ``default`` when the store is disabled, the row is absent, or any error occurs (so the
    caller's env fallback wins). Used for non-per-role toggles like Anthropic extended
    thinking."""
    if not settings.model_config_db_enabled:
        return default
    try:
        from core.database import SessionLocal
        from models.database import AppSetting

        db = SessionLocal()
        try:
            row = db.query(AppSetting).filter(AppSetting.key == key).first()
            if row is None or row.value_json is None:
                return default
            try:
                return json.loads(row.value_json)
            except (json.JSONDecodeError, TypeError):
                return default
        finally:
            db.close()
    except Exception as exc:
        logger.debug("get_flag('%s') fell back to default (%s)", key, exc)
        return default


def set_flag(key: str, value: object, updated_by: Optional[str] = None) -> object:
    """Upsert a deployment-global runtime flag, then bump the config version so workers
    rebuild cached models on the next call (the thinking flag changes model construction).
    Returns the stored value."""
    from core.database import SessionLocal
    from models.database import AppSetting

    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row is None:
            row = AppSetting(key=key, value_json=json.dumps(value), updated_by=updated_by)
            db.add(row)
        else:
            row.value_json = json.dumps(value)
            row.updated_by = updated_by
        db.commit()
    finally:
        db.close()

    bump_version()
    logger.info("app-setting set '%s' = %r", key, value)
    return value


# ── Resolution (read path, hit on factory cache miss) ────────────


def resolve_role(role: str) -> Optional[Dict[str, object]]:
    """Return the active config for a role as
    ``{provider, model, base_url, params, key_mode}``, or ``None`` to fall back to env.

    Returns ``None`` (→ env fallback) when the DB store is disabled, the table is
    missing, there's no active row, or any error occurs.
    """
    if not settings.model_config_db_enabled:
        return None
    try:
        from core.database import SessionLocal
        from models.database import ModelConfig

        db = SessionLocal()
        try:
            row = (
                db.query(ModelConfig)
                .filter(ModelConfig.role == role, ModelConfig.is_active == True)  # noqa: E712
                .order_by(ModelConfig.created_at.desc())
                .first()
            )
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            db.close()
    except Exception as exc:
        logger.debug("resolve_role('%s') fell back to env (%s)", role, exc)
        return None


def _row_to_dict(row) -> Dict[str, object]:
    params: Dict = {}
    if row.params_json:
        try:
            params = json.loads(row.params_json)
        except (json.JSONDecodeError, TypeError):
            params = {}
    return {
        "provider": (row.provider or "").lower().strip(),
        "model": (row.model or "").strip(),
        "base_url": (row.base_url or None),
        "params": params,
        "key_mode": row.key_mode or "managed",
    }


# ── Admin read / write ───────────────────────────────────────────


def list_active() -> Dict[str, Dict[str, object]]:
    """Active config per role (for the admin GET). Roles with no row are omitted; the
    caller can show those as 'inheriting env defaults'."""
    out: Dict[str, Dict[str, object]] = {}
    try:
        from core.database import SessionLocal
        from models.database import ModelConfig

        db = SessionLocal()
        try:
            rows = (
                db.query(ModelConfig)
                .filter(ModelConfig.is_active == True)  # noqa: E712
                .all()
            )
            for row in rows:
                d = _row_to_dict(row)
                d["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
                out[row.role] = d
        finally:
            db.close()
    except Exception as exc:
        logger.warning("list_active failed (%s)", exc)
    return out


def set_role(
    role: str,
    provider: str,
    model: str,
    base_url: Optional[str] = None,
    params: Optional[Dict] = None,
    key_mode: str = "managed",
    updated_by: Optional[str] = None,
) -> Dict[str, object]:
    """Activate a new config for a role (deactivating the prior active row), then bump
    the version so workers rebuild. Returns the stored config dict."""
    from core.database import SessionLocal
    from models.database import ModelConfig

    db = SessionLocal()
    try:
        db.query(ModelConfig).filter(
            ModelConfig.role == role, ModelConfig.is_active == True  # noqa: E712
        ).update({ModelConfig.is_active: False})

        row = ModelConfig(
            role=role,
            provider=provider.lower().strip(),
            model=model.strip(),
            base_url=(base_url.strip() if base_url else None),
            params_json=json.dumps(params) if params else None,
            key_mode=key_mode,
            is_active=True,
            updated_by=updated_by,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        result = _row_to_dict(row)
    finally:
        db.close()

    bump_version()
    logger.info("model-config set role='%s' → %s/%s", role, provider, model)
    return result


def bootstrap_from_env() -> int:
    """Seed a ModelConfig row from env settings for any role that has none yet. Makes the
    DB the source of truth without changing behavior (rows mirror current env values) and
    gives the admin UI something to edit. Idempotent. Returns the number of rows seeded."""
    if not settings.model_config_db_enabled:
        return 0
    try:
        from core.database import SessionLocal
        from models.database import ModelConfig
    except Exception as exc:
        logger.warning("model-config bootstrap skipped (%s)", exc)
        return 0

    seeded = 0
    db = SessionLocal()
    try:
        existing_roles = {
            r[0]
            for r in db.query(ModelConfig.role).filter(
                ModelConfig.is_active == True  # noqa: E712
            ).all()
        }
        for role in ALL_ROLES:
            if role in existing_roles:
                continue
            provider, model, params = _env_defaults_for(role)
            if not provider or not model:
                continue
            db.add(
                ModelConfig(
                    role=role,
                    provider=provider,
                    model=model,
                    params_json=json.dumps(params) if params else None,
                    key_mode="managed",
                    is_active=True,
                )
            )
            seeded += 1
        if seeded:
            db.commit()
    except Exception as exc:
        logger.warning("model-config bootstrap failed (%s)", exc)
        db.rollback()
    finally:
        db.close()

    if seeded:
        logger.info("model-config bootstrap seeded %d role(s) from env", seeded)
    return seeded


def effective_roles() -> Dict[str, Dict[str, object]]:
    """The config in force for every managed role — the active DB row if present,
    otherwise the env default — each tagged with its ``source`` ('db' | 'env'). This is
    what the Admin UI renders."""
    db = list_active()
    out: Dict[str, Dict[str, object]] = {}
    for role in ALL_ROLES:
        if role in db:
            entry = dict(db[role])
            entry["source"] = "db"
            out[role] = entry
        else:
            provider, model, params = _env_defaults_for(role)
            out[role] = {
                "provider": (provider or "").lower().strip(),
                "model": (model or "").strip(),
                "base_url": None,
                "params": params,
                "key_mode": "managed",
                "source": "env",
            }
    return out


def _env_defaults_for(role: str):
    """(provider, model, params) for a role, read from env settings."""
    if role == EMBEDDING_ROLE:
        return (
            settings.embedding_provider,
            settings.embedding_model,
            {"dimensions": settings.embedding_dimensions},
        )
    provider = getattr(settings, f"agent_{role}_provider", "")
    model = getattr(settings, f"agent_{role}_model", "")
    return (provider, model, {})

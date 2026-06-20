"""
Deep Query — Provider API Key Resolver (BYOK + managed)

Resolves the API key to use for a vendor, with a clear, predictable order:

    1. BYOK — an encrypted key stored via the Admin API (``provider_keys`` table).
    2. Managed — the key configured server-side in env settings.
    3. None — for local providers that need no key (ollama / openai_compatible / vllm),
       or an error upstream for cloud providers with no key at all.

Keys are encrypted at rest with the connector credential mechanism (Fernet) — no new
crypto. Plaintext keys are never returned over the API; only a 4-char hint is exposed.
A key change bumps the shared model-config version so cached model clients rebuild with
the new key across all workers. See MODEL_VENDOR_PICKING_PLAN.md §5.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from core.config import settings

logger = logging.getLogger(__name__)

# Managed (env) key setting name per provider. Providers absent here need no key.
MANAGED_ENV_ATTR = {
    "google": "google_api_key",
    "groq": "groq_api_key",
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "deepseek": "deepseek_api_key",
    "qwen": "qwen_api_key",
}
# Providers that legitimately operate without an API key (self-hosted / local).
NO_KEY_PROVIDERS = {"ollama", "openai_compatible", "vllm"}


# ── BYOK storage (encrypted) ─────────────────────────────────────


def _managed_key(provider: str) -> str:
    attr = MANAGED_ENV_ATTR.get(provider)
    return (getattr(settings, attr, "") or "").strip() if attr else ""


def byok_key(provider: str) -> Optional[str]:
    """Decrypt and return the stored BYOK key for a provider, or None. Internal use
    only — never expose the return value over the API."""
    try:
        from connectors.credentials.crypto import decrypt
        from core.database import SessionLocal
        from models.database import ProviderKey

        db = SessionLocal()
        try:
            row = db.query(ProviderKey).filter(ProviderKey.provider == provider).first()
            if row is None:
                return None
            return decrypt(row.encrypted_key)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("BYOK key lookup for '%s' failed (%s)", provider, exc)
        return None


def resolve_api_key(provider: str) -> Optional[str]:
    """The effective key for a provider: BYOK if present, else the managed env key,
    else None (caller decides whether None is acceptable for this provider)."""
    provider = provider.lower().strip()
    return byok_key(provider) or (_managed_key(provider) or None)


def effective_source(provider: str) -> str:
    """Where this provider's key comes from: 'byok' | 'managed' | 'none'."""
    provider = provider.lower().strip()
    if has_byok(provider):
        return "byok"
    if _managed_key(provider):
        return "managed"
    return "none"


def has_byok(provider: str) -> bool:
    try:
        from core.database import SessionLocal
        from models.database import ProviderKey

        db = SessionLocal()
        try:
            return (
                db.query(ProviderKey).filter(ProviderKey.provider == provider).first()
                is not None
            )
        finally:
            db.close()
    except Exception:
        return False


def set_key(provider: str, raw_key: str, created_by: Optional[str] = None) -> Dict[str, object]:
    """Encrypt and upsert a BYOK key for a provider, then bump the config version so
    cached models rebuild. Returns a safe status dict (no plaintext)."""
    from connectors.credentials.crypto import encrypt
    from core.database import SessionLocal
    from models.database import ProviderKey

    provider = provider.lower().strip()
    raw_key = (raw_key or "").strip()
    if not raw_key:
        raise ValueError("API key must not be empty.")

    hint = raw_key[-4:]
    enc = encrypt(raw_key)

    db = SessionLocal()
    try:
        row = db.query(ProviderKey).filter(ProviderKey.provider == provider).first()
        if row is None:
            row = ProviderKey(provider=provider, created_by=created_by)
            db.add(row)
        row.encrypted_key = enc
        row.key_hint = hint
        db.commit()
    finally:
        db.close()

    _bump()
    logger.info("BYOK key set for provider '%s' (hint …%s)", provider, hint)
    return {"provider": provider, "configured": True, "hint": hint, "source": "byok"}


def delete_key(provider: str) -> bool:
    """Remove a provider's BYOK key (reverting it to the managed env key), bump version."""
    from core.database import SessionLocal
    from models.database import ProviderKey

    provider = provider.lower().strip()
    db = SessionLocal()
    try:
        deleted = (
            db.query(ProviderKey).filter(ProviderKey.provider == provider).delete()
        )
        db.commit()
    finally:
        db.close()

    if deleted:
        _bump()
        logger.info("BYOK key deleted for provider '%s'", provider)
    return bool(deleted)


def list_status() -> Dict[str, Dict[str, object]]:
    """Per-provider key status for the admin UI — never includes plaintext keys."""
    hints: Dict[str, str] = {}
    try:
        from core.database import SessionLocal
        from models.database import ProviderKey

        db = SessionLocal()
        try:
            for row in db.query(ProviderKey).all():
                hints[row.provider] = row.key_hint or "????"
        finally:
            db.close()
    except Exception as exc:
        logger.warning("provider-key status read failed (%s)", exc)

    out: Dict[str, Dict[str, object]] = {}
    for provider in list(MANAGED_ENV_ATTR) + sorted(NO_KEY_PROVIDERS):
        out[provider] = {
            "byok": provider in hints,
            "hint": hints.get(provider),
            "managed": bool(_managed_key(provider)),
            "needs_key": provider not in NO_KEY_PROVIDERS,
            "source": effective_source(provider),
        }
    return out


def _bump() -> None:
    """Bump the shared config version (best-effort) so model caches rebuild."""
    try:
        from agents.models import config_store

        config_store.bump_version()
    except Exception as exc:
        logger.warning("config version bump after key change failed (%s)", exc)

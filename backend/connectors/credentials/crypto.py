"""Encryption at rest for connector credentials (guide §6, §12).

Credentials and refresh tokens are encrypted with Fernet (AES-128-CBC + HMAC).
The key comes from CONNECTOR_ENCRYPTION_KEY; in dev, a volatile key is generated
with a loud warning (credentials won't survive a restart) so nothing is ever
stored in plaintext, even locally.
"""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from core.config import settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = (settings.connector_encryption_key or "").strip()
    if not key:
        key = Fernet.generate_key().decode()
        logger.warning(
            "CONNECTOR_ENCRYPTION_KEY is not set — generated a volatile dev key. "
            "Stored connector credentials will NOT survive a restart. Set this in production."
        )
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # malformed key
        raise RuntimeError(
            "CONNECTOR_ENCRYPTION_KEY is invalid; it must be a urlsafe-base64 32-byte Fernet key. "
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from exc
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string, returning a urlsafe token string."""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`."""
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "failed to decrypt a connector credential — the encryption key likely changed "
            "since it was stored."
        ) from exc

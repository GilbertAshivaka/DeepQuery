"""
Deep Query — JWT Token Handler

Creates and verifies JWT access/refresh tokens.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt

# Fix passlib compatibility with newer bcrypt (>= 4.1)
if not hasattr(_bcrypt, "__about__"):
    _bcrypt.__about__ = type("about", (), {"__version__": _bcrypt.__version__})()

from jose import JWTError, jwt
from passlib.context import CryptContext

from core.config import settings
from core.constants import ROLE_COLLECTIONS

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password Hashing ─────────────────────────────────────────
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── Token Creation ───────────────────────────────────────────
def create_access_token(
    user_id: str,
    username: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a short-lived JWT access token."""
    allowed = [c.value for c in ROLE_COLLECTIONS.get(role, [])]
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "allowed_collections": allowed,
        "type": "access",
        "exp": datetime.now(timezone.utc)
        + (expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    user_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a long-lived refresh token."""
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": datetime.now(timezone.utc)
        + (expires_delta or timedelta(days=settings.jwt_refresh_token_expire_days)),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# ── Token Verification ───────────────────────────────────────
def decode_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT token. Returns payload dict or None."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None


# ── Token Hashing (for storing refresh tokens in DB) ─────────
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

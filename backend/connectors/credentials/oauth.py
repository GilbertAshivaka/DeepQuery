"""OAuth 2.1 (authorization-code + PKCE) for per-user connector auth (guide §6).

The SDK supplies the pure flow-construction helpers (PKCE pair, authorization
URL, token/refresh request bodies); the Gateway (here) performs the actual token
exchange and refresh over HTTP and stores the resulting grant bound to the user.
Pending-authorization state (state -> {user, connector, verifier}) lives in Redis
with a short TTL, so a half-finished flow leaves no durable trace.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from deepquery_sdk.auth.oauth2 import (
    build_authorization_url,
    build_refresh_request,
    build_token_request,
    generate_pkce,
)

from connectors.credentials.crypto import decrypt
from core.config import settings
from core.redis_client import redis_client

logger = logging.getLogger(__name__)

_PENDING_PREFIX = "dq:oauth:pending:"
_PENDING_TTL_S = 600  # 10 minutes to complete the consent round-trip
_REFRESH_SKEW_S = 60  # refresh this many seconds before actual expiry


class OAuthError(Exception):
    pass


def _redirect_uri() -> str:
    return settings.connector_oauth_redirect_base.rstrip("/") + "/api/connectors/auth/callback"


def _require(config: dict[str, Any], key: str) -> Any:
    val = config.get(key)
    if not val:
        raise OAuthError(f"connector OAuth config missing required field {key!r}")
    return val


def _client_secret(config: dict[str, Any]) -> Optional[str]:
    enc = config.get("client_secret_enc")
    return decrypt(enc) if enc else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Begin: build the authorization URL the user is redirected to.
# --------------------------------------------------------------------------- #
def begin_authorization(*, user_id: str, connector_ref) -> str:
    config = connector_ref.auth_config or {}
    if connector_ref.auth_method != "oauth2":
        raise OAuthError(f"connector {connector_ref.name!r} does not use OAuth")
    # No external OAuth round-trip in air-gapped mode (guide §11).
    from connectors.gateway.deployment import is_air_gapped

    if is_air_gapped():
        raise OAuthError("external OAuth is not available in air-gapped mode; use a static credential")

    pkce = generate_pkce()
    state = secrets.token_urlsafe(24)
    stored = redis_client.set_json(
        _PENDING_PREFIX + state,
        {"user_id": user_id, "connector_id": connector_ref.id, "code_verifier": pkce.verifier},
        ttl_seconds=_PENDING_TTL_S,
    )
    # Fail closed with an honest message if the pending state can't be persisted.
    if not stored:
        raise OAuthError("the enrollment subsystem is temporarily unavailable; please try again")
    return build_authorization_url(
        authorize_endpoint=_require(config, "authorize_endpoint"),
        client_id=_require(config, "client_id"),
        redirect_uri=_redirect_uri(),
        scopes=list(config.get("scopes", [])),
        code_challenge=pkce.challenge,
        state=state,
    )


# --------------------------------------------------------------------------- #
# Complete: exchange the authorization code for tokens, store bound to the user.
# --------------------------------------------------------------------------- #
def complete_authorization(db: Session, *, state: str, code: str) -> tuple[str, str]:
    """Returns (user_id, connector_id). Raises OAuthError on any failure."""
    pending = redis_client.get_json(_PENDING_PREFIX + state)
    if not pending:
        # Distinguish a Redis outage (fail closed, honest message) from a
        # genuinely unknown/expired state.
        if not redis_client.ping():
            raise OAuthError("the enrollment subsystem is temporarily unavailable; please try again")
        raise OAuthError("unknown or expired OAuth state")
    redis_client.delete(_PENDING_PREFIX + state)

    user_id = pending["user_id"]
    connector_id = pending["connector_id"]

    # Lazy imports avoid import cycles (registry/store import this module's peers).
    from connectors.credentials.store import credential_store
    from connectors.gateway.registry import get_connector_ref

    ref = get_connector_ref(db, connector_id=connector_id)
    if ref is None:
        raise OAuthError("connector no longer registered")
    config = ref.auth_config or {}

    req = build_token_request(
        token_endpoint=_require(config, "token_endpoint"),
        client_id=_require(config, "client_id"),
        code=code,
        code_verifier=pending["code_verifier"],
        redirect_uri=_redirect_uri(),
    )
    data = dict(req.data)
    secret = _client_secret(config)
    if secret:
        data["client_secret"] = secret

    token = _post_token(req.url, data)
    payload, expires_at = _payload_from_token_response(token)
    credential_store.set_credential(
        db, user_id=user_id, connector_id=connector_id, method="oauth2", payload=payload, expires_at=expires_at
    )
    return user_id, connector_id


# --------------------------------------------------------------------------- #
# Refresh: called transparently by the store when an access token is expiring.
# --------------------------------------------------------------------------- #
def refresh_if_needed(
    db: Session,
    *,
    user_id: str,
    connector_ref,
    payload: dict[str, Any],
    expires_at: Optional[datetime],
    store,
) -> tuple[dict[str, Any], Optional[datetime]]:
    if not _is_expiring(expires_at):
        return payload, expires_at
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        return payload, expires_at  # nothing to refresh with; let the call fail if rejected

    config = connector_ref.auth_config or {}
    req = build_refresh_request(
        token_endpoint=_require(config, "token_endpoint"),
        client_id=_require(config, "client_id"),
        refresh_token=refresh_token,
    )
    data = dict(req.data)
    secret = _client_secret(config)
    if secret:
        data["client_secret"] = secret

    try:
        token = _post_token(req.url, data)
    except OAuthError as exc:
        logger.warning("token refresh failed for connector %s: %s", connector_ref.name, exc)
        return payload, expires_at

    new_payload, new_expires = _payload_from_token_response(token)
    # Some providers omit a new refresh_token on refresh — keep the old one.
    new_payload.setdefault("refresh_token", refresh_token)
    if not new_payload.get("refresh_token"):
        new_payload["refresh_token"] = refresh_token
    store.set_credential(
        db, user_id=user_id, connector_id=connector_ref.id, method="oauth2",
        payload=new_payload, expires_at=new_expires,
    )
    return new_payload, new_expires


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _is_expiring(expires_at: Optional[datetime]) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return _now() >= expires_at - timedelta(seconds=_REFRESH_SKEW_S)


def _post_token(url: str, data: dict[str, str]) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, data=data, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OAuthError(f"token endpoint unreachable: {exc}") from exc
    if resp.status_code != 200:
        raise OAuthError(f"token endpoint returned {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise OAuthError("token endpoint returned a non-JSON response") from exc


def _payload_from_token_response(token: dict[str, Any]) -> tuple[dict[str, Any], Optional[datetime]]:
    access = token.get("access_token")
    if not access:
        raise OAuthError("token response has no access_token")
    expires_at: Optional[datetime] = None
    if isinstance(token.get("expires_in"), (int, float)):
        expires_at = _now() + timedelta(seconds=int(token["expires_in"]))
    payload = {
        "access_token": access,
        "refresh_token": token.get("refresh_token"),
        "token_type": token.get("token_type", "Bearer"),
        "scope": token.get("scope"),
    }
    return payload, expires_at

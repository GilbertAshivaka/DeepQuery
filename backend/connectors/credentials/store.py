"""Encrypted, per-user connector credential store (guide §6).

Keyed by (user_id, connector_id). The encrypted payload holds the user's own
external credential; we decrypt it only to inject at call time and never log it.
A credential is bound to user identity, so the agent acts with that user's
external permissions — never a shared service account, never privilege escalation.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from connectors.credentials.crypto import decrypt, encrypt
from models.database import ConnectorCredential

# Env var / header conventions used to inject a credential across the MCP
# boundary (stdio env vars; HTTP headers). SDK connectors read the token env via
# deepquery_sdk.env_credential_provider(token_env=ENV_TOKEN).
ENV_TOKEN = "DEEPQUERY_CONNECTOR_TOKEN"
ENV_USERNAME = "DEEPQUERY_CONNECTOR_USERNAME"
ENV_PASSWORD = "DEEPQUERY_CONNECTOR_PASSWORD"
ENV_CLIENT_CERT = "DEEPQUERY_CONNECTOR_CLIENT_CERT"
ENV_CLIENT_KEY = "DEEPQUERY_CONNECTOR_CLIENT_KEY"


class CredentialError(Exception):
    pass


@dataclass
class InjectedCredential:
    """A resolved credential ready to inject into a connector call."""

    method: str
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None

    def env(self) -> dict[str, str]:
        """Env vars for stdio injection (subprocess spawn)."""
        out: dict[str, str] = {}
        if self.token:
            out[ENV_TOKEN] = self.token
        if self.username is not None:
            out[ENV_USERNAME] = self.username
        if self.password is not None:
            out[ENV_PASSWORD] = self.password
        if self.client_cert_path:
            out[ENV_CLIENT_CERT] = self.client_cert_path
        if self.client_key_path:
            out[ENV_CLIENT_KEY] = self.client_key_path
        return out

    def headers(self) -> dict[str, str]:
        """Headers for HTTP-transport injection."""
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self.username is not None and self.password is not None:
            raw = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            return {"Authorization": f"Basic {raw}"}
        return {}


def _to_injected(method: str, payload: dict[str, Any]) -> InjectedCredential:
    if method in ("oauth2", "api_key"):
        token = payload.get("access_token") or payload.get("token")
        return InjectedCredential(method=method, token=token)
    if method == "basic":
        return InjectedCredential(method=method, username=payload.get("username"), password=payload.get("password"))
    if method == "mtls":
        return InjectedCredential(
            method=method,
            client_cert_path=payload.get("client_cert_path"),
            client_key_path=payload.get("client_key_path"),
        )
    raise CredentialError(f"unsupported auth method: {method!r}")


class CredentialStore:
    """Encrypted CRUD for per-user connector credentials."""

    def set_credential(
        self,
        db: Session,
        *,
        user_id: str,
        connector_id: str,
        method: str,
        payload: dict[str, Any],
        expires_at: Optional[datetime] = None,
    ) -> None:
        """Upsert the encrypted credential for (user, connector)."""
        row = (
            db.query(ConnectorCredential)
            .filter(ConnectorCredential.user_id == user_id, ConnectorCredential.connector_id == connector_id)
            .first()
        )
        enc = encrypt(json.dumps(payload))
        if row is None:
            row = ConnectorCredential(user_id=user_id, connector_id=connector_id)
            db.add(row)
        row.method = method
        row.encrypted_payload = enc
        row.expires_at = expires_at
        db.commit()

    def get_payload(self, db: Session, *, user_id: str, connector_id: str) -> Optional[tuple[str, dict[str, Any], Optional[datetime]]]:
        """Return (method, decrypted payload, expires_at) or None."""
        row = (
            db.query(ConnectorCredential)
            .filter(ConnectorCredential.user_id == user_id, ConnectorCredential.connector_id == connector_id)
            .first()
        )
        if row is None:
            return None
        return row.method, json.loads(decrypt(row.encrypted_payload)), row.expires_at

    def delete_credential(self, db: Session, *, user_id: str, connector_id: str) -> bool:
        """Revoke (delete) one user's credential for a connector."""
        deleted = (
            db.query(ConnectorCredential)
            .filter(ConnectorCredential.user_id == user_id, ConnectorCredential.connector_id == connector_id)
            .delete()
        )
        db.commit()
        return bool(deleted)

    def purge_user(self, db: Session, *, user_id: str) -> int:
        """Revoke all of a user's connector credentials (deprovisioning)."""
        n = db.query(ConnectorCredential).filter(ConnectorCredential.user_id == user_id).delete()
        db.commit()
        return n

    def purge_connector(self, db: Session, *, connector_id: str) -> int:
        """Revoke all credentials for a connector (disabling/removal)."""
        n = db.query(ConnectorCredential).filter(ConnectorCredential.connector_id == connector_id).delete()
        db.commit()
        return n

    def has_credential(self, db: Session, *, user_id: str, connector_id: str) -> bool:
        return (
            db.query(ConnectorCredential)
            .filter(ConnectorCredential.user_id == user_id, ConnectorCredential.connector_id == connector_id)
            .first()
            is not None
        )

    def resolve_injected(self, db: Session, *, user_id: str, connector_ref) -> Optional[InjectedCredential]:
        """Return a ready-to-inject credential for (user, connector), refreshing
        an expired OAuth token transparently. Returns None if the user has no
        credential (the gateway then proceeds unauthenticated for auth_method=none
        connectors, or surfaces an error for ones that require auth)."""
        loaded = self.get_payload(db, user_id=user_id, connector_id=connector_ref.id)
        if loaded is None:
            return None
        method, payload, expires_at = loaded

        if method == "oauth2":
            # Lazy import avoids a store<->oauth import cycle.
            from connectors.credentials import oauth

            payload, expires_at = oauth.refresh_if_needed(
                db,
                user_id=user_id,
                connector_ref=connector_ref,
                payload=payload,
                expires_at=expires_at,
                store=self,
            )
        return _to_injected(method, payload)


# Module-level singleton.
credential_store = CredentialStore()

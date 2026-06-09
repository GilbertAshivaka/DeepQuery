"""Connector registry — the control-plane record of which connectors exist.

Stores manifests, endpoints, and transports (never live content). The Gateway
routes each call to the right connector via this registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from connectors.mcp_client.client import MCPConnectorClient
from connectors.mcp_client.transports import TransportConfig
from models.database import Connector


@dataclass(frozen=True)
class ConnectorRef:
    """A plain, ORM-detached snapshot of a connector — safe to pass across
    thread/async boundaries (we never hold a Session open during an MCP call)."""

    id: str
    name: str
    version: Optional[str]
    transport: str
    endpoint: dict[str, Any]
    requires_network: bool
    auth_method: str
    auth_config: dict[str, Any]
    cache_ttl_seconds: int

    @classmethod
    def from_row(cls, row: Connector) -> "ConnectorRef":
        return cls(
            id=row.id,
            name=row.name,
            version=row.version,
            transport=row.transport,
            endpoint=json.loads(row.endpoint) if row.endpoint else {},
            requires_network=bool(row.requires_network),
            auth_method=row.auth_method or "none",
            auth_config=json.loads(row.auth_config) if row.auth_config else {},
            cache_ttl_seconds=row.cache_ttl_seconds if row.cache_ttl_seconds is not None else 30,
        )


def register_connector(
    db: Session,
    *,
    name: str,
    transport: str,
    endpoint: dict[str, Any],
    version: str | None = None,
    manifest: dict[str, Any] | None = None,
    requires_network: bool = True,
    enabled: bool = True,
    auth_method: str = "none",
    auth_config: dict[str, Any] | None = None,
    cache_ttl_seconds: int = 30,
) -> ConnectorRef:
    """Create or update a connector registration (idempotent on name)."""
    row = db.query(Connector).filter(Connector.name == name).first()
    if row is None:
        row = Connector(name=name)
        db.add(row)
    row.version = version
    row.transport = transport
    row.endpoint = json.dumps(endpoint)
    row.manifest = json.dumps(manifest) if manifest is not None else None
    row.requires_network = requires_network
    row.is_enabled = enabled
    row.auth_method = auth_method
    row.auth_config = json.dumps(auth_config) if auth_config is not None else None
    row.cache_ttl_seconds = cache_ttl_seconds
    db.commit()
    db.refresh(row)
    return ConnectorRef.from_row(row)


def list_connector_refs(db: Session, *, enabled_only: bool = True) -> list[ConnectorRef]:
    q = db.query(Connector)
    if enabled_only:
        q = q.filter(Connector.is_enabled.is_(True))
    return [ConnectorRef.from_row(r) for r in q.order_by(Connector.name).all()]


def get_connector_ref(db: Session, *, connector_id: str | None = None, name: str | None = None) -> Optional[ConnectorRef]:
    q = db.query(Connector)
    if connector_id is not None:
        q = q.filter(Connector.id == connector_id)
    elif name is not None:
        q = q.filter(Connector.name == name)
    else:
        return None
    row = q.first()
    return ConnectorRef.from_row(row) if row else None


def client_for_ref(ref: ConnectorRef, *, timeout_s: float = 30.0) -> MCPConnectorClient:
    """Build an MCP client for a connector from its registry snapshot."""
    config = TransportConfig.from_registry(name=ref.name, transport=ref.transport, endpoint=ref.endpoint)
    return MCPConnectorClient(config, timeout_s=timeout_s)

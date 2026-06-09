"""The Connector Gateway — policy/control plane (Phase 1: routing + audit)."""

from connectors.gateway.gateway import ConnectorGateway, ConnectorNotFoundError, GatewayError
from connectors.gateway.registry import (
    ConnectorRef,
    client_for_ref,
    get_connector_ref,
    list_connector_refs,
    register_connector,
)

__all__ = [
    "ConnectorGateway",
    "GatewayError",
    "ConnectorNotFoundError",
    "ConnectorRef",
    "register_connector",
    "list_connector_refs",
    "get_connector_ref",
    "client_for_ref",
]

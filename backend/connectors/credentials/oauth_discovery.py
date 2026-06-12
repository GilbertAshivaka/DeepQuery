"""Automatic OAuth configuration for spec-compliant MCP servers (guide §6).

So an admin only needs the server URL — not hand-entered endpoints/scopes/credentials.
Implements the MCP / OAuth 2.1 discovery chain:

  unauthenticated request -> 401 `WWW-Authenticate` with `resource_metadata`
    -> protected resource metadata        (RFC 9728)
    -> authorization server metadata       (RFC 8414)
    -> dynamic client registration         (RFC 7591), when the server supports it

with well-known fallbacks for older servers. PKCE is handled by the flow itself
(`oauth.begin_authorization`); DCR public clients use `token_endpoint_auth_method=none`,
so no client secret is needed for those servers.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "DeepQuery-Connector/1.0", "Accept": "application/json"}
_TIMEOUT = 15.0


class DiscoveryError(Exception):
    """OAuth metadata/registration could not be discovered for a server."""


def _base(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _get_json(client: httpx.Client, url: str) -> Optional[dict]:
    try:
        r = client.get(url, headers=_HEADERS)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _resource_metadata_url(client: httpx.Client, server_url: str) -> Optional[str]:
    """The protected-resource-metadata URL a compliant server advertises in its 401
    `WWW-Authenticate: Bearer resource_metadata="..."` header (RFC 9728)."""
    try:
        r = client.get(server_url, headers={"Accept": "application/json"})
    except httpx.HTTPError:
        return None
    www = r.headers.get("WWW-Authenticate") or r.headers.get("www-authenticate")
    if not www:
        return None
    m = re.search(r'resource_metadata="?([^",\s]+)"?', www)
    return m.group(1) if m else None


def _as_metadata(client: httpx.Client, issuer: str) -> Optional[dict]:
    """Authorization-server metadata for an issuer (RFC 8414 / OIDC discovery)."""
    issuer = issuer.rstrip("/")
    candidates = [
        issuer + "/.well-known/oauth-authorization-server",
        issuer + "/.well-known/openid-configuration",
    ]
    # If the issuer URL is itself already a metadata document, try it directly too.
    if issuer.endswith(("server", "configuration")):
        candidates.insert(0, issuer)
    for url in candidates:
        meta = _get_json(client, url)
        if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
            return meta
    return None


def discover_metadata(server_url: str) -> dict:
    """Discover a server's OAuth endpoints + scopes. Raises DiscoveryError if the
    server advertises no usable metadata (then the manual form is the fallback)."""
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        scopes: list[str] = []
        as_issuers: list[str] = []

        # 1) Protected resource metadata (via 401), or the well-known fallback.
        rm_url = _resource_metadata_url(client, server_url) \
            or (_base(server_url) + "/.well-known/oauth-protected-resource")
        rm = _get_json(client, rm_url)
        if rm:
            as_issuers = rm.get("authorization_servers") or []
            scopes = rm.get("scopes_supported") or []

        # 2) Authorization server metadata — from each advertised issuer, else the
        #    server's own domain (older servers that skip the resource step).
        meta: Optional[dict] = None
        for issuer in as_issuers:
            meta = _as_metadata(client, issuer)
            if meta:
                break
        if meta is None:
            meta = _as_metadata(client, _base(server_url))
        if meta is None:
            raise DiscoveryError(
                "could not discover OAuth metadata for this server "
                "(no protected-resource or authorization-server metadata found). "
                "Enter the endpoints manually."
            )

        if not scopes:
            scopes = meta.get("scopes_supported") or []
        reg = meta.get("registration_endpoint")
        return {
            "issuer": meta.get("issuer"),
            "authorize_endpoint": meta["authorization_endpoint"],
            "token_endpoint": meta["token_endpoint"],
            "registration_endpoint": reg,
            "scopes_supported": scopes,
            "supports_dcr": bool(reg),
        }


def register_dynamic_client(
    registration_endpoint: str,
    *,
    redirect_uri: str,
    client_name: str = "DeepQuery",
    scopes: Optional[list[str]] = None,
) -> dict:
    """Dynamic Client Registration (RFC 7591) — get a client_id (and maybe secret)
    from the server with no manual app creation. Public client by default (PKCE,
    `token_endpoint_auth_method=none`)."""
    body: dict[str, Any] = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if scopes:
        body["scope"] = " ".join(scopes)
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = client.post(registration_endpoint, json=body, headers=_HEADERS)
    except httpx.HTTPError as exc:
        raise DiscoveryError(f"dynamic client registration unreachable: {exc}") from exc
    if r.status_code not in (200, 201):
        raise DiscoveryError(f"dynamic client registration failed ({r.status_code}): {r.text[:200]}")
    try:
        data = r.json()
    except ValueError as exc:
        raise DiscoveryError("registration endpoint returned a non-JSON response") from exc
    client_id = data.get("client_id")
    if not client_id:
        raise DiscoveryError("registration response had no client_id")
    return {
        "client_id": client_id,
        "client_secret": data.get("client_secret"),
        "token_endpoint_auth_method": data.get("token_endpoint_auth_method", "none"),
    }

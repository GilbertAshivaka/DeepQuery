"""
Deep Query — Connector Infrastructure Endpoints (live data layer)

GET  /api/connectors                 List registered connectors
POST /api/connectors                 Register a connector (admin)
POST /api/connectors/{id}/discover   Discover a connector's resources/actions
POST /api/connectors/{id}/read       Read a resource through the Gateway (audited)

Phase 1: routing + audit only. Allowlist enforcement (Phase 3), credential
injection (Phase 2), and action gating (Phase 4) attach at the Gateway later.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.dependencies import RoleRequired, get_current_user
from connectors.credentials import CredentialError, credential_store
from connectors.credentials import oauth as oauth_flow
from connectors.credentials.crypto import encrypt
from connectors.gateway import (
    ConnectorGateway,
    ConnectorNotFoundError,
    GatewayError,
    get_connector_ref,
    list_connector_refs,
    register_connector,
)
from connectors.gateway.deployment import mode as deployment_mode
from connectors.governance import (
    GovernanceError,
    approve_connector,
    available_for_role,
    disable_for_user,
    enable_for_user,
    get_approval,
    is_enabled,
    revoke_approval,
)
from core.config import settings
from core.constants import UserRole
from core.database import get_db
from models.database import Connector, ConnectorAuditLog, User

router = APIRouter()

# A single Gateway instance — the chokepoint every connector call passes through.
gateway = ConnectorGateway()

admin_only = RoleRequired([UserRole.ADMIN])


# ── Schemas ──────────────────────────────────────────────────
class RegisterConnectorRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    transport: str = Field("stdio", description="stdio | sse | http")
    endpoint: Dict[str, Any] = Field(
        ...,
        description="stdio: {command, args, env}; sse/http: {url, headers}",
    )
    version: Optional[str] = None
    requires_network: bool = True
    auth_method: str = Field("none", description="none | oauth2 | api_key | basic | mtls")
    # OAuth app config: {authorize_endpoint, token_endpoint, scopes, client_id,
    # client_secret}. A `client_secret` here is encrypted to `client_secret_enc`.
    auth_config: Optional[Dict[str, Any]] = None


class SetCredentialRequest(BaseModel):
    method: str = Field(..., description="api_key | basic | mtls")
    token: Optional[str] = None  # api_key
    username: Optional[str] = None  # basic
    password: Optional[str] = None  # basic
    client_cert_path: Optional[str] = None  # mtls
    client_key_path: Optional[str] = None  # mtls


class AuthStartResponse(BaseModel):
    authorization_url: str


class CredentialStatusResponse(BaseModel):
    connector_id: str
    connected: bool


class ConnectorOut(BaseModel):
    id: str
    name: str
    version: Optional[str]
    transport: str
    requires_network: bool


class DiscoveredToolOut(BaseModel):
    name: str
    description: str
    kind: str
    mutates: bool
    input_schema: Dict[str, Any]


class DiscoveredResourceOut(BaseModel):
    uri: str
    name: str
    description: str
    mime_type: Optional[str]
    is_template: bool


class DiscoveredPromptOut(BaseModel):
    name: str
    description: str
    arguments: List[Dict[str, Any]]


class DiscoveryOut(BaseModel):
    """A connector's full advertised capability set across all MCP primitives."""

    connector: str
    server_label: str
    supports: Dict[str, bool]
    tools: List[DiscoveredToolOut]
    resources: List[DiscoveredResourceOut]
    prompts: List[DiscoveredPromptOut]


class ReadRequest(BaseModel):
    capability: str = Field(..., description="Name of the resource (read) tool to call.")
    arguments: Dict[str, Any] = Field(default_factory=dict)


# ── Endpoints ────────────────────────────────────────────────
@router.get("", response_model=List[ConnectorOut])
def list_connectors(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List registered connectors (control-plane metadata only)."""
    refs = list_connector_refs(db, enabled_only=False)
    return [
        ConnectorOut(
            id=r.id, name=r.name, version=r.version, transport=r.transport, requires_network=r.requires_network
        )
        for r in refs
    ]


@router.post("", response_model=ConnectorOut, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterConnectorRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(admin_only),
):
    """Register (or update) a connector. Admin only."""
    # Encrypt a client_secret (if supplied) so it never rests in plaintext.
    auth_config = dict(body.auth_config) if body.auth_config else None
    if auth_config and auth_config.get("client_secret"):
        auth_config["client_secret_enc"] = encrypt(auth_config.pop("client_secret"))
    try:
        ref = register_connector(
            db,
            name=body.name,
            transport=body.transport,
            endpoint=body.endpoint,
            version=body.version,
            requires_network=body.requires_network,
            auth_method=body.auth_method,
            auth_config=auth_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ConnectorOut(
        id=ref.id, name=ref.name, version=ref.version, transport=ref.transport, requires_network=ref.requires_network
    )


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connector(
    connector_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(admin_only),
):
    """Delete a connector from the registry entirely (admin). Purges its allowlist
    entry, every user enablement, and stored credentials, then removes the connector.
    Its audit-log rows are detached (connector_id → NULL) so the FK doesn't block the
    delete while the trail is preserved via the stored connector name.

    Use revoke (`DELETE /{id}/approve`) to keep a connector but drop access; use this
    to remove it from the directory entirely."""
    ref = get_connector_ref(db, connector_id=connector_id)
    if ref is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    # Purge governance (allowlist + enablements + credentials).
    revoke_approval(db, connector_id=connector_id)
    # Detach audit rows so the FK doesn't block deletion (trail kept via name).
    db.query(ConnectorAuditLog).filter(
        ConnectorAuditLog.connector_id == connector_id
    ).update({ConnectorAuditLog.connector_id: None}, synchronize_session=False)
    conn = db.query(Connector).filter(Connector.id == connector_id).first()
    if conn is not None:
        db.delete(conn)
    db.commit()


@router.post("/{connector_id}/discover", response_model=DiscoveryOut)
async def discover(
    connector_id: str,
    user: User = Depends(get_current_user),
):
    """Discover a connector's full advertised capability set over MCP — tools,
    resources, and prompts (each probed only if the server declares it).

    Passes the caller's id so the Gateway injects their credential — OAuth-protected
    servers (e.g. Linear) reject the handshake without a token. No-auth servers are
    unaffected."""
    try:
        _ref, d = await gateway.discover(connector_id=connector_id, user_id=user.id)
    except ConnectorNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    except GatewayError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return DiscoveryOut(
        connector=d.connector,
        server_label=d.server_label,
        supports=d.supports,
        tools=[
            DiscoveredToolOut(
                name=t.name, description=t.description, kind=t.kind.value,
                mutates=t.mutates, input_schema=t.input_schema,
            )
            for t in d.tools
        ],
        resources=[
            DiscoveredResourceOut(
                uri=r.uri, name=r.name, description=r.description,
                mime_type=r.mime_type, is_template=r.is_template,
            )
            for r in d.resources
        ],
        prompts=[
            DiscoveredPromptOut(name=p.name, description=p.description, arguments=p.arguments)
            for p in d.prompts
        ],
    )


@router.post("/{connector_id}/read")
async def read(
    connector_id: str,
    body: ReadRequest,
    user: User = Depends(get_current_user),
):
    """Read a resource through the Gateway. Returns records + timestamped live
    citations; the call is audited."""
    try:
        return await gateway.read(
            capability=body.capability,
            arguments=body.arguments,
            connector_id=connector_id,
            user_id=user.id,
        )
    except ConnectorNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    except GatewayError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


# ── Resources & prompts (the other two MCP primitives) ──────
class ResourceReadRequest(BaseModel):
    uri: str = Field(..., description="URI of the resource to read.")


class PromptGetRequest(BaseModel):
    name: str = Field(..., description="Name of the prompt template.")
    arguments: Dict[str, str] = Field(default_factory=dict)


@router.post("/{connector_id}/resources/read")
async def read_resource(
    connector_id: str,
    body: ResourceReadRequest,
    user: User = Depends(get_current_user),
):
    """Read a resource by URI through the Gateway; returns contents + live citations."""
    try:
        return await gateway.read_resource(uri=body.uri, connector_id=connector_id, user_id=user.id)
    except ConnectorNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    except GatewayError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/{connector_id}/prompts/get")
async def get_prompt(
    connector_id: str,
    body: PromptGetRequest,
    user: User = Depends(get_current_user),
):
    """Fetch a prompt template through the Gateway. Returned content is untrusted."""
    try:
        return await gateway.get_prompt(
            prompt_name=body.name, arguments=body.arguments, connector_id=connector_id, user_id=user.id
        )
    except ConnectorNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    except GatewayError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


# ── Per-user credentials & enablement (guide §6) ─────────────
@router.post("/{connector_id}/auth/start", response_model=AuthStartResponse)
def auth_start(
    connector_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Begin this user's OAuth flow for the connector; returns the URL to send
    the user to for consent."""
    ref = get_connector_ref(db, connector_id=connector_id)
    if ref is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    try:
        url = oauth_flow.begin_authorization(user_id=user.id, connector_ref=ref)
    except oauth_flow.OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return AuthStartResponse(authorization_url=url)


@router.get("/auth/callback")
def auth_callback(
    state: str,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """OAuth redirect target. Identified by `state` (bound to the user in Redis),
    not a bearer token, since the provider redirects the user's browser here."""
    if error:
        return RedirectResponse(url=f"{settings.frontend_url}/connectors?error={error}")
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorization code.")
    try:
        _user_id, _connector_id = oauth_flow.complete_authorization(db, state=state, code=code)
    except oauth_flow.OAuthError as exc:
        return RedirectResponse(url=f"{settings.frontend_url}/connectors?error={exc}")
    return RedirectResponse(url=f"{settings.frontend_url}/connectors?connected=1")


@router.post("/{connector_id}/credentials", status_code=status.HTTP_204_NO_CONTENT)
def set_credential(
    connector_id: str,
    body: SetCredentialRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Set a static (non-OAuth) credential — API key / basic / mTLS — for this
    user. Used for internal systems and air-gapped deployments."""
    ref = get_connector_ref(db, connector_id=connector_id)
    if ref is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    if body.method == "api_key":
        payload = {"token": body.token}
    elif body.method == "basic":
        payload = {"username": body.username, "password": body.password}
    elif body.method == "mtls":
        payload = {"client_cert_path": body.client_cert_path, "client_key_path": body.client_key_path}
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported method: {body.method}")
    try:
        credential_store.set_credential(
            db, user_id=user.id, connector_id=connector_id, method=body.method, payload=payload
        )
    except CredentialError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{connector_id}/credentials", status_code=status.HTTP_204_NO_CONTENT)
def revoke_credential(
    connector_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Revoke (delete) this user's credential for the connector."""
    credential_store.delete_credential(db, user_id=user.id, connector_id=connector_id)


@router.get("/{connector_id}/credentials/status", response_model=CredentialStatusResponse)
def credential_status(
    connector_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Whether this user has a stored credential for the connector."""
    connected = credential_store.has_credential(db, user_id=user.id, connector_id=connector_id)
    return CredentialStatusResponse(connector_id=connector_id, connected=connected)


# ── OAuth auto-configuration (discovery + dynamic client registration) ──
class OAuthAutoConfigRequest(BaseModel):
    scopes: Optional[List[str]] = Field(
        default=None, description="Override discovered scopes; null = use the server's advertised scopes."
    )
    client_name: str = Field(default="DeepQuery", description="Client name to register via DCR.")


@router.post("/{connector_id}/oauth/autoconfigure")
def oauth_autoconfigure(
    connector_id: str,
    body: OAuthAutoConfigRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(admin_only),
):
    """Auto-configure OAuth for a spec-compliant MCP server so the admin only needs
    the server URL: discover its endpoints + scopes, and — when the server supports
    Dynamic Client Registration — register a client automatically. Stores the result
    as the connector's auth_config (client secret encrypted, never returned). Servers
    without DCR (e.g. GitHub/Atlassian) return needs_manual_client=true with the
    endpoints pre-filled, so the admin only adds a client id/secret."""
    import json
    import logging

    from connectors.credentials import oauth_discovery as disc
    from connectors.gateway.deployment import is_air_gapped

    ref = get_connector_ref(db, connector_id=connector_id)
    if ref is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    if is_air_gapped():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="external OAuth discovery is unavailable in air-gapped mode.")

    endpoint = ref.endpoint if isinstance(ref.endpoint, dict) else json.loads(ref.endpoint or "{}")
    url = endpoint.get("url")
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="this connector has no URL (stdio connectors don't use OAuth discovery).")

    try:
        meta = disc.discover_metadata(url)
    except disc.DiscoveryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    scopes = body.scopes if body.scopes is not None else meta["scopes_supported"]
    cfg: Dict[str, Any] = {
        "authorize_endpoint": meta["authorize_endpoint"],
        "token_endpoint": meta["token_endpoint"],
        "scopes": scopes,
        "registration_endpoint": meta.get("registration_endpoint"),
        "issuer": meta.get("issuer"),
    }

    needs_manual = True
    client_id = None
    if meta["supports_dcr"]:
        try:
            reg = disc.register_dynamic_client(
                meta["registration_endpoint"],
                redirect_uri=oauth_flow._redirect_uri(),
                client_name=body.client_name,
                scopes=scopes,
            )
            cfg["client_id"] = reg["client_id"]
            cfg["token_endpoint_auth_method"] = reg["token_endpoint_auth_method"]
            if reg.get("client_secret"):
                cfg["client_secret_enc"] = encrypt(reg["client_secret"])
            client_id = reg["client_id"]
            needs_manual = False
        except disc.DiscoveryError as exc:
            logging.getLogger(__name__).warning("DCR failed for %s, falling back to manual: %s", ref.name, exc)

    # Persist onto the connector (merge with any existing manual fields).
    conn = db.query(Connector).filter(Connector.id == connector_id).first()
    existing = json.loads(conn.auth_config) if conn.auth_config else {}
    existing.update(cfg)
    conn.auth_config = json.dumps(existing)
    conn.auth_method = "oauth2"
    db.commit()

    return {
        "discovered": True,
        "authorize_endpoint": cfg["authorize_endpoint"],
        "token_endpoint": cfg["token_endpoint"],
        "scopes": scopes,
        "supports_dcr": meta["supports_dcr"],
        "client_id": client_id,
        "needs_manual_client": needs_manual,
        "message": (
            "Ready — users can connect with one click."
            if not needs_manual
            else "Endpoints discovered. This server has no automatic registration — "
                 "create an OAuth app in the provider's console and add the client ID/secret."
        ),
    }


# ── Tiered governance: admin allowlist + user enablement (guide §9) ──
class ApproveRequest(BaseModel):
    allowed_roles: Optional[List[str]] = Field(
        default=None, description="Role strings permitted to use this connector; null = all roles."
    )
    version: Optional[str] = Field(default=None, description="Version to pin; defaults to the registered version.")


class DirectoryItemOut(BaseModel):
    connector_id: str
    name: str
    version: Optional[str]
    auth_method: str
    approved: bool
    approved_version: Optional[str]
    allowed_roles: Optional[List[str]]


@router.get("/directory", response_model=List[DirectoryItemOut])
def directory(
    db: Session = Depends(get_db),
    _admin: User = Depends(admin_only),
):
    """Admin view: every registered connector and its allowlist status."""
    import json as _json

    items: List[DirectoryItemOut] = []
    for ref in list_connector_refs(db, enabled_only=False):
        approval = get_approval(db, connector_id=ref.id)
        items.append(
            DirectoryItemOut(
                connector_id=ref.id,
                name=ref.name,
                version=ref.version,
                auth_method=ref.auth_method,
                approved=approval is not None,
                approved_version=approval.approved_version if approval else None,
                allowed_roles=_json.loads(approval.allowed_roles) if approval and approval.allowed_roles else None,
            )
        )
    return items


@router.post("/{connector_id}/approve", status_code=status.HTTP_204_NO_CONTENT)
def approve(
    connector_id: str,
    body: ApproveRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    """Approve a connector into the allowlist (optionally role-restricted, version-pinned)."""
    try:
        approve_connector(
            db, connector_id=connector_id, approved_by=admin.id,
            allowed_roles=body.allowed_roles, version=body.version,
        )
    except GovernanceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/{connector_id}/approve", status_code=status.HTTP_204_NO_CONTENT)
def revoke(
    connector_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(admin_only),
):
    """Remove a connector from the allowlist; purges enablements + credentials."""
    revoke_approval(db, connector_id=connector_id)


@router.get("/available")
def available(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Connectors approved and permitted for the requesting user's role, with the
    user's own enablement state."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    items = available_for_role(db, role=role)
    for it in items:
        it["enabled"] = is_enabled(db, user_id=user.id, connector_id=it["connector_id"])
    return items


@router.post("/{connector_id}/enable", status_code=status.HTTP_204_NO_CONTENT)
def enable(
    connector_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Enable an approved connector for the requesting user."""
    ref = get_connector_ref(db, connector_id=connector_id)
    if ref is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    try:
        enable_for_user(db, user_id=user.id, connector_ref=ref)
    except GovernanceError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.delete("/{connector_id}/enable", status_code=status.HTTP_204_NO_CONTENT)
def disable(
    connector_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Disable a connector for the requesting user (drops their credential)."""
    disable_for_user(db, user_id=user.id, connector_id=connector_id)


# ── Gated actions: preview -> approve -> execute / reject (guide §5) ──
class ActionPreviewRequest(BaseModel):
    capability: str = Field(..., description="Name of the action tool to preview.")
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ActionExecuteRequest(BaseModel):
    approval_token: str


@router.post("/{connector_id}/actions/preview")
async def action_preview(
    connector_id: str,
    body: ActionPreviewRequest,
    user: User = Depends(get_current_user),
):
    """Preview an action without executing it; opens a pending-approval record."""
    try:
        return await gateway.preview_action(
            connector_id=connector_id, capability=body.capability,
            arguments=body.arguments, user_id=user.id,
        )
    except ConnectorNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    except GatewayError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/actions/{pending_id}/approve")
async def action_approve(
    pending_id: str,
    user: User = Depends(get_current_user),
):
    """Approve a previewed action, returning a single-use approval token."""
    try:
        return await gateway.approve_action(pending_id=pending_id, approver_id=user.id)
    except GatewayError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/actions/{pending_id}/execute")
async def action_execute(
    pending_id: str,
    body: ActionExecuteRequest,
    user: User = Depends(get_current_user),
):
    """Execute a previewed action — refused without a valid approval token."""
    try:
        return await gateway.execute_action(
            pending_id=pending_id, approval_token=body.approval_token, user_id=user.id
        )
    except GatewayError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/actions/{pending_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def action_reject(
    pending_id: str,
    user: User = Depends(get_current_user),
):
    """Reject a previewed action; it is never executed."""
    try:
        await gateway.reject_action(pending_id=pending_id, approver_id=user.id)
    except GatewayError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── Health & deployment mode ─────────────────────────────────
@router.get("/deployment-mode")
def get_deployment_mode(_user: User = Depends(get_current_user)):
    """The deployment mode (cloud | hybrid | air-gapped) constraining connectors."""
    return {"mode": deployment_mode()}


@router.get("/{connector_id}/health")
def connector_health(
    connector_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Circuit-breaker health for a connector."""
    ref = get_connector_ref(db, connector_id=connector_id)
    if ref is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found.")
    return gateway.health(ref.name)

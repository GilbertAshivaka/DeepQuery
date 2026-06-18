"""Tiered governance: admins control what is *possible*, users what is *active*.

Tier 1 (admin): approve a connector into the allowlist, optionally restrict to
roles, pinned to a version. Tier 2 (user): enable an approved connector for
yourself. The gateway enforces both before any call. Roles are treated as opaque
strings — the taxonomy is deployment-specific (academic, clinical, legal, ...).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.database import Connector, ConnectorApproval, User, UserConnectorEnablement


class GovernanceError(Exception):
    """A governance rule denied an action; message is user-legible."""


# --------------------------------------------------------------------------- #
# Version pinning (guide §9, §11)
# --------------------------------------------------------------------------- #
def _major(version: Optional[str]) -> Optional[int]:
    if not version:
        return None
    try:
        return int(str(version).split(".")[0])
    except (ValueError, IndexError):
        return None


def version_compatible(approved_version: Optional[str], current_version: Optional[str]) -> bool:
    """A connector stays approved across minor/patch changes, but a **major**
    bump re-enters review (returns False)."""
    a, c = _major(approved_version), _major(current_version)
    if a is None or c is None:
        return True  # unversioned connectors aren't version-gated
    return a == c


# --------------------------------------------------------------------------- #
# Tier 1 — admin allowlist
# --------------------------------------------------------------------------- #
def approve_connector(
    db: Session,
    *,
    connector_id: str,
    approved_by: Optional[str] = None,
    allowed_roles: Optional[list[str]] = None,
    version: Optional[str] = None,
) -> ConnectorApproval:
    """Approve (or re-approve) a connector into the allowlist. Pins to `version`
    or, if omitted, the connector's currently-registered version."""
    conn = db.query(Connector).filter(Connector.id == connector_id).first()
    if conn is None:
        raise GovernanceError("connector not found")
    # Deployment-mode policy: an air-gapped deployment won't approve a
    # network-dependent connector (guide §11). Lazy import avoids an import cycle.
    from connectors.gateway.deployment import DeploymentError, assert_connector_permitted

    try:
        assert_connector_permitted(conn)
    except DeploymentError as exc:
        raise GovernanceError(str(exc)) from exc
    row = db.query(ConnectorApproval).filter(ConnectorApproval.connector_id == connector_id).first()
    if row is None:
        row = ConnectorApproval(connector_id=connector_id)
        db.add(row)
    row.is_approved = True
    row.approved_version = version or conn.version
    row.allowed_roles = json.dumps(allowed_roles) if allowed_roles else None
    row.approved_by = approved_by
    db.commit()
    db.refresh(row)
    return row


def revoke_approval(db: Session, *, connector_id: str) -> None:
    """Remove a connector from the allowlist and purge all user enablements and
    credentials for it (revocation is immediate — guide §6, §9)."""
    db.query(ConnectorApproval).filter(ConnectorApproval.connector_id == connector_id).delete()
    db.query(UserConnectorEnablement).filter(UserConnectorEnablement.connector_id == connector_id).delete()
    db.commit()
    # Purge stored credentials too.
    from connectors.credentials import credential_store

    credential_store.purge_connector(db, connector_id=connector_id)


def get_approval(db: Session, *, connector_id: str) -> Optional[ConnectorApproval]:
    row = (
        db.query(ConnectorApproval)
        .filter(ConnectorApproval.connector_id == connector_id, ConnectorApproval.is_approved.is_(True))
        .first()
    )
    return row


def _allowed_roles(approval: ConnectorApproval) -> Optional[list[str]]:
    return json.loads(approval.allowed_roles) if approval.allowed_roles else None


def _role_permitted(approval: ConnectorApproval, role: str) -> bool:
    roles = _allowed_roles(approval)
    return roles is None or role in roles


def available_for_role(db: Session, *, role: str) -> list[dict[str, Any]]:
    """Connectors approved and permitted for a given role (Tier 2 user view)."""
    out: list[dict[str, Any]] = []
    rows = (
        db.query(ConnectorApproval, Connector)
        .join(Connector, Connector.id == ConnectorApproval.connector_id)
        .filter(ConnectorApproval.is_approved.is_(True))
        .all()
    )
    for approval, conn in rows:
        if _role_permitted(approval, role):
            out.append(
                {
                    "connector_id": conn.id,
                    "name": conn.name,
                    "version": conn.version,
                    "auth_method": conn.auth_method,
                    "summary": conn.summary,
                    "icon_url": conn.icon_url,
                    "allowed_roles": _allowed_roles(approval),
                }
            )
    return out


# --------------------------------------------------------------------------- #
# Tier 2 — user enablement
# --------------------------------------------------------------------------- #
def _user_role(db: Session, user_id: str) -> Optional[str]:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def enable_for_user(db: Session, *, user_id: str, connector_ref) -> None:
    """Enable an approved connector for a user (subject to role + version)."""
    role = _user_role(db, user_id)
    if role is None:
        raise GovernanceError("user not found")
    _assert_allowed(db, user_id=user_id, role=role, connector_ref=connector_ref, require_enabled=False)
    if not is_enabled(db, user_id=user_id, connector_id=connector_ref.id):
        db.add(UserConnectorEnablement(user_id=user_id, connector_id=connector_ref.id))
        db.commit()


def disable_for_user(db: Session, *, user_id: str, connector_id: str) -> None:
    """Disable a connector for a user and drop their stored credential for it."""
    db.query(UserConnectorEnablement).filter(
        UserConnectorEnablement.user_id == user_id, UserConnectorEnablement.connector_id == connector_id
    ).delete()
    db.commit()
    from connectors.credentials import credential_store

    credential_store.delete_credential(db, user_id=user_id, connector_id=connector_id)


def is_enabled(db: Session, *, user_id: str, connector_id: str) -> bool:
    return (
        db.query(UserConnectorEnablement)
        .filter(UserConnectorEnablement.user_id == user_id, UserConnectorEnablement.connector_id == connector_id)
        .first()
        is not None
    )


# --------------------------------------------------------------------------- #
# Enforcement (called by the gateway before every user call)
# --------------------------------------------------------------------------- #
def _assert_allowed(db: Session, *, user_id: str, role: str, connector_ref, require_enabled: bool) -> None:
    approval = get_approval(db, connector_id=connector_ref.id)
    if approval is None:
        raise GovernanceError(f"connector '{connector_ref.name}' is not approved for this deployment")
    if not _role_permitted(approval, role):
        raise GovernanceError(f"your role is not permitted to use the '{connector_ref.name}' connector")
    if not version_compatible(approval.approved_version, connector_ref.version):
        raise GovernanceError(
            f"the '{connector_ref.name}' connector changed major version "
            f"(approved {approval.approved_version}, now {connector_ref.version}) and must be re-reviewed"
        )
    if require_enabled and not is_enabled(db, user_id=user_id, connector_id=connector_ref.id):
        raise GovernanceError(f"you have not enabled the '{connector_ref.name}' connector")


def check_access(db: Session, *, user_id: str, connector_ref) -> None:
    """Raise GovernanceError unless the user may use this connector right now:
    approved + role-permitted + version-compatible + enabled."""
    role = _user_role(db, user_id)
    if role is None:
        raise GovernanceError("user not found")
    _assert_allowed(db, user_id=user_id, role=role, connector_ref=connector_ref, require_enabled=True)

"""Tiered governance — admin allowlist + per-user enablement (guide §9)."""

from connectors.governance.service import (
    GovernanceError,
    approve_connector,
    available_for_role,
    check_access,
    disable_for_user,
    enable_for_user,
    get_approval,
    is_enabled,
    revoke_approval,
    version_compatible,
)

__all__ = [
    "GovernanceError",
    "approve_connector",
    "revoke_approval",
    "get_approval",
    "enable_for_user",
    "disable_for_user",
    "is_enabled",
    "check_access",
    "available_for_role",
    "version_compatible",
]

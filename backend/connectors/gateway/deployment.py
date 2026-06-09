"""Deployment-mode policy (guide §11).

The mode constrains which connectors are permissible. It is checked at three
points: approval (an air-gapped deployment won't approve a network connector),
credential-setup (no external OAuth in air-gapped), and call time (egress).
"""

from __future__ import annotations

from core.config import settings

CLOUD = "cloud"
HYBRID = "hybrid"
AIR_GAPPED = "air-gapped"


class DeploymentError(Exception):
    """A connector is not permissible under the current deployment mode."""


def mode() -> str:
    return (settings.deployment_mode or CLOUD).strip().lower()


def is_air_gapped() -> bool:
    return mode() == AIR_GAPPED


def connector_permitted(ref) -> tuple[bool, str]:
    """Whether a connector may run under the current mode. `ref` is anything with
    `.transport`, `.requires_network`, and `.name` (ConnectorRef or Connector row)."""
    if is_air_gapped():
        if ref.transport != "stdio":
            return False, (
                f"air-gapped mode permits only self-hosted (stdio) connectors; "
                f"'{ref.name}' uses the '{ref.transport}' transport (external egress)"
            )
        if getattr(ref, "requires_network", False):
            return False, (
                f"air-gapped mode forbids network-dependent connectors; "
                f"'{ref.name}' declares requires_network=True"
            )
    return True, ""


def assert_connector_permitted(ref) -> None:
    ok, reason = connector_permitted(ref)
    if not ok:
        raise DeploymentError(reason)

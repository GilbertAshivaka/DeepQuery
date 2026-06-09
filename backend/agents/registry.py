"""
Deep Query — Sub-Agent Capability Registry

The Orchestrator delegates by *capability*, not by hardcoded sub-agent name. This
registry is the indirection that makes the agent layer extensible: adding a future
sub-agent (e.g. comparison, export) is a `register(...)` call plus a capability the
planner can target — not a refactor of the orchestrator.

Sub-agents register themselves at import time. The Orchestrator asks the registry
which capabilities are available and resolves a handler when it needs one.

Note: SKILL_SYNC is intentionally *not* a query-time capability — it is triggered by
ingestion events, not by user requests (guide §11), so it is not delegated from here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Capability(str, Enum):
    """What a sub-agent can do. The Orchestrator plans in terms of these."""

    RETRIEVAL = "retrieval"      # gather grounded context (document + live)
    ACTION = "action"            # gated, state-mutating actions (Phase 3)
    VERIFICATION = "verification"  # self-correction / groundedness check


@dataclass(frozen=True)
class SubAgentSpec:
    """A registered sub-agent: the capability it provides and the handler object
    that implements it (any object the Orchestrator knows how to drive)."""

    capability: Capability
    name: str
    handler: Any
    description: str = ""


# Single capability → spec mapping. One handler per capability for now; if multiple
# providers of the same capability are ever needed, this becomes capability → list.
_REGISTRY: dict[Capability, SubAgentSpec] = {}


def register(spec: SubAgentSpec, *, override: bool = False) -> None:
    """Register a sub-agent for a capability. Idempotent re-registration of the same
    name is allowed; a different handler for an occupied capability requires
    ``override=True`` to avoid silent clobbering."""
    existing = _REGISTRY.get(spec.capability)
    if existing is not None and existing.name != spec.name and not override:
        raise ValueError(
            f"Capability '{spec.capability.value}' already provided by "
            f"'{existing.name}'. Pass override=True to replace it."
        )
    _REGISTRY[spec.capability] = spec
    logger.info("Registered sub-agent '%s' for capability '%s'", spec.name, spec.capability.value)


def get(capability: Capability) -> SubAgentSpec:
    """Resolve the sub-agent for a capability, or raise if none is registered."""
    spec = _REGISTRY.get(capability)
    if spec is None:
        raise KeyError(
            f"No sub-agent registered for capability '{capability.value}'. "
            f"Available: {[c.value for c in _REGISTRY]}"
        )
    return spec


def has(capability: Capability) -> bool:
    """Whether a capability is currently available."""
    return capability in _REGISTRY


def available() -> list[Capability]:
    """All currently-registered capabilities (for planning + diagnostics)."""
    return list(_REGISTRY.keys())

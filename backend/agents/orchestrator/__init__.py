"""
Deep Query — Orchestrator

    from agents.orchestrator import orchestrator
    async for event in orchestrator.run(query=..., allowed_collections=[...]):
        ...
"""

from agents.orchestrator.graph import Intent, Orchestrator, orchestrator

__all__ = ["orchestrator", "Orchestrator", "Intent"]

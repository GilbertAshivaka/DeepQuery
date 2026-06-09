"""
Deep Query — Retrieval Sub-Agent

Gathers grounded context with citations. Phase 1: the document path only (wraps
``retrieval.pipeline.gather_context``). Phase 2 adds the live path via the Connector
Gateway and merges both into one citation-tagged context set.

Importing this package registers the sub-agent for Capability.RETRIEVAL.
"""

from agents.retrieval_agent.agent import RetrievalAgent, retrieval_agent

__all__ = ["RetrievalAgent", "retrieval_agent"]

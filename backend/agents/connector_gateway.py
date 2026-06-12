"""
Deep Query — Agent-layer Connector Gateway singleton

One ``ConnectorGateway`` instance shared by the agent layer (retrieval + action), so
circuit-breaker state is consistent across both paths. The gateway enforces
governance, credentials, deployment mode, caching, action-gating, and audit; the
agent layer only ever calls it (never speaks MCP directly).
"""

from connectors.gateway import ConnectorGateway

gateway = ConnectorGateway()

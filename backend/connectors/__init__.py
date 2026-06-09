"""Deep Query — Connector Infrastructure (live data layer).

Lets agents read from (and later act in) external systems via MCP, without ever
persisting live data. See CONNECTOR_INFRASTRUCTURE_GUIDE.md.

Components:
- ``mcp_client``  — the single universal MCP interface to every connector.
- ``gateway``     — policy/control plane: routing + audit (Phase 1).
- ``citations``   — live-citation construction from provenance envelopes.
"""

"""
Deep Query — Agent Layer

The reasoning/coordination tier that wraps the existing RAG system: an Orchestrator
that plans and delegates to specialized sub-agents (retrieval, action, verification,
skill-sync). See AGENT_LAYER_GUIDE.md (spec), AGENT_LAYER_HANDOFF.md (ground truth),
and AGENT_LAYER_PLAN.md (decisions) at the repo root.
"""

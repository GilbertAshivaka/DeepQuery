"""
Deep Query — Skill Synchronization Agent

Closes the self-maintaining-groundedness loop (guide §11): when a document changes,
it finds the skill files whose corpus-derived facts depend on it (explicitly declared,
or inferred by semantic similarity) and proposes admin-reviewable, grounded diffs.
Triggered by ingestion events, never by user queries. Never auto-applies.
"""

from agents.skill_sync.agent import run_sync_for_document

__all__ = ["run_sync_for_document"]

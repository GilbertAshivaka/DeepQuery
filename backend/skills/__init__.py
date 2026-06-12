"""
Deep Query — Skill Files (Agent Layer)

DB-backed, versioned, reversible skill files (guide §10). Content follows the
Anthropic Agent-Skills format (frontmatter + human-intent body + corpus-fact
sections); the DB is the source of truth. The Skill Sync Agent (Phase 4 / Sprint 8)
maintains only the corpus-fact sections, never the human-intent body.
"""

from skills import service
from skills.parser import parse_skill_markdown, render_skill

__all__ = ["service", "parse_skill_markdown", "render_skill"]

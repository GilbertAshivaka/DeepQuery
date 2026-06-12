"""
Deep Query — Skill File Format (Anthropic Agent-Skills compatible)

Parse/serialize the on-the-wire skill format: YAML frontmatter (`name`,
`description`, and a namespaced `deepquery:` block) + a human-intent body +
corpus-fact sections. Storage is the DB; this module is for import/authoring and for
rendering a skill into the text an agent/assistant is given.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
# Anthropic name rule: lowercase letters, numbers, hyphens; <=64; no reserved words.
_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
_RESERVED = ("anthropic", "claude")


class SkillFormatError(Exception):
    """The skill markdown is malformed or violates the format rules."""


def validate_name(name: str) -> None:
    if not _NAME_RE.match(name or ""):
        raise SkillFormatError("name must be 1–64 chars, lowercase letters/numbers/hyphens only")
    if any(w in name for w in _RESERVED):
        raise SkillFormatError("name must not contain reserved words ('anthropic', 'claude')")


def parse_skill_markdown(text: str) -> dict[str, Any]:
    """Parse a SKILL.md-style document into its parts. Fact sections are not split
    out on import (the body is taken whole); admins/sync add fact sections later."""
    m = _FRONTMATTER_RE.match(text or "")
    if not m:
        raise SkillFormatError("missing YAML frontmatter (--- ... ---)")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillFormatError(f"invalid YAML frontmatter: {exc}") from exc

    name = str(fm.get("name", "")).strip()
    description = str(fm.get("description", "")).strip()
    validate_name(name)
    if not description:
        raise SkillFormatError("description is required and must be non-empty")

    dq = fm.get("deepquery") or {}
    return {
        "name": name,
        "description": description,
        "kind": str(dq.get("kind", "assistant")),
        "body": m.group(2).strip(),
        "metadata": {
            k: v for k, v in dq.items() if k != "kind"
        },  # connectors, capabilities, model_overrides, dependencies, ...
        "fact_sections": [],
    }


def render_skill(skill) -> str:
    """Render a SkillFile (DB row) back to SKILL.md text: frontmatter + body +
    corpus-fact sections. Used to feed an assistant's instructions to the model."""
    import json

    meta = {}
    if getattr(skill, "metadata_json", None):
        try:
            meta = json.loads(skill.metadata_json)
        except json.JSONDecodeError:
            meta = {}
    dq = {"kind": skill.kind, **meta}
    front = {"name": skill.name, "description": skill.description, "deepquery": dq}

    parts = ["---", yaml.safe_dump(front, sort_keys=False).strip(), "---", "", skill.body.strip()]

    try:
        sections = json.loads(skill.fact_sections) if skill.fact_sections else []
    except json.JSONDecodeError:
        sections = []
    if sections:
        parts.append("\n## Corpus facts\n")
        for s in sections:
            parts.append(f"### {s.get('name','')}\n{s.get('content','')}\n")
    return "\n".join(parts).strip() + "\n"

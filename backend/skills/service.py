"""
Deep Query — Skill File Service

CRUD + versioning over skill files. Every content change writes a new immutable,
attributable ``SkillFileVersion`` snapshot, so any prior version can be restored
(reversibility is mandatory — guide §10). The human-intent ``body`` is editable only
by admins; the corpus-fact sections are the part the Skill Sync Agent maintains.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.database import (
    SkillChangeProposal,
    SkillDependency,
    SkillFile,
    SkillFileVersion,
)


class SkillError(Exception):
    """A skill operation failed (not found, name clash, bad version, ...)."""


def _loads(text: Optional[str], default):
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _snapshot(db: Session, skill: SkillFile, *, triggered_by: str, change_summary: str) -> None:
    """Write an immutable version snapshot of the skill's current content."""
    db.add(SkillFileVersion(
        skill_id=skill.id,
        version_no=skill.current_version,
        body=skill.body,
        fact_sections=skill.fact_sections,
        metadata_json=skill.metadata_json,
        change_summary=change_summary,
        triggered_by=triggered_by,
    ))


# ── Create / read ────────────────────────────────────────────
def create_skill(
    db: Session,
    *,
    name: str,
    description: str,
    kind: str = "assistant",
    body: str = "",
    fact_sections: Optional[list[dict]] = None,
    metadata: Optional[dict] = None,
    created_by: Optional[str] = None,
) -> SkillFile:
    if db.query(SkillFile).filter(SkillFile.name == name).first():
        raise SkillError(f"a skill named '{name}' already exists")
    skill = SkillFile(
        name=name, description=description, kind=kind, body=body,
        fact_sections=json.dumps(fact_sections or []),
        metadata_json=json.dumps(metadata) if metadata else None,
        current_version=1, created_by=created_by,
    )
    db.add(skill)
    db.flush()  # assign id before snapshot
    _snapshot(db, skill, triggered_by="create", change_summary="Initial version")
    db.commit()
    db.refresh(skill)
    return skill


def get_skill(db: Session, skill_id: str) -> Optional[SkillFile]:
    return db.query(SkillFile).filter(SkillFile.id == skill_id).first()


def get_skill_by_name(db: Session, name: str) -> Optional[SkillFile]:
    return db.query(SkillFile).filter(SkillFile.name == name).first()


def list_skills(db: Session, *, include_archived: bool = False) -> list[SkillFile]:
    q = db.query(SkillFile)
    if not include_archived:
        q = q.filter(SkillFile.is_archived.is_(False))
    return q.order_by(SkillFile.name).all()


def fact_sections_of(skill: SkillFile) -> list[dict]:
    return _loads(skill.fact_sections, [])


def delete_skill(db: Session, skill_id: str) -> None:
    """Hard-delete a skill and its child rows (versions, dependencies, pending proposals).
    Irreversible — admins use this to remove a skill outright (distinct from archiving)."""
    skill = get_skill(db, skill_id)
    if skill is None:
        raise SkillError("skill not found")
    db.query(SkillChangeProposal).filter(SkillChangeProposal.skill_id == skill_id).delete()
    db.query(SkillDependency).filter(SkillDependency.skill_id == skill_id).delete()
    db.query(SkillFileVersion).filter(SkillFileVersion.skill_id == skill_id).delete()
    db.delete(skill)
    db.commit()


def list_versions(db: Session, skill_id: str) -> list[SkillFileVersion]:
    return (
        db.query(SkillFileVersion)
        .filter(SkillFileVersion.skill_id == skill_id)
        .order_by(SkillFileVersion.version_no.desc())
        .all()
    )


# ── Edits (each writes a new version) ────────────────────────
def _bump(db: Session, skill: SkillFile, *, triggered_by: str, change_summary: str) -> SkillFile:
    skill.current_version += 1
    _snapshot(db, skill, triggered_by=triggered_by, change_summary=change_summary)
    db.commit()
    db.refresh(skill)
    return skill


def update_human_intent(
    db: Session, skill_id: str, *,
    body: Optional[str] = None, description: Optional[str] = None,
    metadata: Optional[dict] = None, by: str,
) -> SkillFile:
    """Admin edit of the human-intent body / description / metadata. NOT for sync."""
    skill = get_skill(db, skill_id)
    if skill is None:
        raise SkillError("skill not found")
    if body is not None:
        skill.body = body
    if description is not None:
        skill.description = description
    if metadata is not None:
        skill.metadata_json = json.dumps(metadata)
    return _bump(db, skill, triggered_by=f"admin:{by}", change_summary="Edited human-intent content")


def set_fact_section(
    db: Session, skill_id: str, *, section: str, content: str,
    triggered_by: str, change_summary: str,
) -> SkillFile:
    """Create/replace one corpus-fact section's content (used by Skill Sync on
    approval, and by admins). Writes a new reversible version."""
    skill = get_skill(db, skill_id)
    if skill is None:
        raise SkillError("skill not found")
    sections = fact_sections_of(skill)
    for s in sections:
        if s.get("name") == section:
            s["content"] = content
            break
    else:
        sections.append({"name": section, "content": content})
    skill.fact_sections = json.dumps(sections)
    return _bump(db, skill, triggered_by=triggered_by, change_summary=change_summary)


def rollback(db: Session, skill_id: str, *, version_no: int, by: str) -> SkillFile:
    """Restore a prior version's content as a new (reversible) version."""
    skill = get_skill(db, skill_id)
    if skill is None:
        raise SkillError("skill not found")
    target = (
        db.query(SkillFileVersion)
        .filter(SkillFileVersion.skill_id == skill_id, SkillFileVersion.version_no == version_no)
        .first()
    )
    if target is None:
        raise SkillError(f"version {version_no} not found")
    skill.body = target.body
    skill.fact_sections = target.fact_sections
    skill.metadata_json = target.metadata_json
    return _bump(db, skill, triggered_by=f"rollback:v{version_no}",
                 change_summary=f"Rolled back to version {version_no} (by {by})")


# ── Dependencies ─────────────────────────────────────────────
def declare_dependency(
    db: Session, skill_id: str, *, dep_type: str, dep_ref: str,
    declared: bool = True, fact_section: Optional[str] = None,
) -> SkillDependency:
    existing = (
        db.query(SkillDependency)
        .filter(SkillDependency.skill_id == skill_id,
                SkillDependency.dep_type == dep_type,
                SkillDependency.dep_ref == dep_ref)
        .first()
    )
    if existing:
        if declared and not existing.declared:
            existing.declared = True  # promote an inferred dep to declared
        db.commit()
        return existing
    dep = SkillDependency(
        skill_id=skill_id, dep_type=dep_type, dep_ref=dep_ref,
        declared=declared, fact_section=fact_section,
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)
    return dep


def list_dependencies(db: Session, skill_id: str) -> list[SkillDependency]:
    return db.query(SkillDependency).filter(SkillDependency.skill_id == skill_id).all()


def skills_declaring_document(db: Session, document_id: str) -> list[SkillFile]:
    """Skills with an explicit declared dependency on a document (high-confidence
    sync signal)."""
    rows = (
        db.query(SkillDependency)
        .filter(SkillDependency.dep_type == "document",
                SkillDependency.dep_ref == document_id,
                SkillDependency.declared.is_(True))
        .all()
    )
    ids = {r.skill_id for r in rows}
    if not ids:
        return []
    return db.query(SkillFile).filter(SkillFile.id.in_(ids)).all()


# ── Change proposals (Skill Sync Agent → admin review) ──────
def create_proposal(
    db: Session, *, skill_id: str, fact_section: str, old_content: Optional[str],
    new_content: str, trigger_document_id: Optional[str], trigger_summary: str,
    confidence: str,
) -> SkillChangeProposal:
    p = SkillChangeProposal(
        skill_id=skill_id, fact_section=fact_section, old_content=old_content,
        new_content=new_content, trigger_document_id=trigger_document_id,
        trigger_summary=trigger_summary, confidence=confidence, status="pending",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def list_proposals(db: Session, *, status: Optional[str] = "pending") -> list[SkillChangeProposal]:
    q = db.query(SkillChangeProposal)
    if status:
        q = q.filter(SkillChangeProposal.status == status)
    return q.order_by(SkillChangeProposal.created_at.desc()).all()


def get_proposal(db: Session, proposal_id: str) -> Optional[SkillChangeProposal]:
    return db.query(SkillChangeProposal).filter(SkillChangeProposal.id == proposal_id).first()


def approve_proposal(db: Session, proposal_id: str, *, by: str) -> SkillFile:
    """Apply a pending proposal as a new reversible skill version, then mark approved.
    This is the ONLY path a sync edit reaches a skill — always after human approval."""
    p = get_proposal(db, proposal_id)
    if p is None:
        raise SkillError("proposal not found")
    if p.status != "pending":
        raise SkillError(f"proposal is already {p.status}")
    trig = f"skill_sync:doc:{p.trigger_document_id}" if p.trigger_document_id else "skill_sync"
    skill = set_fact_section(
        db, p.skill_id, section=p.fact_section, content=p.new_content,
        triggered_by=trig, change_summary=f"Skill Sync (approved by {by}): {p.trigger_summary}",
    )
    p.status = "approved"
    p.decided_at = datetime.now(timezone.utc)
    p.decided_by = by
    db.commit()
    return skill


def reject_proposal(db: Session, proposal_id: str, *, by: str) -> SkillChangeProposal:
    """Reject a pending proposal — nothing changes; the dismissal is recorded
    (useful for tuning inference)."""
    p = get_proposal(db, proposal_id)
    if p is None:
        raise SkillError("proposal not found")
    if p.status != "pending":
        raise SkillError(f"proposal is already {p.status}")
    p.status = "rejected"
    p.decided_at = datetime.now(timezone.utc)
    p.decided_by = by
    db.commit()
    db.refresh(p)
    return p

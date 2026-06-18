"""
Deep Query — Skill File & Sync Endpoints (admin)

Browse/author skill files, review Skill-Sync proposals, and roll back versions.
Admin-only: editing instructions that govern agents has a wide blast radius, and
every Sync edit is human-gated here (guide §11).

GET    /api/skills                          list skill files
POST   /api/skills                          create a skill file
GET    /api/skills/{id}                     detail + versions + dependencies
POST   /api/skills/{id}/rollback            roll back to a prior version
POST   /api/skills/{id}/dependencies        declare a corpus dependency
GET    /api/skills/proposals                list change proposals (default: pending)
POST   /api/skills/proposals/{id}/approve   apply a proposal (new reversible version)
POST   /api/skills/proposals/{id}/reject    reject a proposal (logged)
"""

import json
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.dependencies import RoleRequired
from core.constants import UserRole
from core.database import get_db
from models.database import Document, User
from skills import service
from skills.parser import SkillFormatError, parse_skill_markdown

router = APIRouter()
admin_only = RoleRequired([UserRole.ADMIN])

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


# ── Human-readable labels for the UUIDs surfaced in the Skills UI ────
def _label_map(db: Session, ids: set[str]) -> dict[str, str]:
    """Resolve a set of UUIDs to readable labels: documents → original filename,
    users → full name. UUIDs that resolve to neither are simply omitted (callers
    fall back to showing the raw id). The underlying ids are untouched — this only
    affects what admins read."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    labels: dict[str, str] = {}
    for doc in db.query(Document.id, Document.original_filename).filter(Document.id.in_(ids)):
        if doc.original_filename:
            labels[doc.id] = doc.original_filename
    for u in db.query(User.id, User.full_name, User.username).filter(User.id.in_(ids)):
        labels.setdefault(u.id, u.full_name or u.username)
    return labels


def _humanize(text: Optional[str], labels: dict[str, str]) -> Optional[str]:
    """Replace any known UUID inside a free-text string with its readable label."""
    if not text:
        return text
    return _UUID_RE.sub(lambda m: labels.get(m.group(0), m.group(0)), text)


# ── Schemas ──────────────────────────────────────────────────
class CreateSkillRequest(BaseModel):
    # Either provide structured fields…
    name: Optional[str] = Field(None, description="lowercase-hyphen, <=64 chars")
    description: Optional[str] = None
    kind: str = "assistant"
    body: str = ""
    metadata: Optional[dict[str, Any]] = None
    # …or paste a full SKILL.md to parse.
    markdown: Optional[str] = None


class RollbackRequest(BaseModel):
    version_no: int


class DependencyRequest(BaseModel):
    dep_type: str = Field(..., description="document | entity")
    dep_ref: str = Field(..., description="document_id or entity name")
    fact_section: Optional[str] = None


def _skill_out(skill) -> dict:
    return {
        "id": skill.id, "name": skill.name, "description": skill.description,
        "kind": skill.kind, "current_version": skill.current_version,
        "is_archived": skill.is_archived,
        "fact_sections": service.fact_sections_of(skill),
        "metadata": json.loads(skill.metadata_json) if skill.metadata_json else {},
    }


def _proposal_out(p, labels: Optional[dict[str, str]] = None) -> dict:
    labels = labels or {}
    return {
        "id": p.id, "skill_id": p.skill_id, "fact_section": p.fact_section,
        "old_content": p.old_content, "new_content": p.new_content,
        "trigger_document_id": p.trigger_document_id,
        "trigger_document_name": labels.get(p.trigger_document_id),
        "trigger_summary": p.trigger_summary,
        "confidence": p.confidence, "status": p.status,
        "created_at": p.created_at,
    }


# ── Skill files ──────────────────────────────────────────────
@router.get("")
def list_skills(db: Session = Depends(get_db), _admin: User = Depends(admin_only)):
    return [_skill_out(s) for s in service.list_skills(db, include_archived=True)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_skill(body: CreateSkillRequest, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    try:
        if body.markdown:
            parsed = parse_skill_markdown(body.markdown)
            skill = service.create_skill(
                db, name=parsed["name"], description=parsed["description"],
                kind=parsed["kind"], body=parsed["body"], metadata=parsed["metadata"],
                created_by=admin.id,
            )
        else:
            if not body.name or not body.description:
                raise HTTPException(status_code=400, detail="name and description are required")
            skill = service.create_skill(
                db, name=body.name, description=body.description, kind=body.kind,
                body=body.body, metadata=body.metadata, created_by=admin.id,
            )
    except (service.SkillError, SkillFormatError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _skill_out(skill)


# ── Sync proposals ─── (declared before /{skill_id} so 'proposals' isn't captured
# as a skill_id path param)
@router.get("/proposals")
def list_proposals(status: str = "pending", db: Session = Depends(get_db), _admin: User = Depends(admin_only)):
    proposals = service.list_proposals(db, status=status or None)
    labels = _label_map(db, {p.trigger_document_id for p in proposals})
    return [_proposal_out(p, labels) for p in proposals]


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    try:
        skill = service.approve_proposal(db, proposal_id, by=admin.id)
    except service.SkillError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "approved", "skill": _skill_out(skill)}


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    try:
        p = service.reject_proposal(db, proposal_id, by=admin.id)
    except service.SkillError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "rejected", "proposal_id": p.id}


# ── Skill detail / rollback / dependencies (path-param routes) ──
@router.get("/{skill_id}")
def get_skill(skill_id: str, db: Session = Depends(get_db), _admin: User = Depends(admin_only)):
    skill = service.get_skill(db, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="skill not found")
    versions = service.list_versions(db, skill_id)
    deps = service.list_dependencies(db, skill_id)

    # Collect every UUID that may appear in version attribution / summaries (doc &
    # user ids) plus document dependency refs, and resolve them to readable labels.
    ids: set[str] = set()
    for v in versions:
        ids.update(_UUID_RE.findall(f"{v.triggered_by or ''} {v.change_summary or ''}"))
    ids.update(d.dep_ref for d in deps if d.dep_type == "document")
    labels = _label_map(db, ids)

    out = _skill_out(skill)
    out["body"] = skill.body
    out["versions"] = [
        {"version_no": v.version_no,
         "triggered_by": _humanize(v.triggered_by, labels),
         "change_summary": _humanize(v.change_summary, labels),
         "created_at": v.created_at}
        for v in versions
    ]
    out["dependencies"] = [
        {"dep_type": d.dep_type, "dep_ref": d.dep_ref,
         "dep_ref_name": labels.get(d.dep_ref) if d.dep_type == "document" else None,
         "declared": d.declared, "fact_section": d.fact_section}
        for d in deps
    ]
    return out


@router.post("/{skill_id}/rollback")
def rollback(skill_id: str, body: RollbackRequest, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    try:
        skill = service.rollback(db, skill_id, version_no=body.version_no, by=admin.id)
    except service.SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _skill_out(skill)


@router.post("/{skill_id}/dependencies", status_code=status.HTTP_201_CREATED)
def declare_dependency(skill_id: str, body: DependencyRequest, db: Session = Depends(get_db), _admin: User = Depends(admin_only)):
    if service.get_skill(db, skill_id) is None:
        raise HTTPException(status_code=404, detail="skill not found")
    dep = service.declare_dependency(
        db, skill_id, dep_type=body.dep_type, dep_ref=body.dep_ref,
        declared=True, fact_section=body.fact_section,
    )
    return {"id": dep.id, "dep_type": dep.dep_type, "dep_ref": dep.dep_ref, "declared": dep.declared}

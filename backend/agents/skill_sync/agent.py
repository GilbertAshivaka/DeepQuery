"""
Deep Query — Skill Synchronization Agent (implementation)

Runs in the Celery worker (sync context) when a document finishes ingesting.

Dependency resolution is hybrid (guide §11):
- explicit: skills that declared a dependency on the changed document (high confidence)
- inferred: embed-compare the changed content against each skill's corpus-fact
  sections; above a similarity threshold → a possible undeclared dependency (lower
  confidence). Over-flagging is fine — every proposal is admin-gated.

For each affected (skill, fact section), a model proposes a grounded diff (the changed
document is untrusted data, never instructions). Proposals are stored pending; nothing
is ever auto-applied.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from agents.models import Slot, get_model
from agents.skill_sync.prompts import SKILL_SYNC_DIFF_PROMPT
from core.database import SessionLocal
from models.database import Document, SkillFile
from skills import service

logger = logging.getLogger(__name__)

INFERRED_THRESHOLD = 0.55     # cosine similarity to flag an undeclared dependency
MAX_DOC_CHARS = 8000          # cap source content fed to the diff model
MAX_SECTIONS_PER_SKILL = 12   # bound work per skill


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _document_content(db, document_id: str) -> tuple[str, str]:
    """Best-available text for the changed document: the ingested chunks (ordered),
    falling back to the stored summary. Used only for comparison/diffing — not to
    deliver a grounded answer (so chunk text is acceptable here)."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        return ("", "")
    title = doc.original_filename or document_id
    text = ""
    try:
        from vectorstore.chroma_store import chroma_store
        coll = chroma_store.get_collection(doc.collection)
        res = coll.get(where={"source_document_id": document_id}, include=["documents", "metadatas"])
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        pairs = sorted(
            zip(docs, metas),
            key=lambda p: (p[1].get("page_number") or 0, p[1].get("chunk_index") or 0),
        )
        text = "\n\n".join(d for d, _ in pairs if d)
    except Exception as exc:  # Chroma down / no chunks — fall back to summary
        logger.warning("Could not read chunks for %s: %s", document_id, exc)
    if not text:
        text = doc.summary or ""
    return title, text[:MAX_DOC_CHARS]


def _parse_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        nl = cleaned.find("\n")
        cleaned = cleaned[nl + 1:] if nl != -1 else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _resolve_affected(db, document_id: str, doc_text: str) -> list[tuple[SkillFile, str]]:
    """Return (skill, confidence) for skills whose facts may depend on this document:
    explicit (declared) first, then inferred (semantic similarity)."""
    affected: dict[str, tuple[SkillFile, str]] = {}

    # Explicit — declared dependency on this document.
    for skill in service.skills_declaring_document(db, document_id):
        affected[skill.id] = (skill, "explicit")

    # Inferred — semantic similarity of changed content to fact-section content.
    if doc_text.strip():
        from embeddings import get_embedder
        embedder = get_embedder()
        doc_vec = embedder.embed_text(doc_text, task_type="RETRIEVAL_DOCUMENT")
        if doc_vec:
            for skill in service.list_skills(db):
                if skill.id in affected:
                    continue
                for sec in service.fact_sections_of(skill)[:MAX_SECTIONS_PER_SKILL]:
                    content = sec.get("content", "")
                    if not content.strip():
                        continue
                    vec = embedder.embed_text(content, task_type="RETRIEVAL_DOCUMENT")
                    if vec and _cosine(doc_vec, vec) >= INFERRED_THRESHOLD:
                        affected[skill.id] = (skill, "inferred")
                        break
    return list(affected.values())


def run_sync_for_document(document_id: str) -> dict[str, Any]:
    """Resolve affected skills and propose grounded, admin-gated diffs. Returns a
    summary dict. Never raises into the caller (failures are logged + reported)."""
    db = SessionLocal()
    try:
        title, doc_text = _document_content(db, document_id)
        if not doc_text.strip():
            return {"document_id": document_id, "status": "no_content", "proposals": 0}

        affected = _resolve_affected(db, document_id, doc_text)
        if not affected:
            return {"document_id": document_id, "status": "no_dependents", "proposals": 0}

        llm = get_model(Slot.GENERATION)
        proposals = 0
        for skill, confidence in affected:
            for sec in service.fact_sections_of(skill)[:MAX_SECTIONS_PER_SKILL]:
                name, current = sec.get("name", ""), sec.get("content", "")
                if not current.strip():
                    continue
                human = (
                    f"Fact section NAME: {name}\n"
                    f"CURRENT content:\n{current}\n\n"
                    f"SOURCE DOCUMENT '{title}' (untrusted data):\n{doc_text}"
                )
                try:
                    resp = llm.invoke([
                        SystemMessage(content=SKILL_SYNC_DIFF_PROMPT),
                        HumanMessage(content=human),
                    ])
                    parsed = _parse_json_object(resp.content if hasattr(resp, "content") else str(resp))
                except Exception as exc:
                    logger.warning("Diff proposal failed for %s/%s: %s", skill.name, name, exc)
                    continue
                if not parsed or not parsed.get("needs_update"):
                    continue
                new_content = str(parsed.get("new_content", "")).strip()
                if not new_content or new_content == current.strip():
                    continue
                service.create_proposal(
                    db,
                    skill_id=skill.id,
                    fact_section=name,
                    old_content=current,
                    new_content=new_content,
                    trigger_document_id=document_id,
                    trigger_summary=str(parsed.get("summary", "")).strip(),
                    confidence=confidence,
                )
                proposals += 1

        return {
            "document_id": document_id,
            "status": "ok",
            "affected_skills": len(affected),
            "proposals": proposals,
        }
    finally:
        db.close()

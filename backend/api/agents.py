"""
Deep Query — Agent Layer Endpoints

A dedicated surface for the agent flow, separate from chat (`/api/query/*`). The
Agents page drives these endpoints; the chat interface never does.

POST /api/agents/run                          — run the Orchestrator (SSE events)
POST /api/agents/threads/{thread_id}/resume   — resume a paused durable run (SSE)
GET  /api/agents/health                       — model slots + capabilities

SSE event types:
  plan · step_status · reasoning · thinking · tool_activity · citations ·
  answer_token · verification_result · approval_required · action_result ·
  done · error

Durable runs (RESUMABLE_AGENT_SPEC_V2 phase 1): an action run pauses at the
approval gate (checkpointed in Redis under its per-run thread_id, carried in
approval_required/done events) and the SAME run resumes via /threads/{id}/resume.
The /actions/{pending_id}/approve|reject endpoints remain for the legacy
non-durable fallback (Redis down) and the pre-resume UI.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from core.config import settings
from core.constants import ROLE_COLLECTIONS, UserRole
from core.database import get_db
from models.database import AgentAttachment, AgentConversation, AgentTurn, User

router = APIRouter()

HISTORY_TURNS = 10  # how many prior turns to carry as memory


class AgentRunRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None
    attachment_ids: Optional[list[str]] = None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/run")
async def run_agent(
    body: AgentRunRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run the Orchestrator and stream its events as SSE, with cross-turn memory.

    Prior turns of the conversation are loaded as history (so follow-ups have
    context). The user turn is persisted up front; the assistant turn is persisted
    when the run completes. If the client disconnects mid-run (stop), the run is
    cancelled and the assistant turn is not saved — the user turn remains, so a
    follow-up ("steer") sees what was asked.
    """
    allowed_collections = [
        c.value for c in ROLE_COLLECTIONS.get(UserRole(user.role), [])
    ]
    user_id = user.id
    query = body.query

    # Get or create the conversation (memory thread).
    conv = None
    if body.conversation_id:
        conv = (
            db.query(AgentConversation)
            .filter(AgentConversation.id == body.conversation_id,
                    AgentConversation.user_id == user_id)
            .first()
        )
    if conv is None:
        conv = AgentConversation(user_id=user_id, title=query[:120])
        db.add(conv)
        db.commit()
        db.refresh(conv)
    conversation_id = conv.id

    # Load prior turns (chronological) as chat history, then record the user turn.
    prior = (
        db.query(AgentTurn)
        .filter(AgentTurn.conversation_id == conversation_id)
        .order_by(AgentTurn.created_at.desc())
        .limit(HISTORY_TURNS)
        .all()
    )
    chat_history = [{"role": t.role, "content": t.content} for t in reversed(prior)]
    user_turn = AgentTurn(conversation_id=conversation_id, role="user", content=query)
    db.add(user_turn)
    db.commit()
    db.refresh(user_turn)

    # Load + link any attachments to this turn (so a reloaded conversation keeps them).
    attachments: list[dict] = []
    if body.attachment_ids:
        rows = (
            db.query(AgentAttachment)
            .filter(AgentAttachment.id.in_(body.attachment_ids),
                    AgentAttachment.user_id == user_id)
            .all()
        )
        for a in rows:
            a.conversation_id = conversation_id
            a.turn_id = user_turn.id
            attachments.append({"filename": a.filename, "text": a.extracted_text or "", "kind": a.kind})
        db.commit()

    async def event_stream() -> AsyncGenerator[str, None]:
        from agents.orchestrator import orchestrator

        answer_parts: list[str] = []
        final: dict = {}
        pending_approval: dict = {}
        citations_payload = None
        # CoT scaffolding to persist so the plan checklist + thinking timeline
        # survive a reload (mirrors how the frontend store assembles them live).
        plan_state: list[dict] = []
        trace_acc: list[dict] = []
        try:
            async for event in orchestrator.run(
                query=query,
                allowed_collections=allowed_collections,
                chat_history=chat_history,
                user_id=user_id,
                conversation_id=conversation_id,
                attachments=attachments,
            ):
                t = event.get("type")
                if t == "answer_token":
                    answer_parts.append(event.get("content", ""))
                elif t == "citations":
                    citations_payload = event.get("citations") or event.get("content")
                elif t == "plan":
                    plan_state = event.get("steps") or []
                elif t == "step_status":
                    for s in plan_state:
                        if s.get("id") == event.get("id"):
                            s["status"] = event.get("status")
                elif t == "thinking":
                    # Coalesce consecutive CoT deltas into one block.
                    if trace_acc and trace_acc[-1].get("kind") == "thinking":
                        trace_acc[-1]["content"] += event.get("content", "")
                    else:
                        trace_acc.append({"kind": "thinking", "content": event.get("content", "")})
                elif t == "reasoning":
                    trace_acc.append({"kind": "reasoning", "text": event.get("text")})
                elif t == "tool_activity":
                    trace_acc.append({"kind": "tool", "tool": event.get("tool"),
                                      "detail": event.get("detail"), "status": event.get("status")})
                elif t == "approval_required":
                    # Action runs end here (no `done`). Capture the gate payload so
                    # the pending approval survives a page reload (rehydrated from
                    # the turn's proposed_action).
                    pending_approval = event
                elif t == "done":
                    final = event
                yield _sse(event)
        except Exception as exc:  # last-resort guard; run() already emits 'error'
            yield _sse({"type": "error", "message": str(exc)})
            return

        # Persist the assistant turn (fresh session — request session is closed).
        from core.database import SessionLocal
        sdb = SessionLocal()
        try:
            verification = final.get("verification") or {}
            citations = final.get("citations") or citations_payload
            # An action run ends at approval_required with no `done`; persist that
            # gate payload as proposed_action so a reload can rehydrate the gate.
            proposed = final.get("proposed_action")
            if not proposed and pending_approval:
                proposed = {k: v for k, v in pending_approval.items() if k != "type"}
            cot = {"plan": plan_state, "trace": trace_acc}
            turn = AgentTurn(
                conversation_id=conversation_id,
                role="assistant",
                content=final.get("answer") or "".join(answer_parts),
                intent=final.get("intent") or ("action" if pending_approval else None),
                citations=json.dumps(citations) if citations else None,
                grounded=final.get("grounded"),
                verification_status=verification.get("outcome"),
                proposed_action=json.dumps(proposed) if proposed else None,
                agent_trace=json.dumps(cot) if (plan_state or trace_acc) else None,
            )
            sdb.add(turn)
            c = sdb.query(AgentConversation).filter(AgentConversation.id == conversation_id).first()
            if c is not None:
                c.updated_at = datetime.now(timezone.utc)
            sdb.commit()
        except Exception:
            sdb.rollback()
        finally:
            sdb.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Attachments (user-provided docs/images) ─────────────────
@router.post("/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    conversation_id: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a document/image to attach to an agent query. Documents are parsed to
    text now; images are stored for the future multimodal path. Returns an id to pass
    as `attachment_ids` on /run."""
    from agents.documents import attachment_kind, extract_text_from_file

    ext = os.path.splitext(file.filename or "")[1].lower()
    kind = attachment_kind(ext)
    store = settings.document_store_dir / "agent_attachments"
    store.mkdir(parents=True, exist_ok=True)
    stored = store / f"{uuid.uuid4().hex}{ext}"
    stored.write_bytes(await file.read())

    text = extract_text_from_file(stored, ext) if kind == "document" else ""
    att = AgentAttachment(
        user_id=user.id, conversation_id=conversation_id, kind=kind,
        filename=file.filename or stored.name, content_type=file.content_type,
        file_extension=ext, stored_path=str(stored), extracted_text=text or None,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return {"id": att.id, "filename": att.filename, "kind": kind, "chars": len(text)}


def _owned_attachment(db: Session, attachment_id: str, user_id: str) -> AgentAttachment:
    a = (
        db.query(AgentAttachment)
        .filter(AgentAttachment.id == attachment_id, AgentAttachment.user_id == user_id)
        .first()
    )
    if a is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    return a


@router.get("/attachments/{attachment_id}")
def get_attachment(attachment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Attachment metadata + its parsed text (for a document viewer/sidebar)."""
    a = _owned_attachment(db, attachment_id, user.id)
    return {
        "id": a.id, "filename": a.filename, "kind": a.kind,
        "content_type": a.content_type, "file_extension": a.file_extension,
        "has_text": bool(a.extracted_text), "chars": len(a.extracted_text or ""),
        "extracted_text": a.extracted_text, "created_at": a.created_at,
    }


@router.get("/attachments/{attachment_id}/content")
def get_attachment_content(attachment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The raw attachment file, served inline so images/PDFs render in-browser (image
    preview on the chat page, document viewer in a modal/sidebar)."""
    a = _owned_attachment(db, attachment_id, user.id)
    if not os.path.exists(a.stored_path):
        raise HTTPException(status_code=404, detail="attachment file is no longer available")
    return FileResponse(
        path=a.stored_path,
        media_type=a.content_type or "application/octet-stream",
        filename=a.filename,
        content_disposition_type="inline",
    )


# ── Conversation history (memory) ────────────────────────────
@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The user's agent conversations, most-recent first."""
    convs = (
        db.query(AgentConversation)
        .filter(AgentConversation.user_id == user.id)
        .order_by(AgentConversation.updated_at.desc())
        .limit(50)
        .all()
    )
    out = []
    for c in convs:
        n = db.query(AgentTurn).filter(AgentTurn.conversation_id == c.id).count()
        out.append({"id": c.id, "title": c.title, "turns": n,
                    "created_at": c.created_at, "updated_at": c.updated_at})
    return out


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Full turn history of one agent conversation."""
    conv = (
        db.query(AgentConversation)
        .filter(AgentConversation.id == conversation_id, AgentConversation.user_id == user.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    turns = (
        db.query(AgentTurn)
        .filter(AgentTurn.conversation_id == conversation_id)
        .order_by(AgentTurn.created_at)
        .all()
    )
    # Group attachments by the turn they were added to (so a reloaded conversation
    # still shows the docs/images the user attached).
    atts = db.query(AgentAttachment).filter(AgentAttachment.conversation_id == conversation_id).all()
    by_turn: dict[str, list] = {}
    for a in atts:
        by_turn.setdefault(a.turn_id, []).append(
            {"id": a.id, "filename": a.filename, "kind": a.kind}
        )
    return {
        "id": conv.id, "title": conv.title,
        "turns": [
            {"role": t.role, "content": t.content, "intent": t.intent,
             "citations": json.loads(t.citations) if t.citations else None,
             "grounded": t.grounded, "verification_status": t.verification_status,
             "proposed_action": json.loads(t.proposed_action) if t.proposed_action else None,
             "cot": json.loads(t.agent_trace) if t.agent_trace else None,
             "attachments": by_turn.get(t.id, []),
             "created_at": t.created_at}
            for t in turns
        ],
    }


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = (
        db.query(AgentConversation)
        .filter(AgentConversation.id == conversation_id, AgentConversation.user_id == user.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    db.query(AgentAttachment).filter(AgentAttachment.conversation_id == conversation_id).delete()
    db.query(AgentTurn).filter(AgentTurn.conversation_id == conversation_id).delete()
    db.delete(conv)
    db.commit()
    return {"detail": "deleted"}


def _persist_action_resolution(pending_id: str, *, plan_status: str, resolved_status: str,
                               error: Optional[str] = None,
                               thread_id: Optional[str] = None) -> None:
    """Record an action's outcome on the turn that proposed it, so a reload shows the
    resolved state: advance the plan's awaiting-approval step (→ done/rejected/failed)
    and stamp the gate's resolved_status (so it rehydrates as a record, not pending).
    ``thread_id`` is the durable-run fallback: if the pending record was refreshed
    during a long pause (expiry re-gate), the stored pending_id differs — the run's
    thread_id still identifies the turn."""
    from core.database import SessionLocal

    sdb = SessionLocal()
    try:
        candidates = (
            sdb.query(AgentTurn)
            .filter(AgentTurn.proposed_action.like(f"%{pending_id}%"))
            .all()
        )
        if not candidates and thread_id:
            candidates = (
                sdb.query(AgentTurn)
                .filter(AgentTurn.proposed_action.like(f"%{thread_id}%"))
                .all()
            )
        for turn in candidates:
            try:
                pa = json.loads(turn.proposed_action) if turn.proposed_action else None
            except Exception:
                pa = None
            if not isinstance(pa, dict):
                continue
            if pa.get("pending_id") != pending_id and not (
                thread_id and pa.get("thread_id") == thread_id
            ):
                continue
            pa["resolved_status"] = resolved_status
            if error:
                pa["resolved_error"] = error
            turn.proposed_action = json.dumps(pa)

            if turn.agent_trace:
                try:
                    cot = json.loads(turn.agent_trace)
                except Exception:
                    cot = None
                if isinstance(cot, dict) and isinstance(cot.get("plan"), list):
                    for step in cot["plan"]:
                        if step.get("status") == "awaiting-approval":
                            step["status"] = plan_status
                    turn.agent_trace = json.dumps(cot)
            sdb.commit()
            break
    except Exception:
        sdb.rollback()
    finally:
        sdb.close()


async def _post_action_continuation(pending_id: str, result_payload: dict) -> Optional[str]:
    """After an action executes, generate + persist a short 'here's what I did' assistant
    turn so the agent reports back instead of going silent. Interim continuation — the
    resumable redesign (RESUMABLE_AGENT_SPEC.md) folds this into a single resumed run.
    Returns the message text (also persisted as an assistant turn)."""
    from agents.action_agent import action_agent
    from core.database import SessionLocal

    sdb = SessionLocal()
    try:
        pa = None
        conv_id = None
        for turn in sdb.query(AgentTurn).filter(AgentTurn.proposed_action.like(f"%{pending_id}%")).all():
            try:
                cand = json.loads(turn.proposed_action) if turn.proposed_action else None
            except Exception:
                cand = None
            if isinstance(cand, dict) and cand.get("pending_id") == pending_id:
                pa = cand
                conv_id = turn.conversation_id
                break
        if pa is None:
            return None
        message = await action_agent.summarize_result(action=pa, result=result_payload.get("result"))
        if message and conv_id:
            sdb.add(AgentTurn(conversation_id=conv_id, role="assistant", content=message, intent="action"))
            sdb.commit()
        return message or None
    except Exception:
        sdb.rollback()
        return None
    finally:
        sdb.close()


class ResumeRequest(BaseModel):
    decision: str  # "approve" | "reject"


@router.post("/threads/{thread_id}/resume")
async def resume_thread(
    thread_id: str,
    body: ResumeRequest,
    user: User = Depends(get_current_user),
):
    """Resume a durable run paused at the approval gate, streaming the continuation
    as SSE on the same event contract as /run: the decision flows into the
    checkpointed run (approve → token + execute → grounded report; reject →
    acknowledged), and the report is persisted as an assistant turn. Supersedes
    /actions/{pending_id}/approve|reject for durable runs (those remain for the
    legacy non-durable gate)."""
    from agents.orchestrator import orchestrator

    async def event_stream() -> AsyncGenerator[str, None]:
        final: dict = {}
        action_res: dict = {}
        regate: dict = {}
        try:
            async for event in orchestrator.resume(
                thread_id=thread_id, decision=body.decision, approver_id=user.id
            ):
                t = event.get("type")
                if t == "action_result":
                    action_res = event
                elif t == "approval_required":
                    regate = event
                elif t == "done":
                    final = event
                yield _sse(event)
        except Exception as exc:  # last-resort guard; resume() already emits 'error'
            yield _sse({"type": "error", "message": str(exc)})
            return

        # Persist: stamp the proposing turn with the resolution, and record the
        # post-action report as a fresh assistant turn (the agent reported back).
        if action_res:
            status_ = action_res.get("status") or "executed"
            _persist_action_resolution(
                action_res.get("pending_id") or "",
                plan_status={"executed": "done", "rejected": "rejected"}.get(status_, "failed"),
                resolved_status=status_,
                error=action_res.get("error"),
                thread_id=thread_id,
            )
            message = action_res.get("message") or final.get("answer")
            conv_id = final.get("conversation_id")
            if message and conv_id:
                from core.database import SessionLocal
                sdb = SessionLocal()
                try:
                    sdb.add(AgentTurn(conversation_id=conv_id, role="assistant",
                                      content=message, intent="action"))
                    c = sdb.query(AgentConversation).filter(AgentConversation.id == conv_id).first()
                    if c is not None:
                        c.updated_at = datetime.now(timezone.utc)
                    sdb.commit()
                except Exception:
                    sdb.rollback()
                finally:
                    sdb.close()
        elif regate:
            # Expired pending record was refreshed: update the stored gate payload so
            # a reload re-presents the NEW pending_id/preview, still awaiting approval.
            _update_turn_gate(thread_id, pending_id=regate.get("pending_id"),
                              preview=regate.get("preview"), regated=True)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _update_turn_gate(thread_id: str, **fields) -> None:
    """Merge fields into the stored proposed_action of the turn that carries this
    durable run's gate (matched by thread_id)."""
    from core.database import SessionLocal

    sdb = SessionLocal()
    try:
        for turn in (
            sdb.query(AgentTurn)
            .filter(AgentTurn.proposed_action.like(f"%{thread_id}%"))
            .all()
        ):
            try:
                pa = json.loads(turn.proposed_action) if turn.proposed_action else None
            except Exception:
                pa = None
            if not (isinstance(pa, dict) and pa.get("thread_id") == thread_id):
                continue
            pa.update({k: v for k, v in fields.items() if v is not None})
            turn.proposed_action = json.dumps(pa)
            sdb.commit()
            break
    except Exception:
        sdb.rollback()
    finally:
        sdb.close()


@router.post("/actions/{pending_id}/approve")
async def approve_action(
    pending_id: str,
    user: User = Depends(get_current_user),
):
    """Approve a previously-proposed action: mint the single-use token and execute it
    exactly once. The gateway refuses execution without a valid token (enforcement).
    Returns an ``action_result`` payload."""
    from agents.action_agent import action_agent

    result = await action_agent.approve(pending_id=pending_id, approver_id=user.id)
    status_ = result.get("status")
    _persist_action_resolution(
        pending_id,
        plan_status="failed" if status_ == "failed" else "done",
        resolved_status=status_ or "executed",
        error=result.get("error"),
    )
    # Post-action continuation: report what was done instead of going silent.
    message = None
    if (status_ or "executed") == "executed":
        message = await _post_action_continuation(pending_id, result)
    return {"type": "action_result", "pending_id": pending_id, "message": message, **result}


@router.post("/actions/{pending_id}/reject")
async def reject_action(
    pending_id: str,
    user: User = Depends(get_current_user),
):
    """Reject a proposed action — it is never executed."""
    from agents.action_agent import action_agent

    result = await action_agent.reject(pending_id=pending_id, approver_id=user.id)
    _persist_action_resolution(
        pending_id,
        plan_status="rejected",
        resolved_status=result.get("status") or "rejected",
    )
    return {"type": "action_result", "pending_id": pending_id, **result}


@router.get("/health")
def agent_health(user: User = Depends(get_current_user)):
    """Report the configured model slots and registered capabilities."""
    from agents.models import describe_slots
    from agents.registry import available

    return {
        "model_slots": describe_slots(),
        "capabilities": [c.value for c in available()],
        "deployment_mode": settings.deployment_mode,
    }

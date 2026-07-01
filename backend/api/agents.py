"""
Deep Query — Agent Layer Endpoints

A dedicated surface for the agent flow, separate from chat (`/api/query/*`). The
Agents page drives these endpoints; the chat interface never does.

POST /api/agents/run                          — run the Orchestrator (SSE events)
POST /api/agents/threads/{thread_id}/resume   — resume a paused durable run (SSE)
GET  /api/agents/threads/{thread_id}/state    — run snapshot (one-GET UI paint)
GET  /api/agents/threads/{thread_id}/events   — SSE subscriber (Last-Event-ID replay)
GET  /api/agents/health                       — model slots + capabilities

SSE event types:
  run_started · plan · step_status · reasoning · thinking · tool_activity ·
  citations · answer_token · verification_result · approval_required ·
  action_result · deliverable · done · error

Durable runs (RESUMABLE_AGENT_SPEC_V2 phase 1): an action run pauses at the
approval gate (checkpointed in Redis under its per-run thread_id, carried in
run_started/approval_required/done events) and the SAME run resumes via
/threads/{id}/resume. The /actions/{pending_id}/approve|reject endpoints remain
for the legacy non-durable fallback (Redis down) and the pre-resume UI.

Event bus (phase R2 §2.5): every run publishes its events to a per-run Redis
Stream and maintains a snapshot, so /threads/{id}/events (replay + live tail via
Last-Event-ID) and /threads/{id}/state (one-GET paint) give disconnect/multi-tab
resilience. Execution is owned by the in-process executor (R3); the SSE on /run is
purely a bus subscriber, so the bus is REQUIRED to start a run — /run fails fast
with 503 when Redis is unreachable (a run started then would execute invisibly).
Producer-side bus writes stay best-effort: a transient blip mid-run degrades
streaming, not execution.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
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
    # Explicitly-selected playbooks to load up front (controller, R8). The controller may
    # also discover + load others itself via the skill index.
    skill_names: Optional[list[str]] = None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/run")
async def run_agent(
    body: AgentRunRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start an agent run and stream its events as SSE, with cross-turn memory.

    Prior turns of the conversation are loaded as history (so follow-ups have context),
    and the user turn is persisted up front. Execution is owned by the in-process
    **executor** (R3), not this request: the SSE below is a *subscriber* to the run's
    event bus. So if the client disconnects mid-run, the run keeps going, the assistant
    turn is still persisted, and the client can reattach via /threads/{id}/events.
    """
    # Fail fast when the bus is down: the response below is only a bus subscriber, so a
    # run started without Redis would execute invisibly (no stream, no reconnect, no
    # resume). 503 is honest; nothing has been persisted yet.
    from agents.orchestrator import event_bus

    if not await event_bus.ping():
        raise HTTPException(
            status_code=503,
            detail="agent runs are unavailable right now: the run event store (Redis) is unreachable",
        )

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

    # Per-run identity, generated up front so the event bus key is known before the
    # first event and the client can reconnect via /threads/{id}/events.
    thread_id = f"run-{uuid.uuid4().hex}"

    # Hand execution to the in-process executor (it owns the orchestrator drive, bus
    # publishing, and assistant-turn persistence) and return a bus subscriber. The run
    # now outlives this request.
    from agents.orchestrator import executor

    executor.start_run(
        thread_id=thread_id, query=query, allowed_collections=allowed_collections,
        chat_history=chat_history, user_id=user_id, conversation_id=conversation_id,
        attachments=attachments, skill_names=body.skill_names,
    )
    return StreamingResponse(
        _bus_subscriber(thread_id, request, last_id=None),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _bus_subscriber(
    thread_id: str, request: Request, last_id: Optional[str]
) -> AsyncGenerator[str, None]:
    """Stream a run's bus events as SSE: replay from ``last_id`` then tail live, with
    ``id:`` frames (browser Last-Event-ID), heartbeats, and disconnect detection. Shared
    by /run, /resume, and /events — the run keeps executing if the client drops."""
    from agents.orchestrator import event_bus, executor

    try:
        async for seq, event in event_bus.subscribe(
            thread_id, last_id, is_live=lambda: executor.is_running(thread_id)
        ):
            if await request.is_disconnected():
                break
            if event is None:
                yield ": ping\n\n"
                continue
            yield f"id: {seq}\ndata: {json.dumps(event)}\n\n"
    except Exception as exc:
        yield _sse({"type": "error", "message": str(exc)})


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


# ── Produced documents (DOCUMENT_GENERATION_SANDBOX_GUIDE §7) ─
@router.get("/artifacts/{thread_id}/{step_id}/{filename}")
async def download_artifact(
    thread_id: str, step_id: str, filename: str,
    user: User = Depends(get_current_user),
):
    """Serve a document produced by a `produce` step, from the artifact store. Authorized
    by run ownership: the requester must own the run (per the run's event-bus snapshot).
    The deliverable event carries this URL; once the run is persisted, the durable copy is
    also reachable as an AgentAttachment via /attachments/{id}/content."""
    from agents.document_agent.agent import mime_for
    from agents.orchestrator import artifacts, event_bus

    snap = await event_bus.get_snapshot(thread_id)
    if not snap or snap.get("user_id") != user.id:
        # No snapshot (expired/unknown) or not the owner — don't reveal which.
        raise HTTPException(status_code=404, detail="artifact not found")
    path = artifacts.output_file(thread_id, step_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(
        path=str(path), media_type=mime_for(filename), filename=filename,
        content_disposition_type="attachment",
    )


# ── Per-user agent preferences (retrieval knobs) ─────────────
class AgentPrefsUpdate(BaseModel):
    max_parallel_reads: Optional[int] = None
    whole_doc_min_chunks: Optional[int] = None
    whole_doc_max_docs: Optional[int] = None
    whole_doc_max_pages: Optional[int] = None


def _prefs_payload(db: Session, user_id: str) -> dict:
    from agents import user_prefs
    return {
        "prefs": user_prefs.get(db, user_id),
        "bounds": user_prefs.BOUNDS,
        "defaults": user_prefs.defaults(),
        "page_chars": settings.agent_whole_doc_page_chars,
    }


@router.get("/preferences")
def get_agent_preferences(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The user's effective agent retrieval knobs, with the allowed [min,max] bounds and
    deployment defaults (so the Settings UI can render sliders with the right ranges)."""
    return _prefs_payload(db, user.id)


@router.put("/preferences")
def update_agent_preferences(
    body: AgentPrefsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update some/all knobs (values are clamped to bounds server-side) and return the
    effective prefs + bounds."""
    from agents import user_prefs
    user_prefs.update(db, user.id, body.model_dump(exclude_none=True))
    return _prefs_payload(db, user.id)


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
    decision: Optional[str] = None  # single gate: "approve" | "reject"
    # batch gate (R6): {pending_id: "approve"|"reject"} per action in the plan.
    batch_decisions: Optional[dict] = None
    answer: Optional[str] = None    # question gate (R7): the user's reply


class InterjectRequest(BaseModel):
    message: str
    mode: Optional[str] = "augment"  # augment | cancel_step | cancel_run


@router.post("/threads/{thread_id}/resume")
async def resume_thread(
    thread_id: str,
    body: ResumeRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Resume a durable run paused at the approval gate. Execution is handed to the
    in-process executor (approve → token + execute → grounded report; reject →
    acknowledged; resolution + report persisted), and the response subscribes to the
    run's bus from the pause point, so only the *continuation* streams — surviving a
    client drop like /run. Supersedes /actions/{pending_id}/approve|reject for durable
    runs (those remain for the legacy non-durable gate)."""
    from agents.orchestrator import executor

    # Subscribe from the current snapshot tip so the response streams only the new
    # continuation events (not a full replay of the already-seen run).
    snap = await _authorize_thread(thread_id, user)
    cursor = snap.get("last_event_id")

    executor.start_resume(thread_id=thread_id, decision=body.decision, approver_id=user.id,
                          batch_decisions=body.batch_decisions, answer=body.answer)
    return StreamingResponse(
        _bus_subscriber(thread_id, request, last_id=cursor),
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


def _update_turn_batch(thread_id: str, results: list[dict]) -> None:
    """Stamp a batch gate's resolution onto the turn that carries it (matched by the
    thread_id folded into cot). Batch gates live in ``agent_trace`` (cot.batch), not the
    ``proposed_action`` column, so ``_persist_action_resolution`` never matches them —
    without this stamp a reloaded conversation re-shows the batch as still pending
    (an already-resolved approval card asking again)."""
    from core.database import SessionLocal

    sdb = SessionLocal()
    try:
        for turn in (
            sdb.query(AgentTurn)
            .filter(AgentTurn.agent_trace.like(f"%{thread_id}%"))
            .all()
        ):
            try:
                cot = json.loads(turn.agent_trace) if turn.agent_trace else None
            except Exception:
                cot = None
            if not (isinstance(cot, dict) and cot.get("thread_id") == thread_id
                    and isinstance(cot.get("batch"), dict)):
                continue
            by_id = {r.get("pending_id"): r for r in results if r.get("pending_id")}
            cot["batch"]["resolved"] = True
            for a in cot["batch"].get("batch") or []:
                r = by_id.get(a.get("pending_id"))
                if r is not None:
                    a["resolved_status"] = r.get("status")
                    if r.get("error"):
                        a["resolved_error"] = r.get("error")
            # Advance the awaiting-approval plan step to a terminal status too (the
            # single-gate path gets this via _persist_action_resolution).
            statuses = [r.get("status") for r in results]
            plan_status = ("done" if any(s == "executed" for s in statuses)
                           else "rejected" if statuses and all(s == "rejected" for s in statuses)
                           else "failed")
            if isinstance(cot.get("plan"), list):
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


def _update_turn_question(thread_id: str, answer: str) -> None:
    """Record the user's answer onto the turn that carries this run's question (matched by
    the thread_id folded into cot), so a reloaded conversation shows the resolved Q&A
    instead of an open question."""
    from core.database import SessionLocal

    sdb = SessionLocal()
    try:
        for turn in (
            sdb.query(AgentTurn)
            .filter(AgentTurn.agent_trace.like(f"%{thread_id}%"))
            .all()
        ):
            try:
                cot = json.loads(turn.agent_trace) if turn.agent_trace else None
            except Exception:
                cot = None
            if not (isinstance(cot, dict) and cot.get("thread_id") == thread_id
                    and isinstance(cot.get("question"), dict)):
                continue
            cot["question"]["status"] = "answered"
            cot["question"]["answer"] = answer
            turn.agent_trace = json.dumps(cot)
            sdb.commit()
            break
    except Exception:
        sdb.rollback()
    finally:
        sdb.close()


async def _authorize_thread(thread_id: str, user: User) -> dict:
    """Load a run's snapshot and confirm the caller owns it. Raises 404 (unknown/
    expired) or 403 (another user's run)."""
    from agents.orchestrator import event_bus

    try:
        snap = await event_bus.get_snapshot(thread_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"run state store unavailable: {exc}")
    if snap is None:
        raise HTTPException(status_code=404, detail="no such run (it may have expired)")
    owner = snap.get("user_id")
    if owner and owner != user.id:
        raise HTTPException(status_code=403, detail="this run belongs to another user")
    return snap


@router.get("/threads/{thread_id}/state")
async def get_thread_state(thread_id: str, user: User = Depends(get_current_user)):
    """One-GET UI paint (RESUMABLE_AGENT_SPEC_V2 §2.5): the current snapshot — plan +
    step statuses + accumulated answer + citations + any pending approval + run status +
    ``last_event_id``. A client paints from this, then subscribes to /events from
    ``last_event_id`` for replay-then-live."""
    snap = await _authorize_thread(thread_id, user)
    # Lazy restart-supervisor correction: a `running` run with no live task here died in a
    # restart — report it `interrupted` rather than a stale `running`.
    if snap.get("run_status") == "running":
        from agents.orchestrator import executor
        if not executor.is_running(thread_id):
            snap = {**snap, "run_status": "interrupted"}
    return {k: v for k, v in snap.items() if k != "user_id"}


@router.get("/threads/{thread_id}/events")
async def get_thread_events(
    thread_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    """SSE subscriber (RESUMABLE_AGENT_SPEC_V2 §2.5/§2.12). Honors ``Last-Event-ID``
    (header, or ``?last_event_id=`` query param): replays missed events from the run's
    Redis Stream, then tails live until the run finishes or pauses. Disconnect-safe and
    multi-tab-safe — reconnect with the last id you saw to resume exactly."""
    await _authorize_thread(thread_id, user)
    last_id = request.headers.get("Last-Event-ID") or request.query_params.get("last_event_id")
    return StreamingResponse(
        _bus_subscriber(thread_id, request, last_id=last_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/threads/{thread_id}/interject")
async def interject_thread(thread_id: str, body: InterjectRequest,
                           user: User = Depends(get_current_user)):
    """Steer a run mid-flight (RESUMABLE_AGENT_SPEC_V2 §2.9). The note goes to the run's
    mailbox and is drained by the controller at its next loop boundary — `augment` ("also
    do X") folds into the plan, `cancel_step` ("skip that") drops the current direction,
    `cancel_run` wraps up gracefully. If the run is paused at a gate/question, the note is
    read when it resumes. Controller runs only."""
    from agents.orchestrator import event_bus

    await _authorize_thread(thread_id, user)  # 404/403 if not the owner's run
    mode = body.mode if body.mode in ("augment", "cancel_step", "cancel_run") else "augment"
    ok = await event_bus.interject(thread_id, body.message, mode)
    return {"thread_id": thread_id, "queued": ok, "mode": mode}


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

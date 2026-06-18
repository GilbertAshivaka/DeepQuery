"""
Deep Query — Agent run executor (RESUMABLE_AGENT_SPEC_V2 §2.5, phase R3)

Owns graph execution. ``POST /run`` and ``/resume`` no longer *are* the run — they
register an **in-process asyncio task** here and return; the task drives the orchestrator,
publishes every event to the event bus (§2.5/R2), and persists the assistant turn on
completion. Because execution is decoupled from the HTTP connection, a client can
disconnect, reload, or come back tomorrow and the run keeps going — SSE endpoints are pure
subscribers to the bus.

Decision §5: in-process (one service), not a separate worker — checkpoints already make
*paused* runs restart-survivable; a process restart mid-step loses only in-flight step work
(the run is then `interrupted`, surfaced on next client contact via ``is_running``). The
client contract is identical to R2 (same events, same bus) — only the producer moved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Live run tasks, keyed by thread_id. Lets subscribers tell "still running" from
# "died in a restart" (a snapshot stuck at run_status=running with no task here).
_tasks: dict[str, asyncio.Task] = {}


def is_running(thread_id: str) -> bool:
    """True if this process is actively executing the run (not finished, not lost to a
    restart). Subscribers use it to avoid tailing a dead run forever."""
    task = _tasks.get(thread_id)
    return task is not None and not task.done()


async def reconcile_orphaned_runs() -> int:
    """Startup supervisor (spec §6): a run whose snapshot still says `running` but has no
    live task in this process died in a restart (in-flight step work is lost by design;
    paused runs are safe in checkpoints). Mark such runs `interrupted` so clients don't
    wait on them. Best-effort — never blocks startup."""
    from agents.orchestrator import event_bus

    n = 0
    try:
        for thread_id in await event_bus.iter_run_threads():
            if is_running(thread_id):
                continue
            snap = await event_bus.get_snapshot(thread_id)
            if snap and snap.get("run_status") == "running":
                await event_bus.set_run_status(thread_id, "interrupted")
                n += 1
    except Exception as exc:
        logger.warning("reconcile_orphaned_runs failed: %s", exc)
    if n:
        logger.info("Marked %s orphaned agent run(s) interrupted after restart", n)
    return n


def _track(thread_id: str, task: asyncio.Task) -> None:
    _tasks[thread_id] = task

    def _done(t: asyncio.Task) -> None:
        _tasks.pop(thread_id, None)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("Agent run task %s crashed: %s", thread_id, exc, exc_info=exc)

    task.add_done_callback(_done)


# ── Run driver ───────────────────────────────────────────────

async def _drive_run(
    *,
    thread_id: str,
    query: str,
    allowed_collections: list[str],
    chat_history: list[dict],
    user_id: str,
    conversation_id: Optional[str],
    attachments: list[dict],
    skill_names: Optional[list[str]] = None,
) -> None:
    """Drive a fresh run to completion: seed the bus, publish run_started, stream the
    orchestrator's events to the bus, then persist the assistant turn. Runs independently
    of any client; the in-request SSE on /run is just a bus subscriber."""
    from agents.orchestrator import event_bus, orchestrator

    answer_parts: list[str] = []
    final: dict = {}
    pending_approval: dict = {}
    pending_question: dict = {}
    pending_batch: dict = {}
    skills_acc: list[dict] = []
    citations_payload = None
    plan_state: list[dict] = []
    trace_acc: list[dict] = []
    deliverables: list[dict] = []
    scripts_acc: list[dict] = []  # produce script.py code per step (pill → code panel)

    await event_bus.init_run(thread_id, user_id)
    await event_bus.publish(thread_id, {"type": "run_started", "thread_id": thread_id,
                                        "conversation_id": conversation_id})
    try:
        async for event in orchestrator.run(
            query=query,
            allowed_collections=allowed_collections,
            chat_history=chat_history,
            user_id=user_id,
            conversation_id=conversation_id,
            attachments=attachments,
            thread_id=thread_id,
            skill_names=skill_names,
        ):
            await event_bus.publish(thread_id, event)
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
                pending_approval = event
            elif t == "batch_approval_required":
                pending_batch = event
            elif t == "question":
                pending_question = event
            elif t == "skill_loaded":
                # Surfaced as a chip (cot.skills), not a trace line — matches the live UI.
                skills_acc.append({"name": event.get("name"), "version": event.get("version")})
            elif t == "deliverable":
                deliverables.append({k: v for k, v in event.items() if k != "type"})
            elif t == "produce_script_start":
                sid = event.get("step_id")
                s = next((x for x in scripts_acc if x.get("step_id") == sid), None)
                if s is not None:
                    s["code"] = ""  # repair attempt restarts the script
                else:
                    scripts_acc.append({"step_id": sid, "code": ""})
            elif t == "produce_script_delta":
                sid = event.get("step_id")
                s = next((x for x in scripts_acc if x.get("step_id") == sid), None)
                if s is not None:
                    s["code"] += event.get("content", "")
            elif t == "produce_script_end":
                sid = event.get("step_id")
                s = next((x for x in scripts_acc if x.get("step_id") == sid), None)
                if s is not None and event.get("code"):
                    s["code"] = event["code"]  # the cleaned, fence-stripped final script
            elif t == "done":
                final = event
    except Exception as exc:
        logger.exception("Agent run %s failed mid-stream", thread_id)
        await event_bus.publish(thread_id, {"type": "error", "message": str(exc)})
        return

    _persist_assistant_turn(
        conversation_id=conversation_id, final=final, answer_parts=answer_parts,
        pending_approval=pending_approval, citations_payload=citations_payload,
        plan_state=plan_state, trace_acc=trace_acc,
        thread_id=thread_id, user_id=user_id, deliverables=deliverables,
        pending_question=pending_question, pending_batch=pending_batch, skills=skills_acc,
        scripts=scripts_acc,
    )


def _persist_assistant_turn(*, conversation_id, final, answer_parts, pending_approval,
                            citations_payload, plan_state, trace_acc,
                            thread_id="", user_id="", deliverables=None,
                            pending_question=None, pending_batch=None, skills=None,
                            scripts=None) -> None:
    """Persist the completed/paused run as an assistant turn (own DB session — the request
    is long gone). Produced documents (DOCUMENT_GENERATION_SANDBOX_GUIDE §7) are attached to
    the turn as AgentAttachment rows so a reloaded conversation keeps them, served by the
    existing /attachments/{id}/content endpoint."""
    from core.database import SessionLocal
    from models.database import AgentAttachment, AgentConversation, AgentTurn

    sdb = SessionLocal()
    try:
        verification = final.get("verification") or {}
        citations = final.get("citations") or citations_payload
        proposed = final.get("proposed_action")
        if not proposed and pending_approval:
            proposed = {k: v for k, v in pending_approval.items() if k != "type"}
        # Fold the controller surfaces into cot so a reloaded conversation keeps them
        # (the question the agent asked, a pending batch plan, loaded playbooks). These
        # rehydrate as read-only records; a still-live run overlays the actionable form.
        cot: dict = {"plan": plan_state, "trace": trace_acc, "thread_id": thread_id}
        if skills:
            cot["skills"] = skills
        if pending_question:
            cot["question"] = {k: v for k, v in pending_question.items() if k != "type"}
        if pending_batch:
            cot["batch"] = {k: v for k, v in pending_batch.items() if k != "type"}
        if scripts:
            cot["scripts"] = scripts  # [{step_id, code}] — rehydrates the script.py pill
        has_cot = bool(plan_state or trace_acc or skills or pending_question
                       or pending_batch or scripts)
        turn = AgentTurn(
            conversation_id=conversation_id,
            role="assistant",
            content=final.get("answer") or "".join(answer_parts),
            intent=final.get("intent") or ("action" if pending_approval else None),
            citations=json.dumps(citations) if citations else None,
            grounded=final.get("grounded"),
            verification_status=verification.get("outcome"),
            proposed_action=json.dumps(proposed) if proposed else None,
            agent_trace=json.dumps(cot) if has_cot else None,
        )
        sdb.add(turn)
        sdb.flush()  # assign turn.id for attachment links
        for d in (deliverables or []):
            src = _deliverable_path(thread_id, d.get("artifact_id"))
            if not src:
                continue
            # Copy into the durable attachments store (never swept) so the deliverable
            # survives the run's transient job dir being TTL-swept. Fall back to the
            # job-dir path if the copy fails (still works until the sweeper runs).
            durable = _copy_to_attachments_store(src) or src
            sdb.add(AgentAttachment(
                user_id=user_id, conversation_id=conversation_id, turn_id=turn.id,
                kind="document", filename=d.get("filename") or "document",
                content_type=d.get("mime"),
                file_extension=os.path.splitext(d.get("filename") or "")[1].lower() or None,
                stored_path=durable,
            ))
        c = sdb.query(AgentConversation).filter(AgentConversation.id == conversation_id).first()
        if c is not None:
            c.updated_at = datetime.now(timezone.utc)
        sdb.commit()
    except Exception:
        sdb.rollback()
    finally:
        sdb.close()


def _copy_to_attachments_store(src_path: str) -> Optional[str]:
    """Copy a produced file into the durable agent-attachments store (where user uploads
    live; the sweeper never touches it), so the deliverable persists after the run's
    transient artifact job dir is TTL-swept. Returns the durable path, or None on failure."""
    import shutil
    import uuid as _uuid

    from core.config import settings
    try:
        ext = os.path.splitext(src_path)[1].lower()
        store = settings.document_store_dir / "agent_attachments"
        store.mkdir(parents=True, exist_ok=True)
        dest = store / f"{_uuid.uuid4().hex}{ext}"
        shutil.copy2(src_path, dest)
        return str(dest)
    except Exception as exc:
        logger.warning("deliverable durable-copy failed (%s): %s", src_path, exc)
        return None


def _deliverable_path(thread_id: str, artifact_id: Optional[str]) -> Optional[str]:
    """Resolve a deliverable's on-disk path from its ``thread/step/filename`` ref, for the
    durable AgentAttachment record."""
    if not artifact_id:
        return None
    parts = artifact_id.split("/", 2)
    if len(parts) != 3:
        return None
    from agents.orchestrator import artifacts
    p = artifacts.output_file(parts[0], parts[1], parts[2])
    return str(p) if p else None


# ── Resume driver ────────────────────────────────────────────

async def _drive_resume(*, thread_id: str, decision: Optional[str], approver_id: str,
                        batch_decisions: Optional[dict] = None, answer: Optional[str] = None) -> None:
    """Drive a resume continuation to the bus, then persist the action resolution + the
    grounded report turn (or update the gate on a re-gate). Handles both the single gate
    and the R6 batch gate (``batch_decisions``). Persistence helpers live in the API layer
    (shared with the legacy approve/reject endpoints); imported lazily."""
    from agents.orchestrator import event_bus, orchestrator
    from api.agents import _persist_action_resolution, _update_turn_gate, _update_turn_question

    # Record the user's answer on the originating question turn (so the resolved Q&A
    # rehydrates), regardless of how the continuation ends.
    if answer:
        _update_turn_question(thread_id, answer)

    final: dict = {}
    action_res: dict = {}
    regate: dict = {}
    try:
        async for event in orchestrator.resume(
            thread_id=thread_id, decision=decision, approver_id=approver_id,
            batch_decisions=batch_decisions, answer=answer,
        ):
            await event_bus.publish(thread_id, event)
            t = event.get("type")
            if t == "action_result":
                action_res = event  # last one wins; the combined report is final.answer
            elif t in ("approval_required", "batch_approval_required"):
                regate = event
            elif t == "done":
                final = event
    except Exception as exc:
        logger.exception("Agent resume %s failed mid-stream", thread_id)
        await event_bus.publish(thread_id, {"type": "error", "message": str(exc)})
        return

    if action_res:
        status_ = action_res.get("status") or "executed"
        _persist_action_resolution(
            action_res.get("pending_id") or "",
            plan_status={"executed": "done", "rejected": "rejected"}.get(status_, "failed"),
            resolved_status=status_,
            error=action_res.get("error"),
            thread_id=thread_id,
        )
        # Prefer the run's final answer (the combined batch report, or the single report).
        message = final.get("answer") or action_res.get("message")
        conv_id = final.get("conversation_id")
        if message and conv_id:
            from core.database import SessionLocal
            from models.database import AgentConversation, AgentTurn
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
        _update_turn_gate(thread_id, pending_id=regate.get("pending_id"),
                          preview=regate.get("preview"), regated=True)
    elif final.get("answer") and final.get("conversation_id") and not final.get("paused"):
        # A question-answer continuation (no action) that ran to a normal answer — persist
        # it as the assistant turn so the conversation reflects the resumed result.
        from core.database import SessionLocal
        from models.database import AgentConversation, AgentTurn
        sdb = SessionLocal()
        try:
            sdb.add(AgentTurn(conversation_id=final["conversation_id"], role="assistant",
                              content=final["answer"], intent="controller",
                              grounded=final.get("grounded")))
            c = sdb.query(AgentConversation).filter(
                AgentConversation.id == final["conversation_id"]).first()
            if c is not None:
                c.updated_at = datetime.now(timezone.utc)
            sdb.commit()
        except Exception:
            sdb.rollback()
        finally:
            sdb.close()


# ── Public start API (returns immediately) ───────────────────

def start_run(*, thread_id: str, query: str, allowed_collections: list[str],
              chat_history: list[dict], user_id: str, conversation_id: Optional[str],
              attachments: list[dict], skill_names: Optional[list[str]] = None) -> None:
    task = asyncio.create_task(_drive_run(
        thread_id=thread_id, query=query, allowed_collections=allowed_collections,
        chat_history=chat_history, user_id=user_id, conversation_id=conversation_id,
        attachments=attachments, skill_names=skill_names,
    ))
    _track(thread_id, task)


def start_resume(*, thread_id: str, decision: Optional[str], approver_id: str,
                 batch_decisions: Optional[dict] = None, answer: Optional[str] = None) -> None:
    task = asyncio.create_task(_drive_resume(
        thread_id=thread_id, decision=decision, approver_id=approver_id, answer=answer,
        batch_decisions=batch_decisions,
    ))
    _track(thread_id, task)

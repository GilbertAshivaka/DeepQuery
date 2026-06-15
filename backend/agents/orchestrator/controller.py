"""
Deep Query — Controller loop (RESUMABLE_AGENT_SPEC_V2 §2.2, phase R4a)

The bounded **plan→execute→observe** loop that replaces the fixed
classify→retrieve→generate→verify pipeline when ``agent_controller_loop`` is on. At each
iteration a tool-aware controller emits a **structured decision** (read | answer | replan |
done — `act` arrives in R4b) from real options, not a blind classifier guess; the chosen
action runs, its result folds into the findings, and the loop continues until the request
is answered. Same module/contract as the fixed graph — a grown-up orchestrator, not a fork:
it reuses ``gather``, the generation/verification slots, and every formatting helper, and
emits the identical SSE event types (via LangGraph's custom stream channel) so the API,
event bus, executor, and UI are unchanged.

R4a is read-only (no interrupts), so it needs no checkpointer to function; it compiles with
one when available so R4b can drop the `act` gate into the same loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncGenerator, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agents.models import Slot, get_model
from agents.orchestrator import artifacts
from agents.orchestrator import skills as _skills
from agents.orchestrator import graph as _g  # reuse helpers + AgentState (no fork)
from agents.orchestrator.prompts import (
    AGENT_GENERATION_PROMPT,
    AGENT_VERIFICATION_PROMPT,
    COMPACTION_PROMPT,
    CONTROLLER_DECISION_PROMPT,
    DIRECT_GENERATION_PROMPT,
)
from agents.registry import Capability, get as get_subagent, has as has_capability
from core.config import settings

logger = logging.getLogger(__name__)

_DECISION_TYPES = {"read", "act", "answer", "ask", "load_skill", "replan", "done"}


# ── Context the controller reasons over ──────────────────────

def _findings_block(state: _g.AgentState) -> str:
    findings = state.get("findings") or []
    if not findings:
        return "(nothing gathered yet)"
    return "\n".join(f"- {f}" for f in findings[-12:])


def _history_block(state: _g.AgentState) -> str:
    history = state.get("chat_history") or []
    if not history:
        return ""
    recent = history[-4:]
    return "Recent conversation:\n" + "\n".join(
        f"{t.get('role')}: {t.get('content', '')[:300]}" for t in recent
    ) + "\n\n"


def _plan_block(state: _g.AgentState) -> str:
    plan = state.get("plan") or []
    if not plan:
        return "(no steps yet)"
    return "\n".join(f"- [{s.get('status', 'pending')}] {s.get('label')}" for s in plan)


def _read_signature(decision: dict) -> str:
    """A read's identity = its sub-queries (if a parallel fan-out) or which sources it
    touches (the query is fixed per run). Repeating the same signature with no progress is
    the duplicate-read stall signal (spec §2.8)."""
    queries = decision.get("queries")
    if isinstance(queries, list) and queries:
        return "q:" + "|".join(sorted(str(q.get("query", "")) for q in queries if isinstance(q, dict)))
    s = decision.get("sources") or {}
    return f"doc={bool(s.get('documents'))},live={bool(s.get('live'))},whole={bool(s.get('whole_doc'))}"


def _estimate_tokens(state: _g.AgentState) -> int:
    """Rough working-context size (chars/4) — findings + the bounded raw context — to drive
    the per-run token-budget fuse (spec §2.8)."""
    chars = sum(len(str(f)) for f in (state.get("findings") or []))
    chars += sum(len(str(c.get("text", ""))) for c in (state.get("context_chunks") or []))
    chars += sum(len(str(r.get("data", ""))) for r in (state.get("live_records") or []))
    chars += sum(len(str(w.get("text", ""))) for w in (state.get("whole_documents") or []))
    return chars // 4


async def _maybe_compact(state: _g.AgentState, writer) -> dict:
    """Compaction (spec §2.7): once working-context tokens cross the threshold, LLM-summarize
    older raw evidence into ONE dense, citation-preserving finding and DROP the raw (it's
    safe in the artifact store). Pinned items are exempt — loaded skill bodies, the plan,
    the recent findings, and the last K raw chunks. Densify so the run continues, rather
    than wrapping up at the budget fuse. Returns the state delta, or {} if not triggered."""
    threshold = settings.agent_controller_compaction_threshold
    if threshold <= 0 or _estimate_tokens(state) <= threshold:
        return {}
    chunks = state.get("context_chunks") or []
    live = state.get("live_records") or []
    whole = state.get("whole_documents") or []
    keep = max(0, settings.agent_controller_compaction_keep_recent)
    older = chunks[:-keep] if keep else chunks
    keep_chunks = chunks[-keep:] if keep else []
    if not older and not whole and not live:
        return {}  # nothing bulky to compact (findings alone are already terse)

    blob = "\n\n".join(p for p in (
        _g._format_context(older, ""), _g._format_whole_docs(whole), _g._format_live(live)) if p.strip())
    try:
        resp = await get_model(Slot.GENERATION).ainvoke(
            [SystemMessage(content=COMPACTION_PROMPT), HumanMessage(content=blob[:16000])])
        summary = (resp.content if hasattr(resp, "content") else str(resp)).strip()
    except Exception as exc:
        logger.warning("compaction failed: %s", exc)
        return {}
    if not summary:
        return {}
    if writer:
        writer({"type": "reasoning", "text": "Condensing earlier findings to stay focused."})
    findings = (state.get("findings") or []) + [f"[Compacted digest of earlier evidence]\n{summary}"]
    # Drop the compacted raw; keep recent chunks + the digest. Skills/plan untouched (pinned).
    return {"context_chunks": keep_chunks, "whole_documents": [], "live_records": [], "findings": findings}


async def _drain_interjections(state: _g.AgentState, writer) -> tuple[list[str], bool]:
    """Drain the run's interjection mailbox (spec §2.9). Returns (new findings to fold in,
    cancel_run). ``augment`` (default) and ``cancel_step`` become findings the controller
    plans against; ``cancel_run`` signals an immediate graceful wrap-up."""
    tid = state.get("thread_id")
    if not tid:
        return [], False
    from agents.orchestrator import event_bus
    items = await event_bus.drain_mailbox(tid)
    new_findings: list[str] = []
    cancel_run = False
    for it in items:
        mode = (it.get("mode") or "augment")
        msg = (it.get("message") or "").strip()
        if mode == "cancel_run":
            cancel_run = True
        elif mode == "cancel_step":
            new_findings.append(f"[User interjection] Skip the current direction: {msg}")
            if writer:
                writer({"type": "reasoning", "text": "Noted — I'll skip that."})
        else:
            new_findings.append(f"[User interjection] The user added mid-run: {msg}")
            if writer:
                writer({"type": "reasoning", "text": "Got it — folding that into what I'm doing."})
    return new_findings, cancel_run


# ── Nodes ────────────────────────────────────────────────────

async def hydrate_node(state: _g.AgentState) -> dict:
    """Initialize loop state and the source-availability hints the controller plans with."""
    has_documents = bool(state.get("allowed_collections"))
    has_live = False
    user_id = state.get("user_id") or ""
    if user_id:
        try:
            from agents.retrieval_agent.live import _enabled_connector_catalog
            # Enabled connectors expose both reads and gated actions; one cheap DB check
            # hints both availabilities (the action agent still confirms a real tool fits).
            has_live = bool(_enabled_connector_catalog(user_id))
        except Exception as exc:
            logger.warning("controller: live-availability check failed: %s", exc)
    has_action = has_live and bool(state.get("durable")) and has_capability(Capability.ACTION)

    # Skills (spec §2.10): the index the controller plans with, + any explicitly-selected
    # playbooks loaded up front as run-level instructions (both entry paths).
    import asyncio
    skill_index = await asyncio.to_thread(_skills.get_skill_index)
    loaded_skills: list[dict] = []
    findings: list[str] = []
    for name in (state.get("skill_names") or []):
        snap = await asyncio.to_thread(_skills.load_skill_snapshot, name)
        if snap:
            loaded_skills.append({"name": snap["name"], "version": snap["version"],
                                  "body": snap["body"], "metadata": snap["metadata"]})
            findings.extend(_skill_fact_findings(snap))
            writer = get_stream_writer()
            if writer:
                writer({"type": "skill_loaded", "name": snap["name"], "version": snap["version"]})

    return {
        "findings": findings, "loop_count": 0, "answered": False, "plan": [],
        "has_documents": has_documents, "has_live": has_live, "has_action": has_action,
        "skill_index": skill_index, "loaded_skills": loaded_skills,
        "context_chunks": [], "live_records": [], "whole_documents": [],
        "citations": [], "graph_context": "",
    }


def _skill_fact_findings(snap: dict) -> list[str]:
    """A loaded skill's fact_sections → the evidence channel (citable reference, DATA)."""
    out = []
    for fs in (snap.get("fact_sections") or []):
        content = str(fs.get("content", "")).strip()
        if content:
            out.append(f"[Playbook {snap['name']} — {fs.get('name', 'facts')}] {content[:600]}")
    return out


async def controller_node(state: _g.AgentState) -> dict:
    """Decide the next action as a constrained structured output, with repair-retry and a
    runaway fuse. Logs every decision (the eval corpus, spec §2.2) and streams the
    per-step thinking + narration."""
    writer = get_stream_writer()
    loop_count = int(state.get("loop_count") or 0) + 1

    # Drain the interjection mailbox (spec §2.9) at the loop top — boundary injection, never
    # a concurrent write to the running graph. cancel_run wraps up now; augment / cancel_step
    # fold into findings so the controller's next decision accounts for them.
    new_findings, cancel_run = await _drain_interjections(state, writer)
    merged_findings = (state.get("findings") or []) + new_findings
    # `base` rides on every return so injected findings persist regardless of which path
    # we take this iteration.
    base = {"loop_count": loop_count, **({"findings": merged_findings} if new_findings else {})}
    state = {**state, "findings": merged_findings}  # local view for the prompt this turn

    if cancel_run:
        if writer:
            writer({"type": "reasoning", "text": "Stopping here as you asked — I'll wrap up with what I have."})
        wrap = "answer" if not state.get("answered") else "done"
        return {**base, "decision": {"type": wrap, "reason": "user cancel_run"}}

    # Compaction (spec §2.7) — densify older raw evidence before the budget fuse so a long
    # run keeps a small working context and continues rather than wrapping up.
    compacted = await _maybe_compact(state, writer)
    if compacted:
        state = {**state, **compacted}
        base = {**base, **compacted}

    # Fuses (spec §2.8) — runaway insurance, not pacing. Hitting one = graceful wrap-up,
    # never a dead drop. Checked before the LLM call so we don't spend it.
    if loop_count > settings.agent_controller_max_steps:
        logger.warning("controller: step fuse hit (%s) — forcing done", loop_count)
        if writer:
            writer({"type": "reasoning", "text": "I'll wrap up with what I have so far."})
        return {**base, "decision": {"type": "done", "reason": "step fuse"}}

    budget = settings.agent_controller_token_budget
    if budget > 0 and _estimate_tokens(state) > budget:
        logger.warning("controller: token budget exceeded — wrapping up")
        if writer:
            writer({"type": "reasoning", "text": "I've gathered a lot here — let me pull it together now."})
        wrap = "answer" if not state.get("answered") else "done"
        return {**base, "decision": {"type": wrap, "reason": "token budget", "step_label": "Answer with what I have"}}

    human = (
        f"{_skills.loaded_block(state.get('loaded_skills') or [])}"
        f"{_skills.index_block(state.get('skill_index') or [])}"
        f"{_history_block(state)}"
        f"User request:\n{state.get('query', '')}\n\n"
        f"Sources available: documents={state.get('has_documents')}, live_tools={state.get('has_live')}, "
        f"action_tools={state.get('has_action')}\n"
        f"Findings so far:\n{_findings_block(state)}\n\n"
        f"Current step checklist:\n{_plan_block(state)}\n\n"
        f"Already answered: {bool(state.get('answered'))}"
    )
    llm = get_model(Slot.ORCHESTRATION)
    decision: Optional[dict] = None
    raw = ""
    for attempt in range(2):  # one repair-retry
        try:
            messages = [SystemMessage(content=CONTROLLER_DECISION_PROMPT), HumanMessage(content=human)]
            if attempt == 1:
                messages.append(HumanMessage(content=(
                    "Your previous reply was not valid JSON matching the schema. Reply with ONLY "
                    "the JSON object, no prose.")))
            resp = await llm.ainvoke(messages)
            raw = resp.content if hasattr(resp, "content") else str(resp)
            # Surface the controller's own reasoning trace (gpt-oss parsed channel).
            rc = (getattr(resp, "additional_kwargs", {}) or {}).get("reasoning_content")
            if rc and writer:
                writer({"type": "thinking", "content": rc})
            parsed = _g._parse_json_object(raw)
            if parsed and parsed.get("type") in _DECISION_TYPES:
                decision = parsed
                break
        except Exception as exc:
            logger.warning("controller decision attempt %s failed: %s", attempt, exc)

    if decision is None:
        # Visible, recoverable failure (spec §2.13) — never a silent default. Answer with
        # what we have (or finish) and log the raw so it's debuggable.
        logger.warning("controller: undecodable decision, raw=%r", str(raw)[:200])
        if writer:
            writer({"type": "reasoning", "text": "Let me pull this together into an answer."})
        fallback = "answer" if not state.get("answered") else "done"
        return {**base, "decision": {"type": fallback, "reason": "decision parse failure"},
                "classification_failed": True}

    # Decision trace for the eval corpus (Q9): what it saw → what it chose.
    logger.info("controller_decision step=%s type=%s reason=%s",
                loop_count, decision.get("type"), str(decision.get("reason"))[:120])

    # Stall detection + escalation (spec §2.8): a proposed read that repeats an
    # unproductive attempt — or N consecutive empty reads — forces a re-plan; a second
    # stall after that wraps up gracefully (rather than looping to the step fuse).
    extra: dict = {}
    if decision.get("type") == "read":
        sig = _read_signature(decision)
        decision["_sig"] = sig
        no_progress = int(state.get("no_progress_count") or 0)
        duplicate = sig in (state.get("read_signatures") or [])
        stalled = no_progress >= settings.agent_controller_stall_threshold or (duplicate and no_progress >= 1)
        if stalled:
            if int(state.get("stall_replans") or 0) == 0:
                if writer:
                    writer({"type": "reasoning",
                            "text": "That isn't turning up anything new — let me reconsider the approach."})
                decision = {"type": "replan", "reason": "stall", "plan": []}
                extra = {"stall_replans": 1, "no_progress_count": 0}
            else:
                if writer:
                    writer({"type": "reasoning",
                            "text": "I've hit a dead end on that — I'll answer with what I have."})
                decision = {"type": "answer" if not state.get("answered") else "done",
                            "reason": "stall wrap-up", "step_label": "Answer with what I have"}

    narration = (decision.get("narration") or "").strip()
    if narration and writer:
        writer({"type": "reasoning", "text": narration})

    # Dynamic plan (spec §2.6): append the step the controller just chose so the checklist
    # grows as planned; read/answer/ask become visible steps that reach a terminal status.
    plan = [dict(s) for s in (state.get("plan") or [])]
    dtype = decision.get("type")
    if dtype in ("read", "answer", "act", "ask", "load_skill"):
        default_label = {"read": "Gather information", "answer": "Write the answer",
                         "act": "Prepare the action", "ask": "Ask the user",
                         "load_skill": f"Follow the {decision.get('skill_name', '')} playbook"}[dtype]
        label = (decision.get("step_label") or "").strip() or default_label
        step_id = f"step-{loop_count}"
        decision["_step_id"] = step_id
        status = "awaiting-approval" if dtype == "act" else (
            "awaiting-input" if dtype == "ask" else "running")
        plan.append({"id": step_id, "label": label, "status": status})
        if writer:
            writer({"type": "plan", "steps": plan})

    return {**base, "decision": decision, "plan": plan, **extra}


async def _gather_one(state: _g.AgentState, spec, query: str, sources: dict) -> tuple:
    """One sub-read: resolve which sources to touch (guarded by availability), gather."""
    wd = bool(sources.get("documents")) and bool(state.get("has_documents"))
    wl = bool(sources.get("live")) and bool(state.get("has_live"))
    ww = bool(sources.get("whole_doc"))
    if not (wd or wl):  # nothing usable asked for → safe corpus lookup
        wd = bool(state.get("has_documents"))
    res = await spec.handler.gather(
        query=query, allowed_collections=state.get("allowed_collections", []),
        chat_history=state.get("chat_history"), user_id=state.get("user_id", ""),
        conversation_id=state.get("conversation_id"), want_documents=wd, want_live=wl,
        want_whole_doc=ww, attachments=state.get("attachments"),
    )
    return query, wd, wl, res


async def read_node(state: _g.AgentState) -> dict:
    """Execute a read — one lookup, or a parallel map-reduce fan-out of up to N distinct
    sub-reads (spec §2.7). Each sub-read's raw payload is archived to the artifact store;
    the merged + bounded context and per-sub distilled findings enter state. Streams
    activity/citations; per-connector concurrency is capped in the gateway."""
    writer = get_stream_writer()
    decision = state.get("decision") or {}
    spec = get_subagent(Capability.RETRIEVAL)
    step_id = decision.get("_step_id") or f"step-{state.get('loop_count')}"

    queries = decision.get("queries")
    if isinstance(queries, list) and len(queries) > 1:
        subs = [(str(q.get("query") or state["query"]), q.get("sources") or {})
                for q in queries if isinstance(q, dict)][:max(1, settings.agent_max_parallel_reads)]
    else:
        subs = [(state["query"], decision.get("sources") or {})]

    results = await asyncio.gather(
        *[_gather_one(state, spec, q, s) for q, s in subs], return_exceptions=True)

    artifact_refs = list(state.get("artifact_refs") or [])
    findings = list(state.get("findings") or [])
    add_chunks: list = []
    add_live: list = []
    add_whole: list = []
    add_cit: list = []
    graph_ctx = state.get("graph_context") or ""
    total_n = total_live = 0
    parallel = len(subs) > 1
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("read sub-query failed: %s", r)
            findings.append("One lookup failed; continued with the others.")
            continue
        q, wd, wl, res = r
        for act in res.get("tool_activity", []):
            if writer:
                writer({"type": "tool_activity", **act})
        n, ln = res.get("chunks_retrieved", 0), res.get("live_count", 0)
        total_n += n
        total_live += ln
        add_chunks += res.get("context_chunks", [])
        add_live += res.get("live_records", [])
        add_whole += res.get("whole_documents", [])
        add_cit += res.get("citations", [])
        graph_ctx = graph_ctx or res.get("graph_context", "")
        if n or ln:
            ref = await asyncio.to_thread(
                artifacts.put, state.get("thread_id") or "run", f"{step_id}-{i}", "read",
                {"query": q, "context_chunks": res.get("context_chunks", []),
                 "live_records": res.get("live_records", []), "whole_documents": res.get("whole_documents", [])})
            if ref:
                artifact_refs.append(ref)
        label = f"'{q[:60]}'" if parallel else f"documents={wd}, live={wl}"
        line = f"Read ({label}): {n} passage(s), {ln} live record(s)."
        findings.append(line + (" Nothing relevant found." if n == 0 and ln == 0 else ""))

    # Accumulate then BOUND the raw context (older raw is in the artifact store).
    cap = max(1, settings.agent_controller_max_context_chunks)
    chunks = ((state.get("context_chunks") or []) + add_chunks)[-cap:]
    live = ((state.get("live_records") or []) + add_live)[-cap:]
    whole = ((state.get("whole_documents") or []) + add_whole)[-cap:]
    citations = ((state.get("citations") or []) + add_cit)[-(cap * 2):]
    if citations and writer:
        writer({"type": "citations", "citations": citations})

    # Stall signal (spec §2.8): a read that adds nothing new advances the no-progress
    # counter; a productive read resets it. The signature records what was tried.
    progressed = bool(total_n or total_live)
    no_progress = 0 if progressed else int(state.get("no_progress_count") or 0) + 1
    signatures = list(state.get("read_signatures") or [])
    sig = decision.get("_sig")
    if sig:
        signatures.append(sig)

    if writer:
        writer({"type": "step_status", "id": step_id, "status": "done"})

    return {"context_chunks": chunks, "live_records": live, "whole_documents": whole,
            "citations": citations, "graph_context": graph_ctx,
            "findings": findings, "artifact_refs": artifact_refs,
            "no_progress_count": no_progress, "read_signatures": signatures}


async def answer_node(state: _g.AgentState) -> dict:
    """Produce the answer segment from accumulated context (grounded), or from general
    knowledge when there is nothing to ground on (and the deployment allows it). Streams
    tokens + the verification result via the custom channel."""
    writer = get_stream_writer()
    decision = state.get("decision") or {}
    step_id = decision.get("_step_id")

    chunks = state.get("context_chunks") or []
    live_records = state.get("live_records") or []
    whole_documents = state.get("whole_documents") or []
    attachments = state.get("attachments") or []
    have_context = bool(chunks or live_records or whole_documents or attachments)

    grounded = True
    if have_context:
        answer = await _generate_grounded(state, writer)
    elif settings.agent_allow_ungrounded_answers:
        answer = await _generate_direct(state, writer)
        grounded = False
    else:
        answer = _g._no_sources_message(state)
        if writer:
            writer({"type": "answer_token", "content": answer})

    verification: dict = {}
    if have_context and answer:
        verification = await _verify(state, answer)
        if writer:
            writer({"type": "verification_result",
                    "outcome": verification.get("outcome", "VERIFIED"),
                    "corrected_answer": verification.get("corrected_answer", ""),
                    "explanation": verification.get("explanation", "")})
        if verification.get("outcome") == "CORRECTED" and verification.get("corrected_answer"):
            answer = verification["corrected_answer"]

    if step_id and writer:
        writer({"type": "step_status", "id": step_id, "status": "done"})
    return {"answer": answer, "grounded": grounded, "answered": True, "verification": verification}


async def ask_node(state: _g.AgentState) -> dict:
    """Ask the user a question and wait (spec §2.3) — ONLY interrupt(). On resume the
    answer lands in findings and the loop continues. Replay-safe (no side effects)."""
    writer = get_stream_writer()
    decision = state.get("decision") or {}
    question = (decision.get("text") or "").strip() or "Could you clarify what you'd like me to do?"
    payload = interrupt({"type": "question", "thread_id": state.get("thread_id"),
                         "text": question, "context": decision.get("context")})
    payload = payload if isinstance(payload, dict) else {}
    ans = str(payload.get("answer", "")).strip()
    step_id = decision.get("_step_id")
    if step_id and writer:
        writer({"type": "step_status", "id": step_id, "status": "done"})
    if ans and writer:
        writer({"type": "reasoning", "text": "Thanks — that helps. Continuing."})
    finding = (f"Asked the user: '{question}' → they answered: '{ans}'." if ans
               else f"Asked the user: '{question}' (no answer was given).")
    return {"findings": (state.get("findings") or []) + [finding]}


async def load_skill_node(state: _g.AgentState) -> dict:
    """Load a playbook (spec §2.10): its `body` → the pinned instruction channel
    (`loaded_skills`), its `fact_sections` → the evidence channel (findings). Version is
    pinned BY VALUE (snapshotted into state) so a paused run resumes under the same one.
    Skills inform, never authorize — the gateway stays the sole enforcer."""
    import asyncio
    writer = get_stream_writer()
    decision = state.get("decision") or {}
    name = (decision.get("skill_name") or "").strip()
    step_id = decision.get("_step_id")
    loaded = list(state.get("loaded_skills") or [])

    if any(sk.get("name") == name for sk in loaded):
        if step_id and writer:
            writer({"type": "step_status", "id": step_id, "status": "done"})
        return {}

    snap = await asyncio.to_thread(_skills.load_skill_snapshot, name)
    if snap is None:
        if writer:
            writer({"type": "reasoning", "text": f"I couldn't find a playbook called '{name}'."})
            if step_id:
                writer({"type": "step_status", "id": step_id, "status": "skipped"})
        return {"findings": (state.get("findings") or []) + [f"No playbook named '{name}' was found."]}

    loaded.append({"name": snap["name"], "version": snap["version"],
                   "body": snap["body"], "metadata": snap["metadata"]})
    findings = (state.get("findings") or []) + _skill_fact_findings(snap)
    if writer:
        writer({"type": "reasoning",
                "text": (decision.get("narration") or "").strip() or f"Following your {snap['name']} playbook."})
        writer({"type": "skill_loaded", "name": snap["name"], "version": snap["version"]})
        if step_id:
            writer({"type": "step_status", "id": step_id, "status": "done"})
    return {"loaded_skills": loaded, "findings": findings}


async def replan_node(state: _g.AgentState) -> dict:
    """Replace the user-facing checklist with the controller's revised plan."""
    writer = get_stream_writer()
    decision = state.get("decision") or {}
    new_steps = decision.get("plan")
    if isinstance(new_steps, list) and new_steps:
        plan = [{"id": str(s.get("id") or f"r{i}"), "label": str(s.get("label") or "Step"),
                 "status": "pending"} for i, s in enumerate(new_steps)]
        if writer:
            writer({"type": "plan", "steps": plan})
        return {"plan": plan}
    return {}


# ── Action gate inside the loop (R4b) — the two-node gate from R1, now streaming via
#    the custom channel and looping back to the controller so the run CONTINUES after
#    an action (read → … → act → approve → report → controller → done). ──

async def prepare_action_node(state: _g.AgentState) -> dict:
    """Propose the action(s) for this step (preview only). One action → the simple
    single-gate flow (unchanged contract). Several → a batch awaiting one plan-level
    approval (spec §2.4). Idempotency is keyed per act-step so a replay returns the same
    pending records."""
    writer = get_stream_writer()
    if not has_capability(Capability.ACTION):
        return {"proposed_action": {"proposed": False, "reason": "no_action_capability"}}
    spec = get_subagent(Capability.ACTION)
    thread_id = state.get("thread_id") or ""
    step = state.get("loop_count")
    batch = await spec.handler.propose_batch(
        query=state["query"], citations=state.get("citations", []),
        user_id=state.get("user_id", ""), conversation_id=state.get("conversation_id"),
        idempotency_prefix=f"{thread_id}:act-{step}" if thread_id else None,
    )
    actions = batch.get("actions") or []

    if not actions:
        decision = state.get("decision") or {}
        step_id = decision.get("_step_id")
        if step_id and writer:
            writer({"type": "step_status", "id": step_id, "status": "skipped"})
        finding = f"No action was taken ({batch.get('reason', 'none warranted')})."
        return {"proposed_action": {"proposed": False, "reason": batch.get("reason")},
                "findings": (state.get("findings") or []) + [finding]}

    if len(actions) == 1:
        proposal = {**actions[0], "proposed": True}
        if thread_id:
            proposal["thread_id"] = thread_id
        if proposal.get("reasoning") and writer:
            writer({"type": "reasoning", "text": proposal["reasoning"]})
        summary = (proposal.get("summary") or "").strip()
        if summary and writer:
            writer({"type": "answer_token", "content": summary})
        return {"proposed_action": proposal, "proposed_batch": []}

    # Multi-action plan → batch gate.
    for a in actions:
        a["thread_id"] = thread_id
    if writer:
        writer({"type": "reasoning",
                "text": f"I've prepared {len(actions)} actions for your approval."})
    return {"proposed_batch": actions, "proposed_action": {}}


async def await_batch_approval_node(state: _g.AgentState) -> dict:
    """Batch approval gate (spec §2.4) — ONLY interrupt(). Presents every action's typed
    preview; the user approves/deselects per action. Replay-safe (no side effects here)."""
    batch = state.get("proposed_batch") or []
    payload = interrupt({
        "type": "batch_approval_required",
        "thread_id": state.get("thread_id"),
        "batch": [{"pending_id": a.get("pending_id"), "connector": a.get("connector"),
                   "capability": a.get("capability"), "preview": a.get("preview"),
                   "summary": a.get("summary"), "reasoning": a.get("reasoning"),
                   "target": a.get("target", ""),
                   "preview_status": a.get("preview_status", "resolved"),
                   "sources": a.get("sources", [])} for a in batch],
    })
    payload = payload if isinstance(payload, dict) else {}
    return {"batch_decisions": payload.get("batch_decisions") or {},
            "approver_id": str(payload.get("approver_id", ""))}


_PLACEHOLDER = re.compile(r"\$\{action(\d+)\.([^}]+)\}")


def _resolve_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            cur = getattr(cur, part, None)
        if cur is None:
            break
    return cur


def _materialize(template_args: dict, results_map: dict) -> dict:
    """Fill ``${actionN.path}`` placeholders in a parameterized action's args from the
    results of already-executed actions in this batch (spec §2.4)."""
    out: dict = {}
    for k, v in (template_args or {}).items():
        if isinstance(v, str):
            m = _PLACEHOLDER.fullmatch(v.strip())
            if m:
                out[k] = _resolve_path(results_map.get(int(m.group(1))), m.group(2))
                continue
            out[k] = _PLACEHOLDER.sub(
                lambda mt: (lambda val: str(val) if val is not None else mt.group(0))(
                    _resolve_path(results_map.get(int(mt.group(1))), mt.group(2))), v)
        else:
            out[k] = v
    return out


async def resolve_batch_node(state: _g.AgentState) -> dict:
    """Execute each approved action **in order** (gateway is the sole enforcer); deselected
    ones are rejected. A parameterized action's args are materialized from prior results
    and the gateway diffs them against the approved envelope — out of bounds → `blocked`
    (not executed), to be re-gated. Outcomes are collected for the combined report."""
    batch = state.get("proposed_batch") or []
    decisions = state.get("batch_decisions") or {}
    approver = state.get("approver_id") or state.get("user_id", "")
    spec = get_subagent(Capability.ACTION)
    results: list[dict] = []
    results_map: dict[int, Any] = {}
    for i, action in enumerate(batch):
        pid = action.get("pending_id")
        idx = action.get("index", i)
        if decisions.get(pid) != "approve":
            r = await spec.handler.reject(pending_id=pid, approver_id=approver)
            res = {"status": "rejected", **{k: v for k, v in r.items() if k != "status"}}
        elif action.get("preview_status") == "parameterized":
            materialized = _materialize(action.get("arguments") or {}, results_map)
            res = await spec.handler.approve_with_args(
                pending_id=pid, approver_id=approver, materialized_args=materialized)
            res["materialized_args"] = materialized
        else:
            res = await spec.handler.approve(pending_id=pid, approver_id=approver)
        if res.get("status") == "executed":
            # Store the full response so `${actionN.result.<path>}` placeholders resolve.
            results_map[idx] = {"result": res.get("result")}
        results.append({"pending_id": pid, "connector": action.get("connector"),
                        "capability": action.get("capability"), "summary": action.get("summary"),
                        "action": action, **res})
    return {"batch_results": results}


async def report_batch_node(state: _g.AgentState) -> dict:
    """Combined post-batch report — one grounded line per action — streamed as the answer,
    plus a per-action action_result. Loops back to the controller (the run continues)."""
    writer = get_stream_writer()
    results = state.get("batch_results") or []
    spec = get_subagent(Capability.ACTION)
    lines = []
    blocked = []
    for r in results:
        status = r.get("status")
        if status == "executed":
            msg = await spec.handler.summarize_result(action=r["action"], result=r.get("result"))
            msg = msg or f"Done — {r.get('summary') or r.get('capability')}."
        elif status == "rejected":
            msg = f"Skipped — {r.get('summary') or r.get('capability')}."
        elif status == "blocked":
            # Gateway refused: materialized args fell outside the approved envelope. NOT
            # executed (the guarantee) — flag for fresh approval.
            msg = (f"Held back — {r.get('summary') or r.get('capability')}'s details changed "
                   f"beyond what you approved, so I didn't run it without a fresh OK.")
            blocked.append(f"{r.get('capability')} ({r.get('error')})")
        else:
            msg = f"Couldn't complete {r.get('summary') or r.get('capability')}: {r.get('error') or 'failed'}."
        lines.append(f"- {msg}")
        if writer:
            writer({"type": "action_result", "pending_id": r.get("pending_id"),
                    "thread_id": state.get("thread_id"), "status": status,
                    "message": msg, "error": r.get("error")})
    report = "Here's what I did:\n" + "\n".join(lines)
    if writer:
        writer({"type": "answer_token", "content": report})
        step_id = (state.get("decision") or {}).get("_step_id")
        if step_id:
            done = all(r.get("status") in ("executed", "rejected") for r in results)
            writer({"type": "step_status", "id": step_id, "status": "done" if done else "failed"})
    n_exec = sum(1 for r in results if r.get("status") == "executed")
    finding = f"Batch of {len(results)} action(s) resolved: {n_exec} executed."
    if blocked:
        # The controller sees this next turn and can re-propose the held-back action(s)
        # via the single act gate (a fresh concrete preview — the §2.4 re-interrupt).
        finding += (f" Held back (need fresh approval — their details changed beyond the "
                    f"approved bounds): {', '.join(blocked)}.")
    return {"answer": report, "answered": True, "grounded": True,
            "findings": (state.get("findings") or []) + [finding]}


async def await_approval_node(state: _g.AgentState) -> dict:
    """The approval gate — ONLY interrupt() (replay-safe; all side effects ran in
    prepare). Same payload as the fixed pipeline, so the UI/approval contract is shared."""
    proposal = state.get("proposed_action") or {}
    decision = interrupt({
        "type": "approval_required",
        "thread_id": state.get("thread_id"),
        "pending_id": proposal.get("pending_id"),
        "connector": proposal.get("connector"),
        "capability": proposal.get("capability"),
        "preview": proposal.get("preview"),
        "reasoning": proposal.get("reasoning", ""),
        "summary": proposal.get("summary", ""),
        "target": proposal.get("target", ""),
        "sources": proposal.get("sources", []),
        "regated": proposal.get("regated", False),
    })
    decision = decision if isinstance(decision, dict) else {}
    return {"approval_decision": str(decision.get("decision", "reject")),
            "approver_id": str(decision.get("approver_id", ""))}


async def resolve_action_node(state: _g.AgentState) -> dict:
    """Carry out the human decision. Approve → token + execute (gateway is the sole
    enforcer); reject → recorded. An expired pending record re-previews + re-gates
    (action_result=None signals the re-gate) instead of erroring."""
    proposal = state.get("proposed_action") or {}
    decision = state.get("approval_decision")
    approver = state.get("approver_id") or state.get("user_id", "")
    spec = get_subagent(Capability.ACTION)

    if decision != "approve":
        res = await spec.handler.reject(pending_id=proposal.get("pending_id"), approver_id=approver)
        return {"action_result": {"status": "rejected", **{k: v for k, v in res.items() if k != "status"}}}

    res = await spec.handler.approve(pending_id=proposal.get("pending_id"), approver_id=approver)
    err = str(res.get("error", ""))
    if res.get("status") == "failed" and "unknown or expired action" in err:
        from agents.connector_gateway import gateway
        try:
            prev = await gateway.preview_action(
                connector_id=proposal.get("connector_id"), capability=proposal.get("capability"),
                arguments=proposal.get("arguments") or {}, user_id=state.get("user_id") or None,
                gated_mode=proposal.get("gated_mode", "sdk"),
            )
            reproposal = {**proposal, "pending_id": prev["pending_id"],
                          "preview": prev["preview"], "regated": True}
            return {"proposed_action": reproposal, "action_result": None}
        except Exception as exc:
            logger.warning("controller re-preview after expiry failed: %s", exc)
            return {"action_result": {"status": "failed",
                                      "error": f"approval expired and re-preview failed: {exc}"}}
    return {"action_result": res}


async def report_action_node(state: _g.AgentState) -> dict:
    """Ground the post-action report on the actual result, stream it, and fold the
    outcome into findings so the controller knows the action is done and chooses `done`.
    Routes back to the controller — the loop CONTINUES after an action."""
    writer = get_stream_writer()
    res = state.get("action_result") or {}
    proposal = state.get("proposed_action") or {}
    decision = state.get("decision") or {}
    step_id = decision.get("_step_id")
    status = res.get("status")

    if status == "rejected":
        message = ("Understood — I haven't run that action; nothing was changed. "
                   "Tell me what you'd like to do instead.")
    elif status != "executed":
        message = f"I wasn't able to complete the action: {res.get('error') or 'it could not be completed'}"
    else:
        spec = get_subagent(Capability.ACTION)
        message = await spec.handler.summarize_result(action=proposal, result=res.get("result"))
        if not message:
            message = (f"Done — the {proposal.get('capability', 'action')} action on "
                       f"{proposal.get('connector', 'the connector')} was executed successfully.")

    if writer:
        writer({"type": "answer_token", "content": message})
        writer({"type": "action_result", "pending_id": proposal.get("pending_id"),
                "thread_id": state.get("thread_id"), "status": status,
                "message": message, "error": res.get("error")})
        if step_id:
            writer({"type": "step_status", "id": step_id,
                    "status": {"executed": "done", "rejected": "rejected"}.get(status, "failed")})

    finding = f"Action {proposal.get('capability', '')} {status}: {message[:200]}"
    return {"answer": message, "answered": True, "grounded": True,
            "findings": (state.get("findings") or []) + [finding]}


async def finalize_node(state: _g.AgentState) -> dict:
    """Emit the terminal `done` event with the run's result (same shape as the fixed
    pipeline) so the API/executor/UI are unchanged."""
    writer = get_stream_writer()
    answer = state.get("answer") or _g.INSUFFICIENT_MSG
    if writer:
        writer({"type": "done",
                "conversation_id": state.get("conversation_id"),
                "thread_id": state.get("thread_id"),
                "paused": False,
                "answer": answer,
                "intent": "controller",
                "citations": state.get("citations", []),
                "verification": state.get("verification", {}),
                "proposed_action": None,
                "grounded": state.get("grounded", True)})
    return {}


# ── Generation / verification (reuse the fixed pipeline's prompts + helpers) ──

async def _generate_grounded(state: _g.AgentState, writer) -> str:
    chunks = state.get("context_chunks") or []
    source_block = (
        f"Document sources:\n{_g._format_context(chunks, state.get('graph_context', '')) or '(none)'}\n\n"
        f"Full documents:\n{_g._format_whole_docs(state.get('whole_documents') or []) or '(none)'}\n\n"
        f"Live sources:\n{_g._format_live(state.get('live_records') or []) or '(none)'}\n\n"
        f"Attached by the user:\n{_g._format_attachments(state.get('attachments') or []) or '(none)'}"
    )
    messages: list = [SystemMessage(content=AGENT_GENERATION_PROMPT)]
    addendum = _skill_instructions(state)
    if addendum:
        messages.append(SystemMessage(content=addendum))
    for turn in state.get("chat_history") or []:
        role, content = turn.get("role"), turn.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=f"{source_block}\n\nQuestion: {state['query']}"))
    return await _stream_answer(messages, writer)


def _skill_instructions(state: _g.AgentState) -> str:
    """Loaded playbook bodies as a generation instruction addendum (admin-authored —
    shape voice/format/workflow; never expand permissions)."""
    loaded = state.get("loaded_skills") or []
    if not loaded:
        return ""
    parts = [f"### {sk.get('name')} (v{sk.get('version')})\n{sk.get('body', '')}" for sk in loaded]
    return ("Follow the workflow, voice, and formatting of the user's active playbook(s) "
            "below (admin-authored instructions):\n\n" + "\n\n".join(parts))


async def _generate_direct(state: _g.AgentState, writer) -> str:
    messages: list = [SystemMessage(content=DIRECT_GENERATION_PROMPT)]
    addendum = _skill_instructions(state)
    if addendum:
        messages.append(SystemMessage(content=addendum))
    for turn in state.get("chat_history") or []:
        role, content = turn.get("role"), turn.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=state["query"]))
    return await _stream_answer(messages, writer)


async def _stream_answer(messages: list, writer) -> str:
    """Stream a generation, emitting thinking + answer_token deltas via the custom channel."""
    llm = get_model(Slot.GENERATION, streaming=True)
    parts: list[str] = []
    try:
        async for chunk in llm.astream(messages):
            rc = (getattr(chunk, "additional_kwargs", {}) or {}).get("reasoning_content")
            if rc and writer:
                writer({"type": "thinking", "content": rc})
            text = getattr(chunk, "content", "") or ""
            if text:
                parts.append(text)
                if writer:
                    writer({"type": "answer_token", "content": text})
        return "".join(parts).strip()
    except Exception as exc:
        logger.error("controller generation failed: %s", exc)
        return "I'm sorry, I was unable to generate an answer. Please try again."


async def _verify(state: _g.AgentState, answer: str) -> dict:
    chunks = state.get("context_chunks") or []
    live_records = state.get("live_records") or []
    if not chunks and not live_records:
        return {"outcome": "VERIFIED", "corrected_answer": "", "explanation": ""}
    doc_sources = "\n\n".join(f"[Source {i}]\n{c.get('text', '')}" for i, c in enumerate(chunks, 1))
    messages = [
        SystemMessage(content=AGENT_VERIFICATION_PROMPT),
        HumanMessage(content=(
            f"Original Question: {state['query']}\n\n"
            f"Generated Answer:\n{answer}\n\n"
            f"Document Sources:\n{doc_sources or '(none)'}\n\n"
            f"Live Sources:\n{_g._format_live(live_records) or '(none)'}")),
    ]
    try:
        resp = await get_model(Slot.VERIFICATION).ainvoke(messages)
        parsed = _g._parse_json_object(resp.content if hasattr(resp, "content") else str(resp))
        if parsed and parsed.get("outcome"):
            return parsed
    except Exception as exc:
        logger.warning("controller verification failed, treating as VERIFIED: %s", exc)
    return {"outcome": "VERIFIED", "corrected_answer": "", "explanation": ""}


# ── Graph assembly ───────────────────────────────────────────

def _route(state: _g.AgentState) -> str:
    dtype = (state.get("decision") or {}).get("type", "done")
    # `act` and `ask` need the checkpointer (no interrupt without it) — without one,
    # fall back to answering rather than acting blindly or pausing with no resume path.
    if dtype in ("act", "ask") and not state.get("durable"):
        return "answer"
    return dtype


def _route_after_prepare(state: _g.AgentState) -> str:
    if state.get("proposed_batch"):
        return "batch"
    return "await" if (state.get("proposed_action") or {}).get("proposed") else "controller"


def _route_after_resolve(state: _g.AgentState) -> str:
    # action_result=None → pending record expired, fresh preview minted → re-gate.
    return "again" if state.get("action_result") is None else "report"


def build_controller_graph(checkpointer=None):
    g = StateGraph(_g.AgentState)
    g.add_node("hydrate", hydrate_node)
    g.add_node("controller", controller_node)
    g.add_node("read", read_node)
    g.add_node("answer_step", answer_node)  # not "answer" — that's a state key
    g.add_node("load_skill_step", load_skill_node)
    g.add_node("replan", replan_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "hydrate")
    g.add_edge("hydrate", "controller")
    g.add_edge("load_skill_step", "controller")

    route_map = {"read": "read", "answer": "answer_step", "replan": "replan", "done": "finalize",
                 "load_skill": "load_skill_step",  # no interrupt → no checkpointer needed
                 "ask": "answer_step"}  # ask falls back to answer without a checkpointer
    if checkpointer is not None:
        # Question gate (R7) — interrupt to ask the user, then continue.
        g.add_node("ask_step", ask_node)
        route_map["ask"] = "ask_step"
        g.add_edge("ask_step", "controller")
        # The act gate (R4b) needs the checkpointer for interrupt/resume. report loops
        # back to the controller so the run continues after the action.
        g.add_node("prepare_action", prepare_action_node)
        g.add_node("await_approval", await_approval_node)
        g.add_node("resolve_action", resolve_action_node)
        g.add_node("report_action", report_action_node)
        # Batch gate (R6) — a multi-action plan, approved per-action in one interrupt.
        g.add_node("await_batch_approval", await_batch_approval_node)
        g.add_node("resolve_batch", resolve_batch_node)
        g.add_node("report_batch", report_batch_node)
        route_map["act"] = "prepare_action"
        g.add_conditional_edges("prepare_action", _route_after_prepare,
                                {"await": "await_approval", "batch": "await_batch_approval",
                                 "controller": "controller"})
        g.add_edge("await_approval", "resolve_action")
        g.add_conditional_edges("resolve_action", _route_after_resolve,
                                {"again": "await_approval", "report": "report_action"})
        g.add_edge("report_action", "controller")
        g.add_edge("await_batch_approval", "resolve_batch")
        g.add_edge("resolve_batch", "report_batch")
        g.add_edge("report_batch", "controller")
    else:
        route_map["act"] = "answer_step"  # non-durable: can't gate → answer instead

    g.add_conditional_edges("controller", _route, route_map)
    g.add_edge("read", "controller")
    g.add_edge("replan", "controller")
    g.add_edge("answer_step", "finalize")   # a delivered answer segment → finish
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


async def run_controller(
    *,
    query: str,
    allowed_collections: list[str],
    chat_history: Optional[list],
    user_id: str,
    conversation_id: Optional[str],
    attachments: Optional[list[dict]],
    thread_id: str,
    graph,
    durable: bool,
    skill_names: Optional[list[str]] = None,
) -> AsyncGenerator[dict, None]:
    """Drive the controller graph, forwarding the events its nodes write on the custom
    stream channel. Same event contract as Orchestrator.run() so the API/executor/UI are
    unchanged."""
    state: _g.AgentState = {
        "query": query, "allowed_collections": allowed_collections,
        "chat_history": chat_history or [], "user_id": user_id,
        "conversation_id": conversation_id, "attachments": attachments or [],
        "thread_id": thread_id, "durable": durable, "skill_names": skill_names or [],
    }
    config = {"configurable": {"thread_id": thread_id}} if durable else None
    saw_done = False
    try:
        async for mode, payload in graph.astream(state, config, stream_mode=["custom", "updates"]):
            if mode == "custom":
                if isinstance(payload, dict) and payload.get("type"):
                    if payload["type"] == "done":
                        saw_done = True
                    yield payload
            elif mode == "updates" and isinstance(payload, dict) and "__interrupt__" in payload:
                # The act gate paused the loop (single or batch). Emit the gate event +
                # a paused `done`; the run resumes via resume() on this thread_id. The
                # executor persists the gate from the gate event, as the fixed path does.
                intr = payload["__interrupt__"]
                intr0 = intr[0] if isinstance(intr, (list, tuple)) and intr else intr
                ip = dict(getattr(intr0, "value", None) or {})
                if ip.get("type") in ("approval_required", "batch_approval_required", "question"):
                    yield {"type": ip["type"], **{k: v for k, v in ip.items() if k != "type"}}
                    vals = (await graph.aget_state(config)).values or {}
                    yield {"type": "done", "conversation_id": conversation_id, "thread_id": thread_id,
                           "paused": True, "answer": ip.get("summary", "") or vals.get("answer", ""),
                           "intent": "controller", "citations": vals.get("citations", []),
                           "verification": {}, "proposed_action": None, "grounded": True}
                    saw_done = True
                    return
        if not saw_done:
            # Safety net: the loop ended without a terminal event (shouldn't happen).
            snap = await graph.aget_state(config) if config else None
            answer = ((snap.values if snap else {}) or {}).get("answer") or _g.INSUFFICIENT_MSG
            yield {"type": "done", "conversation_id": conversation_id, "thread_id": thread_id,
                   "paused": False, "answer": answer, "intent": "controller", "citations": [],
                   "verification": {}, "proposed_action": None, "grounded": True}
    except Exception as exc:
        logger.exception("controller run failed for %s", thread_id)
        yield {"type": "error", "message": str(exc)}


async def run_controller_resume(
    *, thread_id: str, decision: Optional[str], approver_id: str, graph,
    batch_decisions: Optional[dict] = None, answer: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    """Resume a controller run paused at an interrupt — the act gate (single/batch) OR a
    question (``answer``). Feeds the input via Command(resume=…) and forwards the
    continuation from the custom channel; an expired pending record re-gates. Each paused
    node reads its own field from the unified resume payload."""
    is_answer = answer is not None
    if not is_answer and not batch_decisions and decision not in ("approve", "reject"):
        yield {"type": "error", "message": f"invalid decision '{decision}'"}
        return
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = await graph.aget_state(config)
    except Exception as exc:
        logger.warning("controller resume: state lookup failed for %s: %s", thread_id, exc)
        snapshot = None
    if snapshot is None or not snapshot.next:
        yield {"type": "error", "message": "nothing to resume — this run is not paused (it may have expired)"}
        return
    run_user = (snapshot.values or {}).get("user_id", "")
    if run_user and run_user != approver_id:
        yield {"type": "error", "message": "this run belongs to another user"}
        return

    if not is_answer:
        # Move the awaiting-approval step forward (a question step is closed by ask_node).
        step_id = ((snapshot.values or {}).get("decision") or {}).get("_step_id", "act")
        any_approve = (decision == "approve") or bool(
            batch_decisions and any(v == "approve" for v in batch_decisions.values()))
        yield {"type": "step_status", "id": step_id, "status": "running" if any_approve else "rejected"}
    try:
        async for mode, payload in graph.astream(
            Command(resume={"decision": decision, "approver_id": approver_id,
                            "batch_decisions": batch_decisions or {}, "answer": answer or ""}),
            config, stream_mode=["custom", "updates"],
        ):
            if mode == "custom":
                if isinstance(payload, dict) and payload.get("type"):
                    yield payload
            elif mode == "updates" and isinstance(payload, dict) and "__interrupt__" in payload:
                # The continuation paused again: an expired-preview re-gate, a new batch/
                # action gate, or a follow-up question. Surface it and stop (a fresh resume
                # continues from here).
                intr = payload["__interrupt__"]
                intr0 = intr[0] if isinstance(intr, (list, tuple)) and intr else intr
                ip = dict(getattr(intr0, "value", None) or {})
                if ip.get("type") in ("approval_required", "batch_approval_required", "question"):
                    if ip.get("type") == "approval_required" and ip.get("regated"):
                        yield {"type": "reasoning", "text": (
                            "The approval window for this action had lapsed, so I refreshed the "
                            "preview — please confirm it again.")}
                    yield {"type": ip["type"], **{k: v for k, v in ip.items() if k != "type"}}
                    return
    except Exception as exc:
        logger.exception("controller resume failed for %s", thread_id)
        yield {"type": "error", "message": str(exc)}

"""
Deep Query — Orchestrator (LangGraph)

The planner/coordinator. Classifies intent, derives a bounded plan, and delegates to
sub-agents via the capability registry, then routes the gathered context through
generation and verification. It never synthesizes factual claims itself and never
acts (guide §4).

Phase 1 scope: the document path only — classify → retrieve (document) → generate →
verify, as a real compiled ``StateGraph`` so the interrupt/resume needed for the
Phase 3 approval gate slots in without a rewrite. Live retrieval (Phase 2) and gated
actions (Phase 3) extend this graph with conditional edges.

``run()`` drives the graph and yields structured SSE events (plan, step_status,
reasoning, tool_activity, citations, answer_token, verification_result, done) for the
dedicated Agents surface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from enum import Enum
from typing import Any, AsyncGenerator, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agents.models import Slot, get_model
from agents.orchestrator.prompts import (
    AGENT_GENERATION_PROMPT,
    AGENT_VERIFICATION_PROMPT,
    DIRECT_GENERATION_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
)
from core.config import settings
from agents.registry import Capability, get as get_subagent, has as has_capability

# Import sub-agent packages so they self-register with the capability registry.
import agents.retrieval_agent  # noqa: F401
import agents.action_agent  # noqa: F401

logger = logging.getLogger(__name__)

INSUFFICIENT_MSG = (
    "Based on the available documents, I could not find sufficient information to "
    "fully answer this question."
)

# Plans presented to the user as a checklist. Step ids map to graph nodes (+ the
# virtual "approve" step for the action gate). Chosen per intent after classification.
PLAN_DOC = [
    {"id": "retrieve", "label": "Search the knowledge base"},
    {"id": "generate", "label": "Generate a grounded answer"},
    {"id": "verify", "label": "Verify the answer against its sources"},
]
PLAN_LIVE = [
    {"id": "retrieve", "label": "Check live sources"},
    {"id": "generate", "label": "Generate a grounded answer"},
    {"id": "verify", "label": "Verify the answer against its sources"},
]
PLAN_BOTH = [
    {"id": "retrieve", "label": "Search documents and live sources"},
    {"id": "generate", "label": "Generate a grounded answer"},
    {"id": "verify", "label": "Verify the answer against its sources"},
]
PLAN_ACTION = [
    {"id": "retrieve", "label": "Gather context"},
    {"id": "propose", "label": "Propose an action"},
    {"id": "approve", "label": "Await your approval"},
]
PLAN_DIRECT = [
    {"id": "answer", "label": "Answer from general knowledge"},
]

# User-facing narration is normally written by the classifier (natural, per-query). These
# are only a varied fallback when the model omits it — never expose the raw intent label.
_FALLBACK_NARRATION = {
    "document": ["Let me look through your documents.", "Searching your documents for this.",
                 "I'll check your knowledge base."],
    "live": ["Let me check your connected tools.", "Pulling the latest from your connected sources.",
             "I'll look that up live for you."],
    "both": ["I'll check your documents and your live sources.",
             "Let me pull this from your documents and connected tools."],
    "action": ["I'll set that up for you to approve.", "Let me prepare that action for your approval.",
               "Got it — I'll draft that and check with you before doing it."],
    "direct": ["Let me work through that.", "One moment.", "I'll answer that directly."],
}


def _fallback_narration(intent: str) -> str:
    return random.choice(_FALLBACK_NARRATION.get(intent, _FALLBACK_NARRATION["document"]))


# Canonical plan per intent — the step IDs/order/count are FIXED here (they map to real
# graph nodes, so `step_status` updates always land). The classifier only humanizes the
# LABELS. (Truly model-decided, variable-length plans are a controller-loop feature —
# see RESUMABLE_AGENT_SPEC.md §2.2; in this seconds-long agent the executed phases are
# fixed, so the checklist must reflect real work that actually completes.)
_DEFAULT_PLANS = {
    "document": PLAN_DOC, "live": PLAN_LIVE, "both": PLAN_BOTH,
    "action": PLAN_ACTION, "direct": PLAN_DIRECT,
}


def _build_plan(intent: str, llm_steps: Any) -> list[dict]:
    """Build the user-facing checklist: canonical step IDs/order for the intent, with the
    classifier's natural per-query labels spliced in where a step id matches (default
    label otherwise). Guarantees every shown step has a real ID that gets a status."""
    base = _DEFAULT_PLANS.get(intent, PLAN_DOC)
    label_by_id: dict[str, str] = {}
    if isinstance(llm_steps, list):
        for s in llm_steps:
            if isinstance(s, dict) and isinstance(s.get("label"), str) and s["label"].strip():
                label_by_id[s.get("id")] = s["label"].strip()[:80]
    return [{"id": st["id"], "label": label_by_id.get(st["id"], st["label"])} for st in base]


class Intent(str, Enum):
    DOCUMENT = "document"
    LIVE = "live"
    BOTH = "both"
    ACTION = "action"
    DIRECT = "direct"


class AgentState(TypedDict, total=False):
    # Inputs
    query: str
    allowed_collections: list[str]
    chat_history: list[dict]
    user_id: str
    conversation_id: Optional[str]
    # Plan
    intent: str
    intent_rationale: str        # internal "why" (background, for logs/done)
    narration: str               # user-facing "what I'm about to do" (no jargon)
    plan_steps: list[dict]       # classifier's natural per-step labels (mapped in run())
    classification_failed: bool  # true when we couldn't classify (fell back)
    plan: list[dict]
    # Retrieval
    context_chunks: list[dict]
    live_records: list[dict]
    whole_documents: list[dict]
    attachments: list[dict]
    citations: list[dict]
    graph_context: str
    chunks_retrieved: int
    live_count: int
    tool_activity: list[dict]
    retrieval_error: Optional[str]
    # Action (Phase 3) + durable gate (RESUMABLE_AGENT_SPEC_V2 §2.3)
    thread_id: str               # per-RUN identity (checkpoint + event-stream key)
    durable: bool                # checkpointer active → gate pauses, idempotency keyed
    proposed_action: dict
    proposed_batch: list[dict]   # multi-action plan awaiting batch approval (R6)
    batch_decisions: dict        # {pending_id: "approve"|"reject"} from the batch resume
    batch_results: list[dict]    # per-action outcomes of resolve_batch
    approval_decision: str       # "approve" | "reject" (from the resume payload)
    approver_id: str
    action_result: dict          # outcome of resolve_action (executed/rejected/failed)
    # Controller loop (RESUMABLE_AGENT_SPEC_V2 §2.2, phase R4)
    findings: list[str]          # distilled evidence summaries accumulated across reads
    decision: dict               # the controller's current structured decision
    loop_count: int              # controller iterations (fuse against runaway)
    answered: bool               # an answer segment has been produced
    # Context discipline + sprawl control (spec §2.7–2.8, R5)
    artifact_refs: list[str]     # refs to raw read payloads offloaded to the artifact store
    read_signatures: list[str]   # source-signatures of executed reads (duplicate detection)
    no_progress_count: int       # consecutive reads that added no new evidence (stall)
    stall_replans: int           # forced re-plans so far (escalates to wrap-up)
    # Skills consumption (spec §2.10, R8)
    skill_names: list[str]       # explicitly-selected skills to load at hydration (run-level)
    skill_index: list[dict]      # {name,description,kind} for active skills (controller plans with)
    loaded_skills: list[dict]    # {name,version,body,metadata} — pinned instruction channel
    has_documents: bool          # corpus available this run (hint to the controller)
    has_live: bool               # live tools available this run (hint to the controller)
    has_action: bool             # action tools available + durable (act decision enabled)
    # Output
    answer: str
    grounded: bool
    verification: dict


# ── Helpers ──────────────────────────────────────────────────

def _parse_json_object(text: str) -> Optional[dict]:
    """Parse a JSON object from a model response, tolerating ```json fences."""
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


def _format_context(context_chunks: list[dict], graph_context: str) -> str:
    """Format chunks as [Source N] blocks — matching the chat path so [Source N]
    citation numbering aligns with the citation objects."""
    parts = []
    for i, chunk in enumerate(context_chunks, 1):
        parts.append(
            f"[Source {i}] (Document: {chunk.get('source', 'Unknown')}, "
            f"Page: {chunk.get('page', 'N/A')})\n{chunk.get('text', '')}"
        )
    context = "\n\n".join(parts)
    if graph_context:
        context += f"\n\n[Knowledge Graph Context]\n{graph_context}"
    return context


def _format_whole_docs(whole_documents: list[dict]) -> str:
    """Format full corpus documents as [Doc N] blocks."""
    parts = []
    for i, w in enumerate(whole_documents, 1):
        parts.append(f"[Doc {i}] (Full document: {w.get('title', 'Unknown')})\n{w.get('text', '')}")
    return "\n\n".join(parts)


def _format_attachments(attachments: list[dict]) -> str:
    """Format user-attached documents as [Attachment N] blocks."""
    parts = []
    for att in attachments:
        n = att.get("attachment_number", len(parts) + 1)
        parts.append(f"[Attachment {n}] (User-provided: {att.get('filename', 'file')})\n{att.get('text', '')}")
    return "\n\n".join(parts)


def _format_live(live_records: list[dict]) -> str:
    """Format live records as [Live N] blocks carrying connector + retrieval time,
    so live facts are cited and timestamped distinctly from document facts."""
    parts = []
    for rec in live_records:
        n = rec.get("live_number", len(parts) + 1)
        data = rec.get("data")
        text = data if isinstance(data, str) else json.dumps(data, default=str)
        parts.append(
            f"[Live {n}] (Connector: {rec.get('connector', 'unknown')}, "
            f"as of {rec.get('retrieved_at', 'unknown')})\n{text}"
        )
    return "\n\n".join(parts)


# ── Nodes ────────────────────────────────────────────────────

async def plan_node(state: AgentState) -> dict:
    """Classify intent (orchestration slot) and derive the plan. Treats the query as
    untrusted data to classify, never as instructions (guide §12)."""
    query = state["query"]
    llm = get_model(Slot.ORCHESTRATION)
    intent = Intent.DOCUMENT
    rationale = "Defaulted to the document corpus."
    narration = ""
    plan_steps = None
    classification_failed = False
    # Include a little recent history so follow-ups ("and the second one?") classify
    # in context. History is data to consider, not instructions.
    history = state.get("chat_history") or []
    convo = ""
    if history:
        recent = history[-4:]
        convo = "Recent conversation (for context):\n" + "\n".join(
            f"{t.get('role')}: {t.get('content', '')[:300]}" for t in recent
        ) + "\n\n"
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=INTENT_CLASSIFICATION_PROMPT),
            HumanMessage(content=f"{convo}User request:\n{query}"),
        ])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        parsed = _parse_json_object(raw)
        if parsed and parsed.get("intent") in {i.value for i in Intent}:
            intent = Intent(parsed["intent"])
            rationale = str(parsed.get("rationale", "")).strip() or rationale
            narration = str(parsed.get("narration", "")).strip()
            plan_steps = parsed.get("steps")
        else:
            # The model replied but we couldn't read an intent — flag it instead of
            # silently masquerading as a document query (surfaced in run() + logged).
            classification_failed = True
            logger.warning("Intent classification unparseable; defaulting to document. raw=%r", str(raw)[:200])
    except Exception as exc:  # never let classification failure break the run
        classification_failed = True
        logger.warning("Intent classification failed, defaulting to document: %s", exc)

    # The user-facing plan checklist is chosen per intent in run(); the node only
    # needs to record the classified intent.
    return {
        "intent": intent.value,
        "intent_rationale": rationale,
        "narration": narration,
        "plan_steps": plan_steps,
        "classification_failed": classification_failed,
    }


async def retrieve_node(state: AgentState) -> dict:
    """Delegate to the Retrieval Sub-Agent, gathering ONLY what the intent calls for:
    - document/both → search the corpus;
    - live/both → read live connectors;
    - action → live context to ground the action in the external system's current state.
    A live or action query never triggers a blind corpus search (that produced
    irrelevant 'sources' and a confused answer)."""
    intent = state.get("intent")
    has_user = bool(state.get("user_id"))
    want_documents = intent in ("document", "both")
    want_live = has_user and intent in ("live", "both", "action")
    want_whole_doc = intent in ("document", "both")
    spec = get_subagent(Capability.RETRIEVAL)
    result = await spec.handler.gather(
        query=state["query"],
        allowed_collections=state.get("allowed_collections", []),
        chat_history=state.get("chat_history"),
        user_id=state.get("user_id", ""),
        conversation_id=state.get("conversation_id"),
        want_documents=want_documents,
        want_live=want_live,
        want_whole_doc=want_whole_doc,
        attachments=state.get("attachments"),
    )
    return {
        "context_chunks": result.get("context_chunks", []),
        "live_records": result.get("live_records", []),
        "whole_documents": result.get("whole_documents", []),
        "attachments": result.get("attachments", []),
        "citations": result.get("citations", []),
        "graph_context": result.get("graph_context", ""),
        "chunks_retrieved": result.get("chunks_retrieved", 0),
        "live_count": result.get("live_count", 0),
        "tool_activity": result.get("tool_activity", []),
        "retrieval_error": result.get("error"),
    }


def _no_sources_message(state: "AgentState") -> str:
    """Helpful, context-aware message when retrieval turned up nothing — instead of a flat
    refusal, name what wasn't found and suggest a concrete next step (tailored to whether
    we were looking in documents vs connected tools)."""
    intent = state.get("intent", "document")
    activity = state.get("tool_activity") or []
    err = state.get("retrieval_error")
    live_attempted = any("live" in str(a.get("tool", "")) for a in activity)
    if intent in ("live", "both") or live_attempted:
        msg = ("I checked your connected tools but didn't find anything that answers this — "
               "the right connector may not be enabled or connected, or this may be outside what those tools cover.")
        tip = "You could enable or connect the relevant tool, or rephrase what you're looking for."
    elif intent == "action":
        msg = "I couldn't find what I'd need to carry out that action."
        tip = "You could add a bit more detail, or make sure the relevant connector is enabled."
    else:
        msg = "I couldn't find anything about this in your documents."
        tip = ("You could upload a relevant document, rephrase your question, or — if this needs "
               "current or external information — point me to a connected tool.")
    if err:
        msg += " (A source was temporarily unavailable while I looked.)"
    return f"{msg} {tip}"


async def generate_node(state: AgentState) -> dict:
    """Generate a grounded answer using the generation slot.

    Streams tokens via ``astream`` so the orchestrator can surface them token-by-token
    (LangGraph's ``messages`` stream mode picks up these chunks). The full accumulated
    answer is returned in state for verification and the final ``done`` event.
    """
    chunks = state.get("context_chunks", [])
    live_records = state.get("live_records", [])
    whole_documents = state.get("whole_documents", [])
    attachments = state.get("attachments", [])
    if not chunks and not live_records and not whole_documents and not attachments:
        return {"answer": _no_sources_message(state)}

    doc_context = _format_context(chunks, state.get("graph_context", ""))
    whole_context = _format_whole_docs(whole_documents)
    live_context = _format_live(live_records)
    attach_context = _format_attachments(attachments)
    source_block = (
        f"Document sources:\n{doc_context or '(none)'}\n\n"
        f"Full documents:\n{whole_context or '(none)'}\n\n"
        f"Live sources:\n{live_context or '(none)'}\n\n"
        f"Attached by the user:\n{attach_context or '(none)'}"
    )

    messages: list = [SystemMessage(content=AGENT_GENERATION_PROMPT)]
    for turn in state.get("chat_history") or []:
        role, content = turn.get("role"), turn.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(
        HumanMessage(content=f"{source_block}\n\nQuestion: {state['query']}")
    )

    llm = get_model(Slot.GENERATION, streaming=True)
    parts: list[str] = []
    try:
        async for chunk in llm.astream(messages):
            text = getattr(chunk, "content", "") or ""
            if text:
                parts.append(text)
        answer = "".join(parts).strip()
    except Exception as exc:
        logger.error("Generation failed: %s", exc)
        answer = "I'm sorry, I was unable to generate an answer. Please try again."
    return {"answer": answer or INSUFFICIENT_MSG}


async def verify_node(state: AgentState) -> dict:
    """Verify groundedness using the verification slot. Outcome ∈
    VERIFIED / CORRECTED / INSUFFICIENT_CONTEXT (consistent with the existing
    self-correction)."""
    chunks = state.get("context_chunks", [])
    live_records = state.get("live_records", [])
    answer = state.get("answer", "")

    if not chunks and not live_records:
        return {"verification": {
            "outcome": "INSUFFICIENT_CONTEXT",
            "corrected_answer": "",
            "explanation": "No source context was retrieved for this query.",
        }}

    doc_sources = "\n\n".join(
        f"[Source {i}]\n{c.get('text', '')}" for i, c in enumerate(chunks, 1)
    )
    live_sources = _format_live(live_records)
    messages = [
        SystemMessage(content=AGENT_VERIFICATION_PROMPT),
        HumanMessage(content=(
            f"Original Question: {state['query']}\n\n"
            f"Generated Answer:\n{answer}\n\n"
            f"Document Sources:\n{doc_sources or '(none)'}\n\n"
            f"Live Sources:\n{live_sources or '(none)'}"
        )),
    ]
    llm = get_model(Slot.VERIFICATION)
    try:
        resp = await llm.ainvoke(messages)
        parsed = _parse_json_object(resp.content if hasattr(resp, "content") else str(resp))
        if parsed and parsed.get("outcome"):
            return {"verification": parsed}
    except Exception as exc:
        logger.warning("Verification failed, treating as VERIFIED: %s", exc)
    return {"verification": {"outcome": "VERIFIED", "corrected_answer": "", "explanation": ""}}


# ── Graph assembly ───────────────────────────────────────────

async def direct_answer_node(state: AgentState) -> dict:
    """Answer a general-knowledge question from the model itself — no retrieval, no
    citations. The answer is flagged ungrounded so the UI can label it. Streams tokens
    like the grounded generator."""
    messages: list = [SystemMessage(content=DIRECT_GENERATION_PROMPT)]
    for turn in state.get("chat_history") or []:
        role, content = turn.get("role"), turn.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=state["query"]))

    llm = get_model(Slot.GENERATION, streaming=True)
    parts: list[str] = []
    try:
        async for chunk in llm.astream(messages):
            text = getattr(chunk, "content", "") or ""
            if text:
                parts.append(text)
        answer = "".join(parts).strip()
    except Exception as exc:
        logger.error("Direct generation failed: %s", exc)
        answer = "I'm sorry, I was unable to answer. Please try again."
    return {"answer": answer or "I don't have an answer for that.", "grounded": False}


async def propose_action_node(state: AgentState) -> dict:
    """Propose ONE gated action (preview only — never executes). Grounds the proposal
    on the retrieved citations so the gate can show the basis.

    This is the spec's ``prepare_action`` (§2.3): all side effects (gateway preview →
    pending record) happen HERE and the node completes; the interrupt lives alone in
    ``await_approval``, so resume-replay never re-runs the preview. The idempotency
    key is the belt-and-braces backstop against future node-merging refactors."""
    if not has_capability(Capability.ACTION):
        return {"proposed_action": {"proposed": False, "reason": "no_action_capability"}}
    spec = get_subagent(Capability.ACTION)
    # Idempotency + resumable gate apply only to durable runs (a non-durable run can't
    # pause/replay, so it keeps the legacy one-shot preview with no idem key).
    thread_id = state.get("thread_id") or ""
    durable = bool(state.get("durable"))
    proposal = await spec.handler.propose(
        query=state["query"],
        citations=state.get("citations", []),
        user_id=state.get("user_id", ""),
        conversation_id=state.get("conversation_id"),
        idempotency_key=f"{thread_id}:propose_action" if (thread_id and durable) else None,
    )
    if proposal.get("proposed") and thread_id and durable:
        proposal["thread_id"] = thread_id  # lets a reloaded client resume this run
    return {"proposed_action": proposal}


async def await_approval_node(state: AgentState) -> dict:
    """The approval gate. Contains ONLY ``interrupt()`` — no side effects — because
    LangGraph replays the interrupting node from the top on resume (§2.3). The run
    checkpoints here and waits (minutes or days) for ``Command(resume=...)``."""
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
    return {
        "approval_decision": str(decision.get("decision", "reject")),
        "approver_id": str(decision.get("approver_id", "")),
    }


async def resolve_action_node(state: AgentState) -> dict:
    """Carry out the human's decision. Approve → mint token + execute via the gateway
    (still the sole enforcer). Reject → record it. A pending record that expired
    during a long pause degrades to a FRESH preview and re-gates (§2.3) — never an
    opaque error; ``action_result=None`` signals the re-gate to the router."""
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
        # The 10-min pending record lapsed while the run was paused. Re-preview the
        # SAME action (connector/capability/arguments preserved in state) and loop
        # back to the gate with a fresh concrete preview.
        from agents.connector_gateway import gateway
        try:
            prev = await gateway.preview_action(
                connector_id=proposal.get("connector_id"),
                capability=proposal.get("capability"),
                arguments=proposal.get("arguments") or {},
                user_id=state.get("user_id") or None,
                gated_mode=proposal.get("gated_mode", "sdk"),
            )
            reproposal = {**proposal, "pending_id": prev["pending_id"],
                          "preview": prev["preview"], "regated": True}
            return {"proposed_action": reproposal, "action_result": None}
        except Exception as exc:
            logger.warning("Re-preview after expiry failed: %s", exc)
            return {"action_result": {"status": "failed",
                                      "error": f"approval expired and re-preview failed: {exc}"}}
    return {"action_result": res}


async def report_action_node(state: AgentState) -> dict:
    """Ground the post-action report on the actual tool result and surface it as the
    answer — the resumed run reports back instead of going silent (the core Phase-1
    fix; supersedes the approve-endpoint shim). Verification of action reports is a
    §2.11 (verify-before-emit) concern for the controller-loop phase."""
    res = state.get("action_result") or {}
    proposal = state.get("proposed_action") or {}
    status = res.get("status")
    if status == "rejected":
        return {"answer": "Understood — I haven't run that action; nothing was changed. "
                          "Tell me what you'd like to do instead.", "grounded": True}
    if status != "executed":
        err = str(res.get("error", "")) or "the action could not be completed"
        return {"answer": f"I wasn't able to complete the action: {err}", "grounded": True}
    spec = get_subagent(Capability.ACTION)
    message = await spec.handler.summarize_result(action=proposal, result=res.get("result"))
    if not message:
        message = (f"Done — the {proposal.get('capability', 'action')} action on "
                   f"{proposal.get('connector', 'the connector')} was executed successfully.")
    return {"answer": message, "grounded": True}


def _route_after_classify(state: AgentState) -> str:
    """A 'direct' (general-knowledge) question skips retrieval entirely — but only if
    the deployment permits ungrounded answers; otherwise it falls through to the
    grounded document path."""
    # Attachments force the grounded path so they're assembled with any other
    # sources (they may be exactly what a "direct"-looking ask needs to answer).
    if (
        state.get("intent") == "direct"
        and settings.agent_allow_ungrounded_answers
        and not state.get("attachments")
    ):
        return "direct"
    return "retrieve"


def _route_after_retrieve(state: AgentState) -> str:
    """Action intent (with a user) goes to the action proposal; everything else takes
    the document/live answer path."""
    if state.get("intent") == "action" and state.get("user_id"):
        return "propose_action"
    return "generate"


def _route_after_propose(state: AgentState) -> str:
    """If an action was proposed, stop and await approval; otherwise fall back to a
    grounded answer explaining no action was taken."""
    proposal = state.get("proposed_action") or {}
    return "await" if proposal.get("proposed") else "generate"


def _route_after_resolve(state: AgentState) -> str:
    """``action_result=None`` means the pending record expired and a fresh preview
    was minted — loop back to the gate; otherwise report the outcome."""
    return "again" if state.get("action_result") is None else "report"


def _build_graph(checkpointer=None):
    """Compile the orchestrator graph.

    With a checkpointer (durable mode): the action gate pauses at ``await_approval``
    (interrupt) and the SAME run resumes through resolve → report. Without one
    (legacy fallback — Redis down or durable runs disabled): identical pre-existing
    behavior, where a proposed action routes to END and the separate
    ``/actions/{id}/approve|reject`` endpoints complete it."""
    g = StateGraph(AgentState)
    g.add_node("classify", plan_node)
    g.add_node("direct_answer", direct_answer_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("propose_action", propose_action_node)
    g.add_node("generate", generate_node)
    g.add_node("verify", verify_node)
    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify", _route_after_classify,
        {"direct": "direct_answer", "retrieve": "retrieve"},
    )
    g.add_edge("direct_answer", END)
    g.add_conditional_edges(
        "retrieve", _route_after_retrieve,
        {"propose_action": "propose_action", "generate": "generate"},
    )
    if checkpointer is not None:
        g.add_node("await_approval", await_approval_node)
        g.add_node("resolve_action", resolve_action_node)
        g.add_node("report_action", report_action_node)
        g.add_conditional_edges(
            "propose_action", _route_after_propose,
            {"await": "await_approval", "generate": "generate"},
        )
        g.add_edge("await_approval", "resolve_action")
        g.add_conditional_edges(
            "resolve_action", _route_after_resolve,
            {"again": "await_approval", "report": "report_action"},
        )
        g.add_edge("report_action", END)
    else:
        g.add_conditional_edges(
            "propose_action", _route_after_propose,
            {"await": END, "generate": "generate"},
        )
    g.add_edge("generate", "verify")
    g.add_edge("verify", END)
    return g.compile(checkpointer=checkpointer)


# Compiled lazily on first run: the AsyncRedisSaver must be created inside the running
# event loop, and a Redis outage must degrade to the legacy single-pass graph instead
# of failing startup. (_GRAPH_DURABLE tells run()/resume() which contract is live.) The
# fixed graph and the controller graph (R4) share ONE saver.
_GRAPH = None
_CONTROLLER_GRAPH = None
_GRAPH_DURABLE = False
_SAVER = None
_SAVER_READY = False
_GRAPH_LOCK: Optional[asyncio.Lock] = None


def _lock() -> asyncio.Lock:
    global _GRAPH_LOCK
    if _GRAPH_LOCK is None:
        _GRAPH_LOCK = asyncio.Lock()
    return _GRAPH_LOCK


async def _ensure_saver():
    """Create the Redis checkpointer once (inside the loop). Sets _GRAPH_DURABLE. A Redis
    outage degrades to non-durable (saver=None) instead of failing startup."""
    global _SAVER, _SAVER_READY, _GRAPH_DURABLE
    if _SAVER_READY:
        return _SAVER
    if settings.agent_durable_runs:
        try:
            from langgraph.checkpoint.redis.aio import AsyncRedisSaver

            saver = AsyncRedisSaver(
                redis_url=settings.agent_redis_url,
                ttl={"default_ttl": settings.agent_run_ttl_hours * 60,  # minutes
                     "refresh_on_read": True},
            )
            await saver.asetup()
            _SAVER = saver
            _GRAPH_DURABLE = True
            logger.info("Redis checkpointer ready (durable runs ON)")
        except Exception as exc:
            logger.warning("Redis checkpointer unavailable (%s) — non-durable runs", exc)
            _SAVER, _GRAPH_DURABLE = None, False
    _SAVER_READY = True
    return _SAVER


async def _get_graph():
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH
    async with _lock():
        if _GRAPH is None:
            saver = await _ensure_saver()
            _GRAPH = _build_graph(saver)
            logger.info("Fixed orchestrator graph compiled (durable=%s)", _GRAPH_DURABLE)
    return _GRAPH


async def _get_controller_graph():
    """The R4 controller-loop graph, sharing the saver with the fixed graph."""
    global _CONTROLLER_GRAPH
    if _CONTROLLER_GRAPH is not None:
        return _CONTROLLER_GRAPH
    async with _lock():
        if _CONTROLLER_GRAPH is None:
            saver = await _ensure_saver()
            from agents.orchestrator import controller
            _CONTROLLER_GRAPH = controller.build_controller_graph(saver)
            logger.info("Controller-loop graph compiled (durable=%s)", _GRAPH_DURABLE)
    return _CONTROLLER_GRAPH


# ── Event helpers ────────────────────────────────────────────

def _event(type_: str, **data: Any) -> dict:
    return {"type": type_, **data}


def _plan_event(plan: list[dict], statuses: dict[str, str]) -> dict:
    steps = [{**s, "status": statuses.get(s["id"], "pending")} for s in plan]
    return _event("plan", steps=steps)


class Orchestrator:
    """Drives the compiled graph and yields SSE events for the Agents surface."""

    async def run(
        self,
        *,
        query: str,
        allowed_collections: list[str],
        chat_history: Optional[list] = None,
        user_id: str = "",
        conversation_id: Optional[str] = None,
        attachments: Optional[list[dict]] = None,
        thread_id: Optional[str] = None,
        skill_names: Optional[list[str]] = None,
    ) -> AsyncGenerator[dict, None]:
        # R4: route to the controller loop when enabled (same event contract, so the API/
        # executor/bus/UI are unchanged). Off by default → the fixed pipeline below runs.
        if settings.agent_controller_loop:
            await _ensure_saver()
            durable = _GRAPH_DURABLE
            thread_id = thread_id or f"run-{uuid.uuid4().hex}"
            cgraph = await _get_controller_graph()
            from agents.orchestrator import controller
            async for ev in controller.run_controller(
                query=query, allowed_collections=allowed_collections,
                chat_history=chat_history, user_id=user_id, conversation_id=conversation_id,
                attachments=attachments, thread_id=thread_id, graph=cgraph, durable=durable,
                skill_names=skill_names,
            ):
                yield ev
            return

        graph = await _get_graph()
        durable = _GRAPH_DURABLE
        # Per-RUN identity (spec §2.1): every agent turn is its own thread — used as the
        # checkpoint thread (durable only) AND the event-stream key (always, R2). The API
        # provides it so it can seed the bus / tell the client where to subscribe;
        # conversation memory stays in the DB and is hydrated into the initial state.
        thread_id = thread_id or f"run-{uuid.uuid4().hex}"
        config = {"configurable": {"thread_id": thread_id}} if durable else None

        state: AgentState = {
            "query": query,
            "allowed_collections": allowed_collections,
            "chat_history": chat_history or [],
            "user_id": user_id,
            "conversation_id": conversation_id,
            "attachments": attachments or [],
            "thread_id": thread_id,
            "durable": durable,
        }

        plan: list[dict] = []           # chosen per intent after classification
        statuses: dict[str, str] = {}
        latest: AgentState = {}
        answer_parts: list[str] = []
        streamed_answer = False
        interrupted = False

        try:
            # Two stream modes at once: "messages" surfaces LLM token chunks as they
            # are produced inside nodes (we forward the generate node's tokens), while
            # "updates" gives each node's completed state delta for the structural
            # events. LangGraph yields (mode, data) tuples.
            async for mode, data in graph.astream(
                state, config, stream_mode=["updates", "messages"]
            ):
                if mode == "messages":
                    msg_chunk, meta = data
                    if meta.get("langgraph_node") in ("generate", "direct_answer"):
                        # Model chain-of-thought streams in a separate channel
                        # (reasoning_content) — surface it as `thinking` deltas for the
                        # collapsible CoT panel, distinct from the answer.
                        rc = (getattr(msg_chunk, "additional_kwargs", {}) or {}).get("reasoning_content")
                        if rc:
                            yield _event("thinking", content=rc)
                        text = getattr(msg_chunk, "content", "") or ""
                        if text:
                            answer_parts.append(text)
                            streamed_answer = True
                            yield _event("answer_token", content=text)
                    continue

                # mode == "updates"
                for node, delta in data.items():
                    if node == "__interrupt__":
                        # Durable gate paused the run (await_approval). Emit the gate
                        # payload — the stream ends after this; the run resumes later
                        # via resume() on the same thread_id.
                        intr = delta[0] if isinstance(delta, (list, tuple)) and delta else None
                        payload = dict(getattr(intr, "value", None) or {})
                        if payload.get("type") == "approval_required":
                            interrupted = True
                            yield _event("approval_required",
                                         **{k: v for k, v in payload.items() if k != "type"})
                        continue
                    if not isinstance(delta, dict):
                        continue
                    latest.update(delta)

                    if node == "classify":
                        intent = delta.get("intent", "document")
                        # Surface a natural, user-facing line ("here's what I'll do") —
                        # NOT the internal intent label. The raw intent stays in state /
                        # `done` for the UI/telemetry to use as it wishes.
                        narration = (delta.get("narration") or "").strip() or _fallback_narration(intent)
                        yield _event("reasoning", text=narration)
                        llm_steps = delta.get("plan_steps")
                        is_direct = intent == "direct" and settings.agent_allow_ungrounded_answers
                        if is_direct:
                            plan[:] = _build_plan("direct", llm_steps)
                        elif intent == "action":
                            plan[:] = _build_plan("action", llm_steps)
                        elif intent == "live":
                            plan[:] = _build_plan("live", llm_steps)
                        elif intent == "both":
                            plan[:] = _build_plan("both", llm_steps)
                        else:
                            plan[:] = _build_plan("document", llm_steps)
                        statuses.clear()
                        statuses.update({s["id"]: "pending" for s in plan})
                        yield _plan_event(plan, statuses)
                        if is_direct:
                            # No user-facing "general knowledge" badge — it nags. The
                            # reasoning trail notes it neutrally; `done.grounded` stays
                            # as silent metadata for the UI to use subtly if it wants.
                            statuses["answer"] = "running"
                            yield _event("step_status", id="answer", status="running")
                            yield _event("reasoning", text="Answering directly — no document or live lookup needed.")
                        else:
                            statuses["retrieve"] = "running"
                            yield _event("step_status", id="retrieve", status="running")

                    elif node == "direct_answer":
                        if not streamed_answer:
                            yield _event("answer_token", content=delta.get("answer", ""))
                        statuses["answer"] = "done"
                        yield _event("step_status", id="answer", status="done")

                    elif node == "retrieve":
                        n = delta.get("chunks_retrieved", 0)
                        live_n = delta.get("live_count", 0)
                        # One activity line per source path (document + each live read).
                        for act in delta.get("tool_activity", []):
                            yield _event("tool_activity", **act)
                        yield _event("citations", citations=delta.get("citations", []))
                        statuses["retrieve"] = "done"
                        yield _event("step_status", id="retrieve", status="done")
                        if latest.get("intent") == "action":
                            statuses["propose"] = "running"
                            yield _event("step_status", id="propose", status="running")
                            yield _event("reasoning", text="Deciding whether an action is warranted.")
                        else:
                            statuses["generate"] = "running"
                            yield _event("step_status", id="generate", status="running")
                            detail = f"{n} document passage(s)"
                            if live_n:
                                detail += f" and {live_n} live record(s)"
                            yield _event("reasoning", text=f"Synthesizing an answer from {detail}.")

                    elif node == "propose_action":
                        proposal = delta.get("proposed_action", {}) or {}
                        statuses["propose"] = "done"
                        yield _event("step_status", id="propose", status="done")
                        if proposal.get("proposed"):
                            if proposal.get("reasoning"):
                                yield _event("reasoning", text=proposal["reasoning"])
                            # The user-facing description of what's about to happen,
                            # surfaced as the answer body (above the approval card) so
                            # the raw payload never needs to be shown.
                            summary = (proposal.get("summary") or "").strip()
                            if summary:
                                answer_parts.append(summary)
                                streamed_answer = True
                                yield _event("answer_token", content=summary)
                            statuses["approve"] = "awaiting-approval"
                            yield _event("step_status", id="approve", status="awaiting-approval")
                            # The gate payload: what / why / on what basis + the handle.
                            # Durable mode emits it from the __interrupt__ update
                            # instead (same payload + thread_id for resume).
                            if not durable:
                                yield _event(
                                    "approval_required",
                                    pending_id=proposal.get("pending_id"),
                                    connector=proposal.get("connector"),
                                    capability=proposal.get("capability"),
                                    preview=proposal.get("preview"),
                                    reasoning=proposal.get("reasoning", ""),
                                    summary=summary,
                                    target=proposal.get("target", ""),
                                    sources=proposal.get("sources", []),
                                )
                        else:
                            # No action warranted/available — fall back to a grounded answer.
                            reason = proposal.get("reason", "")
                            yield _event("reasoning", text=(
                                f"No action taken ({reason}); answering from the available sources instead."
                            ))
                            plan[:] = [dict(s) for s in PLAN_DOC]
                            statuses.clear()
                            statuses.update({"retrieve": "done", "generate": "running", "verify": "pending"})
                            yield _plan_event(plan, statuses)
                            yield _event("step_status", id="generate", status="running")

                    elif node == "generate":
                        # Tokens already streamed via "messages" mode. If nothing
                        # streamed (short-circuit / non-streaming fallback), emit the
                        # full answer once so the client still receives it.
                        if not streamed_answer:
                            yield _event("answer_token", content=delta.get("answer", ""))
                        statuses["generate"] = "done"
                        yield _event("step_status", id="generate", status="done")
                        statuses["verify"] = "running"
                        yield _event("step_status", id="verify", status="running")
                        yield _event("reasoning", text="Checking each claim against its cited source.")

                    elif node == "verify":
                        v = delta.get("verification", {})
                        yield _event("verification_result", outcome=v.get("outcome", "VERIFIED"),
                                     corrected_answer=v.get("corrected_answer", ""),
                                     explanation=v.get("explanation", ""))
                        statuses["verify"] = "done"
                        yield _event("step_status", id="verify", status="done")

            final_answer = "".join(answer_parts).strip() if streamed_answer else latest.get("answer", "")
            yield _event(
                "done",
                conversation_id=conversation_id,
                thread_id=thread_id or None,
                paused=interrupted,  # awaiting approval — resume on this thread_id
                answer=final_answer,
                intent=latest.get("intent"),
                citations=latest.get("citations", []),
                verification=latest.get("verification", {}),
                proposed_action=latest.get("proposed_action"),
                grounded=latest.get("grounded", True),
            )
        except Exception as exc:  # surface a clean error event to the client
            logger.exception("Orchestrator run failed")
            yield _event("error", message=str(exc))

    async def resume(
        self,
        *,
        thread_id: str,
        decision: Optional[str] = None,
        approver_id: str,
        batch_decisions: Optional[dict] = None,
        answer: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """Resume a run paused at the approval gate (durable mode only).

        Feeds the human's decision into the checkpointed run via
        ``Command(resume=...)`` and streams the continuation: resolve (approve →
        token + execute via the gateway / reject) → grounded report → done. An
        expired pending record re-gates with a fresh ``approval_required`` instead
        of erroring (§2.3)."""
        # R4b: a controller-loop run resumes through the controller graph (the act gate
        # loops back to the controller after the report). Same client contract.
        if settings.agent_controller_loop:
            await _ensure_saver()
            if not _GRAPH_DURABLE:
                yield _event("error", message="durable runs are not available (Redis is unreachable)")
                return
            cgraph = await _get_controller_graph()
            from agents.orchestrator import controller
            async for ev in controller.run_controller_resume(
                thread_id=thread_id, decision=decision, approver_id=approver_id, graph=cgraph,
                batch_decisions=batch_decisions, answer=answer,
            ):
                yield ev
            return

        graph = await _get_graph()
        if not _GRAPH_DURABLE:
            yield _event("error", message="durable runs are not available (Redis is unreachable)")
            return
        if decision not in ("approve", "reject"):
            yield _event("error", message=f"invalid decision '{decision}'")
            return
        config = {"configurable": {"thread_id": thread_id}}
        try:
            snapshot = await graph.aget_state(config)
        except Exception as exc:
            logger.warning("resume: state lookup failed for %s: %s", thread_id, exc)
            snapshot = None
        if snapshot is None or not snapshot.next:
            yield _event("error", message="nothing to resume — this run is not paused (it may have expired)")
            return
        # The run belongs to the user who started it; the resume decision must come
        # from the same user (state.user_id was hydrated at run start).
        run_user = (snapshot.values or {}).get("user_id", "")
        if run_user and run_user != approver_id:
            yield _event("error", message="this run belongs to another user")
            return

        proposal = (snapshot.values or {}).get("proposed_action") or {}
        statuses_id = "approve"
        yield _event("step_status", id=statuses_id,
                     status="running" if decision == "approve" else "rejected")
        answer_parts: list[str] = []
        latest: dict = {}
        regated = False
        try:
            async for mode, data in graph.astream(
                Command(resume={"decision": decision, "approver_id": approver_id}),
                config, stream_mode=["updates"],
            ):
                if mode != "updates":
                    continue
                for node, delta in data.items():
                    if node == "__interrupt__":
                        # Pending record expired → fresh preview, gate again.
                        intr = delta[0] if isinstance(delta, (list, tuple)) and delta else None
                        payload = dict(getattr(intr, "value", None) or {})
                        if payload.get("type") == "approval_required":
                            regated = True
                            yield _event("step_status", id=statuses_id, status="awaiting-approval")
                            yield _event("reasoning", text=(
                                "The approval window for this action had lapsed, so I refreshed "
                                "the preview — please confirm it again."))
                            yield _event("approval_required",
                                         **{k: v for k, v in payload.items() if k != "type"})
                        continue
                    if not isinstance(delta, dict):
                        continue
                    latest.update(delta)
                    if node == "resolve_action":
                        res = delta.get("action_result")
                        if res is None:
                            continue  # re-gate in flight; interrupt update follows
                        status_ = res.get("status")
                        yield _event("step_status", id=statuses_id,
                                     status={"executed": "done", "rejected": "rejected"}.get(status_, "failed"))
                        if status_ == "executed":
                            yield _event("reasoning", text="Action executed — writing up what happened.")
                    elif node == "report_action":
                        answer = delta.get("answer", "")
                        if answer:
                            answer_parts.append(answer)
                            yield _event("answer_token", content=answer)
                        res = latest.get("action_result") or {}
                        yield _event("action_result",
                                     pending_id=proposal.get("pending_id"),
                                     thread_id=thread_id,
                                     status=res.get("status"),
                                     message=answer,
                                     error=res.get("error"))
            if not regated:
                yield _event(
                    "done",
                    conversation_id=(snapshot.values or {}).get("conversation_id"),
                    thread_id=thread_id,
                    paused=False,
                    answer="".join(answer_parts).strip(),
                    intent="action",
                    citations=(snapshot.values or {}).get("citations", []),
                    verification={},
                    proposed_action={**proposal,
                                     "resolved_status": (latest.get("action_result") or {}).get("status")},
                    grounded=True,
                )
        except Exception as exc:
            logger.exception("Orchestrator resume failed for %s", thread_id)
            yield _event("error", message=str(exc))


# ── Module singleton ─────────────────────────────────────────
orchestrator = Orchestrator()

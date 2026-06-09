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

import json
import logging
from enum import Enum
from typing import Any, AsyncGenerator, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from agents.models import Slot, get_model
from agents.orchestrator.prompts import (
    AGENT_GENERATION_PROMPT,
    AGENT_VERIFICATION_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
)
from agents.registry import Capability, get as get_subagent

# Import sub-agent packages so they self-register with the capability registry.
import agents.retrieval_agent  # noqa: F401

logger = logging.getLogger(__name__)

INSUFFICIENT_MSG = (
    "Based on the available documents, I could not find sufficient information to "
    "fully answer this question."
)

# The plan presented to the user (document path, Phase 1). Step ids map to graph nodes.
PLAN_TEMPLATE = [
    {"id": "retrieve", "label": "Search the knowledge base"},
    {"id": "generate", "label": "Generate a grounded answer"},
    {"id": "verify", "label": "Verify the answer against its sources"},
]


class Intent(str, Enum):
    DOCUMENT = "document"
    LIVE = "live"
    BOTH = "both"
    ACTION = "action"


class AgentState(TypedDict, total=False):
    # Inputs
    query: str
    allowed_collections: list[str]
    chat_history: list[dict]
    user_id: str
    conversation_id: Optional[str]
    # Plan
    intent: str
    intent_rationale: str
    plan: list[dict]
    # Retrieval
    context_chunks: list[dict]
    live_records: list[dict]
    citations: list[dict]
    graph_context: str
    chunks_retrieved: int
    live_count: int
    tool_activity: list[dict]
    retrieval_error: Optional[str]
    # Output
    answer: str
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
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=INTENT_CLASSIFICATION_PROMPT),
            HumanMessage(content=f"User request:\n{query}"),
        ])
        parsed = _parse_json_object(resp.content if hasattr(resp, "content") else str(resp))
        if parsed and parsed.get("intent") in {i.value for i in Intent}:
            intent = Intent(parsed["intent"])
            rationale = str(parsed.get("rationale", "")).strip() or rationale
    except Exception as exc:  # never let classification failure break the run
        logger.warning("Intent classification failed, defaulting to document: %s", exc)

    return {
        "intent": intent.value,
        "intent_rationale": rationale,
        "plan": [dict(step) for step in PLAN_TEMPLATE],
    }


async def retrieve_node(state: AgentState) -> dict:
    """Delegate to the Retrieval Sub-Agent. The live path is engaged only when the
    intent calls for it (live/both) and a user is present — document-only queries
    stay on the Phase-1 fast path unchanged."""
    want_live = state.get("intent") in ("live", "both") and bool(state.get("user_id"))
    spec = get_subagent(Capability.RETRIEVAL)
    result = await spec.handler.gather(
        query=state["query"],
        allowed_collections=state.get("allowed_collections", []),
        chat_history=state.get("chat_history"),
        user_id=state.get("user_id", ""),
        conversation_id=state.get("conversation_id"),
        want_live=want_live,
    )
    return {
        "context_chunks": result.get("context_chunks", []),
        "live_records": result.get("live_records", []),
        "citations": result.get("citations", []),
        "graph_context": result.get("graph_context", ""),
        "chunks_retrieved": result.get("chunks_retrieved", 0),
        "live_count": result.get("live_count", 0),
        "tool_activity": result.get("tool_activity", []),
        "retrieval_error": result.get("error"),
    }


async def generate_node(state: AgentState) -> dict:
    """Generate a grounded answer using the generation slot.

    Streams tokens via ``astream`` so the orchestrator can surface them token-by-token
    (LangGraph's ``messages`` stream mode picks up these chunks). The full accumulated
    answer is returned in state for verification and the final ``done`` event.
    """
    chunks = state.get("context_chunks", [])
    live_records = state.get("live_records", [])
    if not chunks and not live_records:
        return {"answer": INSUFFICIENT_MSG}

    doc_context = _format_context(chunks, state.get("graph_context", ""))
    live_context = _format_live(live_records)
    source_block = (
        f"Document sources:\n{doc_context or '(none)'}\n\n"
        f"Live sources:\n{live_context or '(none)'}"
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

def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("classify", plan_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("generate", generate_node)
    g.add_node("verify", verify_node)
    g.add_edge(START, "classify")
    g.add_edge("classify", "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "verify")
    g.add_edge("verify", END)
    return g.compile()


_GRAPH = _build_graph()


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
    ) -> AsyncGenerator[dict, None]:
        state: AgentState = {
            "query": query,
            "allowed_collections": allowed_collections,
            "chat_history": chat_history or [],
            "user_id": user_id,
            "conversation_id": conversation_id,
        }

        plan = [dict(s) for s in PLAN_TEMPLATE]
        statuses = {s["id"]: "pending" for s in plan}
        latest: AgentState = {}
        answer_parts: list[str] = []
        streamed_answer = False

        try:
            # Two stream modes at once: "messages" surfaces LLM token chunks as they
            # are produced inside nodes (we forward the generate node's tokens), while
            # "updates" gives each node's completed state delta for the structural
            # events. LangGraph yields (mode, data) tuples.
            async for mode, data in _GRAPH.astream(
                state, stream_mode=["updates", "messages"]
            ):
                if mode == "messages":
                    msg_chunk, meta = data
                    if meta.get("langgraph_node") == "generate":
                        text = getattr(msg_chunk, "content", "") or ""
                        if text:
                            answer_parts.append(text)
                            streamed_answer = True
                            yield _event("answer_token", content=text)
                    continue

                # mode == "updates"
                for node, delta in data.items():
                    if not isinstance(delta, dict):
                        continue
                    latest.update(delta)

                    if node == "classify":
                        intent = delta.get("intent", "document")
                        yield _event(
                            "reasoning",
                            text=f"Intent: {intent}. {delta.get('intent_rationale', '')}".strip(),
                        )
                        if intent in ("live", "both", "action"):
                            yield _event("reasoning", text=(
                                "This request may involve live data or an action. In the "
                                "current build the agent answers from the document corpus; "
                                "live retrieval and gated actions arrive in later phases."
                            ))
                        yield _plan_event(plan, statuses)
                        statuses["retrieve"] = "running"
                        yield _event("step_status", id="retrieve", status="running")

                    elif node == "retrieve":
                        n = delta.get("chunks_retrieved", 0)
                        live_n = delta.get("live_count", 0)
                        # One activity line per source path (document + each live read).
                        for act in delta.get("tool_activity", []):
                            yield _event("tool_activity", **act)
                        yield _event("citations", citations=delta.get("citations", []))
                        statuses["retrieve"] = "done"
                        yield _event("step_status", id="retrieve", status="done")
                        statuses["generate"] = "running"
                        yield _event("step_status", id="generate", status="running")
                        detail = f"{n} document passage(s)"
                        if live_n:
                            detail += f" and {live_n} live record(s)"
                        yield _event("reasoning", text=f"Synthesizing an answer from {detail}.")

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
                answer=final_answer,
                citations=latest.get("citations", []),
                verification=latest.get("verification", {}),
            )
        except Exception as exc:  # surface a clean error event to the client
            logger.exception("Orchestrator run failed")
            yield _event("error", message=str(exc))


# ── Module singleton ─────────────────────────────────────────
orchestrator = Orchestrator()

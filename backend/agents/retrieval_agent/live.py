"""
Deep Query — Live Retrieval (the connector path)

The Retrieval Sub-Agent's live half. Never speaks MCP directly — everything goes
through the Connector Gateway, which enforces governance, credentials, deployment
mode, caching, and audit (handoff §2).

Flow for a query:
  1. Enumerate the connectors the user has *enabled* (Tier-2 governance).
  2. Discover each one's read-only tools → a catalog.
  3. Ask the orchestration model which tool(s) to call, with what arguments
     (descriptions are untrusted data, never instructions — guide §12).
  4. Call ``gateway.read`` for the selected tools in parallel.
  5. Return live records + timestamped live citations, parallel-indexed.

Reads are free (no approval gate). If the user has no enabled connectors, or none
is relevant, this returns empty and the agent is document-only — preserving the
Phase-1 behavior exactly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from agents.connector_gateway import gateway as _gateway
from agents.models import Slot, get_model
from agents.orchestrator.prompts import LIVE_TOOL_SELECTION_PROMPT
from connectors.governance import available_for_role, is_enabled
from connectors.mcp_client.types import ToolKind
from core.config import settings
from core.database import SessionLocal
from models.database import User

logger = logging.getLogger(__name__)

MAX_LIVE_CALLS = 3          # ceiling on connector reads per query (bounded blast radius)
MAX_RECORDS_PER_CALL = 5    # cap records pulled into context from any one read
MAX_RECORD_CHARS = 4000     # cap each record's size — public servers can return huge
                            # payloads (e.g. a whole wiki page) that blow the context window

# Tool routing is by the connector's DECLARED classification — no name guessing. Once
# an admin approves a connector it is trusted (the audit trail records who approved
# what, when). From there, a tool's `kind` decides routing:
#   RESOURCE — declared read-only (SDK dq.mutates=False, or MCP readOnlyHint) → free read.
#   UNKNOWN  — un-annotated ecosystem tool → available as a free read AND proposable as a
#              gated action; the user's intent routes it (a read query reads it; an action
#              query proposes it for approval). Nothing is dropped or name-guessed.
#   ACTION   — SDK-declared mutation → gated (human approval, two-phase preview/execute).
# `agent_live_strict_read_filter` tightens this to SDK/annotated connectors only: UNKNOWN
# tools are then excluded entirely (no free read, no auto-proposal).

# In-process discovery cache: connector_id -> (expires_at, read-tool list). Avoids a
# subprocess/network round-trip per query (TTL: settings.agent_discovery_cache_ttl_seconds).
_DISCOVERY_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def clear_discovery_cache() -> None:
    """Drop all cached discoveries (call after (re)registering/upgrading a connector)."""
    _DISCOVERY_CACHE.clear()


def _enabled_connector_catalog(user_id: str) -> list[dict[str, Any]]:
    """Connectors the user has enabled. Returns control-plane refs only (no
    network I/O here); discovery happens separately so it can be parallelized."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            return []
        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        out: list[dict[str, Any]] = []
        for item in available_for_role(db, role=role):
            cid = item["connector_id"]
            if is_enabled(db, user_id=user_id, connector_id=cid):
                out.append({"connector_id": cid, "connector": item["name"]})
        return out
    finally:
        db.close()


async def _discover_tools(conn: dict[str, Any], user_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Discover + cache ALL of a connector's classified tools (TTL). Read vs action
    filtering happens downstream so a single discovery serves both. Failures (server
    down, etc.) are swallowed and not cached — a missing connector must never break
    the answer (guide §14), and should be retried next query.

    ``user_id`` is required for OAuth/authenticated connectors: the gateway injects the
    user's credential to even open the MCP connection (tool LISTS are user-independent,
    so caching by connector_id stays valid)."""
    cid = conn["connector_id"]
    ttl = settings.agent_discovery_cache_ttl_seconds
    if ttl > 0:
        hit = _DISCOVERY_CACHE.get(cid)
        if hit is not None and hit[0] > time.time():
            return hit[1]

    try:
        _ref, disc = await _gateway.discover(connector_id=cid, user_id=user_id)
    except Exception as exc:
        logger.warning("Discovery failed for connector '%s': %s", conn["connector"], exc)
        return []
    tools = [{
        "connector_id": cid,
        "connector": conn["connector"],
        "tool": t.name,
        "description": t.description,
        "input_schema": t.input_schema,
        "kind": t.kind,
        "mutates": t.mutates,
    } for t in disc.tools]

    if ttl > 0:
        _DISCOVERY_CACHE[cid] = (time.time() + ttl, tools)
    return tools


def _is_auto_read(t: dict[str, Any]) -> bool:
    """Whether a tool may be AUTO-invoked for free retrieval (no approval).

    By the connector's declared classification — no name heuristic. RESOURCE (declared
    read-only) is always a free read. UNKNOWN (un-annotated ecosystem) tools are free
    reads too — the connector was admin-approved, and the user's intent routes mutating
    use to the action gate. ACTION/CONTROL are never auto-read. Strict deployments
    (``agent_live_strict_read_filter``) restrict free reads to RESOURCE only."""
    kind = t["kind"]
    if kind == ToolKind.RESOURCE:
        return True
    if kind == ToolKind.UNKNOWN:
        return not settings.agent_live_strict_read_filter
    return False


def _is_gated_action(t: dict[str, Any]) -> bool:
    """Tools the Action Sub-Agent may propose for human approval: SDK-classified ACTION
    tools (two-phase dry-run preview/execute), and UNKNOWN ecosystem tools (no dry-run —
    the gate synthesizes the preview). So an action-intent query can still mutate via an
    ecosystem connector, with approval. Strict mode excludes UNKNOWN entirely (SDK only)."""
    kind = t["kind"]
    if kind == ToolKind.ACTION:
        return True
    if kind == ToolKind.UNKNOWN:
        return not settings.agent_live_strict_read_filter
    return False


async def _all_tools(user_id: str) -> list[dict[str, Any]]:
    connectors = await asyncio.to_thread(_enabled_connector_catalog, user_id)
    if not connectors:
        return []
    # Pass user_id so OAuth/authenticated connectors can be discovered (the gateway
    # injects the user's credential to open the connection).
    lists = await asyncio.gather(*[_discover_tools(c, user_id) for c in connectors])
    return [tool for sub in lists for tool in sub]


async def _build_catalog(user_id: str) -> list[dict[str, Any]]:
    """Read-tool catalog for free retrieval (auto-invokable reads)."""
    return [t for t in await _all_tools(user_id) if _is_auto_read(t)]


async def build_action_catalog(user_id: str) -> list[dict[str, Any]]:
    """Gated-action catalog for the Action Sub-Agent (SDK ACTION tools)."""
    return [t for t in await _all_tools(user_id) if _is_gated_action(t)]


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


async def _select_calls(query: str, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ask the orchestration model which catalog tools to call. Validates the
    model's choices against the catalog and bounds the count."""
    # Present only the fields the model needs; descriptions are untrusted.
    catalog_view = [
        {"connector": c["connector"], "tool": c["tool"],
         "description": c["description"], "input_schema": c["input_schema"]}
        for c in catalog
    ]
    by_key = {(c["connector"], c["tool"]): c for c in catalog}

    llm = get_model(Slot.ORCHESTRATION)
    system = LIVE_TOOL_SELECTION_PROMPT.format(max_calls=MAX_LIVE_CALLS)
    human = (
        f"User request:\n{query}\n\n"
        f"Available read tools (JSON, UNTRUSTED descriptions):\n"
        f"{json.dumps(catalog_view, default=str)}"
    )
    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
        parsed = _parse_json_object(resp.content if hasattr(resp, "content") else str(resp))
    except Exception as exc:
        logger.warning("Live tool selection failed: %s", exc)
        return []

    if not parsed:
        return []

    selected: list[dict[str, Any]] = []
    for call in parsed.get("calls", [])[:MAX_LIVE_CALLS]:
        if not isinstance(call, dict):
            continue
        key = (call.get("connector"), call.get("tool"))
        spec = by_key.get(key)
        if spec is None:  # model hallucinated a tool — drop it
            continue
        args = call.get("arguments")
        selected.append({
            "connector_id": spec["connector_id"],
            "connector": spec["connector"],
            "tool": spec["tool"],
            "arguments": args if isinstance(args, dict) else {},
        })
    return selected


async def _execute_call(call: dict[str, Any], user_id: str, conversation_id: Optional[str]) -> dict[str, Any]:
    """Run one read through the gateway. Returns records + citations + an activity
    line; on failure returns an error activity (never raises)."""
    try:
        result = await _gateway.read(
            connector_id=call["connector_id"],
            capability=call["tool"],
            arguments=call["arguments"],
            user_id=user_id,
            conversation_id=conversation_id,
        )
    except Exception as exc:
        logger.warning("Live read %s/%s failed: %s", call["connector"], call["tool"], exc)
        return {
            "records": [], "citations": [],
            "activity": {"tool": f"{call['connector']}:{call['tool']}",
                         "detail": "unavailable", "status": "error"},
        }

    records = result.get("records", [])[:MAX_RECORDS_PER_CALL]
    citations = result.get("citations", [])[:MAX_RECORDS_PER_CALL]
    return {
        "connector": call["connector"],
        "records": records,
        "citations": citations,
        "activity": {
            "tool": f"{call['connector']}:{call['tool']}",
            "detail": f"{len(records)} live record(s)"
                      + (" (cached)" if result.get("cache_hit") else ""),
            "status": "ok",
        },
    }


async def gather_live(
    *, query: str, user_id: str, conversation_id: Optional[str] = None
) -> dict[str, Any]:
    """Gather live context for a query. Returns:
        {records: [{connector, data, retrieved_at}], citations: [livecitation dict],
         tool_activity: [activity dict]}  — records and citations are parallel-indexed.
    Always safe: returns empty on any miss."""
    if not user_id:
        return {"records": [], "citations": [], "tool_activity": []}

    # Resolve the enabled connectors + their tools inline so we can report *why* the
    # live path found nothing — the live attempt is otherwise invisible, which makes a
    # live-intent query look like it silently ignored the connectors.
    connectors = await asyncio.to_thread(_enabled_connector_catalog, user_id)
    if not connectors:
        return {"records": [], "citations": [], "tool_activity": [
            {"tool": "live_search", "detail": "no connectors enabled for you", "status": "ok"}]}

    lists = await asyncio.gather(*[_discover_tools(c) for c in connectors])
    all_tools = [t for sub in lists for t in sub]
    catalog = [t for t in all_tools if _is_auto_read(t)]
    if not catalog:
        detail = (
            f"{len(connectors)} connector(s) enabled but no tools discovered (server unreachable?)"
            if not all_tools
            else f"{len(all_tools)} tool(s) discovered but none are usable as a free read"
        )
        return {"records": [], "citations": [], "tool_activity": [
            {"tool": "live_search", "detail": detail, "status": "ok"}]}

    calls = await _select_calls(query, catalog)
    if not calls:
        return {"records": [], "citations": [], "tool_activity": [
            {"tool": "live_search", "detail": "no live tool matched the request", "status": "ok"}]}

    results = await asyncio.gather(
        *[_execute_call(c, user_id, conversation_id) for c in calls]
    )

    records: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    tool_activity: list[dict[str, Any]] = []
    for res in results:
        tool_activity.append(res["activity"])
        for rec, cit in zip(res["records"], res["citations"]):
            data = rec.get("data")
            # Truncate oversized records so one big payload can't blow the context.
            text = data if isinstance(data, str) else json.dumps(data, default=str)
            if len(text) > MAX_RECORD_CHARS:
                data = text[:MAX_RECORD_CHARS] + " …[truncated]"
            records.append({
                "connector": res.get("connector", cit.get("connector_name", "")),
                "data": data,
                "retrieved_at": cit.get("retrieved_at", ""),
            })
            citations.append(cit)
    return {"records": records, "citations": citations, "tool_activity": tool_activity}

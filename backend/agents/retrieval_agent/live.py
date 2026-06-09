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

from agents.models import Slot, get_model
from agents.orchestrator.prompts import LIVE_TOOL_SELECTION_PROMPT
from connectors.gateway import ConnectorGateway
from connectors.governance import available_for_role, is_enabled
from connectors.mcp_client.types import ToolKind
from core.config import settings
from core.database import SessionLocal
from models.database import User

logger = logging.getLogger(__name__)

# One gateway instance for the agent layer. The circuit breaker is in-process by
# design (handoff §5), so a dedicated instance is fine.
_gateway = ConnectorGateway()

MAX_LIVE_CALLS = 3          # ceiling on connector reads per query (bounded blast radius)
MAX_RECORDS_PER_CALL = 5    # cap records pulled into context from any one read
MAX_RECORD_CHARS = 4000     # cap each record's size — public servers can return huge
                            # payloads (e.g. a whole wiki page) that blow the context window

# Verb fragments that mark an ecosystem (non-SDK) tool as read-like. SDK connectors
# classify reads precisely (dq.mutates=False → RESOURCE); ecosystem servers that omit
# MCP readOnlyHint are conservatively flagged mutates=True/UNKNOWN, so we gate auto-use
# behind this name heuristic — a read-named UNKNOWN tool is safe to call; a mutating one
# (e.g. create_/update_/delete_/send_) is not auto-invoked here (actions are gated, Phase 3).
_READ_NAME_HINTS = (
    "search", "fetch", "get", "list", "read", "query", "find", "lookup",
    "browse", "ask", "retrieve", "view", "show", "describe",
)


def _looks_like_read(tool_name: str) -> bool:
    name = (tool_name or "").lower()
    return any(hint in name for hint in _READ_NAME_HINTS)

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


async def _discover_read_tools(conn: dict[str, Any]) -> list[dict[str, Any]]:
    """Discover one connector's read-only tools, cached with a TTL. Failures (server
    down, etc.) are swallowed and not cached — a missing connector must never break
    the answer (guide §14), and should be retried next query."""
    cid = conn["connector_id"]
    ttl = settings.agent_discovery_cache_ttl_seconds
    if ttl > 0:
        hit = _DISCOVERY_CACHE.get(cid)
        if hit is not None and hit[0] > time.time():
            return hit[1]

    try:
        _ref, disc = await _gateway.discover(connector_id=cid)
    except Exception as exc:
        logger.warning("Discovery failed for connector '%s': %s", conn["connector"], exc)
        return []
    tools = []
    for t in disc.tools:
        # Never auto-invoke SDK-classified mutations or control tools — actions are
        # gated (Phase 3), never used for free retrieval.
        if t.kind in (ToolKind.ACTION, ToolKind.CONTROL):
            continue
        if t.kind == ToolKind.RESOURCE:
            pass  # known read-only (SDK dq.mutates=False, or MCP readOnlyHint)
        elif t.kind == ToolKind.UNKNOWN:
            # Ecosystem tool with unknown mutation status — only auto-read it if its
            # name reads like a read (search/fetch/get/...); the `mutates` flag here is
            # a conservative default, not authoritative.
            if not _looks_like_read(t.name):
                continue
        else:
            continue
        tools.append({
            "connector_id": cid,
            "connector": conn["connector"],
            "tool": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        })

    if ttl > 0:
        _DISCOVERY_CACHE[cid] = (time.time() + ttl, tools)
    return tools


async def _build_catalog(user_id: str) -> list[dict[str, Any]]:
    connectors = await asyncio.to_thread(_enabled_connector_catalog, user_id)
    if not connectors:
        return []
    tool_lists = await asyncio.gather(*[_discover_read_tools(c) for c in connectors])
    return [tool for sub in tool_lists for tool in sub]


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

    catalog = await _build_catalog(user_id)
    if not catalog:
        return {"records": [], "citations": [], "tool_activity": []}

    calls = await _select_calls(query, catalog)
    if not calls:
        return {"records": [], "citations": [], "tool_activity": []}

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

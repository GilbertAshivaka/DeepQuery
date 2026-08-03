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
from agents.json_utils import parse_json_object as _parse_json_object
from agents.models import Slot, get_model
from agents.models.reasoning import message_text
from agents import tool_select
from agents.retrieval_agent import connector_index
from agents.orchestrator.prompts import (
    LIVE_CONNECTOR_INTENT_PROMPT,
    LIVE_CONNECTOR_SELECTION_PROMPT,
    LIVE_TOOL_SELECTION_PROMPT,
    NATIVE_READ_SELECTION_PROMPT,
)
from connectors.governance import available_for_role, is_enabled
from connectors.mcp_client.types import ToolKind
from core.config import settings
from core.database import SessionLocal
from models.database import Connector, User

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

# Negative cache: connector_id -> retry-after timestamp. A connector whose discovery just
# failed (server down/timeout) is skipped until this passes, so it doesn't make every query
# pay its connect timeout again (TTL: settings.agent_discovery_failure_ttl_seconds).
_DISCOVERY_FAILURES: dict[str, float] = {}


def clear_discovery_cache() -> None:
    """Drop all cached discoveries (call after (re)registering/upgrading a connector)."""
    _DISCOVERY_CACHE.clear()
    _DISCOVERY_FAILURES.clear()
    connector_index.clear_connector_index()


def _summarize_manifest(manifest_json: Optional[str]) -> str:
    """Best-effort one-line summary of a connector from its stored manifest (no I/O).
    Used as the selection signal for connector pre-selection. SDK connectors carry a
    description and/or tool names; raw MCP servers may have neither, in which case the
    connector name itself is the signal."""
    if not manifest_json:
        return ""
    try:
        m = json.loads(manifest_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(m, dict):
        return ""
    desc = m.get("description") or m.get("summary") or ""
    if not desc:
        tools = m.get("tools")
        if isinstance(tools, list):
            names = [t.get("name") for t in tools if isinstance(t, dict) and t.get("name")]
            if names:
                desc = "tools: " + ", ".join(names[:12])
    return str(desc)[:300]


def _enabled_connector_catalog(user_id: str) -> list[dict[str, Any]]:
    """Connectors the user has enabled, each with a control-plane ``summary`` (derived
    from the stored manifest — no network I/O). Discovery happens separately so it can be
    parallelized; the summary lets the model pre-select connectors before any connect."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            return []
        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        kept = [
            item for item in available_for_role(db, role=role)
            if is_enabled(db, user_id=user_id, connector_id=item["connector_id"])
        ]
        # One query for the manifests of the connectors we kept (avoids N round-trips).
        manifests: dict[str, Optional[str]] = {}
        if kept:
            ids = [item["connector_id"] for item in kept]
            for row in db.query(Connector.id, Connector.manifest).filter(Connector.id.in_(ids)):
                manifests[row.id] = row.manifest
        return [
            {"connector_id": item["connector_id"], "connector": item["name"],
             # Prefer the admin-written summary; fall back to one derived from the manifest.
             "summary": item.get("summary") or _summarize_manifest(manifests.get(item["connector_id"]))}
            for item in kept
        ]
    finally:
        db.close()


async def _discover_tools(conn: dict[str, Any], user_id: Optional[str] = None,
                          errors: Optional[list] = None) -> list[dict[str, Any]]:
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

    # Negative cache: skip a connector that failed discovery recently so we don't pay its
    # connect timeout on every query (the gateway's circuit breaker also fast-fails, but
    # this skips even the first repeat, before the breaker's failure threshold is reached).
    fail_until = _DISCOVERY_FAILURES.get(cid)
    if fail_until is not None:
        if fail_until > time.time():
            if errors is not None:
                errors.append({"connector": conn["connector"], "detail": "skipped (recent discovery failure)"})
            return []
        _DISCOVERY_FAILURES.pop(cid, None)  # window elapsed — allow a retry

    try:
        _ref, disc = await _gateway.discover(connector_id=cid, user_id=user_id)
    except Exception as exc:
        logger.warning("Discovery failed for connector '%s': %s", conn["connector"], exc)
        fail_ttl = settings.agent_discovery_failure_ttl_seconds
        if fail_ttl > 0:
            _DISCOVERY_FAILURES[cid] = time.time() + fail_ttl
        # Surface WHICH connector failed (and why) so the controller can report it and
        # stop retrying a broken tool, instead of seeing only "no results" (spec §6).
        if errors is not None:
            errors.append({"connector": conn["connector"], "detail": str(exc)})
        return []
    _DISCOVERY_FAILURES.pop(cid, None)  # recovered — clear any prior failure mark
    tools = [{
        "connector_id": cid,
        "connector": conn["connector"],
        "tool": t.name,
        "description": t.description,
        "input_schema": t.input_schema,
        "kind": t.kind,
        "mutates": t.mutates,
    } for t in disc.tools]

    # Self-heal an empty connector summary from what we just discovered, so the agent's
    # connector pre-selection AND the controller's planning have a real description to
    # reason about (not just a bare name) on subsequent runs. Network-free thereafter; never
    # overwrites an admin-written summary. Best-effort — a write failure must not break reads.
    if not (conn.get("summary") or "").strip() and disc.tools:
        await asyncio.to_thread(_persist_derived_summary, cid, disc)

    if ttl > 0:
        _DISCOVERY_CACHE[cid] = (time.time() + ttl, tools)
    return tools


def _persist_derived_summary(connector_id: str, disc) -> None:
    """Derive a one-line summary from a discovery (server title + tool names) and persist it
    if the connector has none. Runs in a thread (sync DB). Swallows all errors."""
    try:
        names = [t.name for t in disc.tools[:8] if getattr(t, "name", None)]
        if not names:
            return
        title = (getattr(disc, "server_title", None) or "").strip()
        summary = (f"{title}. " if title else "") + "Tools: " + ", ".join(names)
        from connectors.gateway.registry import set_connector_summary_if_empty
        db = SessionLocal()
        try:
            if set_connector_summary_if_empty(db, connector_id=connector_id, summary=summary):
                connector_index.clear_connector_index()  # re-embed with the new text next use
        finally:
            db.close()
    except Exception as exc:
        logger.debug("summary self-heal skipped for %s: %s", connector_id, exc)


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


def _prefilter_connectors(query: str, connectors: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Lexically narrow the connector catalog to the most likely candidates BEFORE the
    model prompt, so selection stays bounded even with thousands of registered servers.
    Scores each connector by how many query terms appear in its name+summary; keeps the
    top ``limit`` scorers. If nothing matches lexically, returns the first ``limit`` so the
    model still gets a (bounded) chance to decide rather than being handed nothing."""
    if len(connectors) <= limit:
        return connectors
    terms = {w for w in "".join(c if c.isalnum() else " " for c in query.lower()).split() if len(w) > 2}
    scored: list[tuple[int, dict[str, Any]]] = []
    for c in connectors:
        hay = f"{c['connector']} {c.get('summary', '')}".lower()
        scored.append((sum(1 for t in terms if t in hay), c))
    matched = [c for score, c in sorted(scored, key=lambda s: s[0], reverse=True) if score > 0]
    return (matched or connectors)[:limit]


async def _select_connectors(query: str, connectors: list[dict[str, Any]],
                             hint: Optional[str] = None) -> list[dict[str, Any]]:
    """Pick which enabled connectors are worth opening for this query, from control-plane
    metadata only (name + summary — no network I/O), so discovery connects to those alone.

    Two strategies, chosen by catalog size:
      • small (≤ prefilter_limit): show the list, the model picks from it (cheap, accurate,
        no embeddings needed).
      • large (> prefilter_limit): the model names what it needs WITHOUT seeing the list,
        and we resolve that against the catalog semantically — so prompt size never grows
        with connector count (the thousands-of-servers case)."""
    if (settings.agent_connector_semantic_resolve
            and len(connectors) > settings.agent_connector_prefilter_limit):
        return await _select_by_resolve(query, connectors, hint)
    return await _select_from_list(query, connectors, hint)


async def _select_from_list(query: str, candidates: list[dict[str, Any]],
                            hint: Optional[str] = None) -> list[dict[str, Any]]:
    """Small-catalog path: show the connectors and let the model pick from them.

    On a model/parse failure we conservatively fall back to ALL candidates (optimization
    must never lose a relevant source); a *valid* empty choice ("none relevant") is honored
    and returned as []."""
    catalog_view = [{"connector": c["connector"], "summary": c.get("summary", "")} for c in candidates]
    by_name = {c["connector"]: c for c in candidates}

    llm = get_model(Slot.ORCHESTRATION)
    system = LIVE_CONNECTOR_SELECTION_PROMPT.format(max_connectors=settings.agent_connector_preselect_max)
    human = (
        f"{_request_text(query, hint)}\n\n"
        f"Available connectors (JSON, UNTRUSTED summaries):\n"
        f"{json.dumps(catalog_view, default=str)}"
    )
    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
        parsed = _parse_json_object(message_text(resp))
    except Exception as exc:
        logger.warning("Connector pre-selection failed: %s — falling back to all candidates", exc)
        return candidates
    if parsed is None or "connectors" not in parsed:
        return candidates  # couldn't parse a decision — don't drop sources

    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in parsed.get("connectors", [])[:settings.agent_connector_preselect_max]:
        spec = by_name.get(name)
        if spec is not None and spec["connector"] not in seen:  # ignore hallucinated names
            chosen.append(spec)
            seen.add(spec["connector"])
    return chosen


async def _extract_intent(query: str, hint: Optional[str] = None) -> Optional[dict[str, list[str]]]:
    """Ask the model what KIND of connector the request needs, without showing it the list.
    Returns {"capabilities": [...], "name_guesses": [...]} or None on failure."""
    llm = get_model(Slot.ORCHESTRATION)
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=LIVE_CONNECTOR_INTENT_PROMPT),
            HumanMessage(content=_request_text(query, hint)),
        ])
        parsed = _parse_json_object(message_text(resp))
    except Exception as exc:
        logger.warning("Connector intent extraction failed: %s", exc)
        return None
    if parsed is None:
        return None
    caps = [str(c) for c in parsed.get("capabilities", []) if c]
    names = [str(n) for n in parsed.get("name_guesses", []) if n]
    return {"capabilities": caps, "name_guesses": names}


async def _select_by_resolve(query: str, connectors: list[dict[str, Any]],
                             hint: Optional[str] = None) -> list[dict[str, Any]]:
    """Large-catalog path: the model names what it needs, then we resolve against the
    catalog (name fast-path + semantic search) so the prompt never holds the full list.
    Falls back to lexical narrowing + the shown-list pick if intent or the embedder fails."""
    max_n = settings.agent_connector_preselect_max
    intent = await _extract_intent(query, hint)
    if intent is None:  # couldn't get an intent — narrow lexically and let the model pick
        return await _select_from_list(query, _prefilter_connectors(query, connectors, settings.agent_connector_prefilter_limit), hint)
    if not intent["capabilities"] and not intent["name_guesses"]:
        return []  # model judged no external system is needed — honor it

    chosen: dict[str, dict[str, Any]] = {}
    # 1. Name fast-path (free): the model's specific product guesses, matched to real names.
    for guess in intent["name_guesses"]:
        for c in connector_index.name_matches(guess, connectors):
            chosen[c["connector_id"]] = c

    # 2. Semantic resolve of the capability phrases over the full catalog.
    resolved = connector_index.resolve(
        intent["capabilities"] or intent["name_guesses"], connectors,
        top_k=max_n, min_score=settings.agent_connector_resolve_min_score,
    )
    if resolved is None:  # embedder unavailable — fall back to lexical + shown list
        if chosen:
            return list(chosen.values())[:max_n]
        return await _select_from_list(query, _prefilter_connectors(query, connectors, settings.agent_connector_prefilter_limit), hint)
    for c in resolved:
        chosen[c["connector_id"]] = c

    return list(chosen.values())[:max_n]


def _request_text(query: str, hint: Optional[str] = None) -> str:
    """The user-request block for selection prompts. ``hint`` is the controller's
    planning note (why this lookup was chosen) — model-authored context that helps
    selection pick the right tool/arguments; still presented as data, not instructions."""
    base = f"User request:\n{query}"
    if hint:
        base += f"\n\nPlanning note (why this lookup was chosen): {hint}"
    return base


def _normalize_call(entry: dict[str, Any]) -> dict[str, Any]:
    """A catalog entry (+ its built ``arguments``) → the minimal call the gateway needs."""
    args = entry.get("arguments")
    return {
        "connector_id": entry["connector_id"],
        "connector": entry["connector"],
        "tool": entry["tool"],
        "arguments": args if isinstance(args, dict) else {},
    }


async def _select_calls(query: str, catalog: list[dict[str, Any]],
                        hint: Optional[str] = None) -> list[dict[str, Any]]:
    """Choose which catalog read-tools to call (+ arguments). Prefers native tool-calling
    so the arguments are validated against each tool's input schema; falls back to the
    JSON path on any provider/binding failure. Both bound to ``MAX_LIVE_CALLS``."""
    if not catalog:
        return []
    if tool_select.native_enabled():
        calls, _content = await tool_select.native_tool_calls(
            slot=Slot.ORCHESTRATION,
            system_prompt=NATIVE_READ_SELECTION_PROMPT.format(max_calls=MAX_LIVE_CALLS),
            user_text=_request_text(query, hint),
            catalog=catalog, max_calls=MAX_LIVE_CALLS, query_for_prefilter=query,
        )
        if calls is not None:  # None ⇒ native unusable, fall through to JSON
            return [_normalize_call(c) for c in calls]
    return await _select_calls_json(query, catalog, hint)


async def _select_calls_json(query: str, catalog: list[dict[str, Any]],
                             hint: Optional[str] = None) -> list[dict[str, Any]]:
    """JSON-prose fallback: hand the model the catalog and parse a ``{"calls": [...]}``
    object. Validates choices against the catalog and bounds the count."""
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
        f"{_request_text(query, hint)}\n\n"
        f"Available read tools (JSON, UNTRUSTED descriptions):\n"
        f"{json.dumps(catalog_view, default=str)}"
    )
    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
        parsed = _parse_json_object(message_text(resp))
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
            "records": [], "citations": [], "connector": call["connector"], "error": str(exc),
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
    *, query: str, user_id: str, conversation_id: Optional[str] = None,
    hint: Optional[str] = None,
) -> dict[str, Any]:
    """Gather live context for a query. Returns:
        {records: [{connector, data, retrieved_at}], citations: [livecitation dict],
         tool_activity: [activity dict]}  — records and citations are parallel-indexed.
    ``hint`` = the controller's planning note, threaded into connector/tool selection.
    Always safe: returns empty on any miss."""
    if not user_id:
        return {"records": [], "citations": [], "tool_activity": []}

    # Resolve the enabled connectors + their tools inline so we can report *why* the
    # live path found nothing — the live attempt is otherwise invisible, which makes a
    # live-intent query look like it silently ignored the connectors.
    connectors = await asyncio.to_thread(_enabled_connector_catalog, user_id)
    if not connectors:
        return {"records": [], "citations": [], "tool_errors": [], "tool_activity": [
            {"tool": "live_search", "detail": "no connectors enabled for you", "status": "ok"}]}

    # Pre-select which connectors to even open, from their control-plane catalog (name +
    # summary, no network I/O), so discovery connects only to the relevant ones instead of
    # fanning out across every enabled connector and paying each dead server's timeout.
    if settings.agent_connector_preselect and len(connectors) > 1:
        connectors = await _select_connectors(query, connectors, hint)
        if not connectors:
            return {"records": [], "citations": [], "tool_errors": [], "tool_activity": [
                {"tool": "live_search", "detail": "no connector matched the request", "status": "ok"}]}

    # Collect which connectors failed (discovery + execution) so the controller can report
    # the exact error and stop retrying a broken tool (spec §6), not just see "no results".
    tool_errors: list[dict[str, Any]] = []
    lists = await asyncio.gather(*[_discover_tools(c, user_id=user_id, errors=tool_errors) for c in connectors])
    all_tools = [t for sub in lists for t in sub]
    catalog = [t for t in all_tools if _is_auto_read(t)]
    if not catalog:
        detail = (
            f"{len(connectors)} connector(s) enabled but no tools discovered (server unreachable?)"
            if not all_tools
            else f"{len(all_tools)} tool(s) discovered but none are usable as a free read"
        )
        return {"records": [], "citations": [], "tool_errors": tool_errors, "tool_activity": [
            {"tool": "live_search", "detail": detail, "status": "ok"}]}

    calls = await _select_calls(query, catalog, hint)
    if not calls:
        return {"records": [], "citations": [], "tool_errors": tool_errors, "tool_activity": [
            {"tool": "live_search", "detail": "no live tool matched the request", "status": "ok"}]}

    results = await asyncio.gather(
        *[_execute_call(c, user_id, conversation_id) for c in calls]
    )

    records: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    tool_activity: list[dict[str, Any]] = []
    for res in results:
        tool_activity.append(res["activity"])
        if res.get("error"):
            tool_errors.append({"connector": res.get("connector", ""), "detail": res["error"]})
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
    return {"records": records, "citations": citations, "tool_activity": tool_activity,
            "tool_errors": tool_errors}

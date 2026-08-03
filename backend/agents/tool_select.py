"""
Deep Query — Shared tool/argument selection (native tool-calling + JSON fallback).

The retrieval (live read) and action sub-agents both need the model to pick which
connector tool(s) to call and to construct each call's arguments. Historically this was
done by handing the model a JSON catalog and parsing a ``{"calls": [...]}`` object out of
its prose — which puts the entire burden of producing schema-correct arguments on one
unconstrained generation, the weakest link for smaller models (a missing/!malformed Gmail
``body`` just fails downstream at the connector).

This module adds **native tool-calling**: each candidate tool's real ``input_schema`` is
bound to the model (``bind_tools``), so the provider validates the arguments and returns
structured ``tool_calls``. It degrades safely — on any provider/binding failure it returns
``None`` so the caller falls back to its existing JSON path, and an empty result (the model
chose no tool) is honored as a real decision.

The model never EXECUTES anything here: the bound tools are schema carriers only. The
chosen ``(connector, tool, arguments)`` is mapped back to the catalog entry and routed
through the Connector Gateway exactly as before (the gateway stays the sole enforcer).
Tool descriptions and the user's text remain UNTRUSTED data, never instructions.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from agents.models import Slot, get_model
from agents.models.reasoning import message_text
from core.config import settings

logger = logging.getLogger(__name__)

# OpenAI/Groq tool names must match ^[a-zA-Z0-9_-]{1,64}$. We sanitize connector+tool
# into that space and map back to the real catalog entry.
_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")
# Ceiling on tools bound per call (prompt-size + provider limits). A larger catalog is
# lexically narrowed to the most query-relevant candidates first.
_MAX_TOOLS_BOUND = 64


def _safe_name(connector: str, tool: str, used: set[str]) -> str:
    base = f"{connector}-{tool}"
    name = _NAME_RE.sub("_", base).strip("_")[:60] or "tool"
    cand, i = name, 1
    while cand in used:
        suffix = f"_{i}"
        cand = name[: 60 - len(suffix)] + suffix
        i += 1
    used.add(cand)
    return cand


def _sanitize_schema(schema: Any) -> dict:
    """A JSON-Schema object the provider will accept as a tool's parameters. MCP tools may
    omit ``type`` or carry an empty schema; normalize to a well-formed object schema."""
    if not isinstance(schema, dict) or not schema:
        return {"type": "object", "properties": {}}
    s = dict(schema)
    s.setdefault("type", "object")
    if s.get("type") == "object":
        s.setdefault("properties", {})
    return s


def _prefilter(query: str, catalog: list[dict], limit: int) -> list[dict]:
    """Lexically narrow a large catalog to the ``limit`` most query-relevant tools before
    binding (keeps the request bounded even with many enabled connectors). If nothing
    matches lexically, keep the first ``limit`` so the model still gets a chance."""
    if len(catalog) <= limit:
        return catalog
    terms = {w for w in re.split(r"\W+", query.lower()) if len(w) > 2}
    scored = [
        (sum(1 for t in terms
             if t in f"{c.get('connector', '')} {c.get('tool', '')} {c.get('description', '')}".lower()), c)
        for c in catalog
    ]
    scored.sort(key=lambda s: s[0], reverse=True)
    matched = [c for score, c in scored if score > 0]
    return (matched or [c for _, c in scored])[:limit]


def build_specs(catalog: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Build OpenAI-format tool specs from a connector-tool catalog + a name→entry map."""
    used: set[str] = set()
    specs: list[dict] = []
    by_name: dict[str, dict] = {}
    for c in catalog:
        name = _safe_name(str(c.get("connector", "")), str(c.get("tool", "")), used)
        specs.append({
            "type": "function",
            "function": {
                "name": name,
                "description": (c.get("description") or f"{c.get('connector')} {c.get('tool')}")[:1024],
                "parameters": _sanitize_schema(c.get("input_schema")),
            },
        })
        by_name[name] = c
    return specs, by_name


def missing_required(schema: Any, args: Any) -> list[str]:
    """Required keys declared by ``schema`` that are absent/blank in ``args`` (for a
    repair-retry / validation signal). Empty list means all required fields are present."""
    if not isinstance(schema, dict):
        return []
    req = schema.get("required")
    if not isinstance(req, list):
        return []
    a = args if isinstance(args, dict) else {}
    return [k for k in req if k not in a or a.get(k) in (None, "")]


async def native_tool_calls(
    *,
    slot: Slot,
    system_prompt: str,
    user_text: str,
    catalog: list[dict],
    max_calls: int,
    query_for_prefilter: str = "",
) -> tuple[Optional[list[dict]], str]:
    """Select tool call(s) via native tool-calling.

    Returns ``(calls, content)`` where ``calls`` is a list of catalog entries each with an
    ``arguments`` dict the provider built against the tool's schema, and ``content`` is any
    assistant text accompanying the call(s) (used as a summary fallback by the action
    path). Returns ``(None, "")`` when native tool-calling is unusable (binding/provider
    failure or no structured ``tool_calls`` surfaced) so the caller falls back to its JSON
    path. ``([], content)`` is a real "no tool chosen" decision and is honored. Never raises.
    """
    if not catalog:
        return [], ""
    bound_catalog = _prefilter(query_for_prefilter, catalog, _MAX_TOOLS_BOUND)
    specs, by_name = build_specs(bound_catalog)
    try:
        llm = get_model(slot, for_tools=True)
        bound = llm.bind_tools(specs)
        resp = await bound.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_text),
        ])
    except Exception as exc:
        logger.warning("native tool-calling unavailable (%s); will fall back to JSON", exc)
        return None, ""

    tool_calls = getattr(resp, "tool_calls", None)
    if tool_calls is None:
        return None, ""  # provider didn't surface structured calls → fall back

    # message_text, not `content if isinstance(str)`: a thinking-capable model returns a
    # block list, and discarding it would drop the model's own note — which becomes the
    # approval card's summary line for the action path.
    content = message_text(resp)
    calls: list[dict] = []
    for tc in tool_calls[: max(1, max_calls)]:
        entry = by_name.get(tc.get("name"))
        if entry is None:  # hallucinated / out-of-catalog tool name — drop it
            continue
        args = tc.get("args")
        calls.append({**entry, "arguments": args if isinstance(args, dict) else {}})
    return calls, content


def native_enabled() -> bool:
    return bool(settings.agent_native_tool_calling)

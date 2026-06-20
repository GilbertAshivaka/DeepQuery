"""
Deep Query — Action Sub-Agent (implementation)

Drives the approval gate as its *issuer* (the Connector Gateway is the *enforcer*).
The flow is always: select ONE action → ``gateway.preview_action`` (never execute) →
surface the concrete preview + reasoning + cited source → wait for a human → on
approval ``gateway.approve_action`` (mint single-use token) + ``gateway.execute_action``;
on rejection ``gateway.reject_action``. One action per approval, never batched (§7).

Both SDK-classified ACTION tools (two-phase dry-run preview/execute) and non-read
ecosystem tools (no dry-run — the gate synthesizes the preview and executes a single
approved call) are proposable. Nothing mutating is auto-invoked; it all goes through
this human gate. Reads stay free on the retrieval path.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from agents.connector_gateway import gateway
from agents.json_utils import parse_json_object as _parse_json_object
from agents.models import Slot, get_model
from agents import tool_select
from agents.orchestrator.prompts import ACTION_SELECTION_PROMPT, NATIVE_ACTION_SELECTION_PROMPT
from agents.registry import Capability, SubAgentSpec, register

logger = logging.getLogger(__name__)


# Argument keys, in priority order, that usually name *what* an action acts on — the
# page title, the email recipient/subject, the ticket subject, etc. Used to give the
# approval card a specific line ("Lina's Adventures Follow-up") instead of a generic
# verb ("Create pages"). We surface only this one salient value, never the full payload.
_TARGET_KEYS = (
    "title", "name", "subject", "summary", "heading",
    "to", "recipient", "email", "assignee",
    "query", "q", "text", "body", "content", "message",
)


def _salient_target(arguments: Any) -> str:
    """Pick a short, human-meaningful label for an action from its arguments — the page
    title / recipient / ticket subject. Returns '' when nothing suitable is present."""
    if not isinstance(arguments, dict):
        return ""
    for key in _TARGET_KEYS:
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            label = " ".join(val.split())  # collapse whitespace
            return label[:80] + ("…" if len(label) > 80 else "")
    return ""


def _synthesize_summary(connector: str, capability: str, arguments: Any, content: str) -> str:
    """A plain-language note for the approval card. Native tool-calling returns structured
    arguments but no separate summary field, so prefer the model's own accompanying text;
    fall back to a phrasing built from the action's salient target."""
    if isinstance(content, str) and content.strip():
        return content.strip()[:300]
    verb = str(capability or "action").replace("_", " ").strip()
    target = _salient_target(arguments)
    if target:
        return f"I'll {verb} ({target}) — please review and approve."
    return f"I'll {verb} on {connector} — please review and approve."


def _action_user_text(query: str, context: str) -> str:
    """The user-turn for action selection: the request plus the bounded evidence block the
    action's arguments should be grounded in (the meeting summary to email, etc.)."""
    return f"User request:\n{query}\n\n{context}" if context else f"User request:\n{query}"


class ActionAgent:
    """Proposes and (after approval) executes a single gated action."""

    name = "action_agent"
    capability = Capability.ACTION

    async def _select(self, query: str, catalog: list[dict], context: str = "") -> Optional[dict]:
        """Choose ONE action tool + arguments (or none), grounded in the gathered
        ``context`` (so e.g. an email body comes from what was retrieved, not the bare
        request). Prefers native tool-calling for schema-valid arguments; falls back to
        the JSON path."""
        if not catalog:
            return None
        if tool_select.native_enabled():
            calls, content = await tool_select.native_tool_calls(
                slot=Slot.ORCHESTRATION,
                system_prompt=NATIVE_ACTION_SELECTION_PROMPT,
                user_text=_action_user_text(query, context),
                catalog=catalog, max_calls=1, query_for_prefilter=query,
            )
            if calls is not None:  # None ⇒ native unusable, fall through to JSON
                if not calls:
                    return None  # model declined an action (a real decision)
                entry = calls[0]
                args = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
                return {
                    "connector_id": entry["connector_id"], "connector": entry["connector"],
                    "tool": entry["tool"], "arguments": args,
                    "reasoning": (content or "").strip()[:300]
                                 or f"Fulfils the request via {entry['connector']}.",
                    "summary": _synthesize_summary(entry["connector"], entry["tool"], args, content),
                    "kind": entry.get("kind"),
                }
        return await self._select_json(query, catalog, context)

    async def _select_json(self, query: str, catalog: list[dict], context: str = "") -> Optional[dict]:
        """JSON-prose fallback for single-action selection. Treats descriptions/context as
        untrusted; validates the choice against the catalog."""
        view = [
            {"connector": c["connector"], "tool": c["tool"],
             "description": c["description"], "input_schema": c["input_schema"]}
            for c in catalog
        ]
        by_key = {(c["connector"], c["tool"]): c for c in catalog}
        llm = get_model(Slot.ORCHESTRATION)
        human = (
            f"{_action_user_text(query, context)}\n\n"
            f"Available action tools (JSON, UNTRUSTED descriptions):\n"
            f"{json.dumps(view, default=str)}"
        )
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=ACTION_SELECTION_PROMPT),
                HumanMessage(content=human),
            ])
            parsed = _parse_json_object(resp.content if hasattr(resp, "content") else str(resp))
        except Exception as exc:
            logger.warning("Action selection failed: %s", exc)
            return None

        if not parsed:
            return None
        action = parsed.get("action")
        if not isinstance(action, dict):
            return None  # model declined to propose an action
        spec = by_key.get((action.get("connector"), action.get("tool")))
        if spec is None:  # hallucinated tool
            return None
        args = action.get("arguments")
        return {
            "connector_id": spec["connector_id"],
            "connector": spec["connector"],
            "tool": spec["tool"],
            "arguments": args if isinstance(args, dict) else {},
            "reasoning": str(parsed.get("reasoning", "")).strip(),
            "summary": str(parsed.get("summary", "")).strip(),
            "kind": spec.get("kind"),
        }

    async def propose(
        self,
        *,
        query: str,
        citations: Optional[list[dict]] = None,
        user_id: str,
        conversation_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        context: str = "",
    ) -> dict[str, Any]:
        """Select and PREVIEW one action (never executes). Returns the gate payload:
        preview + reasoning + cited sources + a ``pending_id`` to approve/reject.

        ``context`` is the bounded evidence block the action's arguments are grounded in
        (the content to email/post), built by the caller from the gathered findings."""
        from agents.retrieval_agent.live import build_action_catalog

        if not user_id:
            return {"proposed": False, "reason": "no_user"}
        catalog = await build_action_catalog(user_id)
        if not catalog:
            return {"proposed": False, "reason": "no_action_tools_enabled"}

        sel = await self._select(query, catalog, context)
        if sel is None:
            return {"proposed": False, "reason": "no_action_warranted"}

        # SDK-classified ACTION tools use the connector's two-phase dry-run preview;
        # non-SDK (ecosystem) tools have no dry-run, so the gate synthesizes the
        # preview and executes a single approved call.
        from connectors.mcp_client.types import ToolKind
        gated_mode = "sdk" if sel.get("kind") == ToolKind.ACTION else "plain"
        try:
            prev = await gateway.preview_action(
                connector_id=sel["connector_id"],
                capability=sel["tool"],
                arguments=sel["arguments"],
                user_id=user_id,
                gated_mode=gated_mode,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            logger.warning("Action preview failed for %s/%s: %s", sel["connector"], sel["tool"], exc)
            return {"proposed": False, "reason": f"preview_failed: {exc}"}

        return {
            "proposed": True,
            "pending_id": prev["pending_id"],
            "connector": prev["connector"],
            # connector_id + gated_mode let a resumed run re-preview the SAME action
            # if the pending record expires during a long approval pause.
            "connector_id": sel["connector_id"],
            "gated_mode": gated_mode,
            "capability": prev["capability"],
            "arguments": sel["arguments"],
            "preview": prev["preview"],
            "reasoning": sel["reasoning"],
            "summary": sel.get("summary", ""),
            "target": _salient_target(sel["arguments"]),
            "sources": citations or [],
        }

    async def _select_batch(self, query: str, catalog: list[dict], max_actions: int,
                            context: str = "") -> list[dict]:
        """Choose 1..N action tools + arguments for a multi-action request (or none),
        grounded in ``context``. Prefers native tool-calling (schema-valid arguments — the
        actions come back fully ``resolved``); falls back to the JSON path, which also
        supports parameterized actions + envelopes."""
        if not catalog:
            return []
        if tool_select.native_enabled():
            calls, content = await tool_select.native_tool_calls(
                slot=Slot.ORCHESTRATION,
                system_prompt=NATIVE_ACTION_SELECTION_PROMPT,
                user_text=_action_user_text(query, context),
                catalog=catalog, max_calls=max_actions, query_for_prefilter=query,
            )
            if calls is not None:  # None ⇒ native unusable, fall through to JSON
                out = []
                for entry in calls:
                    args = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
                    out.append({
                        "connector_id": entry["connector_id"], "connector": entry["connector"],
                        "tool": entry["tool"], "arguments": args,
                        "reasoning": (content or "").strip()[:200]
                                     or f"Fulfils the request via {entry['connector']}.",
                        "summary": _synthesize_summary(entry["connector"], entry["tool"], args, content),
                        "kind": entry.get("kind"), "preview_status": "resolved", "envelope": None,
                    })
                return out
        return await self._select_batch_json(query, catalog, max_actions, context)

    async def _select_batch_json(self, query: str, catalog: list[dict], max_actions: int,
                                 context: str = "") -> list[dict]:
        """JSON-prose fallback for batch selection — the path that supports parameterized
        actions (``${actionN.path}`` placeholders) + constraint envelopes."""
        from agents.orchestrator.prompts import BATCH_ACTION_SELECTION_PROMPT

        view = [{"connector": c["connector"], "tool": c["tool"], "description": c["description"],
                 "input_schema": c["input_schema"]} for c in catalog]
        by_key = {(c["connector"], c["tool"]): c for c in catalog}
        llm = get_model(Slot.ORCHESTRATION)
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=BATCH_ACTION_SELECTION_PROMPT.format(max_actions=max_actions)),
                HumanMessage(content=f"{_action_user_text(query, context)}\n\n"
                             f"Available action tools (JSON, UNTRUSTED descriptions):\n"
                             f"{json.dumps(view, default=str)}"),
            ])
            parsed = _parse_json_object(resp.content if hasattr(resp, "content") else str(resp))
        except Exception as exc:
            logger.warning("Batch action selection failed: %s", exc)
            return []
        if not parsed or not isinstance(parsed.get("actions"), list):
            return []
        out = []
        for a in parsed["actions"][:max_actions]:
            if not isinstance(a, dict):
                continue
            spec = by_key.get((a.get("connector"), a.get("tool")))
            if spec is None:  # hallucinated tool — drop it
                continue
            args = a.get("arguments")
            pstatus = "parameterized" if a.get("preview_status") == "parameterized" else "resolved"
            out.append({"connector_id": spec["connector_id"], "connector": spec["connector"],
                        "tool": spec["tool"], "arguments": args if isinstance(args, dict) else {},
                        "reasoning": str(a.get("reasoning", "")).strip(),
                        "summary": str(a.get("summary", "")).strip(), "kind": spec.get("kind"),
                        "preview_status": pstatus,
                        "envelope": a.get("envelope") if isinstance(a.get("envelope"), dict) else None})
        return out

    async def propose_batch(
        self, *, query: str, citations: Optional[list[dict]] = None, user_id: str,
        conversation_id: Optional[str] = None, max_actions: int = 5,
        idempotency_prefix: Optional[str] = None, context: str = "",
    ) -> dict[str, Any]:
        """Select and PREVIEW 1..N resolved actions for a multi-action plan (never
        executes). Returns ``{proposed, actions:[gate payloads]}`` — each action carries
        ``preview_status:"resolved"`` (all args known now). Parameterized actions (args
        derived from a prior action's output) + constraint envelopes are a later slice.

        ``context`` is the bounded evidence block the actions' arguments are grounded in."""
        from agents.retrieval_agent.live import build_action_catalog
        from connectors.mcp_client.types import ToolKind

        if not user_id:
            return {"proposed": False, "reason": "no_user", "actions": []}
        catalog = await build_action_catalog(user_id)
        if not catalog:
            return {"proposed": False, "reason": "no_action_tools_enabled", "actions": []}
        sels = await self._select_batch(query, catalog, max_actions, context)
        if not sels:
            return {"proposed": False, "reason": "no_action_warranted", "actions": []}

        actions: list[dict] = []
        for i, sel in enumerate(sels):
            gated_mode = "sdk" if sel.get("kind") == ToolKind.ACTION else "plain"
            pstatus = sel.get("preview_status", "resolved")
            try:
                prev = await gateway.preview_action(
                    connector_id=sel["connector_id"], capability=sel["tool"],
                    arguments=sel["arguments"], user_id=user_id, gated_mode=gated_mode,
                    idempotency_key=f"{idempotency_prefix}-{i}" if idempotency_prefix else None,
                    envelope=sel.get("envelope"), preview_status=pstatus,
                )
            except Exception as exc:
                logger.warning("Batch preview failed for %s/%s: %s", sel["connector"], sel["tool"], exc)
                continue  # skip an un-previewable action rather than failing the whole batch
            actions.append({
                "pending_id": prev["pending_id"], "connector": prev["connector"],
                "connector_id": sel["connector_id"], "gated_mode": gated_mode,
                "capability": prev["capability"], "arguments": sel["arguments"],
                "preview": prev["preview"], "reasoning": sel["reasoning"],
                "summary": sel.get("summary", ""), "preview_status": pstatus,
                "target": _salient_target(sel["arguments"]),
                "envelope": sel.get("envelope"), "index": i, "sources": citations or [],
            })
        if not actions:
            return {"proposed": False, "reason": "all_previews_failed", "actions": []}
        return {"proposed": True, "actions": actions}

    async def approve(self, *, pending_id: str, approver_id: str) -> dict[str, Any]:
        """Mint the single-use token and execute the previewed action exactly once.
        The gateway refuses execution without a valid token (the enforcement)."""
        try:
            tok = await gateway.approve_action(pending_id=pending_id, approver_id=approver_id)
            result = await gateway.execute_action(
                pending_id=pending_id, approval_token=tok["approval_token"], user_id=approver_id
            )
            return {"status": "executed", "result": result}
        except Exception as exc:
            logger.warning("Action execute failed for %s: %s", pending_id, exc)
            return {"status": "failed", "error": str(exc)}

    async def approve_with_args(self, *, pending_id: str, approver_id: str,
                                materialized_args: dict[str, Any]) -> dict[str, Any]:
        """Approve + execute a PARAMETERIZED action with its now-concrete arguments. The
        gateway diffs them against the approved envelope and refuses if they fall outside
        (status ``blocked`` → the run re-gates with a fresh concrete preview), spec §2.4."""
        from connectors.gateway.gateway import EnvelopeViolation
        try:
            tok = await gateway.approve_action(pending_id=pending_id, approver_id=approver_id)
            result = await gateway.execute_action(
                pending_id=pending_id, approval_token=tok["approval_token"],
                user_id=approver_id, materialized_args=materialized_args,
            )
            return {"status": "executed", "result": result}
        except EnvelopeViolation as exc:
            logger.info("Parameterized action %s blocked by envelope: %s", pending_id, exc)
            return {"status": "blocked", "error": str(exc)}
        except Exception as exc:
            logger.warning("Parameterized execute failed for %s: %s", pending_id, exc)
            return {"status": "failed", "error": str(exc)}

    async def summarize_result(self, *, action: dict[str, Any], result: Any) -> str:
        """After an action executes, produce a short grounded confirmation of what was
        done + the outcome — so the agent reports back instead of going silent. Uses the
        GENERATION slot; the result is treated as untrusted data. Returns '' on failure."""
        from agents.orchestrator.prompts import ACTION_REPORT_PROMPT

        payload = {
            "connector": action.get("connector"),
            "capability": action.get("capability"),
            "arguments": action.get("arguments"),
            "preview": action.get("preview"),
            "result": result,
        }
        llm = get_model(Slot.GENERATION)
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=ACTION_REPORT_PROMPT),
                HumanMessage(content=json.dumps(payload, default=str)[:6000]),
            ])
            return (resp.content if hasattr(resp, "content") else str(resp)).strip()
        except Exception as exc:
            logger.warning("Action report generation failed for %s: %s", action.get("capability"), exc)
            return ""

    async def reject(self, *, pending_id: str, approver_id: str) -> dict[str, Any]:
        try:
            await gateway.reject_action(pending_id=pending_id, approver_id=approver_id)
            return {"status": "rejected"}
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}


# ── Module-level singleton + registration ────────────────────
action_agent = ActionAgent()

register(
    SubAgentSpec(
        capability=Capability.ACTION,
        name=action_agent.name,
        handler=action_agent,
        description="Proposes and (after human approval) executes one gated action.",
    )
)

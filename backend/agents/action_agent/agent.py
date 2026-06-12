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
from agents.models import Slot, get_model
from agents.orchestrator.prompts import ACTION_SELECTION_PROMPT
from agents.registry import Capability, SubAgentSpec, register

logger = logging.getLogger(__name__)


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


class ActionAgent:
    """Proposes and (after approval) executes a single gated action."""

    name = "action_agent"
    capability = Capability.ACTION

    async def _select(self, query: str, catalog: list[dict]) -> Optional[dict]:
        """Ask the orchestration model to choose ONE action tool (or none). Validates
        the choice against the catalog; treats descriptions as untrusted."""
        view = [
            {"connector": c["connector"], "tool": c["tool"],
             "description": c["description"], "input_schema": c["input_schema"]}
            for c in catalog
        ]
        by_key = {(c["connector"], c["tool"]): c for c in catalog}
        llm = get_model(Slot.ORCHESTRATION)
        human = (
            f"User request:\n{query}\n\n"
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
    ) -> dict[str, Any]:
        """Select and PREVIEW one action (never executes). Returns the gate payload:
        preview + reasoning + cited sources + a ``pending_id`` to approve/reject."""
        from agents.retrieval_agent.live import build_action_catalog

        if not user_id:
            return {"proposed": False, "reason": "no_user"}
        catalog = await build_action_catalog(user_id)
        if not catalog:
            return {"proposed": False, "reason": "no_action_tools_enabled"}

        sel = await self._select(query, catalog)
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
            "sources": citations or [],
        }

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

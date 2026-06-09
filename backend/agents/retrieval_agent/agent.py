"""
Deep Query — Retrieval Sub-Agent (implementation)

Owns context gathering. Returns a unified, citation-tagged context set; it does not
generate the answer and does not act (guide §5.1).

Document path: wraps ``retrieval.pipeline.gather_context`` (the behavior-preserving
retrieval-only function shared with the chat pipeline). Live path (Phase 2): via the
Connector Gateway (``agents.retrieval_agent.live``). Both run in parallel and merge
into one citation set — document citations tagged ``source_type="document"`` (keeping
``source_number``), live citations tagged ``source_type="live"`` with a ``live_number``
so the answer cites [Source N] vs [Live N].
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from agents.registry import Capability, SubAgentSpec, register

logger = logging.getLogger(__name__)


class RetrievalAgent:
    """Gathers grounded context (document + live). Stateless; safe as a singleton."""

    name = "retrieval_agent"
    capability = Capability.RETRIEVAL

    async def gather(
        self,
        *,
        query: str,
        allowed_collections: list[str],
        chat_history: Optional[list] = None,
        image_base64: Optional[str] = None,
        user_id: str = "",
        conversation_id: Optional[str] = None,
        want_live: bool = False,
    ) -> dict[str, Any]:
        """Gather grounded context for a query.

        Runs the document path and (when ``want_live``) the live connector path in
        parallel, then merges them.

        Returns dict with: ``context_chunks``, ``live_records``, ``citations``
        (merged + tagged), ``graph_context``, ``chunks_retrieved``, ``live_count``,
        ``tool_activity`` (per-source activity lines), and ``error`` (document path
        only) when retrieval failed.
        """
        from retrieval.pipeline import gather_context

        async def _doc():
            return await gather_context(
                query=query,
                allowed_collections=allowed_collections,
                image_base64=image_base64,
                chat_history=chat_history,
            )

        async def _live():
            if not want_live or not user_id:
                return {"records": [], "citations": [], "tool_activity": []}
            from agents.retrieval_agent.live import gather_live
            return await gather_live(
                query=query, user_id=user_id, conversation_id=conversation_id
            )

        ctx, live = await asyncio.gather(_doc(), _live())

        tool_activity: list[dict] = []
        citations: list[dict] = []
        context_chunks: list[dict] = []
        graph_context = ""
        chunks_retrieved = 0
        error = None

        # ── Document path ──
        if ctx.get("error"):
            logger.warning("Document retrieval failed: %s", ctx.get("error"))
            error = ctx["error"]
            tool_activity.append({"tool": "document_search", "detail": "retrieval unavailable", "status": "error"})
        else:
            context_chunks = ctx.get("formatted_chunks", [])
            graph_context = ctx.get("graph_context", "")
            chunks_retrieved = ctx.get("chunks_retrieved", 0)
            for c in ctx.get("citations", []):
                citations.append({**c, "source_type": "document"})
            tool_activity.append({
                "tool": "document_search",
                "detail": f"{chunks_retrieved} relevant passage(s)",
                "status": "ok",
            })

        # ── Live path ── (records and citations are parallel-indexed)
        live_records: list[dict] = []
        for i, (rec, cit) in enumerate(
            zip(live.get("records", []), live.get("citations", [])), 1
        ):
            live_records.append({**rec, "live_number": i})
            citations.append({**cit, "source_type": "live", "live_number": i})
        tool_activity.extend(live.get("tool_activity", []))

        result: dict[str, Any] = {
            "context_chunks": context_chunks,
            "live_records": live_records,
            "citations": citations,
            "graph_context": graph_context,
            "chunks_retrieved": chunks_retrieved,
            "live_count": len(live_records),
            "tool_activity": tool_activity,
        }
        if error:
            result["error"] = error
        return result


# ── Module-level singleton + registration ────────────────────
retrieval_agent = RetrievalAgent()

register(
    SubAgentSpec(
        capability=Capability.RETRIEVAL,
        name=retrieval_agent.name,
        handler=retrieval_agent,
        description="Gathers grounded context: document path + live connector path.",
    )
)

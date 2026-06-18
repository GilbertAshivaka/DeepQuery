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


def _extract_whole_doc(document_id: str) -> tuple[str, str]:
    """Re-parse a corpus document's full text (sync; runs in an executor)."""
    from core.database import SessionLocal
    from agents.documents import extract_document_text
    db = SessionLocal()
    try:
        return extract_document_text(db, document_id)
    except Exception as exc:
        logger.warning("Whole-doc extraction failed for %s: %s", document_id, exc)
        return ("", "")
    finally:
        db.close()


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
        want_documents: bool = True,
        want_live: bool = False,
        want_whole_doc: bool = False,
        attachments: Optional[list[dict]] = None,
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
            if not want_documents:
                return None  # intent doesn't call for the corpus — skip the search entirely
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

        # ── Document path ── (only when the intent calls for the corpus; ctx is None
        # when the search was skipped, so no misleading "0 passages" activity appears)
        if ctx is not None:
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

        # ── Whole-document expansion ── when the retrieved chunks concentrate on a
        # single corpus document, pull its full extracted text (re-parsed on demand)
        # so the model has complete context, not just fragments.
        whole_documents: list[dict] = []
        if want_whole_doc and context_chunks:
            from collections import Counter
            ids = [c.get("document_id") for c in context_chunks if c.get("document_id")]
            if ids:
                top_id, count = Counter(ids).most_common(1)[0]
                # Expand when at least 2 retrieved chunks come from the same document
                # (signals the query is centred on it). Token-capped, so cost is bounded.
                if top_id and count >= 2:
                    loop = asyncio.get_event_loop()
                    title, text = await loop.run_in_executor(None, _extract_whole_doc, top_id)
                    if text:
                        n = len([w for w in whole_documents]) + 1
                        whole_documents.append({"document_id": top_id, "title": title, "text": text})
                        citations.append({
                            "source_type": "document_full", "doc_number": n,
                            "document_name": title, "document_id": top_id,
                        })
                        tool_activity.append({
                            "tool": "document_expand", "detail": f"loaded full text of '{title}'", "status": "ok",
                        })

        # ── User-attached documents ── (this-turn context, parsed text)
        attachment_ctx: list[dict] = []
        for i, att in enumerate(attachments or [], 1):
            text = (att.get("text") or "").strip()
            if not text:
                continue  # images carry no text for the (text-only) generator yet
            attachment_ctx.append({"attachment_number": i, "filename": att.get("filename", f"attachment-{i}"), "text": text})
            citations.append({
                "source_type": "attachment", "attachment_number": i,
                "filename": att.get("filename", f"attachment-{i}"),
            })

        result: dict[str, Any] = {
            "context_chunks": context_chunks,
            "live_records": live_records,
            "whole_documents": whole_documents,
            "attachments": attachment_ctx,
            "citations": citations,
            "graph_context": graph_context,
            "chunks_retrieved": chunks_retrieved,
            "live_count": len(live_records),
            "tool_activity": tool_activity,
            # Connectors that failed this gather (discovery/execution) — the controller
            # reports these and stops retrying the broken tool (spec §6).
            "tool_errors": live.get("tool_errors", []),
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

"""
Deep Query — Chat / RAG LLM Client

The main user-facing chat path: RAG generation, self-correction, entity extraction,
metadata generation. Provider-agnostic — every call resolves through the shared model
factory via ``Slot.CHAT`` (``agents/models/slots.py``), so the vendor/model is a
configuration choice (``agent_chat_provider`` / ``agent_chat_model``). Defaults preserve
the historical behavior exactly: Groq Llama 3.3 70B.
"""

import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from agents.models import Slot, get_model
from core.constants import LLM_TEMPERATURES
from llm.prompts import (
    ENTITY_EXTRACTION_PROMPT,
    METADATA_GENERATION_PROMPT,
    QUERY_ENTITY_EXTRACTION_PROMPT,
    RAG_GENERATION_PROMPT,
    SELF_CORRECTION_PROMPT,
)

logger = logging.getLogger(__name__)


class GroqClient:
    """Chat/RAG LLM operations, routed through the provider-agnostic model factory.

    (Name retained for back-compat with existing imports; the underlying provider is
    no longer hard-wired to Groq — see ``Slot.CHAT``.)
    """

    MAX_RETRIES = 3
    BASE_BACKOFF = 1.0

    def _get_llm(
        self, temperature: float, streaming: bool = False, slot: Slot = Slot.CHAT
    ) -> BaseChatModel:
        """Resolve the model for a given slot + temperature via the shared factory.

        The classic pipeline routes each workload to its own slot so they can be
        configured to different vendors/models (generation vs. self-correction vs.
        extraction)."""
        return get_model(slot, streaming=streaming, temperature=temperature)

    def _call_with_retry(
        self, messages: list, temperature: float, slot: Slot = Slot.CHAT
    ) -> Optional[str]:
        """Call the model for ``slot`` with retry and exponential backoff.

        Always returns text, never raw content blocks: ``AIMessage.content`` is a list of
        typed blocks (not a ``str``) whenever the reply carries a thinking block, which
        would break every caller here — they all treat the result as a string. Thinking is
        dropped; only answer text is returned."""
        from agents.models.reasoning import message_text

        llm = self._get_llm(temperature, slot=slot)

        for attempt in range(self.MAX_RETRIES):
            try:
                response = llm.invoke(messages)
                return message_text(response)
            except Exception as e:
                wait = self.BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    f"Chat LLM attempt {attempt + 1} failed: {e}. Retrying in {wait}s..."
                )
                time.sleep(wait)

        logger.error(f"Chat LLM call failed after {self.MAX_RETRIES} attempts.")
        return None

    # ── RAG Generation ───────────────────────────────────────

    @staticmethod
    def _assemble_context(
        context_chunks: List[Dict[str, Any]],
        graph_context: str = "",
        whole_documents: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Build the source context block — [Source N] passages, [Knowledge Graph Context],
        [Doc N] full documents, [Attachment N] user files. Shared by the blocking and the
        streaming generators so they never drift."""
        parts = [
            f"[Source {i}] (Document: {c.get('source', 'Unknown')}, "
            f"Page: {c.get('page', 'N/A')})\n{c.get('text', '')}"
            for i, c in enumerate(context_chunks, 1)
        ]
        context = "\n\n".join(parts)
        if graph_context:
            context += f"\n\n[Knowledge Graph Context]\n{graph_context}"
        for i, w in enumerate(whole_documents or [], 1):
            context += f"\n\n[Doc {i}] (Full document: {w.get('title', 'Unknown')})\n{w.get('text', '')}"
        for i, att in enumerate(attachments or [], 1):
            text = (att.get("text") or "").strip()
            if text:
                context += (
                    f"\n\n[Attachment {i}] (User-provided: {att.get('filename', f'attachment-{i}')})\n{text}"
                )
        return context

    @staticmethod
    def _rag_messages(query: str, context: str, chat_history: Optional[list] = None) -> list:
        """Assemble the prompt messages (system + prior turns + context/question)."""
        messages = [SystemMessage(content=RAG_GENERATION_PROMPT)]
        for turn in chat_history or []:
            if turn.get("role") == "user":
                messages.append(HumanMessage(content=turn.get("content", "")))
            elif turn.get("role") == "assistant":
                messages.append(SystemMessage(content=turn.get("content", "")))
        messages.append(HumanMessage(content=f"Context:\n{context}\n\nQuestion: {query}"))
        return messages

    def generate_answer(
        self,
        query: str,
        context_chunks: List[Dict[str, Any]],
        graph_context: str = "",
        chat_history: Optional[list] = None,
        whole_documents: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """Generate a RAG answer (blocking) with [Source N] / [Doc N] / [Attachment N]
        citations. Kept for non-streaming callers; the chat endpoint streams instead."""
        context = self._assemble_context(context_chunks, graph_context, whole_documents, attachments)
        messages = self._rag_messages(query, context, chat_history)
        return self._call_with_retry(messages, LLM_TEMPERATURES["rag_generation"])

    async def generate_answer_stream(
        self,
        query: str,
        context_chunks: List[Dict[str, Any]],
        graph_context: str = "",
        chat_history: Optional[list] = None,
        whole_documents: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream RAG answer tokens for SSE — same context/citations as ``generate_answer``,
        emitted token-by-token so the chat shows text immediately (matching the agent).
        Reasoning deltas (if the chat slot is a reasoning model) are dropped; only answer
        text is yielded."""
        from agents.models.reasoning import extract_text_delta

        context = self._assemble_context(context_chunks, graph_context, whole_documents, attachments)
        messages = self._rag_messages(query, context, chat_history)
        llm = self._get_llm(LLM_TEMPERATURES["rag_generation"], streaming=True)
        async for chunk in llm.astream(messages):
            text = extract_text_delta(chunk)
            if text:
                yield text

    # ── Self-Correction ──────────────────────────────────────

    def verify_answer(
        self,
        query: str,
        answer: str,
        context_chunks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Verify and potentially correct a generated answer.

        Returns:
            dict with 'outcome' (VERIFIED/CORRECTED/INSUFFICIENT_CONTEXT),
            'corrected_answer' (if corrected), and 'explanation'.
        """
        formatted_sources = []
        for i, chunk in enumerate(context_chunks, 1):
            formatted_sources.append(
                f"[Source {i}]\n{chunk.get('text', '')}"
            )
        context = "\n\n".join(formatted_sources)

        messages = [
            SystemMessage(content=SELF_CORRECTION_PROMPT),
            HumanMessage(
                content=(
                    f"Original Question: {query}\n\n"
                    f"Generated Answer:\n{answer}\n\n"
                    f"Source Context:\n{context}"
                )
            ),
        ]

        response = self._call_with_retry(
            messages, LLM_TEMPERATURES["self_correction"], slot=Slot.SELF_CORRECTION
        )

        if response is None:
            return {"outcome": "VERIFIED", "corrected_answer": answer, "explanation": "Verification unavailable."}

        # Strip markdown code fences if present
        cleaned = response.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.index("\n") if "\n" in cleaned else 3
            cleaned = cleaned[first_newline + 1:]
            # Remove closing fence
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        # Parse structured response
        try:
            result = json.loads(cleaned)
            return result
        except json.JSONDecodeError:
            # If the LLM didn't return JSON, try to parse outcome from text
            response_upper = response.upper()
            if '"OUTCOME": "CORRECTED"' in response_upper or '"OUTCOME":"CORRECTED"' in response_upper:
                return {"outcome": "CORRECTED", "corrected_answer": response, "explanation": ""}
            elif "INSUFFICIENT_CONTEXT" in response_upper:
                return {"outcome": "INSUFFICIENT_CONTEXT", "corrected_answer": "", "explanation": response}
            return {"outcome": "VERIFIED", "corrected_answer": answer, "explanation": ""}

    # ── Entity Extraction ────────────────────────────────────

    def extract_entities(self, text: str) -> Optional[Dict]:
        """Extract named entities and relationships from a text chunk.

        Returns:
            dict with 'entities' list and 'relationships' list,
            or None on failure.
        """
        if len(text.strip()) < 30:
            return None

        messages = [
            SystemMessage(content=ENTITY_EXTRACTION_PROMPT),
            HumanMessage(content=text),
        ]

        response = self._call_with_retry(
            messages, LLM_TEMPERATURES["entity_extraction"], slot=Slot.EXTRACTION
        )

        if response is None:
            return None

        try:
            # Try to parse JSON from the response
            # Handle case where LLM wraps JSON in markdown code blocks
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])

            result = json.loads(cleaned)
            return result
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse entity extraction JSON: {response[:200]}")
            return None

    # ── Metadata Generation ──────────────────────────────────

    def generate_metadata(self, text: str) -> Optional[Dict]:
        """Generate summary, tags, and category for a text chunk.

        Returns:
            dict with 'summary', 'topic_tags', 'category', 'category_confidence'.
        """
        if len(text.strip()) < 20:
            return None

        messages = [
            SystemMessage(content=METADATA_GENERATION_PROMPT),
            HumanMessage(content=text),
        ]

        response = self._call_with_retry(
            messages, LLM_TEMPERATURES["metadata_generation"], slot=Slot.EXTRACTION
        )

        if response is None:
            return None

        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse metadata JSON: {response[:200]}")
            return {"summary": "", "topic_tags": [], "category": "other", "category_confidence": 0.0}

    # ── Query Entity Extraction (for graph lookup) ───────────

    def extract_query_entities(self, query: str) -> List[str]:
        """Extract entity names mentioned in a user query for graph lookup."""
        messages = [
            SystemMessage(content=QUERY_ENTITY_EXTRACTION_PROMPT),
            HumanMessage(content=query),
        ]

        response = self._call_with_retry(
            messages, LLM_TEMPERATURES["entity_extraction"], slot=Slot.EXTRACTION
        )

        if response is None:
            return []

        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])
            result = json.loads(cleaned)
            return result.get("entities", [])
        except json.JSONDecodeError:
            # Fallback: split by commas
            return [e.strip().strip('"') for e in response.split(",") if e.strip()]


# ── Module-level singleton ───────────────────────────────────
groq_client = GroqClient()

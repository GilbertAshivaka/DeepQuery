"""
Deep Query — Groq / Llama 3 Client

All LLM calls go through Groq API using llama-3.3-70b-versatile.
Supports: RAG generation, self-correction, entity extraction, metadata generation.
"""

import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from core.config import settings
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
    """Wrapper around Groq API for all LLM operations."""

    MAX_RETRIES = 3
    BASE_BACKOFF = 1.0

    def __init__(self):
        self.model = settings.llm_model

    def _get_llm(self, temperature: float, streaming: bool = False) -> ChatGroq:
        """Create a ChatGroq instance with specified settings."""
        return ChatGroq(
            model=self.model,
            api_key=settings.groq_api_key,
            temperature=temperature,
            streaming=streaming,
            max_tokens=4096,
        )

    def _call_with_retry(
        self, messages: list, temperature: float
    ) -> Optional[str]:
        """Call LLM with retry and exponential backoff."""
        llm = self._get_llm(temperature)

        for attempt in range(self.MAX_RETRIES):
            try:
                response = llm.invoke(messages)
                return response.content
            except Exception as e:
                wait = self.BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    f"Groq API attempt {attempt + 1} failed: {e}. Retrying in {wait}s..."
                )
                time.sleep(wait)

        logger.error(f"Groq API call failed after {self.MAX_RETRIES} attempts.")
        return None

    # ── RAG Generation ───────────────────────────────────────

    def generate_answer(
        self,
        query: str,
        context_chunks: List[Dict[str, Any]],
        graph_context: str = "",
    ) -> Optional[str]:
        """Generate a RAG answer with citations.

        Args:
            query: User's question.
            context_chunks: List of dicts with 'text', 'source', 'page', 'summary'.
            graph_context: Natural-language summary from knowledge graph traversal.

        Returns:
            Generated answer with [Source N] citations.
        """
        # Format context chunks for the prompt
        formatted_sources = []
        for i, chunk in enumerate(context_chunks, 1):
            source_text = (
                f"[Source {i}] (Document: {chunk.get('source', 'Unknown')}, "
                f"Page: {chunk.get('page', 'N/A')})\n{chunk.get('text', '')}"
            )
            formatted_sources.append(source_text)

        context = "\n\n".join(formatted_sources)
        if graph_context:
            context += f"\n\n[Knowledge Graph Context]\n{graph_context}"

        messages = [
            SystemMessage(content=RAG_GENERATION_PROMPT),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {query}"),
        ]

        return self._call_with_retry(
            messages, LLM_TEMPERATURES["rag_generation"]
        )

    async def generate_answer_stream(
        self,
        query: str,
        context_chunks: List[Dict[str, Any]],
        graph_context: str = "",
    ) -> AsyncGenerator[str, None]:
        """Stream RAG answer tokens for SSE."""
        formatted_sources = []
        for i, chunk in enumerate(context_chunks, 1):
            source_text = (
                f"[Source {i}] (Document: {chunk.get('source', 'Unknown')}, "
                f"Page: {chunk.get('page', 'N/A')})\n{chunk.get('text', '')}"
            )
            formatted_sources.append(source_text)

        context = "\n\n".join(formatted_sources)
        if graph_context:
            context += f"\n\n[Knowledge Graph Context]\n{graph_context}"

        llm = self._get_llm(
            LLM_TEMPERATURES["rag_generation"], streaming=True
        )
        messages = [
            SystemMessage(content=RAG_GENERATION_PROMPT),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {query}"),
        ]

        async for chunk in llm.astream(messages):
            if chunk.content:
                yield chunk.content

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
            messages, LLM_TEMPERATURES["self_correction"]
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
            messages, LLM_TEMPERATURES["entity_extraction"]
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
            messages, LLM_TEMPERATURES["metadata_generation"]
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
            messages, LLM_TEMPERATURES["entity_extraction"]
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

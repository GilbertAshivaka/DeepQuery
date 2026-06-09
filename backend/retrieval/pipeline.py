"""
Deep Query — Retrieval Pipeline

Orchestrates the full query → answer flow with parallel execution:
1. Group A (parallel): Embed query, BM25 search, Entity extraction
2. Group B (parallel): Dense retrieval, Graph traversal
3. Group C (sequential): RRF fusion, Cross-encoder reranking
4. Group D (sequential): RAG generation, Self-correction
"""

import asyncio
import json
import logging
import math
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.constants import (
    COSINE_SIMILARITY_THRESHOLD,
    DENSE_TOP_K,
    FINAL_CONTEXT_CHUNKS,
    MIN_RERANK_CANDIDATES,
    RERANK_TOP_N,
    SPARSE_TOP_K,
)

logger = logging.getLogger(__name__)


def apply_cosine_similarity_filter(
    candidates: List[Dict],
    threshold: float,
    min_candidates: int,
) -> List[Dict]:
    """Filter candidates by cosine similarity threshold before reranking.

    ChromaDB returns cosine distance (0 = identical, 2 = opposite).
    We convert to similarity: similarity = 1 - (distance / 2)

    Args:
        candidates: List of retrieval candidates from RRF fusion.
        threshold: Minimum cosine similarity to keep (e.g., 0.45).
        min_candidates: Minimum number of candidates to return even if below threshold.

    Returns:
        Filtered list of candidates.
    """
    # Attach cosine similarity scores to each candidate
    for candidate in candidates:
        distance = candidate.get("distance", 1.0)
        # Convert cosine distance to similarity (normalize to 0-1 range)
        # ChromaDB cosine distance is in [0, 2], where 0 = identical
        candidate["cosine_similarity"] = 1.0 - (distance / 2.0)

    # Filter by threshold
    above_threshold = [
        c for c in candidates if c.get("cosine_similarity", 0.0) >= threshold
    ]

    # If we have enough candidates above threshold, return them
    if len(above_threshold) >= min_candidates:
        return above_threshold

    # Otherwise, return top N by cosine similarity regardless of threshold
    logger.warning(
        f"Only {len(above_threshold)} candidates above threshold {threshold}. "
        f"Relaxing to top {min_candidates * 2} by similarity."
    )
    sorted_by_similarity = sorted(
        candidates, key=lambda x: x.get("cosine_similarity", 0.0), reverse=True
    )
    return sorted_by_similarity[: min_candidates * 2]


async def gather_context(
    query: str,
    allowed_collections: List[str],
    image_base64: Optional[str] = None,
    chat_history: Optional[list] = None,
) -> Dict[str, Any]:
    """Run the retrieval-only path (no answer generation).

    Embed → hybrid retrieve (dense + BM25) → RRF fuse → pre-filter → rerank →
    format chunks → build document citations, plus knowledge-graph context.

    Shared by two callers:
    - ``retrieval_pipeline`` (the chat path), which then generates with Groq/Llama.
    - the Agent Layer's Retrieval Sub-Agent, which assembles dual-source context and
      lets the Orchestrator drive generation via its own model slot.

    Returns:
        dict with 'formatted_chunks', 'citations', 'graph_context',
        'chunks_retrieved', 'query', 'retrieval_time_ms' — or {'error': str} if the
        query could not be embedded.
    """
    from embeddings.gemini_embedder import gemini_embedder
    from knowledge_graph.neo4j_client import neo4j_client
    from llm.groq_client import groq_client
    from retrieval.bm25_retriever import bm25_retriever
    from retrieval.reranker import reranker
    from vectorstore.chroma_store import chroma_store

    start = time.time()

    # ── GROUP A: Parallel execution (embedding, BM25, entity extraction) ──
    logger.info("Group A: Embedding, BM25 search, entity extraction (parallel)")

    async def embed_query_task():
        """Task: Embed the query using Gemini."""
        loop = asyncio.get_event_loop()
        if image_base64:
            import base64
            image_bytes = base64.b64decode(image_base64)
            return await loop.run_in_executor(
                None, gemini_embedder.embed_multimodal, query, image_bytes
            )
        else:
            return await loop.run_in_executor(
                None, gemini_embedder.embed_text, query, "RETRIEVAL_QUERY"
            )

    async def bm25_search_task():
        """Task: BM25 sparse retrieval."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, bm25_retriever.search, query, allowed_collections, SPARSE_TOP_K
        )

    async def entity_extraction_task():
        """Task: Extract entities from query for graph traversal."""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None, groq_client.extract_query_entities, query
            )
        except Exception as e:
            logger.warning(f"Entity extraction failed: {e}")
            return []

    # Run Group A in parallel
    query_embedding, sparse_results, entity_names = await asyncio.gather(
        embed_query_task(),
        bm25_search_task(),
        entity_extraction_task(),
    )

    if query_embedding is None:
        return {"error": "query_embedding_failed"}

    # ── GROUP B: Parallel execution (dense search, graph traversal) ──
    logger.info("Group B: Dense retrieval, graph traversal (parallel)")

    async def dense_search_task():
        """Task: ChromaDB dense vector search."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            chroma_store.query_multiple_collections,
            allowed_collections,
            query_embedding,
            DENSE_TOP_K,
        )

    async def graph_traversal_task():
        """Task: Neo4j graph context retrieval."""
        loop = asyncio.get_event_loop()
        try:
            if entity_names:
                return await loop.run_in_executor(
                    None, neo4j_client.get_entity_context, entity_names
                )
            return ""
        except Exception as e:
            logger.warning(f"Graph traversal failed: {e}")
            return ""

    # Run Group B in parallel
    dense_results, graph_context = await asyncio.gather(
        dense_search_task(),
        graph_traversal_task(),
    )

    # ── GROUP C: Sequential execution (RRF, reranking, context assembly) ──
    logger.info("Group C: RRF fusion, pre-filter, reranking (sequential)")

    # RRF fusion
    fused_results = reciprocal_rank_fusion(dense_results, sparse_results)

    # Pre-filter: Remove candidates with low cosine similarity
    filtered_results = apply_cosine_similarity_filter(
        fused_results, COSINE_SIMILARITY_THRESHOLD, MIN_RERANK_CANDIDATES
    )
    logger.info(
        f"Pre-filter: {len(fused_results)} → {len(filtered_results)} candidates "
        f"(threshold={COSINE_SIMILARITY_THRESHOLD})"
    )

    # Cross-encoder reranking
    loop = asyncio.get_event_loop()
    reranked = await loop.run_in_executor(
        None, reranker.rerank, query, filtered_results, RERANK_TOP_N
    )

    # Select top chunks for context
    context_chunks = reranked[:FINAL_CONTEXT_CHUNKS]

    # Format chunks for the LLM
    formatted_chunks = []
    for chunk in context_chunks:
        meta = chunk.get("metadata", {})
        # Normalise rerank_score to 0-1 via sigmoid; fall back to cosine_similarity
        raw_rerank = chunk.get("rerank_score")
        if raw_rerank is not None:
            relevance = round(1.0 / (1.0 + math.exp(-float(raw_rerank))), 3)
        else:
            relevance = round(float(chunk.get("cosine_similarity", 0.5)), 3)
        formatted_chunks.append({
            "text": chunk.get("document", chunk.get("text", "")),
            "source": meta.get("original_filename", "Unknown"),
            "page": meta.get("page_number", "N/A"),
            "summary": meta.get("summary", ""),
            "document_id": meta.get("source_document_id", ""),
            "relevance_score": relevance,
        })

    # ── Build document citations ─────────────────────────────
    citations = []
    for i, chunk in enumerate(formatted_chunks, 1):
        citations.append({
            "source_number": i,
            "document_name": chunk["source"],
            "page_number": chunk["page"],
            "chunk_summary": chunk["summary"],
            "document_id": chunk["document_id"],
            "relevance_score": chunk.get("relevance_score", 0.5),
        })

    elapsed = time.time() - start
    logger.info(f"Context gathering completed in {elapsed:.2f}s")

    return {
        "formatted_chunks": formatted_chunks,
        "citations": citations,
        "graph_context": graph_context,
        "chunks_retrieved": len(context_chunks),
        "query": query,
        "retrieval_time_ms": int(elapsed * 1000),
    }


async def retrieval_pipeline(
    query: str,
    allowed_collections: List[str],
    image_base64: Optional[str] = None,
    chat_history: Optional[list] = None,
) -> Dict[str, Any]:
    """Execute the full retrieval + generation pipeline (the chat path).

    Gathers context via ``gather_context`` then generates the answer with the
    Groq/Llama client — unchanged behavior for the existing chat endpoint.

    Returns:
        dict with 'answer', 'citations', 'formatted_chunks', 'query',
        'self_correction_status', 'related_documents', 'chunks_retrieved',
        'retrieval_time_ms'.
    """
    from llm.groq_client import groq_client

    ctx = await gather_context(query, allowed_collections, image_base64, chat_history)

    if ctx.get("error"):
        return {
            "answer": "I'm sorry, I encountered an error processing your query. Please try again.",
            "citations": [],
            "self_correction_status": "ERROR",
            "related_documents": [],
            "chunks_retrieved": 0,
        }

    formatted_chunks = ctx["formatted_chunks"]

    # RAG generation (Groq/Llama) — runs in executor to stay non-blocking.
    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(
        None,
        groq_client.generate_answer,
        query,
        formatted_chunks,
        ctx["graph_context"],
        chat_history,
    )

    if answer is None:
        answer = "I'm sorry, I was unable to generate an answer. Please try again."

    return {
        "answer": answer,
        "citations": ctx["citations"],
        "formatted_chunks": formatted_chunks,  # For self-correction
        "query": query,  # For self-correction
        "self_correction_status": "PENDING",  # Will be verified in background
        "related_documents": [],
        "chunks_retrieved": ctx["chunks_retrieved"],
        "retrieval_time_ms": ctx["retrieval_time_ms"],
    }


async def search_pipeline(
    query: str,
    allowed_collections: List[str],
    document_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    topic_tags: Optional[List[str]] = None,
    page: int = 1,
    per_page: int = 10,
) -> Dict:
    """Search pipeline for the dashboard (no LLM generation) with parallel execution.

    Returns structured results with relevance scores.
    """
    from embeddings.gemini_embedder import gemini_embedder
    from retrieval.bm25_retriever import bm25_retriever
    from retrieval.reranker import reranker
    from vectorstore.chroma_store import chroma_store

    loop = asyncio.get_event_loop()

    # Build metadata filter
    where_filter = {}
    if document_type:
        where_filter["document_type"] = document_type

    # Parallel execution: Embed query and BM25 search
    async def embed_task():
        return await loop.run_in_executor(
            None, gemini_embedder.embed_text, query, "RETRIEVAL_QUERY"
        )

    async def bm25_task():
        return await loop.run_in_executor(
            None, bm25_retriever.search, query, allowed_collections, SPARSE_TOP_K
        )

    query_embedding, sparse_results = await asyncio.gather(embed_task(), bm25_task())

    if query_embedding is None:
        return {"results": [], "total": 0, "query": query}

    # Dense retrieval with filters
    dense_results = await loop.run_in_executor(
        None,
        chroma_store.query_multiple_collections,
        allowed_collections,
        query_embedding,
        DENSE_TOP_K * 2,
        where_filter if where_filter else None,
    )

    # RRF + Rerank
    fused = reciprocal_rank_fusion(dense_results, sparse_results)
    reranked = reranker.rerank(query, fused, top_n=per_page * 2)

    # Paginate
    start_idx = (page - 1) * per_page
    page_results = reranked[start_idx : start_idx + per_page]

    # Format results
    results = []
    for item in page_results:
        meta = item.get("metadata", {})
        tags = []
        try:
            tags = json.loads(meta.get("topic_tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            pass

        results.append({
            "chunk_text": item.get("document", item.get("text", ""))[:500],
            "document_name": meta.get("original_filename", "Unknown"),
            "document_id": meta.get("source_document_id", ""),
            "page_number": meta.get("page_number"),
            "topic_tags": tags,
            "relevance_score": round(item.get("rrf_score", item.get("rerank_score", 0.0)), 4),
            "summary": meta.get("summary", ""),
        })

    return {
        "results": results,
        "total": len(reranked),
        "query": query,
    }


def reciprocal_rank_fusion(
    dense_results: List[Dict],
    sparse_results: List[Dict],
    k: int = 60,
) -> List[Dict]:
    """Merge two ranked lists using Reciprocal Rank Fusion.

    RRF score for each document = sum(1 / (k + rank_i)) across all lists
    where rank_i is the rank in list i (1-indexed).

    Args:
        dense_results: Results from vector similarity search.
        sparse_results: Results from BM25 keyword search.
        k: RRF constant (default 60, standard value).

    Returns:
        Merged and re-sorted list of results.
    """
    scores: Dict[str, float] = {}
    result_map: Dict[str, Dict] = {}

    # Score dense results
    for rank, item in enumerate(dense_results, 1):
        doc_id = item.get("id", "")
        if doc_id:
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            result_map[doc_id] = item

    # Score sparse results
    for rank, item in enumerate(sparse_results, 1):
        doc_id = item.get("id", "")
        if doc_id:
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            if doc_id not in result_map:
                result_map[doc_id] = item

    # Sort by RRF score (descending)
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    fused = []
    for doc_id in sorted_ids:
        item = result_map[doc_id]
        item["rrf_score"] = scores[doc_id]
        fused.append(item)

    return fused

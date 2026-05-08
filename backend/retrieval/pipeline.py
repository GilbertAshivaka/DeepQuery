"""
Deep Query — Retrieval Pipeline

Orchestrates the full query → answer flow:
1. Embed query (Gemini Embedding 2)
2. Dense retrieval (ChromaDB) + Sparse retrieval (BM25)
3. Reciprocal Rank Fusion
4. Cross-encoder reranking
5. Knowledge graph augmentation (Neo4j)
6. RAG generation (Llama 3 via Groq)
7. Self-correction verification
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.constants import (
    DENSE_TOP_K,
    FINAL_CONTEXT_CHUNKS,
    RERANK_TOP_N,
    SPARSE_TOP_K,
)

logger = logging.getLogger(__name__)


async def retrieval_pipeline(
    query: str,
    allowed_collections: List[str],
    image_base64: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute the full retrieval + generation pipeline.

    Args:
        query: User's natural-language question.
        allowed_collections: ChromaDB collections the user can access.
        image_base64: Optional base64 image for multimodal query.

    Returns:
        dict with 'answer', 'citations', 'self_correction_status',
        'related_documents', 'chunks_retrieved'.
    """
    from embeddings.gemini_embedder import gemini_embedder
    from knowledge_graph.neo4j_client import neo4j_client
    from llm.groq_client import groq_client
    from retrieval.bm25_retriever import bm25_retriever
    from retrieval.reranker import reranker
    from vectorstore.chroma_store import chroma_store

    start = time.time()

    # ── Step 1: Embed the query ──────────────────────────────
    logger.info("Step 1: Embedding query")
    if image_base64:
        import base64
        image_bytes = base64.b64decode(image_base64)
        query_embedding = gemini_embedder.embed_multimodal(query, image_bytes)
    else:
        query_embedding = gemini_embedder.embed_text(query, task_type="RETRIEVAL_QUERY")

    if query_embedding is None:
        return {
            "answer": "I'm sorry, I encountered an error processing your query. Please try again.",
            "citations": [],
            "self_correction_status": "ERROR",
            "related_documents": [],
            "chunks_retrieved": 0,
        }

    # ── Step 2a: Dense retrieval (ChromaDB) ──────────────────
    logger.info("Step 2a: Dense retrieval")
    dense_results = chroma_store.query_multiple_collections(
        collection_names=allowed_collections,
        query_embedding=query_embedding,
        n_results=DENSE_TOP_K,
    )

    # ── Step 2b: Sparse retrieval (BM25) ─────────────────────
    logger.info("Step 2b: Sparse retrieval")
    sparse_results = bm25_retriever.search(
        query=query,
        allowed_collections=allowed_collections,
        top_k=SPARSE_TOP_K,
    )

    # ── Step 3: Reciprocal Rank Fusion ───────────────────────
    logger.info("Step 3: RRF fusion")
    fused_results = reciprocal_rank_fusion(dense_results, sparse_results)

    # ── Step 4: Reranking ────────────────────────────────────
    logger.info("Step 4: Cross-encoder reranking")
    reranked = reranker.rerank(query, fused_results, top_n=RERANK_TOP_N)

    # ── Step 5: Knowledge graph augmentation ─────────────────
    logger.info("Step 5: Knowledge graph augmentation")
    graph_context = ""
    try:
        entity_names = groq_client.extract_query_entities(query)
        if entity_names:
            graph_context = neo4j_client.get_entity_context(entity_names)
    except Exception as e:
        logger.warning(f"Graph augmentation failed: {e}")

    # ── Step 6: RAG generation ───────────────────────────────
    logger.info("Step 6: RAG generation")
    context_chunks = reranked[:FINAL_CONTEXT_CHUNKS]

    # Format chunks for the LLM
    formatted_chunks = []
    for chunk in context_chunks:
        meta = chunk.get("metadata", {})
        formatted_chunks.append({
            "text": chunk.get("document", chunk.get("text", "")),
            "source": meta.get("original_filename", "Unknown"),
            "page": meta.get("page_number", "N/A"),
            "summary": meta.get("summary", ""),
            "document_id": meta.get("source_document_id", ""),
        })

    answer = groq_client.generate_answer(
        query=query,
        context_chunks=formatted_chunks,
        graph_context=graph_context,
    )

    if answer is None:
        answer = "I'm sorry, I was unable to generate an answer. Please try again."

    # ── Step 7: Self-correction ──────────────────────────────
    logger.info("Step 7: Self-correction")
    correction_result = groq_client.verify_answer(
        query=query,
        answer=answer,
        context_chunks=formatted_chunks,
    )

    outcome = correction_result.get("outcome", "VERIFIED")
    if outcome == "CORRECTED":
        answer = correction_result.get("corrected_answer", answer)
    elif outcome == "INSUFFICIENT_CONTEXT":
        answer = (
            "Based on the available documents, I could not find sufficient "
            "information to fully answer this question.\n\n"
            + correction_result.get("explanation", "")
        )

    # ── Build citations ──────────────────────────────────────
    citations = []
    for i, chunk in enumerate(formatted_chunks, 1):
        citations.append({
            "source_number": i,
            "document_name": chunk["source"],
            "page_number": chunk["page"],
            "chunk_summary": chunk["summary"],
            "document_id": chunk["document_id"],
        })

    elapsed = time.time() - start
    logger.info(f"Retrieval pipeline completed in {elapsed:.2f}s")

    return {
        "answer": answer,
        "citations": citations,
        "self_correction_status": outcome,
        "related_documents": [],
        "chunks_retrieved": len(context_chunks),
        "retrieval_time_ms": int(elapsed * 1000),
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
    """Search pipeline for the dashboard (no LLM generation).

    Returns structured results with relevance scores.
    """
    from embeddings.gemini_embedder import gemini_embedder
    from retrieval.bm25_retriever import bm25_retriever
    from retrieval.reranker import reranker
    from vectorstore.chroma_store import chroma_store

    # Embed query
    query_embedding = gemini_embedder.embed_text(query, task_type="RETRIEVAL_QUERY")
    if query_embedding is None:
        return {"results": [], "total": 0, "query": query}

    # Build metadata filter
    where_filter = {}
    if document_type:
        where_filter["document_type"] = document_type

    # Dense retrieval with filters
    dense_results = chroma_store.query_multiple_collections(
        collection_names=allowed_collections,
        query_embedding=query_embedding,
        n_results=DENSE_TOP_K * 2,
        where_filter=where_filter if where_filter else None,
    )

    # Sparse retrieval
    sparse_results = bm25_retriever.search(query, allowed_collections, SPARSE_TOP_K)

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

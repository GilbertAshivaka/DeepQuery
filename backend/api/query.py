"""
Deep Query — Query Endpoints

POST /api/query/chat     — streaming chat (SSE)
POST /api/query/search   — structured search dashboard
GET  /api/query/history  — conversation history
GET  /api/query/conversations/{id} — conversation detail
"""

import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user, get_token_payload
from core.config import settings
from core.database import get_db
from models.database import AgentAttachment, Conversation, Message, QueryLog, User
from models.schemas import (
    ChatRequest,
    ConversationDetail,
    ConversationSummary,
    MessageResponse,
    SearchRequest,
    SearchResponse,
)

router = APIRouter()


@router.post("/chat")
async def chat_query(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Process a chat query and return a streaming SSE response.

    The response streams tokens as they are generated, then sends
    a final event with citations and self-correction status.
    """
    from core.constants import ROLE_COLLECTIONS, UserRole

    allowed_collections = [
        c.value for c in ROLE_COLLECTIONS.get(UserRole(user.role), [])
    ]

    # Get or create conversation
    conversation = None
    if body.conversation_id:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == body.conversation_id,
                Conversation.user_id == user.id,
            )
            .first()
        )
    if conversation is None:
        conversation = Conversation(user_id=user.id, title=body.query[:100])
        db.add(conversation)
        db.commit()
        db.refresh(conversation)


    # Fetch last 10 messages for chat history (excluding current message)
    history_messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(10)
        .all()
    )
    # Reverse to chronological order
    history_messages = list(reversed(history_messages))

    # Add the current user message to the history (not yet in DB)
    chat_history = [
        {"role": m.role, "content": m.content} for m in history_messages
    ]
    chat_history.append({"role": "user", "content": body.query})

    # ── Attachments ── load any files the user attached (uploaded via the shared
    # /agents/attachments store), cap their text, and fold the parsed text into the answer
    # context below. NOTE: AgentAttachment.conversation_id FKs the *agent* conversations
    # table, so we do NOT set it to this (classical) chat conversation id — ownership is by
    # user_id, and the chat links the files via the user message's citation refs.
    attachments: list[dict] = []
    user_attach_refs: list[dict] = []
    if body.attachment_ids:
        rows = (
            db.query(AgentAttachment)
            .filter(AgentAttachment.id.in_(body.attachment_ids),
                    AgentAttachment.user_id == user.id)
            .all()
        )
        cap = settings.chat_attachment_max_chars
        for i, a in enumerate(rows, 1):
            text = a.extracted_text or ""
            if cap and len(text) > cap:
                text = text[:cap] + " …[truncated]"
            attachments.append({"attachment_number": i, "attachment_id": a.id,
                                "filename": a.filename, "kind": a.kind, "text": text})
            user_attach_refs.append({"source_type": "attachment", "attachment_number": i,
                                     "filename": a.filename, "attachment_id": a.id, "kind": a.kind})

    # Save user message (attachment refs ride on its citations for rehydration of the chips)
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=body.query,
        has_image_attachment=body.image_base64 is not None,
        citations=json.dumps(user_attach_refs) if user_attach_refs else None,
    )
    db.add(user_msg)
    db.commit()

    # Capture scalar values before the session closes
    conversation_id = conversation.id
    user_id = user.id

    start_time = time.time()

    async def event_stream() -> AsyncGenerator[str, None]:
        """Generate SSE events for the chat response."""
        try:
            from retrieval.pipeline import gather_context
            from retrieval.query_cache import get_cached_result, cache_query_result
            from llm.groq_client import groq_client

            # Check cache first (skip if image query, has chat history, or has attachments —
            # the attached context makes the answer turn-specific).
            cached_result = None
            if not body.image_base64 and not chat_history and not attachments:
                cached_result = get_cached_result(body.query, allowed_collections)

            if cached_result:
                # Cache hit → the answer is already complete; emit it in one shot (instant).
                result = cached_result
                answer = result.get("answer", "")
                citations = result.get("citations", [])
                cache_hit = True
                yield f"data: {json.dumps({'type': 'answer_token', 'content': answer})}\n\n"
            else:
                # Retrieval first (can't stream), then STREAM the generation token-by-token
                # so the user sees text immediately — matching the agent surface.
                ctx = await gather_context(
                    body.query, allowed_collections, body.image_base64, chat_history,
                    want_whole_doc=True,
                )
                if ctx.get("error"):
                    answer = "I'm sorry, I encountered an error processing your query. Please try again."
                    citations = []
                    cache_hit = False
                    result = {"answer": answer, "citations": [], "formatted_chunks": [],
                              "self_correction_status": "ERROR", "chunks_retrieved": 0, "query": body.query}
                    yield f"data: {json.dumps({'type': 'answer_token', 'content': answer})}\n\n"
                else:
                    formatted_chunks = ctx["formatted_chunks"]
                    whole_documents = ctx.get("whole_documents", [])
                    # document + whole-doc citations, plus attachment citations
                    citations = list(ctx["citations"])
                    for i, att in enumerate(attachments, 1):
                        citations.append({
                            "source_type": "attachment", "attachment_number": i,
                            "filename": att.get("filename", f"attachment-{i}"),
                            "attachment_id": att.get("attachment_id"),
                            "kind": att.get("kind", "document"),
                        })
                    # Stream the answer tokens as they generate.
                    parts: list[str] = []
                    async for delta in groq_client.generate_answer_stream(
                        body.query, formatted_chunks, ctx.get("graph_context", ""),
                        chat_history, whole_documents, attachments,
                    ):
                        parts.append(delta)
                        yield f"data: {json.dumps({'type': 'answer_token', 'content': delta})}\n\n"
                    answer = "".join(parts).strip() or "I'm sorry, I was unable to generate an answer. Please try again."
                    cache_hit = False
                    result = {"answer": answer, "citations": citations,
                              "formatted_chunks": formatted_chunks, "self_correction_status": "PENDING",
                              "chunks_retrieved": ctx.get("chunks_retrieved", 0), "query": body.query}

            related = result.get("related_documents", [])

            # Send citations
            yield f"data: {json.dumps({'type': 'citations', 'content': citations})}\n\n"

            # Send cache hit indicator
            yield f"data: {json.dumps({'type': 'cache_hit', 'content': cache_hit})}\n\n"

            # Send related documents
            yield f"data: {json.dumps({'type': 'related', 'content': related})}\n\n"

            # Run self-correction in background (if not cached)
            verification_result = {"status": result.get("self_correction_status", "VERIFIED")}

            if not cache_hit and result.get("self_correction_status") == "PENDING":
                from llm.groq_client import groq_client
                import asyncio

                loop = asyncio.get_event_loop()
                formatted_chunks = result.get("formatted_chunks", [])
                query_text = result.get("query", body.query)

                # Run verification in executor (non-blocking)
                correction_result = await loop.run_in_executor(
                    None,
                    groq_client.verify_answer,
                    query_text,
                    answer,
                    formatted_chunks,
                )

                outcome = correction_result.get("outcome", "VERIFIED")
                if outcome == "CORRECTED":
                    verification_result = {
                        "status": "CORRECTED",
                        "amendments": correction_result.get("corrected_answer", ""),
                    }
                elif outcome == "INSUFFICIENT_CONTEXT":
                    verification_result = {
                        "status": "INSUFFICIENT_CONTEXT",
                        "message": correction_result.get("explanation", ""),
                    }
                else:
                    verification_result = {"status": "VERIFIED"}

            # Send verification result event
            yield f"data: {json.dumps({'type': 'verification_result', 'content': verification_result})}\n\n"

            # Cache the final result (if not from image query, chat, or attachments, and not cached)
            if not body.image_base64 and not chat_history and not attachments and not cache_hit:
                # Update result with final verification status before caching
                result_to_cache = result.copy()
                result_to_cache["self_correction_status"] = verification_result.get("status", "VERIFIED")
                # Remove internal fields not needed for cache
                result_to_cache.pop("formatted_chunks", None)
                result_to_cache.pop("query", None)
                cache_query_result(body.query, allowed_collections, result_to_cache)

            # Save assistant message to DB using a fresh session
            # (the original request session is closed by now)
            from core.database import SessionLocal
            save_db = SessionLocal()
            try:
                elapsed_ms = int((time.time() - start_time) * 1000)
                final_status = verification_result.get("status", "VERIFIED")

                assistant_msg = Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                    citations=json.dumps(citations),
                    self_correction_status=final_status,
                )
                save_db.add(assistant_msg)

                # Log query for analytics
                query_log = QueryLog(
                    user_id=user_id,
                    query_text=body.query,
                    answer_status=final_status,
                    total_response_time_ms=elapsed_ms,
                    chunks_retrieved=result.get("chunks_retrieved", 0),
                )
                save_db.add(query_log)
                save_db.commit()
            finally:
                save_db.close()

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': conversation_id})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/search", response_model=SearchResponse)
async def search_query(
    body: SearchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Structured search for the dashboard view.
    Returns ranked chunks with metadata (no LLM generation).
    """
    from core.constants import ROLE_COLLECTIONS, UserRole

    allowed_collections = [
        c.value for c in ROLE_COLLECTIONS.get(UserRole(user.role), [])
    ]

    try:
        from retrieval.pipeline import search_pipeline

        results = await search_pipeline(
            query=body.query,
            allowed_collections=allowed_collections,
            document_type=body.document_type,
            date_from=body.date_from,
            date_to=body.date_to,
            topic_tags=body.topic_tags,
            page=body.page,
            per_page=body.per_page,
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/history")
def get_query_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's conversation list."""
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
        .all()
    )

    result = []
    for conv in conversations:
        msg_count = db.query(Message).filter(Message.conversation_id == conv.id).count()
        result.append(
            ConversationSummary(
                id=conv.id,
                title=conv.title,
                is_pinned=conv.is_pinned or False,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=msg_count,
            )
        )
    return result


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a conversation and all its messages."""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    db.query(Message).filter(Message.conversation_id == conv.id).delete()
    db.delete(conv)
    db.commit()
    return {"detail": "Conversation deleted."}


@router.patch("/conversations/{conversation_id}/pin")
def toggle_pin_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle pin status of a conversation."""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    conv.is_pinned = not (conv.is_pinned or False)
    db.commit()
    return {"is_pinned": conv.is_pinned}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return full conversation with all messages."""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .all()
    )

    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                citations=json.loads(m.citations) if m.citations else None,
                self_correction_status=m.self_correction_status,
                created_at=m.created_at,
            )
            for m in messages
        ],
        created_at=conv.created_at,
    )

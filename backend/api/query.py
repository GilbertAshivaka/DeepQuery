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
from core.database import get_db
from models.database import Conversation, Message, QueryLog, User
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

    # Save user message
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=body.query,
        has_image_attachment=body.image_base64 is not None,
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
            from retrieval.pipeline import retrieval_pipeline

            result = await retrieval_pipeline(
                query=body.query,
                allowed_collections=allowed_collections,
                image_base64=body.image_base64,
            )

            # Stream the answer tokens
            answer = result.get("answer", "")
            # For now, send the full answer — streaming will be implemented
            # when the Groq streaming integration is connected
            yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"

            # Send citations
            citations = result.get("citations", [])
            yield f"data: {json.dumps({'type': 'citations', 'content': citations})}\n\n"

            # Send self-correction status
            correction_status = result.get("self_correction_status", "VERIFIED")
            yield f"data: {json.dumps({'type': 'status', 'content': correction_status})}\n\n"

            # Send related documents
            related = result.get("related_documents", [])
            yield f"data: {json.dumps({'type': 'related', 'content': related})}\n\n"

            # Save assistant message to DB using a fresh session
            # (the original request session is closed by now)
            from core.database import SessionLocal
            save_db = SessionLocal()
            try:
                elapsed_ms = int((time.time() - start_time) * 1000)
                assistant_msg = Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                    citations=json.dumps(citations),
                    self_correction_status=correction_status,
                )
                save_db.add(assistant_msg)

                # Log query for analytics
                query_log = QueryLog(
                    user_id=user_id,
                    query_text=body.query,
                    answer_status=correction_status,
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

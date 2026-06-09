"""
Deep Query — Agent Layer Endpoints

A dedicated surface for the agent flow, separate from chat (`/api/query/*`). The
Agents page drives these endpoints; the chat interface never does.

POST /api/agents/run    — run the Orchestrator, streaming structured SSE events
GET  /api/agents/health — configured model slots + registered capabilities

SSE event types emitted by the run endpoint:
  plan · step_status · reasoning · tool_activity · citations · answer_token ·
  verification_result · done · error
(Approval-gate events — approval_required + the approve/reject resume endpoints —
arrive with Phase 3.)
"""

import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth.dependencies import get_current_user
from core.config import settings
from core.constants import ROLE_COLLECTIONS, UserRole
from models.database import User

router = APIRouter()


class AgentRunRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/run")
async def run_agent(
    body: AgentRunRequest,
    user: User = Depends(get_current_user),
):
    """Run the Orchestrator over the user's request and stream its events as SSE.

    Phase 1: document path only (classify → retrieve → generate → verify), using the
    Gemini 2.5 Flash model slots. No persistence yet — the agent_run trace table is a
    later phase; this endpoint streams events only.
    """
    allowed_collections = [
        c.value for c in ROLE_COLLECTIONS.get(UserRole(user.role), [])
    ]
    user_id = user.id
    conversation_id = body.conversation_id
    query = body.query

    async def event_stream() -> AsyncGenerator[str, None]:
        from agents.orchestrator import orchestrator

        try:
            async for event in orchestrator.run(
                query=query,
                allowed_collections=allowed_collections,
                chat_history=None,
                user_id=user_id,
                conversation_id=conversation_id,
            ):
                yield _sse(event)
        except Exception as exc:  # last-resort guard; run() already emits 'error'
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/health")
def agent_health(user: User = Depends(get_current_user)):
    """Report the configured model slots and registered capabilities."""
    from agents.models import describe_slots
    from agents.registry import available

    return {
        "model_slots": describe_slots(),
        "capabilities": [c.value for c in available()],
        "deployment_mode": settings.deployment_mode,
    }

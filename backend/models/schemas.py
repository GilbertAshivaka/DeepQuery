"""
Deep Query — Pydantic Schemas

Request / response models for the API layer.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ═════════════════════════════════════════════════════════════
# Auth
# ═════════════════════════════════════════════════════════════
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    username: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPayload(BaseModel):
    user_id: str
    username: str
    role: str
    allowed_collections: List[str]
    exp: Optional[datetime] = None


# ═════════════════════════════════════════════════════════════
# Users
# ═════════════════════════════════════════════════════════════
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: str
    password: str = Field(..., min_length=8)
    full_name: str
    role: str = "student"


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    full_name: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    """Self-service profile edit. Username and role are admin-managed and not editable
    here."""

    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


# ═════════════════════════════════════════════════════════════
# Documents
# ═════════════════════════════════════════════════════════════
class DocumentResponse(BaseModel):
    id: str
    original_filename: str
    file_extension: str
    file_size_bytes: Optional[int] = None
    document_type: Optional[str] = None
    collection: str
    summary: Optional[str] = None
    topic_tags: Optional[List[str]] = None
    keywords: Optional[List[str]] = None  # Alias for topic_tags (for frontend)
    entities: Optional[List[dict]] = None  # Placeholder for entity data from Neo4j
    category: Optional[str] = None
    page_count: Optional[int] = None
    chunk_count: int = 0
    uploader_id: str
    upload_timestamp: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int
    page: int
    per_page: int


class UploadResponse(BaseModel):
    document_id: str
    job_id: str
    message: str = "Document uploaded and queued for processing."


class JobStatusResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ═════════════════════════════════════════════════════════════
# Query — Chat
# ═════════════════════════════════════════════════════════════
class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    conversation_id: Optional[str] = None
    image_base64: Optional[str] = None  # optional image attachment
    # Ids of files uploaded via POST /agents/attachments (shared store) to attach to this
    # turn — their parsed text is folded into the answer's context as [Attachment N].
    attachment_ids: Optional[List[str]] = None


class Citation(BaseModel):
    source_number: int
    document_name: str
    page_number: Optional[int] = None
    chunk_summary: str
    document_id: str
    relevance_score: float = 0.5


class ChatResponse(BaseModel):
    """Non-streaming response (used for self-correction summary)."""
    conversation_id: str
    message_id: str
    answer: str
    citations: List[Citation]
    self_correction_status: str
    related_documents: Optional[List[DocumentResponse]] = None


# ═════════════════════════════════════════════════════════════
# Query — Search Dashboard
# ═════════════════════════════════════════════════════════════
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    document_type: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    topic_tags: Optional[List[str]] = None
    page: int = 1
    per_page: int = 10


class SearchResultItem(BaseModel):
    chunk_text: str
    document_name: str
    document_id: str
    page_number: Optional[int] = None
    topic_tags: List[str] = []
    relevance_score: float
    summary: Optional[str] = None


class SearchResponse(BaseModel):
    results: List[SearchResultItem]
    total: int
    query: str


# ═════════════════════════════════════════════════════════════
# Conversations
# ═════════════════════════════════════════════════════════════
class ConversationSummary(BaseModel):
    id: str
    title: Optional[str] = None
    is_pinned: bool = False
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    # dict (not the strict Citation model) so the four citation kinds — document,
    # document_full, attachment — and a user turn's attachment refs all pass through.
    citations: Optional[List[dict]] = None
    self_correction_status: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationDetail(BaseModel):
    id: str
    title: Optional[str] = None
    messages: List[MessageResponse]
    created_at: datetime


# ═════════════════════════════════════════════════════════════
# Knowledge Graph
# ═════════════════════════════════════════════════════════════
class GraphEntity(BaseModel):
    id: str
    name: str
    entity_type: str
    properties: dict = {}


class GraphRelationship(BaseModel):
    source: str
    relationship: str
    target: str


class EntityDetail(BaseModel):
    entity: GraphEntity
    relationships: List[GraphRelationship]


# ═════════════════════════════════════════════════════════════
# Admin — System Stats
# ═════════════════════════════════════════════════════════════
class SystemStats(BaseModel):
    total_documents: int
    total_queries: int
    total_users: int
    total_conversations: int
    avg_retrieval_time_ms: Optional[float] = None
    queries_last_30_days: int
    knowledge_gaps: int  # count of INSUFFICIENT_CONTEXT responses


class TrendingTopic(BaseModel):
    topic: str
    count: int


class KnowledgeGap(BaseModel):
    query_text: str
    frequency: int
    last_asked: datetime

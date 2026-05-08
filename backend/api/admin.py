"""
Deep Query — Admin Endpoints

GET    /api/admin/users
POST   /api/admin/users
PATCH  /api/admin/users/{user_id}
GET    /api/admin/stats
GET    /api/admin/trending-topics
GET    /api/admin/knowledge-gaps
"""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.dependencies import RoleRequired
from auth.jwt_handler import hash_password
from core.constants import UserRole
from core.database import get_db
from models.database import Document, IngestionJob, QueryLog, User
from models.schemas import (
    KnowledgeGap,
    SystemStats,
    TrendingTopic,
    UserCreate,
    UserResponse,
    UserUpdate,
)

router = APIRouter()
admin_only = RoleRequired([UserRole.ADMIN])


@router.get("/users", dependencies=[Depends(admin_only)])
def list_users(db: Session = Depends(get_db)):
    """List all registered users."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        UserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            role=u.role.value if hasattr(u.role, "value") else u.role,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/users", response_model=UserResponse, dependencies=[Depends(admin_only)])
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    """Create a new user."""
    # Check uniqueness
    existing = db.query(User).filter(
        (User.username == body.username) | (User.email == body.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists.")

    # Validate role
    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.patch("/users/{user_id}", response_model=UserResponse, dependencies=[Depends(admin_only)])
def update_user(user_id: str, body: UserUpdate, db: Session = Depends(get_db)):
    """Update a user's role or status."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if body.role is not None:
        try:
            user.role = UserRole(body.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")

    if body.is_active is not None:
        user.is_active = body.is_active

    if body.full_name is not None:
        user.full_name = body.full_name

    db.commit()
    db.refresh(user)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.get("/stats", response_model=SystemStats, dependencies=[Depends(admin_only)])
def get_system_stats(db: Session = Depends(get_db)):
    """Return system-wide statistics."""
    total_docs = db.query(Document).filter(Document.is_deleted == False).count()
    total_queries = db.query(QueryLog).count()
    total_users = db.query(User).count()

    avg_time = db.query(func.avg(QueryLog.total_response_time_ms)).scalar()

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    recent_queries = (
        db.query(QueryLog).filter(QueryLog.created_at >= thirty_days_ago).count()
    )

    gaps = (
        db.query(QueryLog)
        .filter(QueryLog.answer_status == "INSUFFICIENT_CONTEXT")
        .count()
    )

    return SystemStats(
        total_documents=total_docs,
        total_queries=total_queries,
        total_users=total_users,
        avg_retrieval_time_ms=round(avg_time, 1) if avg_time else None,
        queries_last_30_days=recent_queries,
        knowledge_gaps=gaps,
    )


@router.get("/trending-topics", dependencies=[Depends(admin_only)])
def get_trending_topics(db: Session = Depends(get_db)):
    """Aggregate topic tags from recently ingested documents."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    docs = (
        db.query(Document)
        .filter(Document.upload_timestamp >= thirty_days_ago, Document.is_deleted == False)
        .all()
    )

    tag_counter: Counter = Counter()
    for doc in docs:
        if doc.topic_tags:
            try:
                tags = json.loads(doc.topic_tags)
                tag_counter.update(tags)
            except (json.JSONDecodeError, TypeError):
                pass

    return [
        TrendingTopic(topic=tag, count=count)
        for tag, count in tag_counter.most_common(20)
    ]


@router.get("/knowledge-gaps", dependencies=[Depends(admin_only)])
def get_knowledge_gaps(db: Session = Depends(get_db)):
    """Surface queries that returned INSUFFICIENT_CONTEXT."""
    gaps = (
        db.query(
            QueryLog.query_text,
            func.count(QueryLog.id).label("freq"),
            func.max(QueryLog.created_at).label("last_asked"),
        )
        .filter(QueryLog.answer_status == "INSUFFICIENT_CONTEXT")
        .group_by(QueryLog.query_text)
        .order_by(func.count(QueryLog.id).desc())
        .limit(30)
        .all()
    )

    return [
        KnowledgeGap(query_text=g.query_text, frequency=g.freq, last_asked=g.last_asked)
        for g in gaps
    ]

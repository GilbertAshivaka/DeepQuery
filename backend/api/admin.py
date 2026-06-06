"""
Deep Query — Admin Endpoints

GET    /api/admin/users
POST   /api/admin/users
PATCH  /api/admin/users/{user_id}
DELETE /api/admin/users/{user_id}
GET    /api/admin/stats
GET    /api/admin/trending-topics
GET    /api/admin/knowledge-gaps
GET    /api/admin/knowledge-gaps/detail/{topic}
PATCH  /api/admin/knowledge-gaps/{topic}/resolve
POST   /api/admin/recompute-similarity-map
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.dependencies import RoleRequired
from auth.jwt_handler import hash_password
from core.constants import UserRole
from core.database import get_db
from models.database import Conversation, Document, IngestionJob, QueryLog, User
from models.schemas import (
    KnowledgeGap,
    SystemStats,
    TrendingTopic,
    UserCreate,
    UserResponse,
    UserUpdate,
)

_GAP_STOP_WORDS = {
    'a','an','the','and','or','but','in','on','at','to','for','of','with','by',
    'from','is','are','was','were','be','been','have','has','had','do','does',
    'did','will','would','could','should','may','might','can','not','what',
    'how','why','when','where','who','which','this','that','these','those',
    'there','here','about','up','out','so','if','then','than','into','more',
    'also','just','their','they','them','some','any','all','each','get','i',
    'me','my','we','our','you','it','its','tell','show','find','list','give',
    'explain','please','need','want','know','using','used','use','between',
    'among','across','through','after','before','during','without','within',
    'according','based','related','provide','information','details','questions',
    'question','answer','answers','help','like','can','much','many','different',
}


def _extract_gap_topics(query_text: str) -> list[str]:
    """Extract meaningful topic keywords from a gap query string."""
    words = re.findall(r'\b[a-zA-Z]{3,}\b', query_text.lower())
    filtered = [w for w in words if w not in _GAP_STOP_WORDS]
    bigrams = [
        f"{filtered[i]} {filtered[i+1]}"
        for i in range(len(filtered) - 1)
    ]
    return list(dict.fromkeys(filtered[:6] + bigrams[:4]))


def _period_key(dt: datetime, window_days: int) -> str:
    """Bucket a datetime into a readable period label."""
    if window_days <= 7:
        return dt.strftime("%b %d")
    elif window_days <= 90:
        monday = dt - timedelta(days=dt.weekday())
        return f"Wk {monday.strftime('%b %d')}"
    else:
        return dt.strftime("%b %Y")

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
    existing = db.query(User).filter(
        (User.username == body.username) | (User.email == body.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists.")

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


@router.delete("/users/{user_id}", dependencies=[Depends(admin_only)])
def delete_user(user_id: str, db: Session = Depends(get_db)):
    """Delete a user by ID."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    db.delete(user)
    db.commit()
    return {"detail": "User deleted successfully."}


@router.get("/stats", response_model=SystemStats, dependencies=[Depends(admin_only)])
def get_system_stats(db: Session = Depends(get_db)):
    """Return system-wide statistics."""
    total_docs = db.query(Document).filter(Document.is_deleted == False).count()
    total_queries = db.query(QueryLog).count()
    total_users = db.query(User).count()
    total_conversations = db.query(Conversation).count()

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
        total_conversations=total_conversations,
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
def get_knowledge_gaps(
    window: int = 30,
    min_frequency: int = 2,
    db: Session = Depends(get_db),
):
    """Return a topic frequency matrix and top gaps for the heatmap visualization.

    Args:
        window: Number of days to look back (7 / 30 / 90 / 0=all).
        min_frequency: Minimum topic occurrences to include in matrix.
    """
    from core.redis_client import redis_client

    # ── Fetch gap queries within the time window ──────────────
    base_q = db.query(QueryLog).filter(
        QueryLog.answer_status == "INSUFFICIENT_CONTEXT"
    )
    if window > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window)
        base_q = base_q.filter(QueryLog.created_at >= cutoff)

    gap_rows = base_q.order_by(QueryLog.created_at.asc()).all()

    # ── Extract topics from each query ────────────────────────
    # topic → { period_key → count }
    topic_period: dict[str, Counter] = defaultdict(Counter)
    topic_total: Counter = Counter()
    topic_queries: dict[str, list[str]] = defaultdict(list)

    for row in gap_rows:
        period = _period_key(
            row.created_at.replace(tzinfo=timezone.utc)
            if row.created_at.tzinfo is None
            else row.created_at,
            window,
        )
        topics = _extract_gap_topics(row.query_text)
        for t in topics:
            topic_period[t][period] += 1
            topic_total[t] += 1
            topic_queries[t].append(row.query_text)

    # ── Get resolved topics from Redis ────────────────────────
    resolved_raw = redis_client.get("gaps:resolved_topics")
    resolved_set = set(json.loads(resolved_raw)) if resolved_raw else set()

    # ── Filter by min_frequency and exclude resolved ──────────
    active_topics = [
        t for t, cnt in topic_total.most_common(25)
        if cnt >= min_frequency and t not in resolved_set
    ]

    # ── Build ordered period list ─────────────────────────────
    all_periods: list[str] = []
    seen: set[str] = set()
    for row in gap_rows:
        pk = _period_key(
            row.created_at.replace(tzinfo=timezone.utc)
            if row.created_at.tzinfo is None
            else row.created_at,
            window,
        )
        if pk not in seen:
            all_periods.append(pk)
            seen.add(pk)

    # ── Build z-matrix (topics × periods) ────────────────────
    z_matrix = [
        [topic_period[t].get(p, 0) for p in all_periods]
        for t in active_topics
    ]

    # ── Top 10 list ───────────────────────────────────────────
    top_10 = [
        {
            "topic": t,
            "count": topic_total[t],
            "last_asked": max(
                (r.created_at for r in gap_rows if t in _extract_gap_topics(r.query_text)),
                default=None,
            ),
            "resolved": t in resolved_set,
        }
        for t in topic_total.most_common(10)
        if topic_total[t] >= min_frequency
    ]

    # ── Recent raw gap queries (unfiltered) for the analytics summary ──
    # The heatmap aggregates by topic/min_frequency, which can hide one-off
    # unanswered questions. This list surfaces the actual query text so the
    # Analytics panel always reflects real gaps. Role is shown, identity is not.
    recent_gaps = []
    for r in reversed(gap_rows):
        if len(recent_gaps) >= 15:
            break
        role = getattr(r.user.role, "value", r.user.role) if r.user else None
        created = (
            r.created_at.replace(tzinfo=timezone.utc)
            if r.created_at and r.created_at.tzinfo is None
            else r.created_at
        )
        recent_gaps.append({
            "query_text": r.query_text,
            "created_at": created.isoformat() if created else None,
            "user_role": role,
        })

    return {
        "frequency_matrix": {
            "topics": active_topics,
            "periods": all_periods,
            "data": z_matrix,
        },
        "top_gaps": top_10,
        "recent_gaps": recent_gaps,
        "total_gaps": len(gap_rows),
        "window_days": window,
        "resolved_topics": list(resolved_set),
    }


@router.get("/knowledge-gaps/detail/{topic}", dependencies=[Depends(admin_only)])
def get_gap_detail(topic: str, window: int = 30, db: Session = Depends(get_db)):
    """Return individual queries that contributed to a specific topic gap.

    User identity is intentionally excluded — only role and timestamp are returned.
    """
    base_q = db.query(QueryLog, User.role).join(
        User, QueryLog.user_id == User.id
    ).filter(QueryLog.answer_status == "INSUFFICIENT_CONTEXT")

    if window > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window)
        base_q = base_q.filter(QueryLog.created_at >= cutoff)

    rows = base_q.order_by(QueryLog.created_at.desc()).all()

    matched = []
    for log, role in rows:
        if topic.lower() in log.query_text.lower() or any(
            t == topic for t in _extract_gap_topics(log.query_text)
        ):
            matched.append({
                "query_text": log.query_text,
                "submitted_at": log.created_at.isoformat(),
                "user_role": role.value if hasattr(role, "value") else role,
            })

    return {"topic": topic, "queries": matched, "total": len(matched)}


@router.patch("/knowledge-gaps/{topic}/resolve", dependencies=[Depends(admin_only)])
def resolve_gap_topic(topic: str):
    """Mark a gap topic as resolved so it is suppressed from the heatmap."""
    from core.redis_client import redis_client

    resolved_raw = redis_client.get("gaps:resolved_topics")
    resolved = set(json.loads(resolved_raw)) if resolved_raw else set()
    resolved.add(topic)
    redis_client.set("gaps:resolved_topics", json.dumps(list(resolved)))
    return {"topic": topic, "resolved": True}


# ── Similarity Map ───────────────────────────────────────────


@router.post("/recompute-similarity-map", dependencies=[Depends(admin_only)])
def recompute_similarity_map(background_tasks: BackgroundTasks):
    """Manually trigger the UMAP similarity-map computation Celery task."""
    try:
        from tasks.umap_task import compute_umap_coordinates
        result = compute_umap_coordinates.delay()
        return {"job_id": result.id, "status": "queued"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue task: {str(e)}")


# ── Cache Management ─────────────────────────────────────────


@router.delete("/cache/flush", dependencies=[Depends(admin_only)])
def flush_query_cache():
    """Flush the entire query result cache."""
    from retrieval.query_cache import flush_all_query_cache

    deleted = flush_all_query_cache()
    return {"message": f"Flushed {deleted} cache entries", "entries_deleted": deleted}


@router.delete("/cache/flush/{collection}", dependencies=[Depends(admin_only)])
def flush_collection_cache(collection: str):
    """Flush cache entries for a specific collection."""
    from retrieval.query_cache import invalidate_cache_for_collection

    deleted = invalidate_cache_for_collection(collection)
    return {
        "message": f"Invalidated {deleted} cache entries for collection '{collection}'",
        "entries_deleted": deleted,
    }
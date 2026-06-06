"""
Deep Query — FastAPI Application Entry Point
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import init_db
from api.router import api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle events."""
    # ── Startup ──
    print("=" * 60)
    print("Starting Deep Query server...")
    print("=" * 60)

    # 1. Initialize database
    init_db()
    _run_migrations()
    _seed_admin_user()

    # 2. Initialize all service clients
    print("Initializing service clients...")
    _init_service_clients()

    # 3. Build BM25 indexes (requires ChromaDB to be ready)
    print("Building BM25 indexes...")
    _build_bm25_indexes()

    # 4. Run connection warmup calls
    print("Warming up external service connections...")
    await _warmup_connections()

    print("=" * 60)
    print("✓ Server ready to accept traffic")
    print("=" * 60)

    yield

    # ── Shutdown ──
    print("Shutting down Deep Query server...")
    _cleanup_connections()


def _run_migrations():
    """Apply additive schema migrations for SQLite (ALTER TABLE ADD COLUMN)."""
    from sqlalchemy import text
    from core.database import engine

    migrations = [
        ("documents", "umap_x",           "ALTER TABLE documents ADD COLUMN umap_x REAL"),
        ("documents", "umap_y",           "ALTER TABLE documents ADD COLUMN umap_y REAL"),
        ("documents", "umap_computed_at", "ALTER TABLE documents ADD COLUMN umap_computed_at DATETIME"),
    ]

    with engine.connect() as conn:
        for table, column, ddl in migrations:
            try:
                conn.execute(text(ddl))
                conn.commit()
                logger.info(f"Migration applied: {table}.{column}")
            except Exception:
                # Column already exists — safe to ignore
                pass


def _seed_admin_user():
    """Create a default admin user if none exists."""
    from core.database import SessionLocal
    from models.database import User
    from core.constants import UserRole
    from passlib.context import CryptContext

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
        if admin is None:
            admin = User(
                username="admin",
                email="admin@deepquery.local",
                hashed_password=pwd_ctx.hash("admin1234"),
                full_name="System Administrator",
                role=UserRole.ADMIN,
            )
            db.add(admin)
            db.commit()
            logger.info("Default admin user created (admin / admin1234)")
    finally:
        db.close()


def _init_service_clients():
    """Initialize all service clients (ChromaDB, Neo4j, Redis, etc.)."""
    try:
        # Initialize ChromaDB collections
        from vectorstore.chroma_store import chroma_store
        chroma_store.ensure_collections()

        # Initialize Neo4j schema
        from knowledge_graph.neo4j_client import neo4j_client
        neo4j_client.ensure_schema()

        logger.info("Service clients initialized")
    except Exception as e:
        logger.error(f"Failed to initialize service clients: {e}")


def _build_bm25_indexes():
    """Build BM25 indexes for all collections at startup."""
    try:
        from retrieval.bm25_retriever import bm25_retriever
        print("  - Loading chunks from ChromaDB...")
        bm25_retriever.build_all_indexes()

        # Report what was built
        for coll_name, index in bm25_retriever._indexes.items():
            corpus_size = len(bm25_retriever._corpuses.get(coll_name, []))
            if index and corpus_size > 0:
                print(f"  ✓ {coll_name:15} - {corpus_size:5} documents indexed")
            else:
                print(f"  ○ {coll_name:15} - empty (no documents)")
    except Exception as e:
        print(f"  ✗ ERROR building BM25 indexes: {e}")
        import traceback
        traceback.print_exc()


async def _warmup_connections():
    """Warm up connections to all external services."""
    warmup_errors = []

    # Redis
    try:
        from core.redis_client import redis_client
        if redis_client.ping():
            logger.info("✓ Redis connection warmed up")
        else:
            warmup_errors.append("Redis ping failed")
    except Exception as e:
        warmup_errors.append(f"Redis: {e}")

    # ChromaDB
    try:
        from vectorstore.chroma_store import chroma_store
        chroma_store.client.list_collections()
        logger.info("✓ ChromaDB connection warmed up")
    except Exception as e:
        warmup_errors.append(f"ChromaDB: {e}")

    # Neo4j
    try:
        from knowledge_graph.neo4j_client import neo4j_client
        with neo4j_client.driver.session() as session:
            session.run("RETURN 1")
        logger.info("✓ Neo4j connection warmed up")
    except Exception as e:
        warmup_errors.append(f"Neo4j: {e}")

    # Gemini Embedding API
    try:
        from embeddings.gemini_embedder import gemini_embedder
        gemini_embedder.embed_text("warmup", task_type="RETRIEVAL_QUERY")
        logger.info("✓ Gemini Embedding API warmed up")
    except Exception as e:
        warmup_errors.append(f"Gemini: {e}")

    # Groq API
    try:
        from llm.groq_client import groq_client
        from langchain_core.messages import HumanMessage
        llm = groq_client._get_llm(temperature=0.0)
        llm.invoke([HumanMessage(content="test")])
        logger.info("✓ Groq API warmed up")
    except Exception as e:
        warmup_errors.append(f"Groq: {e}")

    # Log warmup results
    if warmup_errors:
        logger.warning(f"Warmup completed with {len(warmup_errors)} errors: {warmup_errors}")
    else:
        logger.info("All connections warmed up successfully")


def _cleanup_connections():
    """Clean up service connections on shutdown."""
    try:
        from knowledge_graph.neo4j_client import neo4j_client
        neo4j_client.close()

        from core.redis_client import redis_client
        redis_client.close()

        logger.info("Connections closed")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")


app = FastAPI(
    title="Deep Query",
    description="Semantic Knowledge Management Ecosystem — Pwani University",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────────────
app.include_router(api_router)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Deep Query API"}

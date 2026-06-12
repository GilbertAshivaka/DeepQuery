"""
Deep Query — Database Setup

SQLAlchemy engine and session management.
Supports SQLite for development, PostgreSQL for production.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from core.config import settings


# ── Engine ───────────────────────────────────────────────────
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=(settings.app_env == "development"),
)

# Enable WAL mode and foreign keys for SQLite
if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ── Session Factory ──────────────────────────────────────────
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Declarative Base ─────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Dependency for FastAPI ───────────────────────────────────
def get_db():
    """Yield a database session for request lifecycle."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once at application startup."""
    from models.database import (  # noqa: F401 — import triggers table registration
        User,
        Document,
        IngestionJob,
        Conversation,
        Message,
        RefreshToken,
        QueryLog,
        Connector,
        ConnectorAuditLog,
        ConnectorCredential,
        ConnectorApproval,
        UserConnectorEnablement,
        SkillFile,
        SkillFileVersion,
        SkillDependency,
        SkillChangeProposal,
        AgentConversation,
        AgentTurn,
        AgentAttachment,
    )

    Base.metadata.create_all(bind=engine)

    # Lightweight additive migrations (SQLite create_all won't add new columns to
    # existing tables). Idempotent — only adds a column when it's missing.
    if settings.database_url.startswith("sqlite"):
        _add_column_if_missing("agent_turns", "agent_trace", "TEXT")


def _add_column_if_missing(table: str, column: str, ddl_type: str):
    """Add `column` to `table` if it isn't already present (SQLite ALTER ADD COLUMN)."""
    with engine.begin() as conn:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")

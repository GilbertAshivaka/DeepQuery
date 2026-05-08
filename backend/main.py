"""
Deep Query — FastAPI Application Entry Point
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import init_db
from api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle events."""
    # ── Startup ──
    init_db()
    _seed_admin_user()
    yield
    # ── Shutdown ──
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
            print("✓ Default admin user created (admin / admin1234)")
    finally:
        db.close()


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

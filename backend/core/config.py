"""
Deep Query — Application Settings

Centralised configuration loaded from environment variables.
"""

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ── Database ─────────────────────────────────────────────
    database_url: str = "sqlite:///./deepquery.db"

    # ── Google AI (Gemini Embedding 2) ───────────────────────
    google_api_key: str = ""
    embedding_model: str = "gemini-embedding-2-preview"
    embedding_dimensions: int = 3072

    # ── Groq (Llama 3.3 70B) ────────────────────────────────
    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"

    # ── ChromaDB ─────────────────────────────────────────────
    chroma_persist_directory: str = "./chroma_data"
    chroma_host: str = "localhost"
    chroma_port: int = 8100

    # ── Neo4j ────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "deepquery_dev_password"

    # ── JWT Authentication ───────────────────────────────────
    jwt_secret_key: str = "change-this-to-a-random-secret-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # ── Celery / Redis ───────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── Document Storage ─────────────────────────────────────
    document_store_path: str = "./document_store"

    @property
    def document_store_dir(self) -> Path:
        p = Path(self.document_store_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── Reranker ─────────────────────────────────────────────
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_device: str = "cpu"

    # ── Chunking ─────────────────────────────────────────────
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 65


settings = Settings()

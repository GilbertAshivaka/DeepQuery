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

    # ── Agent Layer — Model Slots ───────────────────────────
    # Per-slot provider + model for the agent layer (orchestration / generation /
    # verification). Default: GPT-OSS-120B via Groq everywhere (under evaluation —
    # Gemini 2.5 Flash free-tier caps proved too tight). The existing chat RAG path
    # is unaffected; it keeps using llm_model above.
    # Providers: google | groq | anthropic | ollama | vllm. Air-gapped mode forbids
    # cloud providers and requires a local backend for every slot (enforced).
    agent_orchestration_provider: str = "groq"
    agent_orchestration_model: str = "openai/gpt-oss-120b"
    agent_generation_provider: str = "groq"
    agent_generation_model: str = "openai/gpt-oss-120b"
    agent_verification_provider: str = "groq"
    agent_verification_model: str = "openai/gpt-oss-120b"

    # Optional backends for non-default slots.
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # How long (seconds) the agent layer caches a connector's discovered tool list
    # before re-discovering. Tool lists rarely change between queries; caching avoids
    # a subprocess/network round-trip per query. 0 disables the cache.
    agent_discovery_cache_ttl_seconds: int = 600

    # Whether the agent may answer a "direct" (general-knowledge) question from the
    # model itself, without grounding in the corpus/live sources. Such answers are
    # clearly labelled as ungrounded. High-stakes deployments (legal, healthcare) can
    # set this False to force grounded-only answers. (Per-assistant override later.)
    agent_allow_ungrounded_answers: bool = True

    # Strict read filtering for the live path. By default, UNKNOWN (un-annotated
    # ecosystem) tools from an admin-approved connector are usable — as free reads, and
    # proposable as gated actions (the user's intent routes mutating use through the
    # approval gate; admin approval + the audit trail are the trust boundary). No name
    # heuristic. Set True for SDK-only deployments: then ONLY tools that DECLARE their
    # read/mutate status are used — SDK/annotated reads (RESOURCE) are free reads, and
    # every UNKNOWN tool is excluded entirely (not read, not proposed).
    agent_live_strict_read_filter: bool = False

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

    # ── Agent run durability (RESUMABLE_AGENT_SPEC_V2 §2.1) ──
    # Redis URL for the LangGraph checkpointer (paused/resumable agent runs).
    # MUST be db 0: the checkpointer's RediSearch indexes only work there. Coexists
    # with the Celery broker via distinct key prefixes (checkpoint:* vs celery/_kombu*)
    # — never FLUSHDB this db (see SETUP_AND_RUN.md). Redis must run with AOF on.
    agent_redis_url: str = "redis://localhost:6379/0"
    # Durable runs (checkpointer + interrupt/resume action gate). When False — or when
    # Redis is unreachable at startup — the orchestrator compiles without a
    # checkpointer and behaves exactly as before (single-pass, no resume).
    agent_durable_runs: bool = True
    # How long a paused run remains resumable. The TTL sweeper expires older
    # checkpoints (a paused approval older than this requires a fresh run).
    agent_run_ttl_hours: int = 72

    # ── Connector Infrastructure ─────────────────────────────
    # Fernet key for encrypting per-user connector credentials at rest. Generate
    # with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # If empty, a volatile dev key is generated at startup (credentials won't
    # survive a restart) — set this in production.
    connector_encryption_key: str = ""
    # Base URL the OAuth provider redirects back to after user consent.
    connector_oauth_redirect_base: str = "http://localhost:8000"
    # Deployment mode: cloud | hybrid | air-gapped. Air-gapped permits only
    # self-hosted (stdio, no-network) connectors and forbids external egress/OAuth.
    deployment_mode: str = "cloud"

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

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
    # Embedding provider + model. Gemini Embedding 2 is the default and the
    # recommended choice; the provider is configurable so deployments can swap it
    # (requires a re-index — see MODEL_VENDOR_PICKING_PLAN.md §7). The triple
    # (embedding_provider, embedding_model, embedding_dimensions) forms the
    # "embedding identity" bound to each Chroma collection.
    embedding_provider: str = "google"
    embedding_model: str = "gemini-embedding-2-preview"
    embedding_dimensions: int = 3072

    # Active physical suffix for the RBAC collections. Empty = bare logical names
    # (academic, departmental, …) — the current/legacy layout. A re-index migration
    # writes into suffixed shadow collections (e.g. academic__v2) and flips this
    # pointer atomically once verified. Never mutate a live collection in place.
    embedding_collection_version: str = ""
    # When True, assert on every Chroma read/write that the active embedding identity
    # matches the collection's recorded identity (hard error on mismatch). Legacy
    # collections with no recorded identity pass with a warning (and are backfilled).
    embedding_identity_guard: bool = True

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

    # ── Classic RAG pipeline — per-workload provider + model ─
    # The classic user-facing pipeline rides the same provider-agnostic factory as the
    # agent slots, split into three independently-configurable roles so each workload
    # can run a different model (e.g. a cheaper/faster model for batch extraction than
    # for chat). All default to Groq Llama 3.3 70B, preserving current behavior exactly.
    # (llm_model above is retained for reference/back-compat.)
    #   chat            → RAG answer generation
    #   self_correction → answer verification / correction
    #   extraction      → entity extraction, metadata generation, query-entity extraction
    agent_chat_provider: str = "groq"
    agent_chat_model: str = "llama-3.3-70b-versatile"
    agent_self_correction_provider: str = "groq"
    agent_self_correction_model: str = "llama-3.3-70b-versatile"
    agent_extraction_provider: str = "groq"
    agent_extraction_model: str = "llama-3.3-70b-versatile"

    # When True, the model factory reads the active DB-backed ModelConfig row for each
    # role (set via the Admin API), falling back to the env values above when no row
    # exists. When False, the factory ignores the DB entirely and uses env only — a
    # kill-switch back to pure Phase-1 behavior. See MODEL_VENDOR_PICKING_PLAN.md §3.3.
    model_config_db_enabled: bool = True

    # Surface Anthropic extended thinking (Claude 3.7+/4 reasoning) as thinking deltas.
    # Off by default because enabling it forces temperature=1 and reserves part of the
    # output budget for thinking — a behavior change for the generation slot. Reasoning
    # surfacing for Groq / Ollama / DeepSeek / Qwen is always-on and needs no flag.
    agent_anthropic_extended_thinking: bool = False
    # Token budget reserved for Anthropic extended thinking when enabled (< max_tokens).
    agent_anthropic_thinking_budget: int = 2048

    # Optional backends for non-default slots.
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    # OpenAI (and Azure / OpenAI-compatible gateways via openai_base_url).
    openai_api_key: str = ""
    openai_base_url: str = ""
    # Generic OpenAI-protocol endpoint for the 'openai_compatible' provider — also the
    # home for vLLM, LM Studio, Together, OpenRouter, local gateways. Required when a
    # slot selects provider 'openai_compatible' or 'vllm'.
    openai_compatible_base_url: str = ""
    # First-class OpenAI-compatible vendors — preset base_urls, own key slots. The
    # base_urls can be overridden per role/config if a vendor changes endpoints.
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    qwen_api_key: str = ""
    # Alibaba DashScope OpenAI-compatible mode — international endpoint.
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

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

    # Connector pre-selection: before opening ANY connection, let the model pick which
    # enabled connectors are worth consulting from their control-plane catalog (name +
    # summary, no network I/O), and discover only those. Without this, a query fans out
    # discovery to every enabled connector and pays each dead server's full timeout. Off
    # falls back to the old "discover everything" behaviour.
    agent_connector_preselect: bool = True
    # Most connectors to discover after pre-selection (bounds the live blast radius).
    agent_connector_preselect_max: int = 4
    # When more connectors are enabled than this, the selection prompt can't show the full
    # list. Above the limit we switch to the semantic resolve path (the model names what it
    # needs, we look it up); at or below it, the model picks from the shown list directly.
    agent_connector_prefilter_limit: int = 40
    # Scale path: above the limit, let the model emit intent phrases (without seeing the
    # list) and resolve them semantically against the connector catalog. Off falls back to
    # lexical narrowing + the shown-list pick (no embeddings needed).
    agent_connector_semantic_resolve: bool = True
    # Minimum cosine similarity for a connector to be considered a semantic match.
    agent_connector_resolve_min_score: float = 0.55
    # Persist connector embeddings in a Chroma collection so they survive restarts (a
    # connector is only re-embedded when its name/summary changes). Off keeps the index
    # purely in-process (re-embedded on each restart). Best-effort: if Chroma is
    # unreachable, the resolver still works from the in-process cache.
    agent_connector_index_persist: bool = True
    # When a connector declares no icon of its own (MCP serverInfo.icons), fall back to a
    # favicon for the connector's domain. Uses a third-party favicon proxy, so it's
    # disabled automatically in air-gapped mode. Set False to never call out for icons.
    connector_favicon_fallback: bool = True
    # How long (seconds) to skip re-discovering a connector whose discovery just failed
    # (server down / timeout). A failing connector must not make every query pay its
    # timeout again; 0 disables the negative cache (the circuit breaker still applies).
    agent_discovery_failure_ttl_seconds: int = 60

    # Native tool-calling for tool/argument selection (live reads + gated actions).
    # When True, the selector binds each candidate tool's real input_schema to the model
    # and reads provider-validated tool_calls, instead of coercing JSON out of prose — so
    # arguments (e.g. a Gmail body) conform to the tool's schema. Falls back automatically
    # to the JSON path on any provider/parse failure. Set False to force the JSON path.
    agent_native_tool_calling: bool = True
    # Emit the controller-loop decision as a provider-validated tool call instead of
    # JSON-in-prose (schema-constrained; no parse/repair cycle). Opt-in: on Groq gpt-oss,
    # tool-calling mode drops the parsed-reasoning channel, so the controller's thinking
    # panel goes quiet on decision steps (narration is unaffected). Falls back to the
    # JSON path automatically on any provider failure.
    agent_controller_native_decision: bool = False
    # Cap (chars) on the gathered-evidence block fed into action selection so the model
    # grounds an action's arguments (the email body, the page content) in what was actually
    # retrieved, without blowing the prompt. 0 omits the evidence block.
    agent_action_context_max_chars: int = 6000
    # Content-aware findings: when a read returns evidence, the controller's finding carries
    # a short preview of WHAT was found (not just a count), so it can judge sufficiency
    # instead of re-reading blind. These bound that preview.
    agent_finding_preview_items: int = 4      # at most this many evidence snippets per read
    agent_finding_preview_chars: int = 240    # at most this many chars per snippet

    # ── Classic chat context enrichment ──────────────────────
    # Whole-document expansion: when the retrieved chunks concentrate on one corpus
    # document, pull its full text into the chat answer for richer context. Token-guarded
    # so a long document can't blow the context window (chars/4 ≈ tokens).
    chat_whole_doc_enabled: bool = True
    chat_whole_doc_min_chunks: int = 2        # ≥ this many chunks from one doc → expand it
    chat_whole_doc_max_chars: int = 12000     # hard cap on the pulled full-text (≈3k tokens)
    # Per-attachment text cap fed into the chat context (a big upload can't dominate).
    chat_attachment_max_chars: int = 8000

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
    # Controller loop (RESUMABLE_AGENT_SPEC_V2 §2.2, phase R4). When True, runs use the
    # bounded plan→execute→observe controller instead of the fixed
    # classify→retrieve→generate→verify pipeline. Default False — the controller is
    # opt-in until proven; the fixed pipeline stays the default and is unaffected.
    # Requires durable runs (the loop checkpoints + interrupts).
    agent_controller_loop: bool = False
    # Runaway fuse for the controller loop (spec §2.8): hard ceiling on controller
    # iterations per run. Not pacing — a coherent run finishes well under this.
    agent_controller_max_steps: int = 50
    # Context discipline + sprawl control (spec §2.7–2.8), phase R5.
    # Per-run token budget (rough char/4 estimate of working context); crossing it
    # triggers a graceful wrap-up. 0 disables. Set from observed single-pass costs ×10.
    agent_controller_token_budget: int = 120000
    # Stall detector: this many consecutive reads that add no new evidence forces a
    # re-plan; a second stall after that wraps up gracefully (spec §2.8).
    agent_controller_stall_threshold: int = 3
    # Bound the raw context carried in working state across reads (older raw payloads
    # live in the artifact store, not the checkpoint). Keeps long runs from bloating
    # the checkpoint; the per-read distilled findings preserve provenance.
    agent_controller_max_context_chunks: int = 40
    # Artifact store root (disk; spec §2.7). Empty → <document_store>/agent_artifacts.
    # A persistent volume is required in deployment; multi-host later = adapter swap.
    agent_artifact_root: str = ""
    # Compaction (spec §2.7): when working-context tokens cross this, the controller
    # LLM-summarizes older raw evidence into a dense finding and drops the raw (it stays
    # in the artifact store). Lower than the token-budget fuse — densify, don't wrap up.
    # 0 disables (the FIFO context cap still bounds growth). ~60% of the working window.
    agent_controller_compaction_threshold: int = 60000
    agent_controller_compaction_keep_recent: int = 8   # raw chunks kept un-compacted
    # Parallel map-reduce reads (spec §2.7): a read step may fan out into this many
    # concurrent sub-reads, each distilled then merged. This is the DEPLOYMENT DEFAULT;
    # each user can override it (1–5) in their Settings → Agent (see agents/user_prefs.py).
    agent_max_parallel_reads: int = 2
    # Whole-document expansion in the agent retrieval path — deployment defaults, each
    # per-user overridable in Settings → Agent (bounds in agents/user_prefs.py):
    #   min_chunks : ≥ this many chunks from one doc before its full text is pulled (2–5)
    #   max_docs   : how many distinct documents may be expanded in one read (1–5)
    #   max_pages  : per-document length cap, in pages (2–30); chars = pages × page_chars
    agent_whole_doc_min_chunks: int = 2
    agent_whole_doc_max_docs: int = 1
    agent_whole_doc_max_pages: int = 10
    agent_whole_doc_page_chars: int = 3000   # pages→chars conversion (~750 tokens/page)
    # Per-connector concurrency cap (spec §2.7/§6): bounds simultaneous live calls to one
    # connector so a wide fan-out can't trip provider rate limits.
    agent_connector_max_concurrency: int = 3
    # How long a paused run remains resumable. The TTL sweeper expires older
    # checkpoints (a paused approval older than this requires a fresh run).
    agent_run_ttl_hours: int = 72

    # ── Document generation sandbox (DOCUMENT_GENERATION_SANDBOX_GUIDE) ──
    # The `produce` action: the controller asks an LLM to write a self-contained
    # Python script and runs it in a locked-down container, returning the document.
    # Off by default — opt-in like the controller loop; requires the prebaked image
    # (backend/sandbox/) and a container runtime on the host.
    agent_produce_enabled: bool = False
    # Container runtime binary ("docker" | "podman"). run_sandbox shells out to it
    # with the security flags proven in backend/sandbox/README.md. Runtime-agnostic
    # so the deploy shape (Docker Desktop / rootless Podman) stays a config choice.
    agent_sandbox_runtime: str = "docker"
    # Prebaked toolchain image (built from backend/sandbox/Dockerfile). Pinned tag;
    # recorded in telemetry. Bump deliberately when the dep set changes.
    agent_sandbox_image: str = "deepquery-doctools:0.4"
    # Hard per-run resource limits (the blast-radius caps from §3.2). Timeout/memory are
    # sized so a rich, icon/chart-heavy build is never killed mid-run — the sandbox must
    # not be the document-quality ceiling.
    agent_sandbox_timeout_s: int = 240
    agent_sandbox_memory: str = "2g"
    agent_sandbox_cpus: str = "1"
    agent_sandbox_pids_limit: int = 128
    # Global concurrency gate: queued produce steps wait for a build slot.
    agent_sandbox_max_concurrent: int = 2
    # Output size cap (per produced file) enforced at validation, in addition to the
    # container's tmpfs limit.
    agent_sandbox_output_max_mb: int = 25
    # Repair loop (§5): max script-generation attempts before graceful degradation.
    agent_produce_max_attempts: int = 3
    # Output-token ceiling for the document script-generation call. 0 = UNCAPPED (the
    # provider's own maximum applies) — a long document/deck script must never be
    # truncated by our config; truncation is detected and repaired regardless.
    agent_produce_max_output_tokens: int = 0
    # Cap (chars) on the gathered-evidence block fed into script generation. The document's
    # SUBSTANCE comes from this — it carries the formatted sources (passages, whole docs,
    # live records, attachments) + working notes, far richer than the findings one-liners.
    agent_produce_context_max_chars: int = 24000
    # Optional dedicated model for document script generation (the PRODUCE slot). Unset →
    # the GENERATION slot's model writes the scripts. Point this at a code-strong model.
    agent_produce_provider: str = ""
    agent_produce_model: str = ""

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

    # ── OCR (scanned pages → BM25 + downstream text) ─────────
    # Path to the Tesseract binary. Leave empty to use PATH; otherwise the OCR
    # module also probes common install locations as a fallback.
    tesseract_cmd: str = ""


settings = Settings()

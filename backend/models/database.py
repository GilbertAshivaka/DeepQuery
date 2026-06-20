"""
Deep Query — SQLAlchemy ORM Models

All persistent database tables for users, documents, conversations,
ingestion jobs, and refresh tokens.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from core.constants import DocumentType, JobStatus, UserRole
from core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ═════════════════════════════════════════════════════════════
# User
# ═════════════════════════════════════════════════════════════
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.STUDENT)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    documents = relationship("Document", back_populates="uploader")
    conversations = relationship("Conversation", back_populates="user")
    refresh_tokens = relationship("RefreshToken", back_populates="user")
    query_logs = relationship("QueryLog", back_populates="user")


# ═════════════════════════════════════════════════════════════
# Document
# ═════════════════════════════════════════════════════════════
class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_uuid)
    original_filename = Column(String(500), nullable=False)
    stored_filename = Column(String(500), nullable=False)  # UUID-based
    file_extension = Column(String(10), nullable=False)
    file_size_bytes = Column(Integer, nullable=True)
    document_type = Column(Enum(DocumentType), default=DocumentType.OTHER)
    collection = Column(String(50), nullable=False, default="academic")
    summary = Column(Text, nullable=True)
    topic_tags = Column(Text, nullable=True)  # JSON-encoded list
    category = Column(String(100), nullable=True)
    category_confidence = Column(String(10), nullable=True)
    page_count = Column(Integer, nullable=True)
    chunk_count = Column(Integer, default=0)
    uploader_id = Column(String, ForeignKey("users.id"), nullable=False)
    upload_timestamp = Column(DateTime, default=_utcnow)
    is_deleted = Column(Boolean, default=False)
    # UMAP 2-D projection coordinates (computed by background task)
    umap_x = Column(Float, nullable=True)
    umap_y = Column(Float, nullable=True)
    umap_computed_at = Column(DateTime, nullable=True)

    # Relationships
    uploader = relationship("User", back_populates="documents")
    ingestion_jobs = relationship("IngestionJob", back_populates="document")


# ═════════════════════════════════════════════════════════════
# Ingestion Job
# ═════════════════════════════════════════════════════════════
class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(String, primary_key=True, default=_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING)
    celery_task_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    # Relationships
    document = relationship("Document", back_populates="ingestion_jobs")


# ═════════════════════════════════════════════════════════════
# Conversation (persisted server-side)
# ═════════════════════════════════════════════════════════════
class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String(500), nullable=True)  # Auto-generated from first message
    is_pinned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    user = relationship("User", back_populates="conversations")
    messages = relationship(
        "Message", back_populates="conversation", order_by="Message.created_at"
    )


# ═════════════════════════════════════════════════════════════
# Message (individual chat messages within a conversation)
# ═════════════════════════════════════════════════════════════
class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=_uuid)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    citations = Column(Text, nullable=True)  # JSON-encoded list of source references
    self_correction_status = Column(String(30), nullable=True)  # VERIFIED / CORRECTED / INSUFFICIENT_CONTEXT
    has_image_attachment = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")


# ═════════════════════════════════════════════════════════════
# Refresh Token (server-side storage for revocation)
# ═════════════════════════════════════════════════════════════
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")


# ═════════════════════════════════════════════════════════════
# Connector Registry (control plane — never holds live content)
# ═════════════════════════════════════════════════════════════
class Connector(Base):
    """A registered connector (an MCP server Deep Query can talk to).

    Control-plane metadata only: identity, where/how to reach it, and its
    manifest. No live business data is ever stored here (see guide §2, §13).
    """

    __tablename__ = "connectors"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(120), unique=True, nullable=False, index=True)
    version = Column(String(40), nullable=True)
    # Admin-supplied one-line description of what this connector provides. Drives the
    # semantic connector index (agent routing) and the connector cards in the UI.
    summary = Column(Text, nullable=True)
    # Connector logo/icon URL. Captured from the server's MCP serverInfo.icons at discovery
    # (the connector's own declared icon); falls back to a domain favicon at the API layer.
    icon_url = Column(Text, nullable=True)
    # Transport: "stdio" (local subprocess) | "sse" | "http" (remote).
    transport = Column(String(20), nullable=False, default="stdio")
    # For stdio: JSON {"command": "...", "args": [...]}; for sse/http: {"url": "..."}.
    endpoint = Column(Text, nullable=False)
    manifest = Column(Text, nullable=True)  # JSON snapshot of the SDK manifest, when available
    requires_network = Column(Boolean, default=True)
    is_enabled = Column(Boolean, default=True, nullable=False)
    # How the connector authenticates to its external system.
    auth_method = Column(String(20), nullable=False, default="none")
    # JSON OAuth/app config: {authorize_endpoint, token_endpoint, scopes, client_id,
    # client_secret_enc (encrypted), token_env}. Never holds a user credential.
    auth_config = Column(Text, nullable=True)
    # Ephemeral read-cache TTL in seconds (0 disables caching for this connector).
    cache_ttl_seconds = Column(Integer, nullable=False, default=30)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    audit_entries = relationship("ConnectorAuditLog", back_populates="connector")
    credentials = relationship("ConnectorCredential", back_populates="connector")


# ═════════════════════════════════════════════════════════════
# Connector Credential (per-user, encrypted at rest — guide §6)
# ═════════════════════════════════════════════════════════════
class ConnectorCredential(Base):
    """One per (user, connector). The encrypted payload holds the user's own
    external credential (OAuth tokens / API key / basic / mTLS paths). Bound to
    user identity so the agent acts with that user's permissions, never a shared
    service account."""

    __tablename__ = "connector_credentials"
    __table_args__ = (UniqueConstraint("user_id", "connector_id", name="uq_user_connector_cred"),)

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    connector_id = Column(String, ForeignKey("connectors.id"), nullable=False, index=True)
    method = Column(String(20), nullable=False)  # oauth2 | api_key | basic | mtls
    encrypted_payload = Column(Text, nullable=False)  # Fernet-encrypted JSON credential
    expires_at = Column(DateTime, nullable=True)  # access-token expiry, when known
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    connector = relationship("Connector", back_populates="credentials")


# ═════════════════════════════════════════════════════════════
# Connector Audit Log (compliance — who/what/when/outcome)
# ═════════════════════════════════════════════════════════════
class ConnectorAuditLog(Base):
    """One row per connector call. The enterprise audit trail the raw MCP
    ecosystem lacks (guide §5, §12). Records control-plane facts only."""

    __tablename__ = "connector_audit_log"

    id = Column(String, primary_key=True, default=_uuid)
    # Nullable: agentless/system calls (e.g. the Phase 1 smoke test) have no user.
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    connector_id = Column(String, ForeignKey("connectors.id"), nullable=True)
    connector_name = Column(String(120), nullable=False)
    capability_name = Column(String(200), nullable=False)
    kind = Column(String(20), nullable=False)  # "read" | "action"
    action_phase = Column(String(20), nullable=True)  # "preview" | "execute" | None
    approved_by = Column(String, nullable=True)  # user id who approved an action (Phase 4)
    outcome = Column(String(20), nullable=False)  # "success" | "error"
    error_message = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)

    # Relationships
    connector = relationship("Connector", back_populates="audit_entries")


# ═════════════════════════════════════════════════════════════
# Connector Approval — the admin allowlist (guide §9, Tier 1)
# ═════════════════════════════════════════════════════════════
class ConnectorApproval(Base):
    """One per connector: whether an admin approved it into this deployment's
    allowlist, which roles may use it, and the version it was approved at
    (version-pinned — a major upgrade re-enters review)."""

    __tablename__ = "connector_allowlist"

    id = Column(String, primary_key=True, default=_uuid)
    connector_id = Column(String, ForeignKey("connectors.id"), nullable=False, unique=True, index=True)
    is_approved = Column(Boolean, default=True, nullable=False)
    approved_version = Column(String(40), nullable=True)  # version pin
    # JSON list of role strings permitted to use it; NULL/empty = all roles.
    # Stored as opaque strings (the role taxonomy is deployment-specific).
    allowed_roles = Column(Text, nullable=True)
    approved_by = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    connector = relationship("Connector")


# ═════════════════════════════════════════════════════════════
# User Connector Enablement (guide §9, Tier 2)
# ═════════════════════════════════════════════════════════════
class UserConnectorEnablement(Base):
    """A user opting in to an approved connector for themselves."""

    __tablename__ = "user_connector_enablement"
    __table_args__ = (UniqueConstraint("user_id", "connector_id", name="uq_user_connector_enable"),)

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    connector_id = Column(String, ForeignKey("connectors.id"), nullable=False, index=True)
    enabled_at = Column(DateTime, default=_utcnow)


# ═════════════════════════════════════════════════════════════
# Query Log (for knowledge gap detection & analytics)
# ═════════════════════════════════════════════════════════════
class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    query_text = Column(Text, nullable=False)
    answer_status = Column(String(30), nullable=True)  # VERIFIED / CORRECTED / INSUFFICIENT_CONTEXT
    retrieval_time_ms = Column(Integer, nullable=True)
    total_response_time_ms = Column(Integer, nullable=True)
    chunks_retrieved = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    # Relationships
    user = relationship("User", back_populates="query_logs")


# ═════════════════════════════════════════════════════════════
# Skill Files (Agent Layer — versioned, reversible instructions)
# ═════════════════════════════════════════════════════════════
class SkillFile(Base):
    """An agent/assistant skill file (guide §10). Two content kinds: `body` =
    human intent (goal, workflow, voice — off-limits to the Skill Sync Agent), and
    `fact_sections` = corpus-derived facts (maintained by Skill Sync). DB is the
    source of truth; content follows the Anthropic Agent-Skills format."""

    __tablename__ = "skill_files"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(120), unique=True, nullable=False, index=True)  # lowercase-hyphen
    description = Column(Text, nullable=False)  # what + when (drives triggering)
    kind = Column(String(20), nullable=False, default="assistant")  # assistant | sub-agent
    body = Column(Text, nullable=False, default="")            # human-intent markdown
    fact_sections = Column(Text, nullable=False, default="[]")  # JSON [{name, content}] (sync-maintained)
    metadata_json = Column(Text, nullable=True)  # JSON deepquery: connectors, capabilities, model_overrides
    current_version = Column(Integer, nullable=False, default=1)
    is_archived = Column(Boolean, default=False, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class SkillFileVersion(Base):
    """An immutable snapshot of a skill file at one version — the basis for
    attributable, reversible edits (guide §10)."""

    __tablename__ = "skill_file_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version_no", name="uq_skill_version"),)

    id = Column(String, primary_key=True, default=_uuid)
    skill_id = Column(String, ForeignKey("skill_files.id"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    body = Column(Text, nullable=False, default="")
    fact_sections = Column(Text, nullable=False, default="[]")
    metadata_json = Column(Text, nullable=True)
    change_summary = Column(Text, nullable=True)
    # Attribution: "create" | "admin:<uid>" | "skill_sync:doc:<docid>" | "rollback:v<N>"
    triggered_by = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class SkillDependency(Base):
    """A skill's dependency on a corpus document/entity. `declared=True` = explicitly
    declared by the author (high-confidence sync signal); `declared=False` = inferred
    by the Sync Agent (lower confidence)."""

    __tablename__ = "skill_dependencies"

    id = Column(String, primary_key=True, default=_uuid)
    skill_id = Column(String, ForeignKey("skill_files.id"), nullable=False, index=True)
    dep_type = Column(String(20), nullable=False)   # "document" | "entity"
    dep_ref = Column(String(500), nullable=False)    # document_id or entity name
    declared = Column(Boolean, default=True, nullable=False)
    fact_section = Column(String(200), nullable=True)  # which fact section it grounds
    created_at = Column(DateTime, default=_utcnow)


class AgentConversation(Base):
    """A multi-turn agent conversation (the Agents surface — separate from chat).
    Provides cross-turn memory: prior turns are loaded as history for each new run."""

    __tablename__ = "agent_conversations"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class AgentTurn(Base):
    """One turn in an agent conversation (user or assistant). Doubles as the
    lightweight agent-run trace (intent, citations, grounding, verification, any
    proposed action) — guide §13."""

    __tablename__ = "agent_turns"

    id = Column(String, primary_key=True, default=_uuid)
    conversation_id = Column(String, ForeignKey("agent_conversations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False, default="")
    intent = Column(String(20), nullable=True)
    citations = Column(Text, nullable=True)            # JSON list (document + live)
    grounded = Column(Boolean, nullable=True)
    verification_status = Column(String(30), nullable=True)
    proposed_action = Column(Text, nullable=True)      # JSON (pending action, if any)
    agent_trace = Column(Text, nullable=True)          # JSON {plan:[...], trace:[...]} — CoT timeline + plan, for reload
    created_at = Column(DateTime, default=_utcnow, index=True)


class AgentAttachment(Base):
    """A document/image a user attached to an agent query. The raw file is saved to
    disk (`stored_path`); for documents the parsed `extracted_text` is kept so a
    reloaded conversation can re-use it without re-parsing. Images are stored now
    (file + metadata) and fed to the model once a multimodal generation path exists."""

    __tablename__ = "agent_attachments"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(String, ForeignKey("agent_conversations.id"), nullable=True, index=True)
    turn_id = Column(String, ForeignKey("agent_turns.id"), nullable=True, index=True)
    kind = Column(String(20), nullable=False, default="document")  # "document" | "image"
    filename = Column(String(500), nullable=False)
    content_type = Column(String(100), nullable=True)
    file_extension = Column(String(10), nullable=True)
    stored_path = Column(String(1000), nullable=False)   # raw file on disk
    extracted_text = Column(Text, nullable=True)          # parsed text (documents)
    created_at = Column(DateTime, default=_utcnow)


class SkillChangeProposal(Base):
    """A Skill-Sync-Agent-proposed edit to one corpus-fact section, awaiting admin
    review. Never auto-applied (guide §11). On approval → new reversible version."""

    __tablename__ = "skill_change_proposals"

    id = Column(String, primary_key=True, default=_uuid)
    skill_id = Column(String, ForeignKey("skill_files.id"), nullable=False, index=True)
    fact_section = Column(String(200), nullable=False)
    old_content = Column(Text, nullable=True)
    new_content = Column(Text, nullable=False)
    trigger_document_id = Column(String, nullable=True)
    trigger_summary = Column(Text, nullable=True)              # what changed in the doc
    confidence = Column(String(20), nullable=False, default="inferred")  # explicit | inferred
    status = Column(String(20), nullable=False, default="pending")  # pending | approved | rejected
    created_at = Column(DateTime, default=_utcnow, index=True)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String, ForeignKey("users.id"), nullable=True)


# ═════════════════════════════════════════════════════════════
# Model Config — runtime, DB-backed model-vendor selection
# ═════════════════════════════════════════════════════════════
class ModelConfig(Base):
    """The active (and historical) model selection for a role.

    A 'role' is a model slot — agent: orchestration | generation | verification;
    classic pipeline: chat | self_correction | extraction; plus embedding. Each PUT
    inserts a new row and deactivates the prior active row for that role, so history is
    retained for audit/rollback. The model factory reads the active row, falling back to
    env settings when none exists (env is the bootstrap floor). See
    MODEL_VENDOR_PICKING_PLAN.md §4.
    """

    __tablename__ = "model_config"

    id = Column(String, primary_key=True, default=_uuid)
    role = Column(String(40), nullable=False, index=True)
    provider = Column(String(40), nullable=False)
    model = Column(String(200), nullable=False)
    base_url = Column(String(500), nullable=True)       # openai_compatible / self-hosted
    params_json = Column(Text, nullable=True)           # JSON: temperature, max_tokens, …
    key_mode = Column(String(20), nullable=False, default="managed")  # managed | byok
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    created_at = Column(DateTime, default=_utcnow, index=True)


# ═════════════════════════════════════════════════════════════
# Provider Key — encrypted BYOK vendor API keys (deployment-global)
# ═════════════════════════════════════════════════════════════
class ProviderKey(Base):
    """A bring-your-own-key (BYOK) vendor API key, encrypted at rest. One row per
    provider, deployment-global (per-deployment granularity). When present, the key
    resolver prefers it over the managed env key. The plaintext key is never returned
    over the API — only ``key_hint`` (last 4 chars). Reuses the connector credential
    encryption (Fernet). See MODEL_VENDOR_PICKING_PLAN.md §5."""

    __tablename__ = "provider_keys"

    id = Column(String, primary_key=True, default=_uuid)
    provider = Column(String(40), nullable=False, unique=True, index=True)
    encrypted_key = Column(Text, nullable=False)        # Fernet token
    key_hint = Column(String(12), nullable=True)        # last 4 chars, for display
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# ═════════════════════════════════════════════════════════════
# App Setting — deployment-global runtime flags (key/value)
# ═════════════════════════════════════════════════════════════
class AppSetting(Base):
    """A small key/value store for deployment-global runtime settings that don't fit the
    per-role ``model_config`` shape — e.g. the Anthropic extended-thinking toggle. The
    value is JSON-encoded so booleans, numbers, and small objects all round-trip. Writes
    bump the shared model-config version so the model factory rebuilds across workers
    (the thinking flag changes how Anthropic models are constructed). Env settings remain
    the bootstrap floor when a key is absent."""

    __tablename__ = "app_settings"

    key = Column(String(80), primary_key=True)
    value_json = Column(Text, nullable=True)            # JSON-encoded value
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

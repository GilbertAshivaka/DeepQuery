"""
Deep Query — Constants

Application-wide constants and enumerations.
"""

from enum import Enum


# ── User Roles ───────────────────────────────────────────────
class UserRole(str, Enum):
    STUDENT = "student"
    RESEARCHER = "researcher"
    LECTURER = "lecturer"
    HOD = "hod"
    STAFF = "staff"
    ADMIN = "admin"


# ── Document Types ───────────────────────────────────────────
class DocumentType(str, Enum):
    RESEARCH_PAPER = "research_paper"
    THESIS = "thesis"
    POLICY_DOCUMENT = "policy_document"
    ADMINISTRATIVE_RECORD = "administrative_record"
    DEPARTMENTAL_REPORT = "departmental_report"
    LECTURE_NOTES = "lecture_notes"
    EXAM_PAPER = "exam_paper"
    OTHER = "other"


# ── ChromaDB Collection Names (RBAC tiers) ───────────────────
class Collection(str, Enum):
    ACADEMIC = "academic"
    DEPARTMENTAL = "departmental"
    ADMINISTRATIVE = "administrative"
    MANAGEMENT = "management"


# ── Role → Collection Access Map ─────────────────────────────
ROLE_COLLECTIONS: dict[UserRole, list[Collection]] = {
    UserRole.STUDENT: [Collection.ACADEMIC],
    UserRole.RESEARCHER: [Collection.ACADEMIC, Collection.DEPARTMENTAL],
    UserRole.STAFF: [Collection.ADMINISTRATIVE],
    UserRole.ADMIN: [
        Collection.ACADEMIC,
        Collection.DEPARTMENTAL,
        Collection.ADMINISTRATIVE,
        Collection.MANAGEMENT,
    ],
}


# ── Ingestion Job Status ─────────────────────────────────────
class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


# ── Self-Correction Outcomes ─────────────────────────────────
class CorrectionOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    CORRECTED = "CORRECTED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


# ── LLM Temperature Profiles ────────────────────────────────
LLM_TEMPERATURES = {
    "rag_generation": 0.2,
    "self_correction": 0.0,
    "entity_extraction": 0.0,
    "metadata_generation": 0.3,
}

# ── Supported Upload Extensions ──────────────────────────────
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm"}

# ── Retrieval Defaults ───────────────────────────────────────
DENSE_TOP_K = 20
SPARSE_TOP_K = 20
RERANK_TOP_N = 8
FINAL_CONTEXT_CHUNKS = 5

# ── Cross-Encoder Pre-Filter ─────────────────────────────────
COSINE_SIMILARITY_THRESHOLD = 0.45  # Filter candidates below this before reranking
MIN_RERANK_CANDIDATES = 3  # Minimum candidates to send to reranker

# ── Max token budget for RAG prompt ──────────────────────────
RAG_PROMPT_TOKEN_BUDGET = 8000

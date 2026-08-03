"""
Deep Query — Model Vendor Config Endpoints (admin)

Runtime selection of the vendor/model per role. Backs the upcoming Settings page.

GET    /api/admin/model-config            — effective config per role + provider availability
PUT    /api/admin/model-config/{role}     — set a role's provider/model (bumps cache version)
POST   /api/admin/model-config/{role}/test — test-connection probe (no persistence)
GET    /api/admin/provider-keys           — per-provider key status (hints only, no plaintext)
PUT    /api/admin/provider-keys/{provider} — store a BYOK key (encrypted; bumps version)
DELETE /api/admin/provider-keys/{provider} — remove a BYOK key (revert to managed)

Keys resolve BYOK-first, then managed env. Plaintext keys are never returned.
"""

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.models import Slot, config_store, probe_model, provider_keys
from agents.models.slots import (
    CLOUD_PROVIDERS,
    DEFAULT_EFFORT,
    LOCAL_PROVIDERS,
    VALID_EFFORTS,
    ModelSlotError,
)
from auth.dependencies import RoleRequired, get_current_user
from core.config import settings
from core.constants import UserRole
from models.database import User

router = APIRouter()
admin_only = RoleRequired([UserRole.ADMIN])

SUPPORTED_PROVIDERS = sorted(CLOUD_PROVIDERS | LOCAL_PROVIDERS)
_SLOT_BY_ROLE = {s.value: s for s in Slot}


class ModelConfigUpdate(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    params: Optional[dict] = None


class ModelConfigTest(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None


class ProviderKeyUpdate(BaseModel):
    api_key: str


class ReindexRequest(BaseModel):
    provider: str
    model: str
    dimensions: int
    base_url: Optional[str] = None


class ThinkingConfigUpdate(BaseModel):
    enabled: bool
    # Thinking depth for the Claude 5 family (which takes an effort level instead of a
    # token budget). Omitted → the current effort is left unchanged.
    effort: Optional[str] = None


THINKING_FLAG = "anthropic_extended_thinking"
EFFORT_FLAG = "anthropic_thinking_effort"


def _provider_availability() -> dict:
    """Whether each provider has a usable credential/endpoint — BYOK key, managed env
    key, or (for local providers) a configured base_url. The UI uses this to disable
    providers that aren't ready, and to show where the key comes from."""
    status = provider_keys.list_status()
    out: dict = {}
    for p in SUPPORTED_PROVIDERS:
        s = status.get(p, {})
        if p in ("openai_compatible", "vllm"):
            available = bool(settings.openai_compatible_base_url)
        elif p == "ollama":
            available = bool(settings.ollama_base_url)
        else:
            available = bool(s.get("byok") or s.get("managed"))
        out[p] = {
            "available": available,
            "needs_key": p not in LOCAL_PROVIDERS,
            "key_source": s.get("source", "none"),
            "byok": s.get("byok", False),
            "hint": s.get("hint"),
        }
    return out


def _validate(role: str, provider: str) -> None:
    provider = provider.lower().strip()
    if role not in config_store.ALL_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role '{role}'. Valid: {', '.join(config_store.ALL_ROLES)}.",
        )
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider '{provider}'. Valid: {', '.join(SUPPORTED_PROVIDERS)}.",
        )
    mode = settings.deployment_mode.lower().strip()
    if mode == "air-gapped" and provider not in LOCAL_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Deployment mode 'air-gapped' forbids cloud provider '{provider}'. "
                f"Choose a local provider ({', '.join(sorted(LOCAL_PROVIDERS))})."
            ),
        )


@router.get("/model-config", dependencies=[Depends(admin_only)])
def get_model_config():
    """Effective per-role config + provider availability + supported-provider list."""
    return {
        "roles": config_store.effective_roles(),
        "providers": _provider_availability(),
        "supported_providers": SUPPORTED_PROVIDERS,
        "llm_roles": list(config_store.LLM_ROLES),
        "embedding_role": config_store.EMBEDDING_ROLE,
        "deployment_mode": settings.deployment_mode,
        "version": config_store.current_version(),
        "db_enabled": settings.model_config_db_enabled,
    }


# ── Reasoning / extended-thinking toggle ─────────────────────────
# Declared before the parameterized /model-config/{role} routes so the literal
# "/model-config/thinking" path isn't captured as role="thinking".


@router.get("/model-config/thinking", dependencies=[Depends(admin_only)])
def get_thinking_config():
    """Current Anthropic extended-thinking setting. Effective value resolves to the
    DB-backed flag if set, otherwise the env default. CoT for other providers (Groq /
    DeepSeek / Qwen / Ollama) is always-on and not controlled here."""
    db_value = config_store.get_flag(THINKING_FLAG, None)
    enabled = (
        bool(db_value)
        if db_value is not None
        else bool(settings.agent_anthropic_extended_thinking)
    )
    db_effort = config_store.get_flag(EFFORT_FLAG, None)
    effort = str(
        db_effort if db_effort is not None else settings.agent_anthropic_thinking_effort
    ).lower().strip()
    if effort not in VALID_EFFORTS:
        effort = DEFAULT_EFFORT
    return {
        "enabled": enabled,
        "source": "db" if db_value is not None else "env",
        "effort": effort,
        "effort_source": "db" if db_effort is not None else "env",
        "effort_options": list(VALID_EFFORTS),
        # Legacy control: applies to the older Claude models (thinking type "enabled").
        # The Claude 5 family uses `effort` instead.
        "budget_tokens": settings.agent_anthropic_thinking_budget,
        "applies_to": "anthropic",
        "note": (
            "Only affects Anthropic models. Other providers surface chain-of-thought "
            "automatically and cannot be toggled. Effort applies to the Claude 5 family; "
            "older Claude models use the token budget instead."
        ),
    }


@router.put("/model-config/thinking", dependencies=[Depends(admin_only)])
def set_thinking_config(
    body: ThinkingConfigUpdate,
    user: User = Depends(get_current_user),
):
    """Enable/disable Anthropic extended thinking at runtime, and optionally set the
    thinking effort used by the Claude 5 family. Bumps the config version so cached
    Anthropic models rebuild across workers on the next call."""
    if not settings.model_config_db_enabled:
        raise HTTPException(
            status_code=409,
            detail="DB-backed model config is disabled (model_config_db_enabled=False).",
        )
    effort = None
    if body.effort is not None:
        effort = body.effort.lower().strip()
        if effort not in VALID_EFFORTS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid effort '{body.effort}'. One of: {', '.join(VALID_EFFORTS)}.",
            )
    config_store.set_flag(THINKING_FLAG, bool(body.enabled), updated_by=user.id)
    if effort is not None:
        config_store.set_flag(EFFORT_FLAG, effort, updated_by=user.id)
    return {
        "enabled": bool(body.enabled),
        "source": "db",
        **({"effort": effort, "effort_source": "db"} if effort is not None else {}),
        "version": config_store.current_version(),
    }


@router.put("/model-config/{role}", dependencies=[Depends(admin_only)])
def set_model_config(
    role: str,
    body: ModelConfigUpdate,
    user: User = Depends(get_current_user),
):
    """Set the active provider/model for a role. Bumps the version so the model factory
    rebuilds across all workers on the next call. Does not validate connectivity — call
    the /test endpoint first."""
    if not settings.model_config_db_enabled:
        raise HTTPException(
            status_code=409,
            detail="DB-backed model config is disabled (model_config_db_enabled=False).",
        )
    if role == config_store.EMBEDDING_ROLE:
        raise HTTPException(
            status_code=400,
            detail=(
                "The embedding model cannot be changed in place — switching it requires "
                "a re-index. Use POST /api/admin/embedding/reindex."
            ),
        )
    _validate(role, body.provider)
    if not body.model.strip():
        raise HTTPException(status_code=400, detail="Model id is required.")

    stored = config_store.set_role(
        role=role,
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
        params=body.params,
        updated_by=user.id,
    )
    return {"role": role, "config": stored, "version": config_store.current_version()}


@router.post("/model-config/{role}/test", dependencies=[Depends(admin_only)])
def test_model_config(role: str, body: ModelConfigTest):
    """Build the candidate config and do a 1-token round-trip. Returns ok/latency/error
    without persisting anything — so the UI can validate before saving."""
    _validate(role, body.provider)
    slot = _SLOT_BY_ROLE.get(role)  # None for the embedding role (LLM probe N/A)
    if slot is None:
        raise HTTPException(
            status_code=400,
            detail="Test-connection is only available for LLM roles in this phase.",
        )

    from langchain_core.messages import HumanMessage

    t0 = time.perf_counter()
    try:
        llm = probe_model(body.provider, body.model, base_url=body.base_url, role=slot)
        resp = llm.invoke([HumanMessage(content="ping")])
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        sample = (resp.content or "")[:80] if hasattr(resp, "content") else ""
        return {"ok": True, "latency_ms": latency_ms, "sample": sample}
    except ModelSlotError as exc:
        return {"ok": False, "error": str(exc), "kind": "config"}
    except Exception as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"ok": False, "error": str(exc), "kind": "runtime", "latency_ms": latency_ms}


# ── BYOK provider keys ───────────────────────────────────────────


@router.get("/provider-keys", dependencies=[Depends(admin_only)])
def get_provider_keys():
    """Per-provider key status (BYOK present?, hint, managed present?, effective source).
    Never returns plaintext keys."""
    return {
        "keys": provider_keys.list_status(),
        "version": config_store.current_version(),
    }


@router.put("/provider-keys/{provider}", dependencies=[Depends(admin_only)])
def set_provider_key(
    provider: str,
    body: ProviderKeyUpdate,
    user: User = Depends(get_current_user),
):
    """Store (encrypted) a BYOK key for a provider. It then takes precedence over the
    managed env key. Bumps the version so cached models rebuild. Returns only a hint."""
    provider = provider.lower().strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider '{provider}'. Valid: {', '.join(SUPPORTED_PROVIDERS)}.",
        )
    try:
        return provider_keys.set_key(provider, body.api_key, created_by=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/provider-keys/{provider}", dependencies=[Depends(admin_only)])
def delete_provider_key(provider: str):
    """Remove a provider's BYOK key, reverting it to the managed env key. Bumps version."""
    provider = provider.lower().strip()
    removed = provider_keys.delete_key(provider)
    return {"provider": provider, "removed": removed, "source": provider_keys.effective_source(provider)}


# ── Embedding re-index (blue-green migration) ────────────────────

EMBEDDING_PROVIDERS = ["google", "openai", "ollama", "qwen"]
EMBEDDING_LOCAL_PROVIDERS = {"ollama"}


@router.get("/embedding", dependencies=[Depends(admin_only)])
def get_embedding_config():
    """Active embedding config + the current re-index job status. Embedding is special —
    it changes only via re-index, not the generic model-config PUT."""
    from tasks.reindex_task import get_status

    roles = config_store.effective_roles()
    return {
        "active": roles.get(config_store.EMBEDDING_ROLE),
        "supported_providers": EMBEDDING_PROVIDERS,
        "providers": {p: _provider_availability().get(p) for p in EMBEDDING_PROVIDERS},
        "deployment_mode": settings.deployment_mode,
        "reindex_status": get_status(),
        "warning": (
            "Switching the embedding model re-embeds the entire corpus into new "
            "collections (blue-green) and cannot be undone in place. Multimodal/image "
            "chunks are re-embedded from their caption/OCR text on text-only providers."
        ),
    }


@router.post("/embedding/reindex", dependencies=[Depends(admin_only)])
def start_embedding_reindex(body: ReindexRequest):
    """Launch a blue-green re-index with a new embedding provider/model. The current
    embedder keeps serving until the job completes and promotes the new one."""
    provider = body.provider.lower().strip()
    if provider not in EMBEDDING_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported embedding provider '{provider}'. Valid: {', '.join(EMBEDDING_PROVIDERS)}.",
        )
    if not body.model.strip():
        raise HTTPException(status_code=400, detail="Model id is required.")
    if body.dimensions <= 0:
        raise HTTPException(status_code=400, detail="dimensions must be a positive integer.")
    mode = settings.deployment_mode.lower().strip()
    if mode == "air-gapped" and provider not in EMBEDDING_LOCAL_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Deployment mode 'air-gapped' forbids embedding provider '{provider}'.",
        )

    from tasks.reindex_task import get_status, reindex_embeddings

    current = get_status()
    if current.get("state") == "running":
        raise HTTPException(status_code=409, detail="A re-index is already running.")

    result = reindex_embeddings.delay(
        provider=provider,
        model=body.model.strip(),
        dimensions=body.dimensions,
        base_url=body.base_url,
    )
    return {"job_id": result.id, "state": "queued"}


@router.get("/embedding/reindex/status", dependencies=[Depends(admin_only)])
def embedding_reindex_status():
    """Poll the current/last re-index job status (progress per collection)."""
    from tasks.reindex_task import get_status

    return get_status()

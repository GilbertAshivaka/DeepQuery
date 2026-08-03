"""
Deep Query — Agent Model Slots

A provider-agnostic abstraction over the LLMs that drive the agent layer. Three
independently configurable slots — orchestration, generation, verification — each
resolving to a LangChain ``BaseChatModel``. The model is a configuration choice, not
a hard dependency (guide §6): any slot can be swapped per deployment.

Default (under evaluation): Gemini 2.5 Flash for all three slots. The existing chat
RAG path is unaffected; it keeps using the Groq/Llama client in ``llm/``.

Air-gapped deployments are constrained here, not just advised: when
``settings.deployment_mode == "air-gapped"`` only local providers are permitted, and
selecting a cloud provider for any slot raises ``ModelSlotError``.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

from core.config import settings

logger = logging.getLogger(__name__)


class Slot(str, Enum):
    """The independently-configurable model slots.

    ORCHESTRATION / GENERATION / VERIFICATION drive the agent layer. CHAT /
    SELF_CORRECTION / EXTRACTION drive the classic user-facing RAG pipeline
    (``llm/groq_client.py``), folded onto this same factory so it is vendor-swappable
    too — and so each classic workload can run a different model (e.g. a cheaper model
    for batch extraction than for chat). Each slot reads ``agent_{slot}_provider`` /
    ``agent_{slot}_model`` from settings.

    Note SELF_CORRECTION (classic answer verification) is distinct from the agent
    layer's VERIFICATION slot; they are different subsystems with independent config.
    """

    ORCHESTRATION = "orchestration"
    GENERATION = "generation"
    VERIFICATION = "verification"
    # Document script generation (the produce sandbox). Unconfigured → falls back to
    # GENERATION, so a deployment can point a code-strong model at document building
    # without touching what answers chat.
    PRODUCE = "produce"
    # Classic RAG pipeline roles:
    CHAT = "chat"                      # RAG answer generation
    SELF_CORRECTION = "self_correction"  # answer verification / correction
    EXTRACTION = "extraction"         # entity extraction, metadata, query-entity extraction


# Providers that require external network egress — forbidden in air-gapped mode.
# deepseek / qwen are first-class OpenAI-compatible cloud vendors (preset base_urls).
CLOUD_PROVIDERS = {"google", "groq", "anthropic", "openai", "deepseek", "qwen"}
# Providers that run on local/self-hosted infrastructure — the only ones allowed
# in air-gapped mode. 'openai_compatible' is a generic OpenAI-protocol endpoint
# (vLLM / LM Studio / local gateways); its base_url is admin-controlled, so it is
# treated as local for deployment-mode purposes.
LOCAL_PROVIDERS = {"ollama", "vllm", "openai_compatible"}

# Default sampling temperature per slot. Orchestration plans (near-deterministic),
# generation has a little room, verification is strict. CHAT is a fallback only —
# the legacy client passes an explicit per-operation temperature on every call.
SLOT_TEMPERATURES = {
    Slot.ORCHESTRATION: 0.1,
    Slot.GENERATION: 0.2,
    Slot.VERIFICATION: 0.0,
    Slot.PRODUCE: 0.2,
    Slot.CHAT: 0.2,
    Slot.SELF_CORRECTION: 0.0,
    Slot.EXTRACTION: 0.0,
}

# Cap output tokens for providers that require/accept an explicit ceiling.
DEFAULT_MAX_TOKENS = 4096
# Sentinel for "no output cap": the provider's output-token parameter is omitted
# entirely, so its own maximum applies (a long document script is never truncated by
# our config). Anthropic REQUIRES max_tokens, so it gets a large fixed ceiling instead.
UNCAPPED = -1
ANTHROPIC_UNCAPPED_TOKENS = 64000


class ModelSlotError(RuntimeError):
    """Raised when a slot cannot be resolved (missing key, missing optional
    dependency, or a deployment-mode violation)."""


def _resolve_slot(slot: Slot) -> tuple[str, str, str | None, dict]:
    """Resolve a slot to ``(provider, model, base_url, params)``.

    Prefers the active DB-backed ``ModelConfig`` row (set via the Admin API), falling
    back to env settings when no row exists or the store is disabled/unavailable — env
    is the bootstrap floor (MODEL_VENDOR_PICKING_PLAN.md §3.3)."""
    from agents.models import config_store  # lazy: avoids import cycle at module load

    row = config_store.resolve_role(slot.value)
    if row and row.get("provider") and row.get("model"):
        return row["provider"], row["model"], row.get("base_url"), row.get("params") or {}

    provider = getattr(settings, f"agent_{slot.value}_provider", "").lower().strip()
    model = getattr(settings, f"agent_{slot.value}_model", "").strip()
    if not provider or not model:
        if slot is Slot.PRODUCE:
            # PRODUCE is optional config — unconfigured, document scripts are written
            # by the GENERATION model (the pre-slot behavior).
            return _resolve_slot(Slot.GENERATION)
        raise ModelSlotError(
            f"Slot '{slot.value}' is not configured "
            f"(agent_{slot.value}_provider / agent_{slot.value}_model)."
        )
    return provider, model, None, {}


def _slot_config(slot: Slot) -> tuple[str, str]:
    """Return the (provider, model) resolved for a slot (DB-backed, env fallback)."""
    provider, model, _, _ = _resolve_slot(slot)
    return provider, model


def _assert_deployment_allows(provider: str, slot: Slot) -> None:
    """Enforce deployment-mode constraints on provider choice (guide §6)."""
    mode = settings.deployment_mode.lower().strip()
    if mode == "air-gapped" and provider not in LOCAL_PROVIDERS:
        raise ModelSlotError(
            f"Deployment mode 'air-gapped' forbids cloud provider '{provider}' "
            f"for the '{slot.value}' slot. Configure a local provider "
            f"({', '.join(sorted(LOCAL_PROVIDERS))})."
        )
    if provider not in CLOUD_PROVIDERS and provider not in LOCAL_PROVIDERS:
        raise ModelSlotError(
            f"Unknown model provider '{provider}' for slot '{slot.value}'. "
            f"Supported: {', '.join(sorted(CLOUD_PROVIDERS | LOCAL_PROVIDERS))}."
        )


# Substrings that mark a model as a reasoning/thinking model (used to enable the local
# Ollama reasoning mode only where the model supports it).
_REASONING_MODEL_HINTS = ("r1", "qwq", "reasoning", "think", "o1", "o3", "magistral", "phi-4-reasoning")


def _is_reasoning_model(model: str) -> bool:
    m = model.lower()
    return any(h in m for h in _REASONING_MODEL_HINTS)


# ── Anthropic model generations ──────────────────────────────────
# Anthropic changed its parameter contract with the Claude 5 family:
#
#   older (3.x / 4.x)  temperature required; thinking={"type": "enabled",
#                      "budget_tokens": N}
#   Claude 5 family    temperature REJECTED ("`temperature` is deprecated for this
#                      model"); thinking={"type": "adaptive"} plus a top-level
#                      output_config={"effort": ...} in place of a token budget
#
# Match on explicit family prefixes — never a bare "-5" suffix. 'claude-haiku-4-5' is
# new-generation while 'claude-sonnet-4-5' / 'claude-opus-4-5' are old, so a substring
# test on "-5" would misclassify the latter two and break working deployments.
_ANTHROPIC_ADAPTIVE_FAMILIES = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-5",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-haiku-4-5",
)

# Effort levels accepted by output_config.effort (anthropic.types.OutputConfigParam).
# Note 'xhigh' is optional per-model in the API's capability metadata, so it is offered as
# an explicit admin choice but never auto-selected as a fallback.
VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "medium"


def _is_anthropic_adaptive(model: str) -> bool:
    """Whether an Anthropic model id belongs to the Claude 5 (adaptive-thinking) family.

    Substring match on explicit family prefixes, so a gateway-prefixed id
    (``anthropic.claude-opus-5`` via Bedrock/Vertex) still classifies correctly. Ids
    carrying no known marker return False — an unknown alias keeps the long-standing
    parameter shape rather than silently switching contracts."""
    m = model.lower().strip()
    return any(f in m for f in _ANTHROPIC_ADAPTIVE_FAMILIES)


def _resolve_effort() -> str:
    """The thinking effort level for the Claude 5 family: DB flag → env default. An
    unrecognized value degrades to ``DEFAULT_EFFORT`` rather than raising — a bad flag
    should never take the agent layer down."""
    from agents.models import config_store  # lazy: avoids import cycle at module load

    raw = config_store.get_flag(
        "anthropic_thinking_effort", settings.agent_anthropic_thinking_effort
    )
    effort = str(raw or "").lower().strip()
    if effort not in VALID_EFFORTS:
        if effort:
            logger.warning(
                "Unknown Anthropic thinking effort %r; falling back to %r",
                effort,
                DEFAULT_EFFORT,
            )
        return DEFAULT_EFFORT
    return effort


def _anthropic_params(
    model: str, temperature: float | None, extended_thinking: bool, max_out: int
) -> dict:
    """Constructor kwargs for ``ChatAnthropic`` that match the model's parameter contract.

    Shared by ``_build_chat_model`` and ``probe_model`` so the two cannot drift apart.

    ``temperature=None`` is how the parameter is omitted from the request entirely:
    ChatAnthropic declares it ``Optional[float]`` and drops None-valued keys when building
    the payload. That is the fix for the Claude 5 family, which rejects it outright.
    """
    if _is_anthropic_adaptive(model):
        # Claude 5: no temperature, ever. Thinking depth is an effort level.
        if not extended_thinking:
            # Send no thinking config at all — the model applies its own default. An
            # explicit {"type": "disabled"} is a different opt-out and isn't needed here.
            return {"temperature": None}
        return {
            "temperature": None,
            "thinking": {"type": "adaptive"},
            # output_config is not a declared ChatAnthropic field, so it must ride in
            # model_kwargs to reach the request payload.
            "model_kwargs": {"output_config": {"effort": _resolve_effort()}},
        }

    # Older models: unchanged behavior.
    if not extended_thinking:
        return {"temperature": temperature}
    # Extended thinking surfaces CoT as `thinking` content blocks. It requires
    # temperature=1 and a thinking budget strictly below max_tokens.
    budget = max(1024, min(settings.agent_anthropic_thinking_budget, max_out - 1024))
    return {
        "temperature": 1,
        "thinking": {"type": "enabled", "budget_tokens": budget},
    }


_reasoning_openai_cls = None


def _reasoning_chat_openai_cls():
    """A ChatOpenAI subclass that recovers ``reasoning_content`` deltas (DeepSeek-R1,
    Qwen QwQ, vLLM-served reasoning models) — stock langchain-openai drops them. The CoT
    is normalized into ``additional_kwargs['reasoning_content']`` to match the Groq/Ollama
    shape so one extractor handles every provider. Defined lazily (langchain-openai is an
    optional dependency) and cached."""
    global _reasoning_openai_cls
    if _reasoning_openai_cls is not None:
        return _reasoning_openai_cls

    from langchain_openai import ChatOpenAI

    class _ReasoningChatOpenAI(ChatOpenAI):
        def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
            gen = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )
            if gen is not None:
                try:
                    choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
                    if choices:
                        delta = choices[0].get("delta") or {}
                        rc = delta.get("reasoning_content") or delta.get("reasoning")
                        if isinstance(rc, str) and rc:
                            gen.message.additional_kwargs["reasoning_content"] = rc
                except Exception:
                    pass
            return gen

    _reasoning_openai_cls = _ReasoningChatOpenAI
    return _reasoning_openai_cls


def _groq_quirks(model: str, for_tools: bool = False) -> dict:
    """Provider-specific kwargs for Groq, keyed off the model id.

    Reasoning models (gpt-oss) expose their chain-of-thought. "parsed" puts the CoT in
    a separate ``reasoning_content`` field (streamed as deltas) and keeps ``content`` as
    the clean final answer — so we can render a distinct thinking panel AND get cleaner
    answers / JSON. (raw/tag mode is unsupported for gpt-oss.) Non-reasoning models
    (e.g. Llama 3.3) take no quirk, preserving the legacy chat path exactly.

    ``for_tools``: when the model is built for native tool-calling (``bind_tools``), the
    parsed-reasoning channel is dropped — Groq does not combine parsed reasoning with
    tool calls, and selection steps don't need the CoT panel anyway.
    """
    if "gpt-oss" in model.lower() and not for_tools:
        return {"reasoning_format": "parsed"}
    return {}


def _build_chat_model(
    provider: str,
    model: str,
    temperature: float | None,
    streaming: bool,
    base_url: str | None = None,
    for_tools: bool = False,
    max_tokens: Optional[int] = None,
) -> BaseChatModel:
    """Instantiate the LangChain chat model for a provider. Optional provider
    packages are imported lazily so a missing one only fails the slot that needs it.

    ``base_url`` (when set, e.g. from a DB config row) overrides the env default for
    OpenAI / OpenAI-compatible providers. ``max_tokens`` overrides the output-token
    ceiling; ``UNCAPPED`` omits the parameter entirely so the provider's own maximum
    applies (Anthropic, which requires it, gets ``ANTHROPIC_UNCAPPED_TOKENS``). API keys
    resolve BYOK-first then managed env (``provider_keys.resolve_api_key``)."""
    from agents.models import provider_keys  # lazy: avoids module-load cycle

    uncapped = max_tokens == UNCAPPED
    out_tokens = None if uncapped else (max_tokens or DEFAULT_MAX_TOKENS)
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        key = provider_keys.resolve_api_key("google")
        if not key:
            raise ModelSlotError("No API key for provider 'google' (set a BYOK key or google_api_key).")
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=key,
            temperature=temperature,
            **({"max_output_tokens": max_tokens} if max_tokens and not uncapped else {}),
        )

    if provider == "groq":
        from langchain_groq import ChatGroq

        key = provider_keys.resolve_api_key("groq")
        if not key:
            raise ModelSlotError("No API key for provider 'groq' (set a BYOK key or groq_api_key).")
        return ChatGroq(
            model=model,
            api_key=key,
            temperature=temperature,
            streaming=streaming,
            **({"max_tokens": out_tokens} if out_tokens else {}),
            **_groq_quirks(model, for_tools=for_tools),
        )

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:  # optional dependency
            raise ModelSlotError(
                "Provider 'anthropic' selected but langchain-anthropic is not "
                "installed. Run: pip install langchain-anthropic"
            ) from exc
        key = provider_keys.resolve_api_key("anthropic")
        if not key:
            raise ModelSlotError("No API key for provider 'anthropic' (set a BYOK key or anthropic_api_key).")
        # Anthropic requires an explicit max_tokens — UNCAPPED maps to a large ceiling.
        anthropic_out = out_tokens or ANTHROPIC_UNCAPPED_TOKENS
        kwargs = dict(model=model, api_key=key, max_tokens=anthropic_out)
        # Runtime-overridable via the Settings UI (app_settings flag), falling back to the
        # env default. A flag change bumps the config version, rebuilding this cached model.
        from agents.models import config_store  # lazy: avoids import cycle at module load

        extended_thinking = bool(
            config_store.get_flag(
                "anthropic_extended_thinking", settings.agent_anthropic_extended_thinking
            )
        )
        # The remaining kwargs depend on the model generation (see _anthropic_params).
        # Merge model_kwargs rather than assigning, so a future addition here can't
        # clobber output_config.
        params = _anthropic_params(model, temperature, extended_thinking, anthropic_out)
        extra_model_kwargs = params.pop("model_kwargs", None)
        kwargs.update(params)
        if extra_model_kwargs:
            kwargs["model_kwargs"] = {**kwargs.get("model_kwargs", {}), **extra_model_kwargs}
        # NOTE (langchain-anthropic 0.3.22): its `_thinking_in_params` / structured-output
        # guards test for thinking type == "enabled", so they don't fire under "adaptive".
        # Streaming still yields thinking blocks (the thinking_delta branch is
        # unconditional) and reasoning.py handles them; with_structured_output would take
        # the plain bind_tools path, which this codebase never exercises.
        return ChatAnthropic(**kwargs)

    if provider in ("openai", "openai_compatible", "vllm", "deepseek", "qwen"):
        # All OpenAI-protocol clients. 'openai' → OpenAI / Azure / any gateway.
        # 'deepseek' / 'qwen' → first-class vendors with preset base_urls + own keys.
        # 'openai_compatible' / 'vllm' → self-hosted server (vLLM, LM Studio, gateways).
        try:
            ChatOpenAI = _reasoning_chat_openai_cls()  # recovers reasoning_content deltas
        except ImportError as exc:  # optional dependency
            raise ModelSlotError(
                f"Provider '{provider}' selected but langchain-openai is not "
                "installed. Run: pip install langchain-openai"
            ) from exc

        if provider == "openai":
            resolved_base_url = base_url or settings.openai_base_url or None
            api_key = provider_keys.resolve_api_key("openai")
            if not api_key:
                raise ModelSlotError("No API key for provider 'openai' (set a BYOK key or openai_api_key).")
        elif provider == "deepseek":
            resolved_base_url = base_url or settings.deepseek_base_url
            api_key = provider_keys.resolve_api_key("deepseek")
            if not api_key:
                raise ModelSlotError("No API key for provider 'deepseek' (set a BYOK key or deepseek_api_key).")
        elif provider == "qwen":
            resolved_base_url = base_url or settings.qwen_base_url
            api_key = provider_keys.resolve_api_key("qwen")
            if not api_key:
                raise ModelSlotError("No API key for provider 'qwen' (set a BYOK key or qwen_api_key).")
        else:
            resolved_base_url = base_url or settings.openai_compatible_base_url
            if not resolved_base_url:
                raise ModelSlotError(
                    f"Provider '{provider}' selected but no base_url is configured "
                    "(set it on the role's config or openai_compatible_base_url)."
                )
            # Local OpenAI-compatible servers usually ignore the key but require a
            # non-empty string; allow a BYOK/managed key, else a placeholder.
            api_key = provider_keys.resolve_api_key("openai") or "EMPTY"

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=resolved_base_url,
            temperature=temperature,
            streaming=streaming,
            **({"max_tokens": out_tokens} if out_tokens else {}),
        )

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:  # optional dependency
            raise ModelSlotError(
                "Provider 'ollama' selected but langchain-ollama is not "
                "installed. Run: pip install langchain-ollama"
            ) from exc
        kwargs = dict(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )
        if max_tokens and not uncapped:
            kwargs["num_predict"] = max_tokens  # Ollama's output-token cap
        # Enable local reasoning mode only for models that support it (else Ollama
        # errors). The CoT surfaces in additional_kwargs['reasoning_content'].
        if _is_reasoning_model(model):
            kwargs["reasoning"] = True
        return ChatOllama(**kwargs)

    raise ModelSlotError(f"Unknown model provider '{provider}'.")


# Process-local model cache, keyed on (slot, streaming, temperature, config_version).
# The config_version component is the cross-worker invalidation mechanism: when the
# admin changes a role's model, the Redis version bumps, the key changes, and every
# worker rebuilds from the new config on its next call. Old-version entries are pruned
# so the cache stays bounded.
_MODEL_CACHE: dict = {}


def get_model(
    slot: Slot, streaming: bool = False, temperature: float | None = None,
    for_tools: bool = False, max_tokens: int | None = None,
) -> BaseChatModel:
    """Resolve and cache the chat model for a slot.

    Args:
        slot: Which model slot to resolve.
        streaming: Whether to construct the model in streaming mode (only affects
            providers that need it at construction time; ``.astream`` works either way).
        temperature: Optional per-call sampling temperature. When ``None`` the slot's
            default (``SLOT_TEMPERATURES``) is used. The legacy chat path passes an
            explicit per-operation temperature here. Distinct temperatures produce
            distinct cached instances (a small, bounded set).
        for_tools: Build the model for native tool-calling (``bind_tools``). For Groq
            gpt-oss this drops the parsed-reasoning quirk, which is incompatible with
            tool calls. The returned model is otherwise identical; bind tools on it.
        max_tokens: Optional output-token ceiling override. When ``None`` the provider
            default (``DEFAULT_MAX_TOKENS``) is used. Produce script-generation passes a
            much larger value — a long document script truncates at the chat default.

    Returns:
        A ready-to-use LangChain ``BaseChatModel``.

    Raises:
        ModelSlotError: misconfiguration, missing credential/dependency, or a
            deployment-mode violation.
    """
    from agents.models import config_store  # lazy import (avoids module-load cycle)

    version = config_store.current_version()
    key = (slot, streaming, temperature, for_tools, max_tokens, version)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached

    # A new version means the config changed — drop entries from older versions.
    if any(k[5] != version for k in _MODEL_CACHE):
        for stale in [k for k in _MODEL_CACHE if k[5] != version]:
            _MODEL_CACHE.pop(stale, None)

    provider, model, base_url, _params = _resolve_slot(slot)
    _assert_deployment_allows(provider, slot)
    temp = SLOT_TEMPERATURES[slot] if temperature is None else temperature
    llm = _build_chat_model(provider, model, temp, streaming, base_url=base_url,
                            for_tools=for_tools, max_tokens=max_tokens)
    _MODEL_CACHE[key] = llm
    logger.info(
        "Resolved model slot '%s' → provider=%s model=%s (streaming=%s, temperature=%s, v=%s)",
        slot.value,
        provider,
        model,
        streaming,
        temp,
        version,
    )
    return llm


def clear_model_cache() -> None:
    """Drop all cached models (e.g. after a config change in-process, or in tests)."""
    _MODEL_CACHE.clear()


def probe_model(
    provider: str, model: str, base_url: str | None = None, role: Slot | None = None
) -> BaseChatModel:
    """Build a model from an explicit config (not cached), for a test-connection probe.
    Enforces deployment-mode rules when a ``role`` is given. Raises ``ModelSlotError`` on
    misconfiguration/missing dependency exactly like the normal path."""
    provider = provider.lower().strip()
    if role is not None:
        _assert_deployment_allows(provider, role)
    # temperature is passed through rather than reaching the provider unconditionally: the
    # Anthropic branch drops it for the Claude 5 family, which rejects the parameter. A
    # probe against a Claude 5 model would otherwise 400 even on a correct config.
    return _build_chat_model(provider, model.strip(), 0.0, False, base_url=base_url)


def describe_slots() -> dict[str, dict[str, str]]:
    """Return the configured provider/model per slot (for health/diagnostics).
    Does not instantiate the models, so it never raises on a missing credential."""
    out: dict[str, dict[str, str]] = {}
    for slot in Slot:
        try:
            provider, model = _slot_config(slot)
            out[slot.value] = {"provider": provider, "model": model}
        except ModelSlotError as exc:
            out[slot.value] = {"error": str(exc)}
    return out

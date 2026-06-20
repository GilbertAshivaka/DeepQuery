# Model Vendor Picking — Implementation Plan

> Goal: make DeepQuery genuinely model-agnostic in practice. Every LLM call routes
> through one provider-agnostic factory, the vendor/model is **picked at runtime**
> (DB-backed, admin-driven), keys can be **managed by us OR brought by the client
> (BYOK)**, and clients can pick their **embedding model** too (with a re-index
> migration, because embeddings are not a live toggle).

Status: PLANNING. Nothing in this doc is built yet. Author hands off to implementation.

---

## 0. Decisions locked (2026-06-18 brainstorm)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Scope | **LLM everywhere** — unify the legacy Groq chat/RAG path into the slot factory so *all* LLM calls are vendor-agnostic. **Plus embeddings** as a separate, clearly-flagged track (re-index required). |
| 2 | Config model | **DB-backed + Admin UI.** Env values become bootstrap defaults; runtime source of truth is the DB. A dedicated Settings page is the next workstream after this. |
| 3 | Granularity | **Global per-deployment.** One choice per slot/path for the whole instance. Per-assistant/per-user overrides are explicitly deferred. |
| 4 | API keys | **Both.** BYOK (admin enters keys in UI, stored encrypted in DB) **and** managed (our keys in env). A key-resolution order decides which wins. |

---

## 1. Current state (what exists today)

**Already vendor-agnostic — the agent layer:**
- [`backend/agents/models/slots.py`](backend/agents/models/slots.py) — `get_model(Slot)` factory. Three slots (`ORCHESTRATION`, `GENERATION`, `VERIFICATION`) → LangChain `BaseChatModel`. Supports `google | groq | anthropic | ollama | vllm`, lazy provider imports, air-gapped enforcement, `describe_slots()` diagnostics. `@lru_cache` on `get_model`.
- Consumed across `agents/**` via `get_model(Slot.X)`.

**NOT vendor-agnostic yet:**
- **Legacy chat/RAG path** — [`backend/llm/groq_client.py`](backend/llm/groq_client.py) hard-wired to `ChatGroq`. Used by [`api/query.py`](backend/api/query.py), [`retrieval/pipeline.py`](backend/retrieval/pipeline.py), [`ingestion/pipeline.py`](backend/ingestion/pipeline.py). Operations: `generate_answer(_stream)`, `verify_answer`, `extract_entities`, `generate_metadata`, `extract_query_entities`. Per-operation temps in [`core/constants.py:70`](backend/core/constants.py#L70) (`LLM_TEMPERATURES`).
- **Embeddings** — [`backend/embeddings/gemini_embedder.py`](backend/embeddings/gemini_embedder.py) hard-wired to Google GenAI. Note it does **text + image + interleaved multimodal** embedding — multimodal is a Gemini-specific capability.
- **Config** — pydantic `BaseSettings`, env-only, static at startup ([`core/config.py`](backend/core/config.py)). No DB-backed settings, no admin write path. `deployment_mode: "cloud"` default at [config.py:219](backend/core/config.py#L219).

**Known gaps in the existing factory:**
- `openai` is in `CLOUD_PROVIDERS` but has **no branch** in `_build_chat_model` → selecting it raises today.
- `vllm` is routed through `ChatOllama` rather than its native OpenAI-compatible server.

---

## 2. Target architecture

```
                      ┌─────────────────────────────────────┐
   admin Settings UI ─┤  POST /api/admin/model-config       │
                      │  (per-slot + chat + embedding)      │
                      └──────────────┬──────────────────────┘
                                     │ writes
                              ┌──────▼───────┐
                              │ model_config  │  DB table (single active row + history)
                              │ provider_keys │  encrypted BYOK keys
                              └──────┬────────┘
                                     │ read by
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                             │
 ┌──────▼───────┐          ┌─────────▼─────────┐         ┌─────────▼─────────┐
 │ get_model()  │          │ get_chat_model()  │         │ get_embedder()    │
 │ (agent slots)│          │ (legacy RAG path) │         │ (ingestion+query) │
 └──────┬───────┘          └─────────┬─────────┘         └─────────┬─────────┘
        └────────────┬───────────────┘                             │
                ┌────▼────────────────┐                  ┌─────────▼──────────┐
                │ provider registry    │                  │ embedder registry  │
                │ + key resolver       │                  │ + dim/space guard  │
                └──────────────────────┘                  └────────────────────┘
```

Core idea: **one resolver, one config source, one key resolver.** Slots become a
special case of "a named model role." Add a `CHAT` role for the legacy path so it
joins the same machinery instead of living in `llm/groq_client.py`.

---

## 3. Provider abstraction (backend)

### 3.1 Generalize the slot factory into a model registry
Rename/extend the concept from "agent slots" to "model roles" so the chat path fits:

- Add `Slot.CHAT` (or a parallel `ModelRole` enum) for the legacy RAG path.
- Extend `_build_chat_model` with the missing providers:
  - **`openai`** — `from langchain_openai import ChatOpenAI`, key `openai_api_key`, optional `openai_base_url` (enables Azure / OpenAI-compatible gateways).
  - **`openai_compatible`** (new) — generic OpenAI-protocol provider taking an explicit `base_url` + key. This is the right home for **vLLM**, LM Studio, Together, OpenRouter, local gateways. Re-point `vllm` here instead of `ChatOllama`.
- Keep lazy imports + the `ModelSlotError` on missing optional packages (already the pattern).
- Centralize a **capability/quirks map** per provider (see §6) so callers don't special-case (e.g. the current `if "gpt-oss" in model: reasoning_format="parsed"` belongs in the quirks map, not inline).

### 3.2 Fold the legacy path onto the factory
Replace the hard-wired `GroqClient` internals so `llm/groq_client.py` becomes a thin
behavior layer (prompt assembly, JSON cleanup, retries) over `get_chat_model(Slot.CHAT)`:

- `_get_llm(temperature, streaming)` → `get_chat_model(Slot.CHAT, temperature=…, streaming=…)`.
- Keep the per-operation temperatures: pass `LLM_TEMPERATURES[op]` as a per-call override
  rather than relying on a single slot temperature. **Reconcile** §2 temps with
  `SLOT_TEMPERATURES` — make per-call temperature an argument to the factory, defaulting
  to the slot temp when omitted.
- Preserve current public methods (`generate_answer`, `verify_answer`, etc.) so callers
  in `api/query.py` / `retrieval` / `ingestion` don't change. **Rename the singleton** away
  from `groq_client` (e.g. `chat_llm`) or keep the alias for one release to avoid churn.
- **Streaming**: `generate_answer_stream` already uses `.astream`; the factory must
  construct streaming-capable models for whichever provider is chosen.

### 3.3 Cache invalidation (critical)
`get_model` is `@lru_cache`d → runtime config changes are invisible until process restart.

- Replace the bare `lru_cache` with a cache keyed by **(slot, streaming, config_version)**.
- `config_version` = a monotonic counter (or hash) bumped whenever model-config or keys
  are written. Store it in Redis (already in the stack) so **all workers** (API + Celery)
  invalidate together, not just the process that took the write.
- On read, compare cached version to current; rebuild on mismatch. Cheap and lock-free.
- Alternative if you want zero-cache complexity: just `get_model.cache_clear()` broadcast
  via a Redis pub/sub channel on write. The version-key approach is more robust for
  multi-worker; prefer it.

---

## 4. Data model (DB-backed config)

Two tables (SQLAlchemy, alongside [`models/database.py`](backend/models/database.py)):

### 4.1 `model_config`
Single logical active config (keep history rows for audit/rollback; flag one `is_active`).

| column | type | notes |
|--------|------|-------|
| `id` | uuid PK | |
| `role` | str | agent: `orchestration` \| `generation` \| `verification`; classic pipeline: `chat` \| `self_correction` \| `extraction`; plus `embedding` |
| `provider` | str | `google` \| `groq` \| `anthropic` \| `openai` \| `openai_compatible` \| `ollama` \| `vllm` |
| `model` | str | provider-native id (e.g. `claude-…`, `openai/gpt-oss-120b`) |
| `base_url` | str null | for `openai_compatible` / self-hosted |
| `params_json` | json | temperature override, max_tokens, reasoning flags, embedding dimensions |
| `key_mode` | str | `managed` (our env key) \| `byok` (DB key) |
| `is_active` | bool | one active row per `role` |
| `updated_by` / `updated_at` | | audit |

### 4.2 `provider_keys` (BYOK)
| column | type | notes |
|--------|------|-------|
| `id` | uuid PK | |
| `provider` | str | one row per provider |
| `encrypted_key` | bytes | **reuse the connector credential encryption** — see [`connectors/credentials/store.py`](backend/connectors/credentials/store.py). Do NOT roll new crypto. |
| `key_hint` | str | last 4 chars for UI display only |
| `created_by` / `created_at` | | audit |

### 4.3 Bootstrap
On first run (empty `model_config`), seed rows from the current env settings
(`agent_*_provider/model`, `llm_model`→chat, `embedding_model`→embedding). Existing
deployments keep working with zero config. Env stays the **fallback** when no active row
exists for a role.

---

## 5. Key resolution order

For a given `(role, provider)`:

1. If `model_config.key_mode == "byok"` and a `provider_keys` row exists → **decrypt and use it.**
2. Else if a managed key is configured in env (`groq_api_key`, `anthropic_api_key`,
   `openai_api_key`, `google_api_key`, …) → use it.
3. Else → `ModelSlotError("no key available for provider X")`, surfaced cleanly to the UI.

Local providers (`ollama` / `openai_compatible` self-hosted) may need **no key** — resolver
must allow a missing key when the provider doesn't require one.

Security notes:
- Never return decrypted keys over the API. UI shows only `key_hint` (last 4) + "configured".
- Encrypt at rest with the existing connector-store mechanism; keep the data-key out of the DB.
- BYOK keys are deployment-global here (granularity = per-deployment). Per-user BYOK is a
  future granularity change, not in scope.

---

## 6. Capability / quirks matrix (don't skip this)

Vendors are **not** drop-in equivalent. The agent layer depends on tool/function calling
and structured JSON; the thinking panel depends on reasoning exposure. Maintain an explicit
per-provider capability map and use it to (a) drive validation and (b) warn in the UI.

| Capability | groq (gpt-oss) | anthropic | openai | google | ollama / vllm |
|-----------|----------------|-----------|--------|--------|----------------|
| Tool/function calling | yes | yes | yes | yes | model-dependent |
| Structured/JSON output | via prompt | yes | yes (json mode) | yes | model-dependent |
| Reasoning/CoT exposure | `reasoning_format="parsed"` → `reasoning_content` | extended-thinking blocks | reasoning models (o-series) hide CoT | "thinking" varies | varies |
| Streaming | yes | yes | yes | yes | yes |
| `max_tokens` required | accepts | **required** | optional | optional | varies |

Implications to encode:
- **Thinking panel**: the frontend currently assumes Groq's parsed `reasoning_content`
  delta stream. Switching providers must map each vendor's reasoning surface to the same
  internal "thinking delta" event — or the panel silently goes blank. Add a per-provider
  reasoning-adapter in the streaming layer.
- **Anthropic requires `max_tokens`** — already handled in the existing branch; keep it.
- **JSON parsing**: `verify_answer` / `extract_entities` / `generate_metadata` already
  strip markdown fences and tolerate non-JSON. Keep that defensive parsing — it's what makes
  provider-swapping survivable.
- **Validation at pick-time**: when an admin selects a model that lacks tool-calling for a
  role that needs it (orchestration), warn (don't hard-block — let them override knowingly).

---

## 7. Embeddings track (separate, flagged — NOT a live toggle)

> This is the part that bites people. Read before building.

Switching embedding vendor/model/dimensions **invalidates the entire Chroma index**:
different model = different vector space (similarity across models is meaningless) and often
a different dimension count ([`chroma_store.py`](backend/vectorstore/chroma_store.py) +
`embedding_dimensions=3072`). You **cannot** mix old and new vectors in one collection.

Also: **multimodal is Gemini-specific.** `embed_image` / `embed_multimodal` have no
equivalent in text-only embedders (OpenAI `text-embedding-3`, Cohere, local
sentence-transformers). Choosing a text-only embedder means image/mixed chunks lose their
native embedding — they'd fall back to caption/OCR-text embedding. Surface this in the UI.

**Good news — the codebase makes this much cheaper than the generic warning implies:**
- **Source files are retained** ([`pipeline.py:68`](backend/ingestion/pipeline.py#L68) reads
  `document_store_dir / stored_filename`) — originals are never discarded.
- **Full chunk text is already in Chroma** ([`chroma_store.py:114`](backend/vectorstore/chroma_store.py#L114)
  stores `text_for_index` in `documents`; [`get_all_chunk_texts`](backend/vectorstore/chroma_store.py#L226)
  reads it back) — so you re-embed from stored text without re-parsing.
- **Ingest and query embed through the same embedder** ([`retrieval/pipeline.py:116/120/338`](backend/retrieval/pipeline.py#L116))
  — a single `get_embedder()` swap covers both sides; they can't drift.
- **BM25 is text-only** (built from Chroma `documents` via `get_all_chunk_texts`) — **completely
  embedding-independent, survives a re-index untouched.** No action needed.

### 7.1 Collection-identity guardrail (build in Phase 1)
Cheap insurance, landed *before* switching is ever possible:
- On collection create/upsert, write `(embedding_provider, embedding_model, embedding_dimensions)`
  into the Chroma collection metadata (alongside the existing `hnsw:space`).
- On every query/upsert, assert the **active** embedder identity matches the collection's
  recorded identity. Mismatch → **hard error**, never a silent wrong-vector-space query.
- Add an "active embedding version" indirection in [`get_collection`](backend/vectorstore/chroma_store.py#L45):
  resolve logical name → physical name (`academic` → `academic__{version}`). The four
  `Collection` enum names ([`constants.py:33`](backend/core/constants.py#L33)) stay the logical
  API; only the physical suffix changes across a migration. This is the one-line change that
  makes the blue/green swap possible without touching every call site.

### 7.2 Pluggable embedder + factory (Phase 4)
1. **`Embedder` interface** (`embed_text`, `embed_texts_batch`, optional
   `embed_image`/`embed_multimodal`, `.dimensions`, `.supports_multimodal`). `GeminiEmbedder`
   becomes one implementation. Add `OpenAIEmbedder`, `OllamaEmbedder`/local
   sentence-transformers as needed.
2. **`get_embedder()`** factory reading `model_config[role=embedding]`, same key resolution
   and air-gapped enforcement (local-only) as the chat slots.

### 7.3 Re-index migration job (Phase 4) — re-embed ONLY
Admin-triggered async Celery job. **Do not re-run the full ingestion pipeline** — re-embed
only. Parse/OCR/entity-extraction/metadata are LLM-derived and embedding-independent;
re-running them would re-hit Groq, regenerate summaries, and **duplicate/mutate the Neo4j
graph** for zero benefit.

```
version = bump_embedding_version()
for collection in Collection:                       # academic, departmental, ...
    chunks = chroma.get_all_chunk_texts([collection])      # text already stored
    vecs   = new_embedder.embed_texts_batch([c.text ...])  # re-embed text
    chroma.write(f"{collection}__{version}", ids, vecs, docs, metas,
                 collection_metadata=new_embedder.identity())
verify counts/dim → flip active version pointer (atomic)
keep old collections until verified, then delete
```
- **Image/mixed chunks**: re-embedding native image vectors needs the original bytes (not in
  Chroma). For text-only target embedders this is moot — they degrade to caption/OCR-text
  embedding, which is correct. Only a Gemini→Gemini-class switch that wants to *preserve* native
  image embeddings needs the heavier re-parse path; treat that as an opt-in, not the default.
- **Progress + rollback** surfaced in the Settings UI. Old collections are the rollback target.
- Cost/scope: ~150-line Celery task + the §7.1 indirection. No LLM calls, no Neo4j touch, no
  re-parse in the default path — this is why it's low-complexity.

---

## 8. API surface (admin)

New router section in [`api/admin.py`](backend/api/admin.py) (or a dedicated `api/settings.py`),
all behind `RoleRequired([ADMIN])`:

- `GET  /api/admin/model-config` — active config per role + provider availability
  (which providers have a usable key) + `describe_slots()`-style diagnostics. Never returns keys.
- `PUT  /api/admin/model-config/{role}` — set provider/model/base_url/params/key_mode for a
  role. Bumps `config_version` (→ cache invalidation §3.3).
- `POST /api/admin/model-config/{role}/test` — **test-connection probe**: instantiate + do a
  1-token round-trip (or a tiny embed), return ok/latency/error. Run this before persisting,
  and offer it as a button.
- `GET/PUT/DELETE /api/admin/provider-keys/{provider}` — BYOK CRUD. PUT stores encrypted;
  GET returns only `key_hint` + configured flag.
- `POST /api/admin/embedding/reindex` — kick the re-index migration job (§7). Returns job id.
- `GET  /api/admin/model-catalog` — per-provider known model ids for the picker dropdown
  (free-text still allowed for new models). **Populate the catalog from each vendor's live
  docs at build time — do not hardcode model ids/pricing from memory.** For the Anthropic
  entries use the `claude-api` skill as the source of truth.

Frontend (next workstream — the Settings page): per-role provider dropdown → model dropdown
(catalog + free text) → key mode (managed/BYOK) → key entry if BYOK → **Test** button →
Save. Embedding role shows the re-index warning + a separate migrate action. Air-gapped
deployments hide cloud providers.

---

## 9. Phasing (suggested build order)

1. **Phase 1 — Backend unification (no behavior change).** Add `openai` + `openai_compatible`
   branches; move quirks into a map; add `Slot.CHAT`; refactor `groq_client.py` to ride the
   factory; reconcile temperatures. Config still env-only. Ship behind defaults identical to
   today. Verify chat/search/ingestion/agents unchanged.
   **Also land the collection-identity guardrail now (§7.1)** — write `(provider, model,
   dimensions)` into each Chroma collection's metadata and assert it on read. It's a few lines,
   costs nothing while you're still on Gemini, and it must exist *before* anyone can switch
   embedders so a botched switch fails loud (hard error) instead of silently querying the wrong
   vector space. This is the cheap insurance that makes Phase 4 safe.
2. **Phase 2 — DB-backed config + cache invalidation.** Add `model_config` table, bootstrap
   from env, version-keyed cache (Redis), admin GET/PUT + test-connection. No key entry yet
   (managed keys only).
3. **Phase 3 — BYOK.** `provider_keys` table, encryption reuse, key-resolution order, key
   CRUD endpoints.
4. **Phase 4 — Embeddings.** `Embedder` interface + `get_embedder()`, collection identity
   binding, re-index migration job. Highest risk — do last, behind its own flag.
5. **Phase 5 — Settings UI.** The admin page that drives all of the above (separate workstream).

Each phase is independently shippable and reversible. Keep a feature flag
(`runtime_model_config` on/off) so Phase 1 can land while config stays env-driven.

---

## 10. Gotchas checklist

- [ ] `lru_cache` will mask runtime changes — must move to version-keyed cache across workers.
- [ ] Celery workers and the API process must invalidate the **same** way (Redis-backed version).
- [ ] Embedding swap = re-index; bind embedding identity to collection metadata and assert on read (land in **Phase 1**, §7.1).
- [ ] Re-index job must **re-embed only** — never re-run parse/OCR/entity/metadata (would mangle Neo4j + re-hit LLM).
- [ ] Chroma dimension is fixed at collection creation — switch via versioned shadow collections + pointer flip, never in-place.
- [ ] BM25 is text-only and embedding-independent — leave it alone during a re-index.
- [ ] Multimodal embedding is Gemini-only — warn when switching to a text-only embedder.
- [ ] Thinking panel depends on Groq parsed `reasoning_content` — add per-provider reasoning adapters.
- [ ] Anthropic requires `max_tokens`; some providers ignore `temperature` ranges differently.
- [ ] Don't roll new crypto for BYOK — reuse the connector credential store.
- [ ] Never expose decrypted keys via API; only `key_hint`.
- [ ] Keep defensive JSON parsing — it's what survives provider swaps.
- [ ] Air-gapped enforcement must extend to the chat path AND embeddings, not just agent slots.
- [ ] Catalog model ids/pricing from live vendor docs (Anthropic via `claude-api` skill), never from memory.
- [ ] Rename/alias the `groq_client` singleton carefully to avoid breaking imports.
- [ ] Test-connection before persist, so a bad pick can't take the chat path down.

## 11. Testing

- Unit: factory builds each provider with a stubbed key; missing key/dep → clean `ModelSlotError`;
  air-gapped rejects cloud for every role including chat + embedding.
- Cache: version bump rebuilds; concurrent workers converge.
- Key resolver: byok > managed > none; local providers allowed without key.
- Embedding identity: mismatched collection vs active embedder → hard error, not silent.
- Integration: flip chat provider groq→anthropic→openai, run a real chat/search/ingest, assert
  citations/JSON/streaming/thinking-panel all still work.
- Regression: Phase 1 with defaults unchanged must produce identical behavior to today.

## 12. Open questions (revisit before/while building)

- Fallback chain on provider outage mid-stream, or hard fail? (Lean hard-fail + clear error first.)
- Token/cost accounting per vendor — extend `QueryLog`? (Probably a later analytics pass.)
- Per-assistant / per-user model override — deferred, but design `model_config.role` so a future
  `scope`/`owner` column can extend it without a rewrite.

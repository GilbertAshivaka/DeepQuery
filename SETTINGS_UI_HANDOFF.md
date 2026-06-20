# Settings UI — Backend Contract Handoff

Everything the Settings page needs to talk to. The backend (Phases 1–4 of
`MODEL_VENDOR_PICKING_PLAN.md`) is **complete and verified**; this is the API contract to
build the UI against. All endpoints are **admin-only** (JWT, `RoleRequired([ADMIN])`),
mounted under `/api/admin`.

---

## 1. The three things the page manages

1. **Per-role model selection** (which vendor/model each workload uses)
2. **Provider API keys** (managed env keys vs. BYOK, encrypted)
3. **Embedding model** (special — switching it runs a re-index migration)

## 2. Roles

LLM roles (each independently selectable):
- **Agent layer**: `orchestration`, `generation`, `verification`
- **Classic RAG pipeline**: `chat` (answer generation), `self_correction` (answer verify), `extraction` (entity + metadata + query-entity)
- Plus **`embedding`** (managed only via re-index, not the generic PUT)

Group them in the UI as "Agent" / "Classic pipeline" / "Embedding". `GET /model-config`
returns `llm_roles` and `embedding_role` so you don't hardcode.

## 3. Providers

LLM providers (`supported_providers` from the API):
`anthropic, deepseek, google, groq, ollama, openai, openai_compatible, qwen, vllm`

Embedding providers: `google, openai, ollama, qwen` (deepseek has **no** embeddings).

Notes for the UI:
- **deepseek / qwen** have preset base_urls (qwen = DashScope **international**) — leave `base_url` blank.
- **openai_compatible / vllm** **require** a `base_url`.
- **ollama** needs no key (local); **openai_compatible / vllm** key optional.
- `base_url` field is meaningful for: openai (optional override), openai_compatible, vllm, and per-config overrides of deepseek/qwen.

---

## 4. Endpoints

### 4.1 `GET /api/admin/model-config`
The whole model-config screen in one call.
```jsonc
{
  "roles": {                       // effective config per role
    "chat": {
      "provider": "groq", "model": "llama-3.3-70b-versatile",
      "base_url": null, "params": {}, "key_mode": "managed",
      "source": "db" | "env",      // "env" = inheriting the bootstrap default
      "updated_at": "..."          // present only when source == "db"
    },
    "embedding": { "provider": "google", "model": "gemini-embedding-2-preview",
                   "params": { "dimensions": 3072, "collection_version": "v..." }, ... }
    // ... one entry per role
  },
  "providers": {                   // availability per provider
    "anthropic": { "available": false, "needs_key": true,
                   "key_source": "none"|"managed"|"byok", "byok": false, "hint": null },
    // ...
  },
  "supported_providers": ["anthropic","deepseek", ...],
  "llm_roles": ["orchestration","generation","verification","chat","self_correction","extraction"],
  "embedding_role": "embedding",
  "deployment_mode": "cloud" | "air-gapped",
  "version": 0,                    // config version; bumps on every change
  "db_enabled": true               // if false, editing is disabled (PUT → 409)
}
```

### 4.2 `PUT /api/admin/model-config/{role}`
Set a role's model. Body: `{ provider, model, base_url?, params? }` → returns
`{ role, config, version }`.
- **Rejects `role=embedding`** (400 — use re-index).
- Returns **409** if `db_enabled` is false.
- Does **not** test connectivity — call `/test` first (see below).

### 4.3 `POST /api/admin/model-config/{role}/test`
Validate a candidate before saving (no persistence). Body: `{ provider, model, base_url? }`.
```jsonc
{ "ok": true, "latency_ms": 412.3, "sample": "pong..." }
// or
{ "ok": false, "error": "No API key for provider 'anthropic' ...", "kind": "config"|"runtime" }
```
LLM roles only (embedding role → 400). Recommended UX: **Test → then Save**.

### 4.4 Provider keys (BYOK)
- `GET /api/admin/provider-keys` →
  ```jsonc
  { "keys": { "anthropic": { "byok": false, "hint": null, "managed": false,
                             "needs_key": true, "source": "none" }, ... },
    "version": 0 }
  ```
- `PUT /api/admin/provider-keys/{provider}` — body `{ api_key }` → `{ provider, configured, hint, source }`.
  Stored **encrypted**; takes precedence over the managed env key.
- `DELETE /api/admin/provider-keys/{provider}` → `{ provider, removed, source }`. Reverts to managed.
- **Plaintext keys are never returned** — only `hint` (last 4 chars). Show "•••• 7788".

### 4.5 Embedding (re-index migration)
- `GET /api/admin/embedding` →
  ```jsonc
  { "active": { ...embedding role config... },
    "supported_providers": ["google","openai","ollama","qwen"],
    "providers": { "google": {availability...}, ... },
    "deployment_mode": "...",
    "reindex_status": { ...see below... },
    "warning": "Switching the embedding model re-embeds the entire corpus ..." }
  ```
- `POST /api/admin/embedding/reindex` — body `{ provider, model, dimensions, base_url? }` →
  `{ job_id, state: "queued" }`. Returns **409** if a re-index is already running.
- `GET /api/admin/embedding/reindex/status` → poll this; shape:
  ```jsonc
  { "state": "idle"|"running"|"complete"|"failed"|"unknown",
    "job_id": "...", "target": { "provider","model","dimensions" },
    "new_version": "v20260619...", "started_at": "...",
    "collections": { "academic": { "total": 1200, "written": 800 }, ... },
    "written": 3400, "completed_at": "...", "error": "..." }
  ```
  Drive a progress bar from `collections[*].written / total`. Poll every ~2–3s while `running`.

---

## 5. Rules the UI must respect

- **Test before Save** — `PUT` stores blindly; a bad model only fails at request time otherwise.
- **Embedding ≠ generic PUT** — always go through `/embedding/reindex`. Show the `warning` and a confirm dialog ("re-embeds entire corpus, can't be undone in place").
- **Air-gapped** (`deployment_mode === "air-gapped"`): only local providers are allowed — filter the picker to `ollama` / `openai_compatible` / `vllm` (LLM) and `ollama` (embedding). The backend also rejects cloud (400), but hide them proactively.
- **Availability** — disable/grey a provider when `providers[p].available === false`; show `key_source` ("managed" / "BYOK" / "none") and `hint`.
- **`db_enabled === false`** — render the model-config section read-only (kill-switch is on; PUT → 409).
- **Keys** — never expect plaintext back; render `byok`/`managed`/`source`/`hint`. "Use my own key" = PUT; "Use managed" = DELETE.
- **deepseek has no embeddings**; **qwen embeddings** use the preset DashScope intl base_url (leave blank).
- **base_url required** for `openai_compatible` / `vllm`; optional elsewhere.

## 6. Model-id placeholders (free-text fields; examples only)

| Provider | Example model ids |
|----------|-------------------|
| groq | `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` |
| google | `gemini-2.0-flash`, `gemini-2.5-pro` |
| anthropic | `claude-sonnet-4-6`, `claude-opus-4-1` |
| openai | `gpt-4o-mini`, `gpt-4o` |
| deepseek | `deepseek-chat`, `deepseek-reasoner` |
| qwen | `qwen-plus`, `qwen-max`, `qwq-32b` |
| ollama | `llama3`, `deepseek-r1:7b`, `qwq` |
| embedding: google | `gemini-embedding-2-preview` (3072) |
| embedding: openai | `text-embedding-3-small` (1536), `-large` (3072) |
| embedding: qwen | `text-embedding-v3` |
| embedding: ollama | `nomic-embed-text` (768) |

(Don't hardcode a closed list — keep model a free-text input with these as placeholder hints.)

## 7. Not exposed via these endpoints (yet)

> ⚠️ **DECISION NEEDED — reasoning/thinking has no API toggle.**
> Chain-of-thought surfacing is automatic per provider (Groq / DeepSeek / Qwen / Ollama
> always-on; Anthropic gated by the **env-only** flag `agent_anthropic_extended_thinking`,
> default off). None of the endpoints above read or write it, so the Settings page
> **cannot** control it as built.
> **Action:** decide whether the UI needs a thinking on/off control.
> - If **no** → nothing to do; it just works per provider.
> - If **yes** → it needs a small new backend endpoint (e.g. `GET/PUT /api/admin/model-config/thinking`)
>   backed by a DB/config value; flag this back so it gets built before wiring the toggle.
> Don't build a UI switch against the current API — there's nothing for it to call.

- **Per-assistant / per-user** model overrides are out of scope (global per-deployment only).

## 8. Frontend integration notes

- Follow the existing admin pattern in [frontend/src/pages/AdminPage.jsx](frontend/src/pages/AdminPage.jsx) and the service layer in [frontend/src/services/](frontend/src/services/) (auth header / base URL handling already established there).
- All calls need the admin JWT bearer token, same as other `/api/admin/*` calls.
- The `version` field on responses can be used to detect out-of-band changes (another admin/worker), but isn't required for a first cut.

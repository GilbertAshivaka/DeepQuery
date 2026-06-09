# Agent Layer — Build Handoff

**Read this alongside `AGENT_LAYER_GUIDE.md`.** This doc gives a fresh session the
project context that isn't in the guide: what's already built, the exact contracts
the Agent Layer plugs into, where the code lives, how to run/test, and the known
caveats. The guide is the *spec*; this is the *current ground truth*.

---

## 1. Where the project stands

Build order is **DeepQuerySDK → Connector Infrastructure → Agent Layer → UI**.
The first two are **done**; you are building the third.

- **DeepQuerySDK** — published to PyPI as `deepquery-sdk` (1.0.0, and 1.1.0 adding
  resources/prompts emission). Lives in `DeepQuerySDK/`. Connectors emit MCP servers.
- **Connector Infrastructure** — **complete**, in `backend/connectors/`. All four
  phases of `CONNECTOR_INFRASTRUCTURE_GUIDE.md` plus full consumption of all three
  MCP primitives (tools, resources, prompts). Verified by agentless smoke tests
  (`backend/connectors/smoke_test*.py`, all passing).

The existing **document RAG** path (the "document path") already works:
`backend/retrieval/` (hybrid dense+BM25+RRF, cross-encoder rerank), `backend/
vectorstore/` (ChromaDB), `backend/knowledge_graph/` (Neo4j), `backend/llm/`
(Groq Llama), `backend/embeddings/` (Gemini). Your job is to add the agent that
orchestrates **document path + live path** and gates actions.

---

## 2. The contracts the Agent Layer builds on

The Agent Layer **never speaks MCP** — it calls the Connector Gateway, which owns
all connector I/O, policy, and safety. The gateway instance lives at
`connectors.gateway.ConnectorGateway` (also a module singleton used by the API in
`backend/api/connectors.py`). Key async methods (all enforce governance, deployment
mode, caching, credentials, audit, and circuit-breaking under the hood):

- `await gw.read(connector_id|name, capability, arguments, user_id, conversation_id)`
  → tool read; returns `{records, citations, cache_hit, ...}`. Each citation is a
  timestamped **live citation** (`connectors/citations/live_citation.py`).
- `await gw.read_resource(uri, connector_id|name, user_id, conversation_id)` → MCP
  resource by URI; returns `{contents, citations, ...}`.
- `await gw.get_prompt(prompt_name, arguments, connector_id|name, user_id)` → MCP
  prompt; returns `{messages, untrusted: true, ...}`.
- `await gw.discover(connector_id|name, user_id)` → `Discovery{tools, resources, prompts, supports}`.
- **Action gating (this is the key integration):**
  - `await gw.preview_action(connector_id|name, capability, arguments, user_id)` → `{pending_id, preview}` (does NOT execute).
  - `await gw.approve_action(pending_id, approver_id)` → `{approval_token}`.
  - `await gw.execute_action(pending_id, approval_token, user_id)` → runs it; **refused without a valid token**.
  - `await gw.reject_action(pending_id, approver_id)`.

> **The approval gate is the most important seam.** The Connector Infrastructure
> *enforces* gating (execute is refused without a valid approval token). The
> **Agent Layer is the *issuer*** — it must, after a human confirms, call
> `approve_action(...)` to mint the token, then `execute_action(...)`. The
> approval UI/modal is an Agent-Layer concern. Build the human-in-the-loop flow
> around these four methods.

Other gateway/governance facts you'll rely on:
- **Governance**: a connector must be admin-**approved** (allowlist, role-restricted,
  version-pinned) and user-**enabled** before the gateway will serve it. For real
  agent calls pass `user_id` so this is enforced; system/agentless calls pass
  `enforce_governance=False`. APIs in `backend/api/connectors.py`.
- **Credentials**: per-user, encrypted; injected by the gateway at call time. The
  agent never sees them.
- **Deployment mode** (`cloud|hybrid|air-gapped`, `settings.deployment_mode`)
  constrains connectors AND must constrain **model choice** — in air-gapped mode the
  Agent Layer must use local models (Ollama/vLLM), no cloud LLM APIs. See guide §11.

---

## 3. What the Agent Layer must deliver (from AGENT_LAYER_GUIDE.md)

Read the guide for the authoritative spec; at a high level expect:
- **Orchestration**: decide per query whether to use the document path, the live
  path (connectors), or both.
- **Dual-source context assembly** (Connector guide §10): merge document chunks +
  live records into one context, **jointly cited**; live citations are visually
  distinct and carry `retrieved_at`. The existing **self-correction** step must
  treat a live citation's `retrieved_at` as part of the claim's truth ("true as of
  T", not "true absolutely").
- **Action approval loop**: preview → human approve/reject → execute, via the
  gateway methods above.
- **Untrusted content discipline (critical safety)**: all live connector data AND
  all connector/prompt descriptions are **untrusted** — wrap them so they can never
  be interpreted as instructions to the agent. The gateway preserves the provenance
  boundary; the Agent Layer must not collapse it.

---

## 4. How to run & test

- **Backend env**: `backend/venv` (Windows). Activate or call
  `backend/venv/Scripts/python.exe` directly. Run things **from the `backend/`
  directory** (imports are top-level: `from core...`, `from connectors...`).
- **Infra dependencies** (dockerized): Redis (required — action gate, OAuth pending,
  cache), ChromaDB, Neo4j. Redis must be up for action gating.
- **DB**: SQLite (`backend/deepquery.db`), sync SQLAlchemy, `init_db()` creates
  tables. **No Alembic yet** — schema changes are applied by dropping/recreating the
  connector tables (a migration is a planned follow-up; see §5).
- **Smoke tests** (agentless, good as living examples of the gateway API):
  `python -m connectors.smoke_test` (dual-source read), `_auth`, `_governance`,
  `_actions`, `_resources`. All pass today.
- **Config**: `.env` (copy from `.env.example`). Note `CONNECTOR_ENCRYPTION_KEY`
  (Fernet, for credentials) and `DEPLOYMENT_MODE`.

---

## 5. Known caveats / open items (don't trip on these)

- **Nothing was committed to git** during the SDK + connector build (unless you
  commit before starting). Check `git status` first.
- **No Alembic migrations** — connector tables get drop/recreated on schema change.
  If you add Agent-Layer tables, follow the existing `models/database.py` +
  `init_db()` pattern, or introduce Alembic (a noted future task).
- **SDK is published to PyPI at 1.1.1** (1.1.1 was a metadata-only fix over 1.1.0:
  corrected repo URLs). The backend venv has the 1.1.0 wheel installed locally —
  functionally identical; `pip install -U deepquery-sdk` picks up 1.1.1 anytime.
  The backend requirement is `deepquery-sdk>=1,<2`. The Agent Layer consumes
  connectors via the gateway, so the exact SDK version doesn't affect it.
- **Circuit breaker is in-process** (per worker) by design — not shared across
  workers. Deliberate; don't "fix" unless scaling demands it.

---

## 6. Org-agnostic reminder

DeepQuery targets **any vertical** (finance, legal, healthcare, research,
corporate) — the Pwani University roles (`student/lecturer/hod/...` in
`core/constants.py`) are a **case-study artifact** to be generalized before ship.
**Treat roles as opaque strings**; don't hard-code the academic taxonomy or assume
an academic context in the Agent Layer.

---

## 7. Suggested first steps for the new session

1. `git status` / commit the existing work if not already committed.
2. Read `AGENT_LAYER_GUIDE.md` end to end; skim this handoff and the connector
   smoke tests for the live gateway API in action.
3. Confirm infra is up (Redis/Chroma/Neo4j) and `python -m connectors.smoke_test`
   passes — that proves the live path the agent will call.
4. Follow the guide's phased roadmap. The earliest valuable slice is usually:
   route a query to the document path + (when relevant) the live path, assemble a
   dual-source context, and render document + live citations together.

Persistent project memory exists in the user's Claude memory (SDK status,
dev-environment topology, org-agnostic roles) and will load automatically.

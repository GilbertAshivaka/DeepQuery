# Agent Layer — Build Plan & Decisions

**Companion to `AGENT_LAYER_GUIDE.md` (the spec) and `AGENT_LAYER_HANDOFF.md` (ground truth).**
This document records the architecture and the concrete decisions agreed before building, so we
can come back to them as we build. Where this doc and the guide differ, the differences are
deliberate and called out under *Divergences from the guides*.

_Status: agreed during planning (2026-06-08). No agent-layer code written yet._

---

## 1. What we're building (one paragraph)

A reasoning/coordination tier that **wraps** the existing RAG system without breaking it. An
**Orchestrator** classifies each request (document / live / both / action), plans bounded steps,
and delegates to specialized **sub-agents** (retrieval, action, verification, skill-sync). It
assembles dual-source context (document + live, jointly cited), gates every state-mutating action
behind a human approval, and keeps agent instructions (skill files) grounded as the corpus changes.
The agent layer is the **issuer** of approval tokens; the Connector Gateway already **enforces** them.

---

## 2. Decisions

### 2.1 Orchestration framework — LangGraph + LangChain slots
- **LangGraph** for the orchestration control-flow: a bounded, inspectable graph with intent
  classification, conditional delegation, parallel reads, a step ceiling, and — critically —
  `interrupt()`/resume for the approval gate.
- **Why LangGraph specifically:** the approval gate is a human-in-the-loop pause that spans HTTP
  requests (agent pauses → user sees a modal → approves on a *later* request → graph resumes).
  That needs durable paused state. LangGraph's checkpointer handles it, and we already run **Redis**
  (it backs the action gate today) — a Redis checkpointer is the natural fit.
- **LangChain** stays as the **model-abstraction layer**: chat-model classes are the swappable
  model slots (provider-agnostic). `langchain-groq` and `langchain-google-genai` are already
  installed; we'd add `langchain-anthropic` and `langchain-ollama` (the latter for air-gapped).
- **Not** using a hosted agent runtime (e.g. Anthropic Managed Agents): it would lock us to one
  vendor's infra and cannot satisfy multi-provider / air-gapped / self-hosted-compute requirements.
  We run the loop in-process.
- Keep the graph **explicit and small** — no open-ended ReAct wandering. The step ceiling +
  explicit intent classification are the "agent sprawl" guardrails (guide §4). The `agent_run`
  trace table pairs with the checkpointer for auditability.

### 2.2 Models — GPT-OSS-120B via Groq throughout the agent layer (evaluation)
- Three independently configurable **model slots**: `orchestration`, `generation`, `verification`.
- **Decision (current):** use **`openai/gpt-oss-120b` via Groq for all three slots**.
  - *History:* first defaulted to Gemini 2.5 Flash, but the Google free tier proved too tight
    for development — **5 requests/min** and **~20/day** for `gemini-2.5-flash` generate (verified
    empirically; a run makes 3 generate calls, so ~6 runs/day exhausted the daily cap). Switched to
    GPT-OSS-120B on Groq (key already on hand, far more generous). Verified end-to-end against live
    Chroma/Neo4j: classify → retrieve (5 real passages) → grounded answer → VERIFIED.
- This is **slot config, not a hard dependency** — any slot can be swapped per deployment (Gemini,
  Claude Haiku/Sonnet, local Ollama/vLLM, etc.). To re-evaluate Gemini later (e.g. with billing on),
  set `agent_*_provider=google`.
- **Air-gapped mode is enforced**, not advisory: cloud models hidden, a local backend required for
  every slot (`settings.deployment_mode`).
- The **existing chat RAG path is unchanged** — it keeps using `llm_model` (Groq/Llama). The agent
  layer's slots are configured independently of the chat path.

### 2.3 Surface & UX — a dedicated Agents page, separate flow
- A **dedicated Agents page**, separate from the existing Chat page, with its **own flow and own
  API endpoints**. Chat (`/api/query/*`) is untouched; the agent flow reuses underlying services
  (retrieval pipeline, gateway, model slots) but never goes through the chat interface.
- UX (Manus-style inspiration): plan rendered as a **todo checklist** (Claude-Code style),
  **output streams onto the page as the agent works**, and a **collapsible/expandable CoT /
  reasoning panel** so users can watch the agent think. Keep a short **"why"** on actions.
- **Groundedness vs CoT:** the delivered answer stays grounded — every factual claim cites a
  document (rust, stable) or live (violet-family + timestamp) source. The CoT panel is a *process*
  view, never a source. Untrusted content shown in the trail stays visibly fenced (provenance
  preserved); the action "why" draws on the cited source (the catch-a-misread surface).
- CoT panel is fed by two merged streams: model *thinking* where the slot exposes it (Gemini 2.5
  Flash can), plus our own structured `plan` / `step_status` / `tool_activity` events — so the
  view is consistent across model slots.

### 2.4 Capability stance — capability-first, no artificial caps
- Multi-step plans, many tools, parallel reads, concurrent runs, and user-authored assistants are
  all in scope. We do **not** artificially limit capability.
- The only non-negotiables are the **safety invariants**: the action gate + single-use scoped
  token, untrusted-content fencing, and the governance allowlist. These are seams that make
  capability safe — not capability limits.
- **No code-execution VM** for the orchestrator by default. Capability surface = gateway connectors
  + retrieval + sub-agents. (A gated scripting capability could be added later if ever wanted.)

### 2.5 Sub-agents vs assistants (resolves "do we need custom GPTs?")
- **Sub-agents = fixed machinery** (code): orchestrator, retrieval, action, verification,
  skill-sync. Exposed via a **capability registry** so the orchestrator delegates by *capability*,
  not by hardcoded name — adding a future sub-agent is a registration, not a refactor.
- **Assistants = user/admin-authored configurations** over that machinery: a skill folder
  (`SKILL.md` + `facts/*`) plus a `deepquery:` binding block, stored in a registry.
- **They converge:** an "assistant" *is* the custom-GPT concept. There is **no separate custom-GPT
  system to build.** Ours is more capable (versioned, grounded, sync-maintained, governed) and
  simpler (one schema). Build the foundation now; the assistant-authoring UI comes later.

### 2.6 Skill files — adopt Anthropic Agent Skills format as a namespaced superset
- Use Anthropic's `SKILL.md` + YAML frontmatter **verbatim** for compatibility:
  - `name`: lowercase letters/numbers/hyphens, ≤64 chars, no XML, no "claude"/"anthropic".
  - `description`: third-person, says **what + when**, ≤1024 chars (this drives triggering).
  - Body **under ~500 lines**; reference files **one level deep** from `SKILL.md`.
- Add a namespaced **`deepquery:`** frontmatter block for our governance metadata:
  `kind` (assistant | sub-agent), `version`, `connectors`, `capabilities`, `model_overrides`,
  `dependencies` {documents, entities}, `corpus_facts` (list of sync-owned reference files).
- **Key elevation — the human-intent / corpus-fact split becomes structural** (solves guide §10
  cleanly):
  - **Human intent** (goal, workflow, voice) → the **`SKILL.md` body**. *Off-limits to Skill Sync.*
  - **Corpus-derived facts** (policies, thresholds, definitions) → **bundled `facts/*.md`**.
    *Owned, diffed, and proposed-on by the Skill Sync Agent.*
  This also gives Anthropic-style progressive disclosure: always-load `description`, load body when
  the assistant is selected, load a `facts/*.md` only when relevant.
- **Our moat over plain Anthropic Skills:** the self-maintaining groundedness loop (Skill Sync),
  versioned/reversible/attributable edits, admin gating, and the governed action seam. (Anthropic
  docs note skills go stale and can misdirect tools — we fix both.)
- Adopt their **evaluation-driven** discipline: ≥3 eval scenarios per assistant, tested across the
  model slots, before writing extensive instructions.
- **Divergences:** loading is our own loader (not a bash VM); "scripts" map to **connector
  capabilities through the gateway**, not arbitrary bash. Treat user-uploaded skill files like
  "installing software" — admin review before an assistant goes live.

---

## 3. Architecture

### 3.1 Modules (guide §13, plus model slots + registry)
```
backend/agents/
  orchestrator/       intent classify, plan, delegate, stop control   (LangGraph graph)
  retrieval_agent/    wraps retrieval_pipeline (document) + gateway (live); citation merge
  action_agent/       preview -> gate -> token -> execute  (4 gateway calls)
  verification_agent/ extends self-correction; live-citation timestamp-aware
  skill_sync/         ingestion-event subscriber, dependency resolver, diff proposer
  approval/           approval-gate logic; pairs with connectors' action_gate
  models/             slot abstraction: orchestration | generation | verification
  registry.py         capability -> sub-agent registry (extensibility)
backend/skills/
  files/              versioned skill markdown (SKILL.md + facts/*.md)
  registry/           skill metadata, declared dependencies, version history
```

### 3.2 Integration point
- `backend/api/agents.py` (new) calls `orchestrator.run(...)`. Chat (`backend/api/query.py`) is
  unchanged. The orchestrator calls the existing
  [`retrieval_pipeline`](backend/retrieval/pipeline.py) as the **document path** tool.
- Live path = the gateway's async methods (`read`, `read_resource`, `get_prompt`, `discover`); the
  agent layer **never speaks MCP directly**.
- Action path = `preview_action` -> (human approval) -> `approve_action` (mint token) ->
  `execute_action`. One action per approval; reads are never gated.

### 3.3 SSE event contract (extends today's single `answer_token` blob)
`plan` (ordered steps) · `step_status` (pending/running/done/awaiting-approval/failed) ·
`reasoning` (CoT panel) · `tool_activity` · `answer_token` (real streaming) ·
`citations` (document + live, visually distinguished) ·
`approval_required` (concrete preview + why + cited sources + `pending_id`) ·
`verification_result` · `done`. Approval is resolved by a **separate endpoint**
(`approve` / `reject`) that resumes the paused LangGraph run.

### 3.4 New persistent data (follow `models/database.py` + `init_db()`; no Alembic yet)
`agent_run` (plan/delegations/steps trace) · `approval_log` (every approval/rejection + token +
approver) · `skill_file` (+ versions) · `skill_dependency` (declared deps per skill) ·
`skill_change_proposal` (pending diffs + trigger + confidence) · `assistant` (registry entry).
Persists control-plane + instruction data only — **never** live business data.

### 3.5 Config additions (`backend/core/config.py`)
Per-slot provider + model: `orchestration_*`, `generation_*` (agent layer), `verification_*`
— defaulting to Gemini 2.5 Flash. `anthropic_api_key` only if a Claude slot is chosen later.
All choices constrained by `deployment_mode` (air-gapped enforcement).

---

## 4. Divergences from the guides (deliberate)
- **UI guide §7** assumed the plan/progress display lives *inline in the chat thread*. We override
  this with a **dedicated Agents page** and a separate flow. The design system still applies
  (rust/violet, citation chips, approval modal) on the new surface.
- **Guide §6** suggests Claude Haiku 4.5 as the economical default. We use **GPT-OSS-120B via Groq**
  throughout the agent layer initially to evaluate it (after Gemini 2.5 Flash's free-tier caps proved
  too tight); the slot abstraction keeps this reversible.

---

## 5. Phased roadmap (guide §15; each phase preserves prior behavior)

**Phase 1 — Orchestrator over existing RAG**
- Sprint 1: model-slot abstraction (GPT-OSS-120B via Groq wired into all three slots); intent
  classification + minimal LangGraph planner; capability registry; new `backend/api/agents.py`
  SSE run endpoint emitting the enriched event set; wrap `retrieval_pipeline` as the document path.
- Sprint 2: route document Q&A through Orchestrator -> Retrieval Sub-Agent (doc only) ->
  generation -> Verification Sub-Agent.
- **Exit:** a document-only query returns identically to today, now flowing through the graph.

**Phase 2 — Live retrieval through agents** ✅ DONE & verified
- Retrieval Sub-Agent now runs the document + live paths in parallel
  ([live.py](backend/agents/retrieval_agent/live.py)): enumerate the user's enabled connectors →
  discover read-only tools → orchestration model selects ≤3 calls (descriptions treated as
  untrusted) → parallel `gateway.read`. Dual-source citations merged ([Source N] document / [Live N]
  live, the latter carrying `retrieved_at`); generation and verification are timestamp-aware.
- Live engages only for `live`/`both` intent — document-only stays the Phase-1 fast path.
- **Exit met:** verified end-to-end against the local `demo-tickets` dev connector — the agent
  answered with a live `[Live 1]` citation alongside document sources, governance-enforced and
  audited, no live data persisted.

**Phase 3 — Actions & approval gate**
- Action Sub-Agent (preview -> surface), approval gate + single-use scoped short-lived token,
  resume-on-approval; wire token -> gateway enforcement; one-action-per-approval; reasoning + source
  display. Test approve and reject end to end.
- **Exit:** an agent proposes an action, a human approves the specific preview, it executes once;
  an unapproved or mismatched execute is refused.

**Phase 4 — Skill files & synchronization**
- Versioned/reversible skill files + dependency registry + ingestion event carrying prior-version
  diff context; Skill Sync Agent (explicit + inferred-fallback resolution, admin-gated diffs,
  reversible writes); untrusted-content handling across all agents.
- **Exit:** a document change yields a proposed, human-reviewed skill-file diff that, on approval,
  updates the dependent assistant's instructions as a reversible version — never autonomously.

---

## 6. Open / deferred items
- Assistant-authoring **UI** (registry CRUD surface) — foundation now, UI later.
- A gated **code-execution/scripting** capability for the orchestrator — out of scope unless
  explicitly wanted.
- **Alembic** migrations — still a planned follow-up (inherited from the connector layer).
- Per-assistant **evaluation harness** — adopt Anthropic's eval-driven discipline once assistants
  exist.

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

**Phase 3 — Actions & approval gate** ✅ DONE & verified
- Action Sub-Agent ([action_agent](backend/agents/action_agent/)) proposes ONE gated action (SDK
  ACTION tools only), calls `gateway.preview_action`, surfaces preview + reasoning + cited sources via
  an `approval_required` SSE event with a `pending_id`. Approve/reject go through
  `POST /api/agents/actions/{pending_id}/approve|reject`, which mint the single-use token and execute
  once (or cancel). Resume uses the **gateway's Redis pending-record**, not a LangGraph checkpointer
  (checkpointer reserved for cross-turn memory / multi-action plans — see §6).
- Orchestrator routes `action` intent: classify -> retrieve (ground) -> propose_action -> await approval;
  falls back to a grounded answer when no action is warranted/available.
- **Exit met (verified with `demo-tickets create_ticket`):** propose -> reject never executes (later
  approve refused: "action already rejected"); propose -> approve executes once (`OPS-3` created);
  re-approve refused ("unknown or expired action") — single-use enforcement confirmed.

**Phase 4 — Skill files & synchronization** — Sprint 7 ✅ DONE, Sprint 8 next
- **Sprint 7 ✅ (DB source of truth):** DB models (SkillFile = human-intent `body` + corpus-fact
  `fact_sections`; SkillFileVersion immutable+attributable; SkillDependency declared/inferred;
  SkillChangeProposal). [skills/service.py](backend/skills/service.py) (create / versioned fact edits /
  admin body edits / rollback / dependency declare+resolve / render) + [skills/parser.py](backend/skills/parser.py)
  (Anthropic-format frontmatter+body+fact sections). Ingestion-complete **Celery event**
  ([tasks/skill_sync_task.py](backend/tasks/skill_sync_task.py)) enqueued from the ingestion pipeline.
  Verified: 4 attributed versions incl. rollback, dependency resolution, SKILL.md render.
- **Sprint 8 ✅ DONE & verified:** Skill Sync Agent ([agents/skill_sync/](backend/agents/skill_sync/))
  — `run_sync_for_document` (runs in the Celery worker): explicit dep resolution
  (`skills_declaring_document`) + inferred (Gemini-embedding cosine of changed content vs each fact
  section, threshold 0.55), model-proposed grounded diffs (changed doc treated as untrusted data) into
  `SkillChangeProposal` (pending). Admin endpoints [api/skills.py](backend/api/skills.py): list/create/get
  skills, rollback, declare dependency, list proposals, approve (→ new reversible version via
  `set_fact_section`), reject (logged). Never auto-applies.
- **Exit MET (verified):** a changed doc ("leave now 30 days") produced an explicit proposal
  `21→30 days`; approve wrote skill v2 (attributed `skill_sync:doc:<id>`); reject left the version
  unchanged. The self-maintaining-groundedness loop is closed.

> **Backend layers complete:** DeepQuerySDK → Connector Infrastructure → **Agent Layer (Phases 1–4)**.
> Remaining before UI: the §5b pre-UI capability gaps (#1 direct-intent ✅ done; #2 conversation
> memory + stop/steer; #3 whole-doc + attachments).

---

## 5b. Pre-UI capability gaps (agreed — do before the UI phase)
These reshape the agent from "RAG-over-chunks" into a capable assistant; required before UI.
1. **Direct / general-knowledge intent (no retrieval). ✅ DONE & verified.** 4th intent `direct` →
   `direct_answer` node skips retrieval + verifier, streams the answer, emits a `grounding` event
   (`grounded:false`) + `done.grounded=False`, no citations. Gated by `settings.agent_allow_ungrounded_answers`
   (default True; False → direct falls through to the grounded path). Per-assistant override + explicit
   per-query toggle still to come with the registry/UI.
2. **Conversation memory + stop/steer. ✅ DONE & verified.** App-level (DB history → `chat_history`),
   not the LangGraph checkpointer — its unique value (mid-flight resume) isn't needed here, and this
   avoids restructuring graph state + a new dependency. `AgentConversation`/`AgentTurn` tables (also the
   agent-run trace); `/api/agents/run` loads prior turns as memory, persists user turn up front +
   assistant turn on completion; GET/DELETE `/api/agents/conversations[/{id}]`. Stop = disconnect
   cancels the run (assistant turn unsaved, user turn persists); steer = new turn in the same
   conversation loads history. Verified: a follow-up resolved "the same percentage" from prior turns.
   True mid-flight interject deferred (would use checkpointer/`interrupt`).
3. **Whole-document & user-attached context. ✅ DONE & verified (text path).** Whole-doc =
   **reparse-on-demand** ([agents/documents.py](backend/agents/documents.py), via ingestion parsers,
   12k-char cap); auto-expands when ≥2 retrieved chunks share a document → `[Doc N]`. User attachments:
   `AgentAttachment` table (raw file on disk + extracted text + kind — **images stored from day 1**,
   fed to the model once the Gemini multimodal path lands), `POST /api/agents/attachments`, `/run`
   `attachment_ids`, persisted + returned on conversation load (`[Attachment N]`). generate_node now
   assembles 4 source kinds. Verified: an attached `notes.txt` was cited `[Attachment 1]`; a corpus PDF
   re-parsed to full text. Deferred: images-to-model (Gemini path), reparse caching, mid-flight interject.

All §5b pre-UI gaps (#1, #2, #3) are **done**. Order completed: Phase 4 → {#1, #2, #3} → **UI next**.

## 5c. Resumable agent (RESUMABLE_AGENT_SPEC_V2) — build status

**Phase R1 — Checkpointer + two-node gate + resume ✅ DONE (2026-06-12).**
`langgraph-checkpoint-redis==0.1.1` (the only langgraph-0.2.x-compatible release; forced
`redis-py 5.2.1 → 6.4.0`, inside kombu's `<6.5` window) + Redis 8 (`redis:8-alpine`,
bundles RedisJSON/RediSearch) with **AOF on** (`--appendonly yes --appendfsync everysec`)
— compose + SETUP_AND_RUN.md updated; checkpoints share **db 0** (RediSearch constraint;
distinct key prefixes from Celery — never FLUSHDB db 0). Graph compiles lazily WITH the
checkpointer (TTL `agent_run_ttl_hours`, default 72h) and degrades to the legacy
single-pass graph if Redis is down. Per-RUN `thread_id`; two-node gate
(`propose_action` = prepare w/ side effects + idempotent preview keyed
`(thread_id, step)`; `await_approval` = interrupt only); resume → `resolve_action`
(approve→token+execute / reject) → `report_action` (grounded report streamed as the
answer — supersedes the Q6 shim once the UI migrates). Expired pending record (10-min
gate TTL vs multi-day pause) re-previews + re-gates, never errors.
`POST /api/agents/threads/{thread_id}/resume` (SSE continuation; persists resolution +
report turn); old `/actions/{id}/approve|reject` kept for legacy fallback + current UI.
Verified: 17-check e2e (pause/resume across orchestrator instances, reject, double-resume,
wrong-user, doc-path regression) + 6-check legacy-fallback suite, live endpoint check.
**Next: R2 event bus + snapshot → R3 executor ownership → R4 controller loop** (spec §4).

## 6. Open / deferred items
- ~~**LangGraph checkpointer + `interrupt`**~~ — **landed in Phase R1 (§5c)** for the action
  gate; the multi-action/controller-loop consumers arrive with R4+.
- **Admin-curated read-tool allowlist** (+ `agent_allow_unannotated_reads` strict toggle) — the
  reliable production hardening over the ecosystem read-name heuristic; do it with connector-governance UI.
- Assistant-authoring **UI** (registry CRUD surface) — foundation now, UI later.
- A gated **code-execution/scripting** capability for the orchestrator — out of scope unless
  explicitly wanted.
- **Alembic** migrations — still a planned follow-up (inherited from the connector layer).
- Per-assistant **evaluation harness** — adopt Anthropic's eval-driven discipline once assistants
  exist.

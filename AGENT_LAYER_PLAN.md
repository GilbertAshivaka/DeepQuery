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

**Phase R2 — Event bus + snapshot ✅ DONE (2026-06-14).** Every run mirrors its events to
a per-run Redis **Stream** (`agent:run:{tid}:events`, XADD monotonic IDs, MAXLEN-capped)
and folds them into a **snapshot** (`agent:run:{tid}:snapshot`) — new module
[event_bus.py](backend/agents/orchestrator/event_bus.py). `thread_id` hoisted to the API
(generated per run, passed into `run()`; idempotency/resume gated on `durable` so legacy
behavior is unchanged). New first event `run_started{thread_id}`. New subscriber endpoints:
`GET /threads/{id}/state` (one-GET paint snapshot) and `GET /threads/{id}/events` (SSE,
`Last-Event-ID` replay-then-live-tail with `id:` frames + heartbeats, terminal-aware).
`/run` and `/resume` publish through the bus (best-effort — a Redis hiccup never breaks the
in-request SSE). Execution still in-request (R3 moves it behind the same contract).
`UI_HANDOFF.md` §3/§3a/§8 updated. Verified: 21-check bus suite (fold, snapshot, replay,
reconnect-cursor, resume continuation, live tail, doc run) + R1 suites still green (17+6),
live endpoint registration.

**Phase R3 — Executor ownership ✅ DONE (2026-06-14).** Execution moved off the request
into an in-process asyncio **executor** ([executor.py](backend/agents/orchestrator/executor.py),
decision §5: one service, not a separate worker). `/run` and `/resume` now register a run
task and return a **bus subscriber** (`_bus_subscriber` SSE: replay-from-cursor → live tail
→ heartbeats → disconnect detection); the executor owns the orchestrator drive, bus
publishing, AND assistant-turn persistence — so a client can disconnect/reload mid-run and
the run still finishes and persists, then reattach via `/threads/{id}/events`. `/resume`
subscribes from the pause cursor (`snapshot.last_event_id`) so only the continuation
streams. Restart safety: `executor.is_running()` feeds an `is_live` guard in
`event_bus.subscribe` so a subscriber never tails a run whose producer died in a restart
(stops after replay instead of hanging). **Client contract unchanged from R2** (same events,
same bus — only the producer moved), so no UI rework. Verified: 11-check executor suite
(no-subscriber completion + persistence, `is_running` lifecycle, dead-run no-hang, action
pause→resume persistence) + R1/R2 suites still green (17+6+21), clean boot + endpoint
registration.

**Phase R4a — Controller loop (read-only) ✅ DONE (2026-06-14).** The bounded
plan→execute→observe loop, gated behind `agent_controller_loop` (default OFF — the fixed
pipeline stays the default and is byte-for-byte unaffected). New module
[controller.py](backend/agents/orchestrator/controller.py): nodes
hydrate→controller→(read|answer_step|replan|finalize), a cyclic graph. The controller emits
a **structured decision** (`read|answer|replan|done`) via the orchestration slot, with a
JSON schema ([CONTROLLER_DECISION_PROMPT](backend/agents/orchestrator/prompts.py)),
**repair-retry**, a **runaway fuse** (`agent_controller_max_steps`, default 50), decision
logging (the Q9 eval corpus), and visible-failure recovery (parse failure → still answers,
never a silent default/hang). Events stream via LangGraph's **custom channel**
(`get_stream_writer`, verified available in 0.2.76) so the loop emits the IDENTICAL event
contract (plan/step_status/reasoning/thinking/tool_activity/citations/answer_token/
verification_result/done) — API/executor/bus/UI unchanged. Reuses `gather`, the
generation/verification slots, and every formatting helper (not a fork; shares `AgentState`
+ the saver via `_ensure_saver`/`_get_controller_graph`). Dispatch is one branch at the top
of `Orchestrator.run()`. Covers document/live/both/direct queries; dynamic plan grows as
the controller decides steps. Verified: 11-check controller suite (read→answer→done same
contract, direct-no-read, step fuse, parse-failure recovery) + R1/R2/R3 suites still green
(17+6+21+11) with the flag off + clean imports.

**Phase R4b — `act` in the loop ✅ DONE (2026-06-14).** The `act` decision runs the R1
two-node gate INSIDE the controller loop, so the agent continues after an action:
read→…→**act → prepare → await_approval (interrupt) → resolve → report → controller →
done**. New gate nodes in [controller.py](backend/agents/orchestrator/controller.py)
(prepare_action/await_approval/resolve_action/report_action) reuse `action_agent`
.propose/approve/reject/summarize_result + the gateway (idempotency keyed `{thread_id}:act-{n}`,
expiry re-gate) and stream via the custom channel — identical approval/`action_result`
contract to the fixed gate. Gate nodes are added only when a checkpointer exists; without
one the `act` route falls back to `answer` (can't pause). `run_controller` catches the
loop's `__interrupt__` (updates channel) → emits `approval_required` + `done{paused:true}`;
new `run_controller_resume` feeds `Command(resume=…)` and forwards the continuation;
`Orchestrator.resume` branches to it when the flag is on. `report_action` loops back to the
controller (the run CONTINUES after an action — the core resumable win, now in the loop).
Verified: 12-check act suite (pause, resume-across-instances execute+report+continue,
reject, read-only unaffected) + R4a (11) + R1/R2/R3 suites green (17+6+21+11) + clean
imports. **R4 (a+b) complete.**

**Phase R5 (partial) — context discipline + sprawl control ✅ core DONE (2026-06-14),
spec §2.7–2.8.** New disk **artifact store**
([artifacts.py](backend/agents/orchestrator/artifacts.py)) behind a thin
`put/get/exists/delete/delete_thread` interface, keyed `{root}/{thread_id}/{step_id}/{id}`
(root = `agent_artifact_root` or `<document_store>/agent_artifacts`; local-disk adapter,
S3 swap later). The controller `read_node` now **offloads each read's raw payload to the
store** (refs in state) and **bounds the accumulated working context**
(`agent_controller_max_context_chunks`, default 40) so the checkpoint can't bloat across a
long run — distilled one-line findings preserve provenance. **Sprawl control** in
`controller_node` (all graceful wrap-ups, never dead drops): **stall detection** (a repeated
unproductive read, or `agent_controller_stall_threshold`=3 consecutive empty reads → forced
re-plan; a second stall → wrap up with what we have), a **per-run token-budget fuse**
(`agent_controller_token_budget`=120k, char/4 estimate), plus the existing step fuse.
Verified: 12-check R5 suite (artifact roundtrip, read archiving, stall escalation bounded
below the step fuse, token fuse) + R4a/R4b + R1/R2/R3 suites green (11+12+11+17+6+21+11 = 90
total) + clean imports.

**R5 remainder (deferred, documented):** the LLM **compaction node** (threshold-triggered
summarization of older findings, pinned-items-exempt — the bounded-context cap above is the
lightweight stand-in); **true multi-query parallel map-reduce reads** (the controller emits
one read/step today; gather already runs doc+live concurrently internally); **per-connector
concurrency caps in the gateway** for ≤5-wide fan-out; and a **question interrupt** on a
second stall (currently wraps up — the interrupt machinery lands with R7).

**Phase R6 — Multi-action + batch approval ✅ core DONE (2026-06-14), spec §2.4.** The
controller's `act` step now proposes a **plan of actions** (`action_agent.propose_batch` +
[BATCH_ACTION_SELECTION_PROMPT](backend/agents/orchestrator/prompts.py)): one action → the
unchanged single-gate flow; several → a **batch gate** (new controller nodes
await_batch_approval/resolve_batch/report_batch). The batch interrupt emits
`batch_approval_required` with a **typed preview per action** (`preview_status:"resolved"`)
and a **per-action toggle**; resume carries `{batch_decisions:{pending_id:approve|reject}}`
(plumbed through `Orchestrator.resume` → `run_controller_resume` → executor →
`ResumeRequest`). Approved actions execute serially (gateway still the sole enforcer),
deselected ones are skipped, and a **combined report** (one line/action + per-action
`action_result`) streams before the loop continues to done. `UI_HANDOFF.md` §3/§8 updated.
Verified: 10-check batch suite (pause with 3 typed previews, approve-2-reject-1 →
execute+skip+combined report+continue, single-action still simple gate) + all prior suites
green (12+12+11+17+6+21+11 = **100 total**) + clean imports.

**R6 parameterized actions + envelopes ✅ DONE (2026-06-14).** The §2.4 action-chaining
half: a batch action may be `parameterized` — its args reference an earlier action's result
via `${actionN.result.path}` placeholders, and it carries a declared **constraint envelope**
(`{derived_from, constraints:{field:{in|equals|derived}}, max_executions}`). At batch time
the gateway synthesizes a template preview (no dry-run — concrete args unknown). At execute
time the controller **materializes** the args from prior results in-order and
`gateway.execute_action(materialized_args)` runs `_within_envelope` — the enforcement:
no added/removed fields, concrete fields unchanged, derived fields satisfy their constraint.
Out of bounds → `EnvelopeViolation` (gateway REFUSES — never executes out-of-envelope) →
the action is `blocked`, reported held-back, and re-gated via the loop's single act path
(fresh concrete preview). `action_agent.propose_batch` emits parameterized actions +
`approve_with_args`; `BATCH_ACTION_SELECTION_PROMPT` teaches placeholders + envelopes.
Verified: 14-check suite (envelope diff edge cases, materialization, in-envelope executes,
**tampered → blocked not executed**) + all prior suites green (**114 total**). **R6 fully
complete.**

**Phase R7 — Question interrupt + interjection mailbox ✅ DONE (2026-06-14), spec §2.3/§2.9.**
New `ask` controller decision → `ask_node` interrupts with a `question` payload; on resume
the user's `answer` lands in findings and the loop continues (same two-node, replay-safe
pattern as the gates). **Interjection mailbox**: `event_bus.interject/drain_mailbox` on a
per-run Redis list; the controller drains it at the loop top (spec §2.9) — `augment` /
`cancel_step` fold into findings (the controller plans against them), `cancel_run` wraps up
gracefully. New `POST /threads/{id}/interject`; new `question` SSE event + `awaiting_input`
run status + `pending_question` snapshot field. The unified `Command(resume)` payload now
carries `{decision, approver_id, batch_decisions, answer}` — each paused node reads its own
field — plumbed through `Orchestrator.resume`/`run_controller_resume`/executor/`ResumeRequest`.
`UI_HANDOFF.md` §3/§3a/§3b updated. Verified: 10-check R7 suite (mailbox roundtrip, question
pause→answer→continue with the answer in findings, augment folded in, cancel_run wrap-up) +
all prior suites green (**124 total**). (R5's second-stall still wraps up; turning it into an
`ask` is a one-line swap now that the machinery exists.)

**Phase R8 — Skills consumption ✅ DONE (2026-06-14), spec §2.10. LAST FEATURE PHASE.**
The consumption side of the skills subsystem, finally wired. New
[skills.py](backend/agents/orchestrator/skills.py): `get_skill_index` ({name,description,
kind} for active skills — loaded at hydration, the controller always plans with it) and
`load_skill_snapshot` (snapshots a skill at its current version — **pinned by value** into
run state, so a paused run resumes under the version it started with). New `load_skill`
controller decision → `load_skill_node`: **two channels** — `body` → the pinned instruction
channel (`loaded_skills`, surfaced to the controller prompt AND the answer generation as
admin-authored instructions), `fact_sections` → the evidence channel (findings, citable).
**Both entry paths**: controller-discovered (index match → `load_skill`) and explicit
(`/run` `skill_names` → loaded at hydration). **Inform-never-authorize**: `metadata_json`
connectors surface as a "prefer these tools" focus hint that explicitly grants no new
permissions — the gateway stays the sole enforcer. New `skill_loaded{name,version}` event
(+ snapshot trace fold). `UI_HANDOFF.md` §3 updated. Verified: 10-check R8 suite (index in
context, load_skill → pinned body + facts-as-evidence + event, explicit selection at
hydration, body injected into generation, unknown-skill graceful) + all prior suites green
(**134 total**) + clean boot with all endpoints registered.

## 5d. Resumable agent — ALL FEATURE PHASES COMPLETE (R1–R8)

The durable, resumable, disconnect-surviving, sprawl-bounded controller agent is fully
built behind `agent_controller_loop` (default OFF — the fixed pipeline is the default and
untouched). 145 test checks across 12 suites.

**Deferred work — ✅ ALL DONE (2026-06-14):**
- **§2.7 Compaction node**: threshold-triggered (`agent_controller_compaction_threshold`,
  ~60% of window) — once working-context tokens cross it, the controller LLM-summarizes
  older raw evidence ([COMPACTION_PROMPT](backend/agents/orchestrator/prompts.py),
  citation-preserving) into one dense finding and drops the raw (safe in the artifact store);
  pinned items exempt (skill bodies, plan, recent findings + last K raw chunks). Densifies
  *below* the budget fuse so a long run continues.
- **§2.7 Multi-query parallel map-reduce reads**: a read decision may carry
  `queries:[{query,sources}]` → up to `agent_max_parallel_reads` (5) concurrent sub-reads
  (`asyncio.gather`), each archived + distilled, merged into the bounded context.
- **§2.7 Per-connector concurrency caps**: `_connector_semaphore` in the gateway read path
  (`agent_connector_max_concurrency`, 3) so a wide fan-out can't trip provider rate limits.
- **Startup supervisor**: `executor.reconcile_orphaned_runs()` (called from the FastAPI
  lifespan) marks restart-orphaned `running` snapshots `interrupted`; `/state` also applies
  the lazy `is_live` correction. (`interrupted` is now a terminal status so subscribers stop.)
- **TTL sweeper**: [sweeper.py](backend/agents/orchestrator/sweeper.py) `sweep_artifacts()`
  deletes on-disk artifact dirs whose Redis snapshot has expired; wired as Celery-beat task
  `tasks.sweep_agent_runs` (hourly). Redis keys self-expire via TTL.
- **Graph viz**: [scripts/viz_graphs.py](backend/scripts/viz_graphs.py) renders both graphs
  to [docs/agent_graphs/](docs/agent_graphs/) (.mmd + .png).
Verified: 11-check deferred suite (compaction densify+drop, parallel reads, per-connector
sem, supervisor, sweeper) + all prior suites green (**145 total**) + clean boot.

**What's left is non-feature work only:**
- **Turn the flag on + UI migration** (UI_HANDOFF.md is the spec): the Agents page consumes
  the new events (`question`, `batch_approval_required`, `skill_loaded`, …), the `/resume`
  (answer/decision/batch) + `/interject` + `/state` + `/events` endpoints.
- **Refinement** of anything surfaced once the UI is live.

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

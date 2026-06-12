# Resumable / Long-Running Agent — Build Spec v2 (Durable Controller Architecture)

**Status:** supersedes `RESUMABLE_AGENT_SPEC.md` (v1). All open questions (Q1–Q9) and the
new decisions from the 2026-06-12 design session are **resolved** in §5 — this spec is
build-ready. Read alongside `AGENT_LAYER_PLAN.md`, `UI_HANDOFF.md` (gains a new contract,
see §2.6/§2.12), and `AGENT_LAYER_GUIDE.md` (§4 stop-control, §7 approval gate — note the
§7 divergence is now resolved safely via constraint envelopes, §2.4).

**Goal:** a durable, resumable, genuinely long-running agent that: streams its plan,
narration, and CoT *as it works*; performs many reads (corpus + live connectors, up to 5
in parallel); uses what it learns to propose and — with user approval — execute actions;
continues after each action (report → verify → next step); pauses to ask the user
questions and resumes from the exact point; absorbs mid-flight interjections; consumes
**skills** (DB-stored playbooks) to govern how it executes; and survives client
disconnects, process restarts, and multi-day approval pauses.

---

## 0. Capability assurance — what this architecture guarantees, and via which mechanism

Every capability requested maps to a concrete mechanism in this spec. Nothing below is
aspirational; each row names the section that builds it.

| Capability | Mechanism | §
|---|---|---|
| Pause mid-run and resume exactly where it stopped | LangGraph checkpointer (Redis), per-run `thread_id`; `interrupt()` + `Command(resume=…)` | 2.1, 2.3 |
| Ask the user for input mid-run | `interrupt({type:"question"})` → checkpoint → `resume {answer}` → loop continues | 2.3 |
| Display plans as output while working | dynamic plan checklist streamed (`plan` / `step_status` events, append-as-planned, terminal status guaranteed incl. `skipped`) | 2.6 |
| Generate output *as* it works (not one final blob) | event bus streaming: narration, `tool_activity`, `answer_token` segments interleaved across steps | 2.5, 2.6 |
| Reasoning trail (CoT) for models that support it | `reasoning_format="parsed"` (already implemented on gpt-oss slots) → `thinking` deltas per controller/planning/generation call; graceful no-op for models without a reasoning channel | 2.6 |
| Subsequent reads → use info → execute action with approval | controller loop: read steps feed findings → `prepare_action` (gateway preview) → `await_approval` interrupt → approve → execute → report → continue | 2.2, 2.3 |
| Multiple actions in one run | loop continues after each action; batch (plan-level) approval with typed previews + constraint envelopes | 2.4 |
| Survive disconnects / reconnect to a live run | run executor owns execution; per-thread Redis Stream with seq IDs + `Last-Event-ID` replay + state snapshot GET | 2.5 |
| Mid-flight interjection ("also do X" / "skip that") | per-thread Redis mailbox drained at top of each loop iteration; augment / cancel-step / cancel-run semantics | 2.9 |
| Long runs without degradation | context compaction → findings, artifact store for raw payloads, map-reduce parallel reads, pinned instruction context | 2.7 |
| Long runs without runaway | stall detection + periodic re-planning + generous fuses (50 steps / token budget) instead of tight caps | 2.8 |
| Skill-governed execution | skill index always in controller context; `load_skill` controller action; body→instruction channel, fact_sections→evidence channel; version-pinned per run | 2.10 |
| Verified factual output, no retractions | verify-before-emit per factual segment | 2.11 |

---

## 1. The gap this closes (from v1, unchanged in substance)

Today (Phases 1–4): a single-pass graph compiled **without a checkpointer**; the action
gate ends the stream and a separate endpoint executes; the run never resumes. Therefore:
no post-action continuation (interim `summarize_result` shim only), one action per run,
no mid-run questions, no interjections, no durability. The v1 analysis stands; v2 changes
*how* we close the gap (see the architectural deltas in §2.5, §2.7, §2.8, §2.10 — none of
which existed in v1).

---

## 2. Target architecture

### 2.1 Checkpointer + run identity

- Compile the orchestrator graph **with `langgraph-checkpoint-redis`**. **⚠️ Pin
  deliberately**: verify compatibility with `langgraph 0.2.76` / `langchain-core 0.3.x`
  before installing (the prior `-U` incident pulled `langchain-core 1.x` and broke
  langgraph). Redis must run with **AOF persistence** (§6) — checkpoints are now a source
  of truth.
- **`thread_id` is per-RUN, not per-conversation.** Each user turn that starts agent work
  creates a new run-thread. Conversation memory stays where it is (DB
  `AgentConversation`/`AgentTurn`) and is **hydrated into the run's initial state**.
  Three stores, three jobs, no overlap:
  - **Checkpointer (Redis):** run state — plan, findings, pending interrupt, pinned
    skill versions, decision trace refs.
  - **Relational DB:** conversation state — turns, attachments, persisted answers.
  - **Artifact store (disk, §2.7):** large payloads, referenced from run state by key.
- A paused run (awaiting approval/answer) belongs to its run-thread indefinitely (subject
  to the TTL sweeper, §6). A new user turn in the same conversation starts a *new* run and
  may reference the paused one.

### 2.2 Controller loop with structured decisions

Replace the fixed pipeline with a bounded **plan→execute→observe loop** (custom
controller — not prebuilt ReAct; we need the gating/narration/policy seams):

```
hydrate (history + skill index)
  → opening narration + initial plan
  → ┌─ controller ──────────────────────────────────────────────────────┐
    │ drain interjection mailbox (§2.9)                                 │
    │ stall check (§2.8)                                                │
    │ DECIDE (structured): read | load_skill | act | ask |              │
    │                      answer_segment | replan | done               │
    └───────────────────────────────────────────────────────────────────┘
        read           → gather(want_…) ×1..5 parallel → map-reduce → findings
        load_skill     → §2.10 (instruction channel, pinned, version-recorded)
        act            → prepare_action → await_approval (interrupt) → execute
                          → report → verify → continue
        ask            → interrupt(question) → resume(answer) → continue
        answer_segment → verify-before-emit (§2.11) → stream → continue
        replan         → revise plan; append/skip checklist steps
        done           → final delivery → END
```

- **The controller's decision is a constrained structured output**, not free-form: one of
  the enumerated action types, with required fields per type and a one-line justification,
  validated against a JSON schema with a **repair-retry** on parse failure. A repeated
  failure is surfaced per the §2.9-carry-over rule (visible, recoverable — never a silent
  default). **Log every decision with its inputs** — this trace corpus is the eval set
  that will answer Q9 (stronger planner slot?) empirically rather than by guess.
- **The controller is tool-aware by construction** (v1 §2.11 carried forward verbatim):
  at each iteration it sees the live tool catalogs + the skill index + current findings,
  and decides from **real options, not a blind guess**. The one-shot classifier survives
  only as a cheap opening hint for the first narration — never as a router or gate.
- Parallel reads fan out **within** a step (≤5, §2.7); **actions are strictly serial**,
  and **interrupts never live inside parallel branches** (LangGraph parallel-branch
  interrupt semantics are messy; reads fan out, gates do not).

### 2.3 Human-in-the-loop interrupts — the two-node gate (replay-safe)

`interrupt()` **replays its containing node from the top on resume.** Every gate is
therefore **two nodes**:

1. **`prepare_action`** — calls `gateway.preview_action(...)` (creates the pending record
   + single-use token), writes `pending_id` + preview into state, **completes**.
   Additionally, make preview **idempotent in the gateway keyed on
   `(thread_id, step_id)`** — same key returns the existing pending record instead of
   minting a duplicate (belt-and-braces against future refactors re-merging the nodes).
2. **`await_approval`** — contains **only**
   `interrupt({type:"approval_required", pending_id, connector, capability, preview,
   constraints?, reasoning, sources})`. Replay re-runs a node that does nothing but
   interrupt. Safe.

Resume with `Command(resume={"decision":"approve"|"reject", ...})`:
- **approve** → `gateway.approve_action` + `execute_action` → **the loop CONTINUES**:
  `action_agent.summarize_result()` grounds the report, verification runs on it, the
  controller proposes the next step. This is the core fix — the agent never again stops
  dead after an action.
- **reject** → recorded as a finding; controller re-plans (alternative approach, ask the
  user, or finish with what it has).

**Question interrupts** use the same machinery with a different payload:
`interrupt({type:"question", text, context?})` → checkpoint → user answers via `resume
{answer}` → the answer lands in findings and the loop continues.

**Token-expiry degradation:** the gateway's single-use tokens expire; a run can pause for
days. A resume that finds an expired token **re-runs `prepare_action`** (cheap, thanks to
the node split) and re-presents the gate — never an opaque error.

The gateway remains the **sole enforcer** (token, audit, policy); LangGraph owns only the
run lifecycle. A bug in resume logic cannot execute an unapproved action — the token must
still be minted and consumed. Do not weaken this separation.

### 2.4 Multi-action runs + batch approval (Q2 — resolved safely)

Plan-level approval ships, but **typed**, so the user never approves fiction:

- Every planned action carries `preview_status: "resolved" | "parameterized"`.
  - **resolved** — all parameters known now → full concrete preview in the batch.
  - **parameterized** — parameters depend on a prior action's output (e.g. "create the
    page, then email *the link*") → the batch shows the action template **plus a declared
    constraint envelope**: e.g.
    `{recipient_in: [...], target_workspace: "Y", content_derived_from: "<artifact ref>",
    max_send_count: 1}`.
- The batch UI shows a concrete preview for every resolved action and the envelope for
  every parameterized one, with a **per-action toggle** (approve all / deselect some).
- **At execution time the GATEWAY diffs materialized parameters against the envelope**
  (enforcement, not advisory): inside → execute under the batch approval; outside → the
  run re-interrupts for *that action only* with a fresh concrete preview.
- Single-action runs keep the simple one-gate flow; batching is for multi-action plans.

This preserves guide §7's intent (a human never approves an action they haven't
meaningfully seen) while delivering the plan-level UX decided in Q2.

### 2.5 Execution ownership + event bus (the durability backbone — NEW in v2)

Request-tethered execution is disqualifying for long runs: a 30-step run cannot depend on
one HTTP connection surviving. Target model:

- **Run executor** owns graph execution: `POST /api/agents/run` registers/starts the run
  in an **in-process asyncio task** (decision §5: in-process, not a separate worker — one
  service; checkpoints already give restart-survivability of *paused* runs, and a process
  restart mid-step simply resumes the run from its last checkpoint) and returns. The
  graph advances independently of any client connection.
- The executor writes **every event** to a per-thread **Redis Stream**
  (`agent:run:{thread_id}:events`, `XADD`, monotonic sequence IDs).
- **SSE endpoints are pure subscribers**: connect with `Last-Event-ID`, replay missed
  events from the stream, then tail live. Reconnects, multi-tab, and
  "come back tomorrow to an awaiting-approval run" all fall out for free.
- A compact **run-state snapshot** (`agent:run:{thread_id}:snapshot`: plan + step
  statuses + pending interrupt payload + partial answer segments + run status) is
  maintained alongside, so a fresh client paints the UI with **one GET**, then subscribes.
- `resume` / `interject` are writes the executor consumes (resume → `Command` into the
  graph; interject → mailbox §2.9). No second request ever mutates in-flight graph state
  directly.
- On process restart: in-flight step work is lost by design; the supervisor marks
  affected runs `resumable`, and they restart from the last checkpoint (automatically or
  on next client contact — implementer's choice, document it).

**Phasing within this section:** ship the Redis-Stream event bus + snapshot **first**
with execution still in-request (subscribers already gain replay/reconnect), then move
execution into the executor. Same client contract both steps — the UI is built once.

### 2.6 Streaming contract (what the UI consumes — update `UI_HANDOFF.md`)

Continuous across the whole run, every event carrying the stream sequence ID:

- **`thinking` deltas — the CoT trail.** Slots run gpt-oss with
  `reasoning_format="parsed"` (already implemented): every controller decision, planning
  pass, and generation call exposes `reasoning_content`, emitted as `thinking` deltas
  scoped to the current step. The collapsible CoT trace fills across the entire
  multi-step run, not just final generation. **Models without a reasoning channel
  degrade gracefully**: no `thinking` events, everything else unchanged.
- **`reasoning` (narration)** — natural first-person "here's what I'm doing" lines, one
  per step, model-authored, varied; **never** internal labels/jargon (full v1 §2.7 rules
  carried forward, see §2.13).
- **`plan` / `step_status`** — **dynamic-length checklist**: steps append as the
  controller plans them, each reaches a terminal status
  (`done | failed | skipped`) — `skipped` is **new**, required by interjection-cancel and
  re-planning. Invariant unchanged: a step shown == a step that gets a terminal status;
  never pre-pad with steps that may not run. Labels are model-authored
  (generalizing `_build_plan` to dynamic plans).
- **`tool_activity`** — each read/action as it runs, reflecting a source that was
  actually chosen for a reason (§2.13 gather rules).
- **`answer_token`** — verified answer segments (§2.11), interleaved between steps:
  output flows *as* retrieval returns, not as one final blob.
- **`approval_required`** — single or batch (typed previews + envelopes, §2.4).
- **`question`** — NEW: the question interrupt payload.
- **`action_result`** — includes `message` (the grounded post-action report; the interim
  Q6 shim's field, now produced by the resumed run itself).
- **`skill_loaded`** — NEW: `{name, version}`; the UI may render it as a checklist step
  ("Following your *quarterly-report* playbook").
- **`done`** — terminal, with run telemetry summary (steps, reads, actions,
  skills@versions used).

`UI_HANDOFF.md` must be updated with: the snapshot GET + `Last-Event-ID` replay flow, the
`question` event, dynamic plan-append + `skipped`, batch-approval payloads, `skill_loaded`,
and the resume re-stream semantics.

### 2.7 Context discipline — what actually enables long runs (NEW in v2)

Window size is not the binding constraint (slots are 128k-class; even 1M-class models
degrade on raw transcripts). Long runs are enabled by keeping the working context a
**curated digest, not a transcript**:

- **Map-reduce parallel reads.** Fan-out is controller-decided per step, **1–5 reads**,
  each with a stated reason (no blind fan-out — §2.13). Each branch ends with a cheap
  per-result distillation ("what this read contributed, ≤N tokens, with citations");
  **only distillations + artifact references enter controller state.** Raw payloads
  (already capped at 4000 chars at the record level) go to the artifact store.
  **Per-connector concurrency limits live in the gateway** (the enforcement seam) so 5
  concurrent reads can't trip provider rate limits.
- **Compaction node, threshold-triggered** (decision §5): when accumulated run-state
  tokens cross the threshold (default ~60% of the model window; configurable), a
  compaction pass summarizes raw observations into structured **findings** and drops the
  raw forms from state, leaving artifact refs for re-reading. **Pinned items are exempt**:
  loaded skill bodies (§2.10), the current plan, constraint envelopes, and the last K
  steps' findings.
- **Artifact store: disk, behind a thin interface** (decision §5).
  `put / get / exists / delete` by key; first adapter = local disk at
  `{ARTIFACT_ROOT}/{thread_id}/{step_id}/{artifact_id}`. Deployment requires a persistent
  volume. Multi-host later = one adapter swap (S3/MinIO), zero call-site changes. The TTL
  sweeper (§6) cleans artifact directories alongside expired threads. Never store large
  payloads in checkpoints or the relational DB.

### 2.8 Stall detection, re-planning, fuses (replaces conservative caps)

Step count is an **output, not a knob**. Control sprawl by detecting non-progress, not by
capping productive work:

- **Stall detector**, checked at each loop top: (a) a proposed tool call whose normalized
  argument hash near-duplicates one already executed, or (b) N (default 3) consecutive
  steps producing no new findings → **force `replan`**. A second stall after a forced
  replan → **question interrupt** ("I'm not finding X via A or B — should I try C, or do
  you have a pointer?"). A stuck agent is stopped at step 6, not step 50.
- **Periodic re-planning**: an explicit "given findings so far, is the plan still right?"
  pass every K steps (default 5) and after every completed action — this is what keeps a
  30-step run coherent, and the streamed checklist is its natural artifact.
- **Fuses (runaway insurance only, not pacing):** hard ceiling **50 steps/run**;
  **≤5 parallel reads/step**; **per-run token budget** (configurable; set initial value
  from observed single-pass costs ×10 and tune from telemetry). Hitting a fuse =
  graceful wrap-up ("here's what I have so far + what remains"), never a dead drop.

### 2.9 Mid-flight interjection — external mailbox (race-free)

- The mailbox is a **Redis structure per thread** (`agent:run:{thread_id}:mailbox`),
  written by `POST /threads/{thread_id}/interject`, **drained by the controller at the
  top of each loop iteration**. It is *not* graph state — a second HTTP request never
  mutates an in-flight run's checkpoint (LangGraph does not support concurrent state
  writes to a running thread).
- **Semantics (Q3 — resolved):** default **augment** ("also do X" → folded into the
  plan); explicit **cancel-step** ("skip that" → step gets terminal status `skipped`);
  explicit **cancel-run** (graceful wrap-up). Boundary injection (lands at the next step
  boundary) is the contract — true mid-node cancellation is out of scope and not needed
  at second-scale steps.
- If the run is paused at an interrupt, an interjection is simply read on resume.

### 2.10 Skills consumption — procedure channel, not a retrieval source (NEW in v2)

Skills (DB-stored, versioned, Anthropic-format: `body` = human-intent playbook,
`fact_sections` = sync-maintained corpus facts, `metadata_json` = connectors/capabilities/
model overrides, declared document dependencies) finally get their consumption side.
**Core principle: two channels.** Everything `gather()` returns is **evidence** (cited,
compactable). A skill body is **procedure** — instructions that shape behavior. They must
not be flattened into one stream:

- **Skill index always in controller context.** `name + description + kind` for every
  active (non-archived) skill, loaded once at hydration (a few hundred tokens). The
  `description` column drives triggering — exactly what it was designed for. The index is
  metadata the controller *plans with*, not a step it takes.
- **`load_skill` is a controller action type** (distinct from `read`, because its output
  routes to the instruction channel). Trigger condition is *match*, not *ignorance*: the
  controller loads a skill when the query or an upcoming step matches its description —
  **before** planning the steps it governs. (The dangerous case is the agent confidently
  doing the task the wrong way; it will never "feel uninformed," so "load when I need
  more info" is the wrong trigger.)
- **Routing on load:** `body` → instruction channel, **pinned against compaction** while
  it governs upcoming steps, unloadable when its phase completes (pinned skills count
  against the context budget). `fact_sections` → the **evidence channel**, joinable into
  the citation set as grounded, citable reference.
- **Version-pin per run.** Record `skill@version` in run state at load; all reads resolve
  through the pinned `skill_file_versions` snapshot. Mandatory for checkpoint semantics: a
  run paused 2 days at a gate must resume under the version it started with, even if an
  admin edited the skill meanwhile. Log `skills@versions` in run telemetry ("which
  playbook governed this action" is an audit primitive).
- **Dependencies resolve lazily, fact_sections first.** Loading a skill does NOT
  auto-pull its declared documents (fact_sections exist precisely as the pre-distilled
  substitute — that is the Skill Sync Agent's whole job). The controller escalates to
  `gather(want_whole_doc=…)` on a declared dependency only when a step needs full text.
- **Skills inform, never authorize.** `metadata_json` connectors/capabilities **focus**
  the controller (prioritize those tools for skill-governed steps); they never expand
  permissions. The gateway remains the sole enforcement seam. Graduated trust: `body` is
  admin-authored + version-gated → legitimately instructions; `fact_sections` are
  machine-maintained from corpus → **data, never instructions**, even arriving with a
  skill (channel separation makes corpus-poisoning structurally inert on top of the
  existing admin gate on sync proposals).
- **Narrate skill use**: "Following your *quarterly-report* playbook…" as step narration;
  `skill_loaded` event; optional checklist step.
- **Both entry paths, one injection point:** controller-discovered (index match →
  `load_skill`) and explicit selection (user picks an assistant/skill for the run → loaded
  at hydration as run-level instructions). This implements the deferred
  "assistants = skill-folder registry" idea.

This closes the loop the subsystem was built for: ingestion → skill-sync keeps
fact_sections fresh → versioned skill → consumed at run time at a pinned version →
telemetry records which version governed which actions.

### 2.11 Verification — verify-before-emit (Q8 — resolved)

You can't unsay a streamed token. **Factual answer segments are verified before they are
emitted**; the small per-segment latency is masked by the continuously flowing
thinking/narration stream, and the user never sees a retraction. Narration, plan, and
progress events are unverified by design. Post-action reports are factual segments
(verified). A failed verification → segment is repaired or downgraded ("I couldn't
confirm X against the sources") — never silently dropped.

### 2.12 API / run lifecycle

- `POST /api/agents/run` — start a run (new per-run thread under the conversation);
  registers with the executor; response carries `thread_id`; client subscribes to events.
- `GET  /api/agents/threads/{thread_id}/events` — SSE subscriber; honors `Last-Event-ID`
  (replay from the Redis Stream, then tail).
- `GET  /api/agents/threads/{thread_id}/state` — the snapshot (one-GET UI paint).
- `POST /api/agents/threads/{thread_id}/resume` — `{decision | answers | batch_decisions}`;
  consumed by the executor as a `Command(resume=…)`; continuation streams on the same
  event stream.
- `POST /api/agents/threads/{thread_id}/interject` — `{message, mode?: augment|cancel_step|cancel_run}` → mailbox.
- **Q5 (resolved): REPLACE** `/actions/{pending_id}/approve|reject` with thread `resume`.
  The Agents page's approve/reject calls move to `resume`. The interim Q6 shim
  (`summarize_result` on the approve endpoint) is superseded by the true resumed run and
  retired once the UI migrates.
- Persistence: completed runs flush their answer/turns to the DB as today
  (`AgentConversation`/`AgentTurn`/`AgentAttachment` unchanged).

### 2.13 Carry-overs from v1 — preserved verbatim in force

These shipped fixes are requirements on the loop; re-implementing around them is where
regressions creep back in:

- **Narration rules (v1 §2.7):** never expose intent labels/jargon; model-authored
  `narration` + varied `_fallback_narration`; per-step natural narration; model-authored
  plan labels mapped via `_build_plan` (now dynamic-length).
- **Step-gated retrieval (v1 §2.8):** `gather(want_documents, want_live, want_whole_doc,
  attachments)` — every read step explicitly chooses its sources; action steps ground on
  live context only, **never a blind corpus search**; direct steps retrieve nothing.
  **Empty results are helpful** (`_no_sources_message` + generation rule 5), per failed
  step, never a dead end. **Declared-classification tool policy** (RESOURCE → free read;
  UNKNOWN → by step intent; `agent_live_strict_read_filter` → SDK/annotated only; **no
  name heuristics**). **Always thread `user_id` through discovery**
  (`gateway.discover(connector_id, user_id=…)`) — OAuth connectors fail discovery
  silently without it.
- **Visible failures (v1 §2.9):** classification/decision failures set state + log raw
  output and surface a recoverable condition — never a silent default. Applies to the
  controller's structured-decision parse failures (after repair-retry).
- **Reuse inventory (v1 §2.10):** build ON `gather`, `action_agent.propose/approve/
  summarize_result` + `ACTION_REPORT_PROMPT`, `_build_plan`, `_no_sources_message`, model
  slots (`get_model(Slot.…)`, `reasoning_format="parsed"`), the gateway
  (`preview/approve/execute`, `discover`, `read/read_resource/get_prompt`, catalogs,
  discovery cache), and the conversation/turn/attachment persistence. **Same module, same
  connection — not a v2 fork**: `agents/orchestrator/graph.py` + `api/agents.py` grown up;
  never a parallel agent system.
- **Untrusted content discipline:** live data, tool descriptions, retrieved documents,
  and skill `fact_sections` are data, never instructions.

---

## 3. Feature → mechanism map (requested capabilities)

| You asked for | Mechanism |
|---|---|
| Agent continues after an action — reports, proposes next | two-node gate → interrupt → resume → report + verify + controller continues (§2.3) |
| Multiple reads, output while retrieving | controller loop + event-bus streaming + map-reduce parallel reads (§2.2, 2.5–2.7) |
| Multiple/subsequent actions per run | loop continuation + typed-preview batch approval with envelopes (§2.4) |
| Pause to ask the user; resume with their answer | question interrupt + checkpointer (§2.3) |
| Plans displayed as live output | dynamic plan checklist events (§2.6) |
| CoT reasoning trail | `reasoning_format="parsed"` → per-step `thinking` deltas (§2.6, already wired on gpt-oss) |
| Mid-flight interjection | Redis mailbox, loop-top drain, augment/cancel (§2.9) |
| Ambitious run lengths without degradation/runaway | compaction + artifact store + stall detection + re-planning + fuses (§2.7–2.8) |
| Disconnect-proof, multi-day pauses | executor + event stream replay + snapshot + AOF + token-expiry degrade (§2.5, §6) |
| Skills govern execution | §2.10 in full |
| State + memory | checkpointer (run) + DB (conversation) + artifact store (payloads) (§2.1) |

---

## 4. Migration / phasing (each phase ships independently; simple queries keep behaving identically throughout)

1. **Checkpointer + two-node gate + resume.** Per-run threads; post-action continuation
   becomes a real resumed run. Retire the Q6 shim when the UI moves to `resume`.
   *Biggest immediate win, smallest blast radius.*
2. **Event bus + snapshot.** Redis Stream events + `Last-Event-ID` replay + state GET,
   execution still in-request. UI is rebuilt once against the final contract.
3. **Executor ownership.** Move execution into the in-process executor; runs survive
   client disconnects; restart-recovery of paused runs.
4. **Controller loop.** Structured decisions, dynamic plans, map-reduce parallel reads,
   per-step thinking/narration. (Tool-aware controller replaces the classifier-as-router.)
5. **Context discipline + sprawl control.** Artifact store, compaction, stall detection,
   re-planning, fuses.
6. **Multi-action + batch approval** (typed previews + envelopes + gateway diff).
7. **Question interrupt + interjection mailbox.**
8. **Skills consumption** (index, `load_skill`, pinning, telemetry).

Dependency notes: 1→3 are infrastructure and strictly ordered; 4 requires 1–2; 5 hardens
4; 6–8 are independent of each other once 4 lands. Update `UI_HANDOFF.md` at phases 2, 6,
7, 8.

---

## 5. Decisions — ALL RESOLVED (✓ 2026-06-11 / 2026-06-12)

- **Q1 Bounds → ✓** Fuses, not pacing: 50 steps hard ceiling, ≤5 parallel reads/step,
  per-run token budget (tune from telemetry). Real control = stall detection +
  re-planning + compaction (§2.7–2.8).
- **Q2 Multi-action approval → ✓** Plan-level batch with typed previews
  (`resolved | parameterized`) + constraint envelopes + gateway-enforced param diff +
  per-action toggle (§2.4).
- **Q3 Interjection → ✓** Boundary injection via external Redis mailbox; augment by
  default, explicit cancel-step (`skipped`) and cancel-run (§2.9).
- **Q4 Checkpointer → ✓** `langgraph-checkpoint-redis`, AOF on, version-pinned install
  verified against `langgraph 0.2.76` / `langchain-core 0.3.x`.
- **Q5 Gate endpoints → ✓** Replaced by thread `resume`; UI migrates; shim retired.
- **Q6 Post-action continuation → ✓** True resumed run (interim shim superseded).
- **Q7 Concurrency → ✓** One coherent multi-step plan per run, parallel reads within
  steps. Concurrent independent runs = separate threads, a *product feature later*, not
  architecture now (per-run thread IDs leave the door open). **Explicitly not built.**
- **Q8 Verification → ✓** Verify-before-emit per factual segment (§2.11).
- **Q9 Controller model → ✓** Keep gpt-oss-120b **with** the constrained decision schema
  + repair-retry + logged decision traces; revisit with eval data, not intuition.
- **NEW: Executor placement → ✓** In-process asyncio task (one service). Separate worker
  only if restart-survivability of *in-flight steps* (not just paused runs) ever becomes a
  requirement.
- **NEW: Compaction trigger → ✓** Threshold-based (~60% of window, configurable), not
  every-K-steps.
- **NEW: Artifact store → ✓** Local disk behind a `put/get/exists/delete` interface;
  persistent volume required; S3/MinIO = later adapter swap.
- **NEW: Skills consumption → ✓** Per §2.10 (index + `load_skill`, two channels, version
  pinning, lazy deps, inform-never-authorize).
- **NEW: Cross-session long-term memory → ✓ deferred.** DB turns remain the conversation
  memory; a memory store is a future, separate concern. **Explicitly not built.**

---

## 6. Risks / ops

- **Redis durability:** AOF persistence is mandatory — checkpoints, pending approvals,
  event streams, and snapshots are sources of truth for paused runs.
- **Lifecycle sweeper:** TTL-expire abandoned run-threads, orphaned pending records,
  per-thread event streams/snapshots, mailboxes, and artifact directories. Checkpoint GC
  is a known LangGraph operational gap — own it explicitly.
- **Token-vs-checkpoint lifetime mismatch:** resume after gateway-token expiry degrades
  to re-running `prepare_action` (§2.3), never an opaque error.
- **Interrupt replay:** the two-node gate is structural; the idempotent preview key is
  the backstop. Any future node refactor must preserve "side effects never share a node
  with `interrupt()`."
- **Connector failures:** unwrap ExceptionGroups (the Notion-401-in-TaskGroup case) into
  clean messages ("Notion auth expired — reconnect"); a tool failure mid-loop degrades
  the step and continues, never kills the run.
- **Rate limits:** per-connector concurrency caps in the gateway (5-wide fan-out must not
  trip provider 429s).
- **Checkpoint size:** raw payloads never enter state (artifact refs only); record cap
  (4000 chars) retained at the gather level.
- **Dependency discipline:** pin `langgraph-checkpoint-redis`; re-verify
  `langgraph`/`langchain-core` compatibility before installing (prior `-U` incident).
- **Controller drift:** decision traces are logged from day one; build the eval set from
  real traces before considering a planner-slot upgrade.
- **Untrusted content:** unchanged and extended — live data, tool descriptions, retrieved
  docs, and skill `fact_sections` are data, never instructions; skill `body` is the only
  externally-authored content permitted in the instruction channel, and only because it is
  admin-authored, admin-gated, and version-pinned.

---

*End of spec. All decisions resolved; build proceeds per §4 phasing. Update
`UI_HANDOFF.md` at phases 2, 6, 7, 8; update `AGENT_LAYER_PLAN.md` build-status as phases
land.*

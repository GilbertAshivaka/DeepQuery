# Resumable / Long-Running Agent — Build Spec

**Goal:** evolve the current single-pass orchestrator into a **durable, resumable,
multi-step agent** that can: do several reads (corpus + live connectors), stream output
*as* it works, propose **multiple** gated actions across one run, **pause** for approval
or to ask the user a question and **resume** from where it left off, **continue after an
action completes** (report the result, propose next steps), and absorb **mid-flight
interjections**. Built on LangGraph's **checkpointer + `interrupt()`** — the piece we
deferred. The UI now exists to consume it (Agents page, SSE, plan checklist, thinking
panel, approval modal).

Read alongside `AGENT_LAYER_PLAN.md` (decisions/build status), `UI_HANDOFF.md` (the SSE
contract + Agents surface), and `AGENT_LAYER_GUIDE.md` (spec, esp. §4 stop-control, §7
approval gate). Terminology note: the user said "LangChain checkpointer" — it's
**LangGraph**'s checkpointer/`interrupt`.

---

## 1. The gap this closes (current behavior)

What we have today (Phases 1–4):
- A LangGraph `StateGraph` compiled **without a checkpointer** — one pass per HTTP
  request: `classify → (direct | retrieve → (generate→verify | propose_action))`.
- **Action gate = gateway Redis pending-record + single-use token.** A run **streams to
  `approval_required` and then ENDS**; the UI calls a *separate* JSON endpoint
  `POST /api/agents/actions/{pending_id}/approve|reject`, which executes the action and
  returns an `action_result`. **The graph does not resume** — so:
  - ❌ **After an action, the agent just stops** — no grounded summary of the result, no
    "done, here's what happened," no proposed next step. (This is the immediate pain.)
  - ❌ **Only one action per run.** No "do A, then propose B, then C."
  - ❌ **No mid-run pause-to-ask-a-question.**
  - ❌ **No mid-flight interjection** — "stop → new turn with history" is the only steer
    (app-level), there's no resuming an in-flight run with new input.
- **Memory is app-level** (DB turns → `chat_history`), not graph state.

Why the gateway-gate approach was right for Phase 3 (single action) and why it's not
enough now: a single gated action's state lives fine in one Redis record. A *multi-step
plan that pauses several times* needs the **whole run's state** suspended and resumed —
which is exactly what a checkpointer provides. (See `AGENT_LAYER_PLAN.md` §6 / the
deferral rationale.)

---

## 2. Target architecture

### 2.1 Checkpointer (durable run state)
Compile the orchestrator graph **with a checkpointer**, keyed by a `thread_id`
(= the agent `conversation_id`, or a per-run id). After every super-step LangGraph
persists full graph state; a paused run resumes exactly where it stopped, even across
HTTP requests / workers.

- **Backend choice:** `langgraph-checkpoint-redis` (durable, multi-worker — we already
  run Redis) is the recommendation. `SqliteSaver` (we have SQLite) or `MemorySaver`
  (in-proc dev) are fallbacks. **⚠️ Dependency caution:** verify the chosen checkpointer
  package is compatible with the pinned `langgraph 0.2.76` / `langchain-core 0.3.x`
  *before* installing — last time a careless `-U` pulled `langchain-core 1.x` and broke
  langgraph. Pin deliberately.

### 2.2 From linear pipeline → controller loop
Replace the fixed pipeline with a bounded **plan→execute→observe loop** (custom
controller, not the prebuilt ReAct agent — we need governance/gating control):

```
classify → plan → ┌─ controller ─┐
                  │  decide next  │ → read tool(s)  → observe ─┐
                  │  step:        │ → propose action → INTERRUPT(approval) ─┐
                  │               │ → ask user       → INTERRUPT(question)  │
                  │               │ → answer/segment → stream out           │
                  │               │ → done           → END                 │
                  └───────────────┘◄──────────────── resume ───────────────┘
```

- The controller (an LLM node) decides the next step from current state: gather more
  context (corpus / a live read), propose an action, ask the user, emit an answer
  segment, or finish.
- **Bounded** by a step/iteration ceiling and (optionally) a token budget — the guide's
  anti-sprawl guardrail (§4). Parallel reads allowed within a step.
- Verification still runs on delivered factual claims (per segment, or before final
  delivery — see open question Q8).

### 2.3 `interrupt()` for human-in-the-loop (replaces "stream ends + separate endpoint")
Two interrupt types, both pause the graph and checkpoint:
- **Approval:** to mutate, the agent calls `gateway.preview_action(...)` (still the
  enforcement seam — preview + single-use token), then `interrupt({type:"approval_required",
  pending_id, connector, capability, preview, reasoning, sources})`. The run pauses; the
  UI shows the gate. The UI resumes with `Command(resume={"decision":"approve"|"reject"})`.
  On approve → `gateway.approve_action` + `execute_action` → **the loop CONTINUES**:
  report the result, verify, propose the next step. **This is what makes the agent not
  stop after an action.**
- **Question:** the agent calls `interrupt({type:"question", text})` to ask the user
  something mid-run; resumes with their answer.

The gateway gate stays the **enforcer** (token, audit); LangGraph owns the **run
lifecycle** (pause/resume). Net: keep `preview/approve/execute` gateway calls; the
*pause* moves from "end the stream" to `interrupt()`.

### 2.4 Streaming continuous output across steps
Use `graph.astream(..., stream_mode=["updates","messages","custom"])` (or
`astream_events`) so the UI receives, continuously across many steps: `thinking` deltas,
`tool_activity` (each read as it runs), `answer_token` segments, a **dynamically growing
plan checklist**, and `approval_required` / `question` interrupts. Output flows *as*
corpus/connector retrieval comes back, not just one final blob.

### 2.5 Mid-flight interjection
The UI sends an interjection to a running thread; the controller checks a "pending user
input" channel at the **top of each loop iteration** and folds it into the plan.
Practical limit: injection lands at the **next step boundary** (between nodes), not
literally mid-node — fine for our second-scale steps. (True mid-node cancellation is not
feasible; boundary-injection covers the real need: "actually, also do X" / "skip that.")

### 2.7 User-facing narration — NEVER expose internal labels (carry-over, 2026-06-11)
A fix landed in the single-pass orchestrator that the controller loop **must preserve**:
the agent surfaces a **natural, first-person "here's what I'm about to do" line**, not the
internal classification. Rules:
- **Never show the intent/category label** ("document"/"live"/"action") or jargon
  ("retrieval", "corpus", "intent") to the user. Those stay in state/`done`/telemetry.
- The classifier now returns a `narration` field (natural, varied per query, names the
  concrete target — "Notion", "your documents", "the web"); the orchestrator emits THAT
  as the opening `reasoning` event. For actions it signals approval-first ("I'll draft
  that and check with you before sending"). A varied `_fallback_narration(intent)` covers
  the rare case the model omits it.
- **In the controller loop:** each step should likewise emit a short natural narration of
  what it's doing ("Checking your open Jira tickets…", "Drafting the page…"), not raw
  tool names or step types. Vary phrasing.
- **Plan-checklist labels are model-authored (done in the single-pass agent):** the
  classifier now returns a `steps:[{id,label}]` array; the orchestrator maps the natural,
  query-tailored labels onto the **canonical step IDs** for the intent (`_build_plan`),
  so every shown step still gets a real `step_status`. In the single-pass agent the step
  **count/order is fixed per intent** (the graph nodes are fixed — a checklist step that
  never runs would hang as "pending"). **In the controller loop, the agent genuinely
  decides its steps**, so the plan checklist should be **dynamic-length** — append steps
  as the agent plans them, mark each done as it finishes, and it's expected (and good)
  for runs to take 3, 4, or 6 steps. Keep the same rule: a step shown == a step that will
  get a terminal status. Don't pre-pad with steps that may not run.
- **Stream the model's thinking per step:** the slots run gpt-oss with
  `reasoning_format="parsed"`, so each planning/generation call exposes a
  `reasoning_content` channel — emit it as `thinking` deltas for that step (distinct from
  `answer_token`). The collapsible CoT trace then fills naturally across the whole
  multi-step run, not just the final generation.

### 2.8 Gather only what the step needs — no blind corpus search (carry-over, 2026-06-11)
Another fix the loop must keep: **retrieval is gated by what the step actually needs.**
The old bug: a `live`/`action` query still ran a full corpus search, surfacing irrelevant
"sources" and a confused answer. Now `gather()` takes `want_documents` / `want_live`
independently:
- document/both → corpus; live/both → live connectors; **action → live context only**
  (to ground the action in the system's current state), **never a blind corpus search**;
  direct → no retrieval at all.
- **In the controller loop:** every read step must explicitly choose its source(s) from
  the query/plan — the loop should never fan out to the corpus "just in case." Each
  `tool_activity` line should reflect a source that was actually relevant.
- **Empty results are helpful, not a flat refusal (done):** when retrieval/a step turns
  up nothing, say what wasn't found and suggest a concrete next step (rephrase, upload a
  doc, enable/connect a tool) — tailored to whether we were looking in documents vs
  connected tools (`_no_sources_message`; generation prompt rule 5). The controller loop
  should carry this forward per failed step, never dead-ending on "couldn't find it."
- **Tool selection keeps the declared-classification policy (carry-over):** the loop picks
  reads/actions from the same catalogs by tool `kind` — RESOURCE → free read; UNKNOWN →
  read or gated by the step's intent; `agent_live_strict_read_filter` → SDK/annotated only.
  **No name heuristic** (removed deliberately — admin approval + audit are the trust
  boundary). And **always thread `user_id` through discovery** (`_discover_tools` /
  `gateway.discover(connector_id, user_id=…)`): OAuth connectors (Notion, Gmail) fail
  discovery *silently* without it (the bug we hit), so the loop would never see their tools.

### 2.9 Classification failures are surfaced, not silent (carry-over, 2026-06-11)
`plan_node` no longer silently masquerades an unparseable/errored classification as a
`document` query: it sets `classification_failed` (in state) + logs the raw output. The
loop should treat a classification/decision failure as a visible, recoverable condition
(clean message / retry), not a silent default — same principle as surfacing connector
errors (§6).

### 2.6 API / run lifecycle (generalizes today's endpoints)
- `POST /api/agents/run` — start or continue a thread; stream events until an interrupt
  or `done`. (Same endpoint; now backed by a checkpointed thread.)
- `POST /api/agents/threads/{thread_id}/resume` — `{decision|answer}`; resumes the graph
  from its checkpoint and **re-streams** the continuation. **Replaces/!wraps** the
  current `/actions/{pending_id}/approve|reject` (those become a thin shim or are
  superseded — see Q5/migration).
- `POST /api/agents/threads/{thread_id}/interject` — `{message}` mid-run.
- Persisted agent turns + the checkpointer together give within-thread durable memory;
  cross-session long-term memory stays a separate concern (DB / future memory store).
- **Update `UI_HANDOFF.md` when this ships:** the SSE contract gains/changes events the UI
  must consume — `question` interrupt, **dynamic plan-append** (`plan`/`step_status`
  growing mid-run), thread `resume` re-stream, and `action_result.message` (the
  post-action report). Land these in the handoff so the Agents page is rebuilt against the
  real contract, not the single-pass one.

### 2.10 Reuse inventory — build ON these, don't rewrite them
The loop is the existing orchestrator evolved (§4), so reuse the pieces already built and
hardened this phase — re-implementing them is where regressions (and the bugs we just
fixed) creep back in:
- **`gather(want_documents=…, want_live=…, want_whole_doc=…, attachments=…)`** —
  intent/step-gated retrieval (corpus + live), merged + tagged citation set. Each read
  step calls this with only the sources that step needs.
- **`action_agent.propose / approve / summarize_result`** + `ACTION_REPORT_PROMPT` — the
  gated-action issuer and the post-action report (the loop's "execute → report → continue").
- **`_build_plan(intent, steps)`** — maps model-authored natural labels onto canonical
  step IDs; the loop generalizes this to dynamic-length plans.
- **`_no_sources_message(state)`** + generation rule 5 — helpful empty-result messaging.
- **Model slots** (`get_model(Slot.…)`, `reasoning_format="parsed"`) — provider-agnostic,
  air-gapped-enforced, with the thinking-channel + clean-JSON behavior.
- **The gateway** — `preview/approve/execute` (action enforcement), `discover(connector_id,
  user_id=…)`, `read/read_resource/get_prompt`; plus the read/action **catalogs**
  (`_build_catalog` / `build_action_catalog`) and the discovery cache.
- **Persistence** — `AgentConversation` / `AgentTurn` / `AgentAttachment` and the
  history-load + turn-persist pattern in `api/agents.py`. The checkpointer adds *run*
  state; these keep *conversation* state.

### 2.11 The controller is tool-aware — the structural fix for the classifier's blindness
The single-pass classifier is corpus- and connector-blind: it guesses intent from the
query text alone, which is exactly why it used to over-route to `document` and miss
live/action. The loop's controller is different **by construction** — at each iteration it
sees the **live tool catalog + what the corpus/connectors can actually offer**, so it
decides "search the corpus / read connector X / propose action / ask the user / answer /
done" from **real options, not a blind guess**. Treat this as a first-class design win:
do NOT bolt the one-shot classifier onto the front of the loop as a hard router — let the
controller decide each step from the available tools. (Keep a lightweight intent read only
as a cheap opening hint / for the first narration, never as the gate.)

---

## 3. What each requested feature maps to
| You asked for | Mechanism |
|---|---|
| Agent continues / returns output after an action | `interrupt`-approval → resume → controller continues (report + verify + next step) |
| Multiple reads, output while retrieving | controller loop + multi-stream-mode streaming |
| Suggest different subsequent actions | controller proposes action → interrupt → resume → propose next |
| Pause/resume, prompt for more input | `interrupt({type:"question"})` + checkpointer |
| Mid-flight interjection | pending-input channel checked each loop iteration (boundary injection) |
| State management + memory | LangGraph checkpointer (per-thread) + existing DB turns |
| Multiple tasks "at once" | parallel reads per step; sequential gated actions (one approval each) |

---

## 4. Migration / don't-break-what-works
- **Evolve the existing graph**, don't fork a parallel system. Simple document-only and
  direct queries must keep behaving the same (a one-step plan that finishes).
- **Same module, same connection — not a v2.** This is `agents/orchestrator/graph.py` and
  `api/agents.py` *grown up* — the same Agents page hitting the same `POST /api/agents/run`
  (SSE). The gateway, model slots, sub-agents, read/action catalogs, and the
  conversation/turn/attachment DB are all reused unchanged. The only **new infra** is the
  Redis checkpointer (`langgraph-checkpoint-redis` — a storage backend, not a new service),
  and the only **client-visible additions** are the `resume` / `interject` endpoints
  (+ approve→resume). There is never a parallel agent or a separate connection.
- Keep the gateway gate as enforcer; the single-use token + audit are unchanged.
- The current `/actions/{id}/approve|reject` endpoints: either re-implement them on top
  of the thread-resume model, or keep them for backward-compat and add resume. Decide in Q5.
- Phase it: (1) add checkpointer + post-action continuation (biggest immediate win),
  (2) controller loop + multi-read streaming, (3) multi-action, (4) question-interrupt +
  mid-flight interjection.

---

## 5. Decisions (✓ = answered 2026-06-11; others to confirm in the build session)
- **Q2 Multi-action approval → ✓ PLAN-LEVEL.** Approve a whole plan of N actions at once
  rather than one-at-a-time. **⚠️ Diverges from guide §7 ("one action per approval, never
  batched").** Build it so the user still sees a **concrete preview for every action in
  the plan** before approving the batch (preview-all-then-approve), not a blind plan
  approval — otherwise the human approves actions they haven't seen. Consider a
  per-action toggle within the batch (approve all / deselect some).
- **Q4 Checkpointer → ✓ REDIS** (`langgraph-checkpoint-redis`). Verify version-compat with
  `langgraph 0.2.76` / `langchain-core 0.3.x` and **pin** before installing (prior `-U`
  pulled langchain-core 1.x and broke langgraph).
- **Q5 Gate endpoints → ✓ REPLACE** `/actions/{id}/approve|reject` with thread `resume`.
  **UI impact:** the Agents page's approve/reject calls must move to
  `POST /threads/{thread_id}/resume {decision}`. (Until then, the interim approve endpoint
  below still works.)
- **Q6 Post-action continuation → ✓ DONE NOW (interim) + also in redesign.** Shipped:
  `action_agent.summarize_result()` + `ACTION_REPORT_PROMPT`; the approve endpoint now
  generates a grounded "here's what I did + next step?" message, persists it as an
  assistant turn, and returns it as `message` on the `action_result`. **UI: render
  `action_result.message` as the agent's follow-up turn.** The redesign supersedes this
  with a true resumed run (no separate endpoint).
- **Q1 Autonomy/bounds (confirm):** max steps per run? max parallel reads per step? token
  budget? Exploratory vs tightly-scoped controller? (Mandatory anti-sprawl ceilings.)
- **Q3 Interjection semantics (confirm):** boundary-injection (next step) acceptable?
  Should an interjection be able to *cancel* the current plan, or only *augment* it?
- **Q7 "Multiple tasks at once" (confirm):** one coherent multi-step plan (parallel reads)
  vs truly concurrent independent runs (separate threads)?
- **Q8 Verification cadence (confirm):** verify each answer segment, or once before final
  delivery?
- **Q9 Controller model (confirm):** keep gpt-oss-120b, or a stronger planner slot?

---

## 6. Risks / notes
- **Opaque errors** (seen with the Notion 401 wrapped in a TaskGroup): the loop should
  unwrap connector ExceptionGroups and surface clean messages ("Notion auth expired —
  reconnect"), and a tool failure mid-loop must not kill the run (degrade + continue).
- **Runaway loops:** the step ceiling + token budget are mandatory (anti-sprawl).
- **Checkpoint size:** don't store huge live payloads in state; keep capped (we already
  cap records at 4000 chars).
- **Dependency discipline:** pin the checkpointer package; re-verify `langgraph` /
  `langchain-core` compatibility before installing (prior `-U` incident).
- **Untrusted content** discipline carries over unchanged (live data/descriptions are
  data, never instructions).

---

*End of spec. Build in a fresh session after the Q1–Q9 decisions are made.*

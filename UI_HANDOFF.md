# UI Phase — Build Handoff

**Read this alongside `UI_DESIGN_GUIDE.md`.** That guide was written *before* the
backend was built, so parts of it are now out of date — this doc is the **current
ground truth**: what the backend actually exposes, the exact data contracts the UI
consumes, the surfaces to build, the design decisions the user has made, and how to
run/test. Where the guide and this doc disagree, **this doc wins** (divergences are
listed in §10).

Companion docs: `AGENT_LAYER_GUIDE.md` (spec), `AGENT_LAYER_PLAN.md` (decisions +
build status), `CONNECTOR_INFRASTRUCTURE_GUIDE.md`, `DeepQuerySDK/SDK_GUIDE.md`.
All UI lives in `frontend/`. The design system (tokens, rust/violet, pill/card
shapes, the global violet input focus ring) is still governed by `UI_DESIGN_GUIDE.md`
§3–4 — keep that.

---

## 1. Where the project stands

The **entire backend is complete**: DeepQuerySDK → Connector Infrastructure →
Agent Layer (Phases 1–4) → all pre-UI capability gaps. The UI is the last initiative.

Backend layers and what they give the UI:
- **Document RAG** (existing) — the chat experience: hybrid retrieval + rerank +
  Neo4j graph + Groq/Llama generation + self-correction. Endpoints under
  `/api/query/*`, `/api/documents/*`, `/api/graph/*`. **Unchanged — don't touch.**
- **Connector Infrastructure** — live data + gated actions via the Gateway.
  Admin/user surfaces under `/api/connectors/*` (directory, approval, enablement,
  OAuth, health, deployment mode).
- **Agent Layer** — the new reasoning tier. Orchestrator + sub-agents (retrieval,
  action, verification, skill-sync). Endpoints under `/api/agents/*` and
  `/api/skills/*`.

Models: the agent layer runs on **`openai/gpt-oss-120b` via Groq** (all slots);
chat still uses Groq/Llama. (Configurable per deployment.)

---

## 2. Two distinct surfaces: Chat vs Agents (left-sidebar tools)

**Chat and Agents are different pages.** DeepQuery's left sidebar is a list of tools;
the Agents page is a **new sibling** alongside the existing ones:

```
DeepQuery left sidebar (tools)
├─ New chat            → Chat page          (/api/query/*)         [exists]
├─ Search             → structured search   (/api/query/search)    [exists]
├─ Knowledge graph    → graph explorer      (/api/graph/*)         [exists]
├─ Agents      ★NEW    → Agents page         (/api/agents/*)
└─ (admin) Connectors, Skills                (/api/connectors, /api/skills)
```

- **Chat page**: the existing document Q&A chat. Keep its behavior. (It gains one
  new thing only — attachment viewing UX, §6, since chat may show images/docs.)
- **Agents page** ★: a **separate** conversational surface that drives `/api/agents/run`
  (SSE). It shows the **plan checklist**, the **streaming answer**, the **collapsible
  thinking/CoT trail**, **multi-source citations**, the **approval-gate modal**, and
  **attachments**. It has its **own conversation history** (separate from chat), its
  own `+`-attach input, etc. Do **not** route the Agents page through the chat flow.

The UI guide assumed the agent plan/progress would render *inline in the chat thread*
(§7). **That is superseded** — the user has decided Agents is its own page.

---

## 3. The Agents run stream — the core contract the UI consumes

`POST /api/agents/run` (auth: Bearer JWT) returns **SSE** (`text/event-stream`).
Request body:
```json
{ "query": "string",
  "conversation_id": "optional — omit to start a new conversation",
  "attachment_ids": ["optional ids from /attachments upload"] }
```
Each SSE frame is `data: {json}\n\n`. Event types and shapes (render each):

| `type` | payload | UI treatment |
|---|---|---|
| `plan` | `{steps:[{id,label,status}]}` | the **todo checklist** (Claude-Code style). statuses: `pending`/`running`/`done`/`awaiting-approval`. Plans differ by intent (doc: search→generate→verify; action: gather→propose→await approval; direct: single "answer" step). |
| `step_status` | `{id, status}` | update one checklist step's state |
| `thinking` | `{content}` | **streamed model chain-of-thought deltas** (gpt-oss reasoning channel) — the **Anthropic-style collapsible thinking block**. Append deltas as they arrive; distinct from the answer. |
| `reasoning` | `{text}` | the orchestrator's **structured** narration (intent, "synthesizing from N sources", "checking each claim", action rationale). Complements `thinking` in the CoT panel. |
| `tool_activity` | `{tool, detail, status}` | quiet activity line ("document_search · 5 passages", "deepwiki:read_wiki_contents · 1 live record", "document_expand · loaded full text of X"). |
| `citations` | `{citations:[…]}` | the source chips (§7). Emitted once after retrieval; may include all 4 source kinds. |
| `answer_token` | `{content}` | **append** to the streaming answer (many small deltas — true token streaming). |
| `approval_required` | `{pending_id, connector, capability, preview, reasoning, sources:[citations]}` | open the **approval-gate modal** (§8). The run stream **ends** after this; resume via the approve/reject endpoints. |
| `verification_result` | `{outcome, corrected_answer, explanation}` | outcome ∈ `VERIFIED`/`CORRECTED`/`INSUFFICIENT_CONTEXT`. Show a small verification badge; if `CORRECTED`, the corrected answer is the authoritative one. |
| `done` | `{conversation_id, answer, intent, citations, verification, proposed_action, grounded}` | terminal. `conversation_id` is the thread to reuse for follow-ups. `grounded:false` = a direct/general-knowledge answer (see §5 — do **not** badge it as "ungrounded"; the user finds that nagging). |
| `error` | `{message}` | show a calm error; the rest of the answer (if any) still stands. |

**Notes for the UI:**
- A typical doc run emits: `reasoning`→`plan`→`step_status`(retrieve running)→
  `tool_activity`→`citations`→`step_status`s→`reasoning`→`answer_token`×N→
  `step_status`→`reasoning`→`verification_result`→`step_status`→`done`.
- An **action** run ends at `approval_required` (no answer tokens) until the human decides.
- A **direct** run: `reasoning`→`plan`(single step)→`step_status`→`reasoning`→
  `answer_token`×N→`done` (no retrieval/citations/verify).

---

## 4. Conversation memory (the Agents page history)

Agent conversations are persisted and **separate from chat**:
- `GET /api/agents/conversations` → `[{id,title,turns,created_at,updated_at}]` (sidebar/history list for the Agents page).
- `GET /api/agents/conversations/{id}` → `{id,title,turns:[…]}` where each turn has
  `role, content, intent, citations, grounded, verification_status, proposed_action,
  attachments:[{id,filename,kind}], created_at`. **Use this to rehydrate a conversation,
  including the attachments the user added** (§6).
- `DELETE /api/agents/conversations/{id}`.
- Follow-ups: pass the same `conversation_id` to `/run` — the backend loads prior
  turns as memory automatically (the UI just needs to keep using the id from `done`).

**Stop / steer:** to stop a run, the UI simply **aborts the SSE fetch** (close the
`EventSource`/`fetch` reader). The backend cancels the run; the user's message is kept,
the assistant turn is not saved. To "add context / steer", send a new `/run` with the
same `conversation_id` and the added input — prior context comes along. (True
mid-flight interject — injecting while the agent runs — is intentionally **not**
supported yet; "stop → new turn" covers it for these short runs.)

---

## 5. Thinking / CoT display (Anthropic style)

The user wants the **Anthropic-style collapsible "thinking" block**: a quiet,
collapsed-by-default panel that the user can expand to watch the agent reason, with
content **streaming in** as the run progresses.

- **Data source (real model CoT now streams):** the panel is fed by **`thinking`
  events** — the model's actual chain-of-thought, streamed token-by-token from gpt-oss's
  reasoning channel (`reasoning_format="parsed"` on the Groq slots → a separate
  `reasoning_content` stream; the answer `content` is kept clean). Render `thinking`
  deltas as the collapsed-by-default, expandable Anthropic-style block. Complement them
  with the orchestrator's **`reasoning`** events (structured narration) and optionally
  `tool_activity`/`step_status` for richer detail.
- The **plan checklist** (`plan`/`step_status`) is a separate, always-visible element
  (the todo list); the thinking panel is the deeper, collapsible CoT trail.
- **Provider note:** the streamed CoT comes from **gpt-oss via Groq** (`parsed` mode;
  no `<thinking>` tags — gpt-oss returns reasoning as a structured field, raw/tag mode is
  unsupported for it). **Gemini 2.5 Flash does *not* expose a thinking channel** through
  the currently-installed `langchain-google-genai` — if/when the Gemini multimodal path
  lands, surfacing Gemini thoughts would need a newer lib or the raw `google.genai` SDK
  with `thinking_config`. So expect `thinking` events on the gpt-oss slots; a Gemini slot
  may emit none until that work is done.
- **Grounding:** `done.grounded === false` marks a general-knowledge (direct) answer.
  Per the user's explicit decision, **do not show a "not grounded / general knowledge"
  badge** — it nags. The distinction can live subtly (e.g. simply the absence of
  citations) or in the reasoning trail; no warning label.

---

## 6. Attachments (uploads, the input UX, and viewing)

Users can attach **documents** (pdf/docx/html → parsed to text) and **images**
(stored; see the multimodal note in §11) to an agent query.

**Backend contract:**
- `POST /api/agents/attachments` — **multipart** (`file`, optional `conversation_id`
  form field) → `{id, filename, kind, chars}` (`kind` ∈ `document`|`image`).
- `POST /api/agents/run` with `attachment_ids:[…]` — the agent uses them this turn and
  links them to the turn (persisted).
- `GET /api/agents/attachments/{id}` → metadata + **`extracted_text`** (for a document
  viewer).
- `GET /api/agents/attachments/{id}/content` → the **raw file**, served **inline**
  (correct `Content-Type`) — use directly as an `<img src>` for images, or embed in an
  `<iframe>`/PDF viewer for documents.
- Attachments come back per turn from `GET /conversations/{id}` so a **reloaded
  conversation still shows them**.

**Input UX (user's spec):**
- A **`+` button** on the chat/agent input signals "add attachments".
- When a file is added, show it as a **chip just above the text input**, each chip with
  an **`×`** to detach it (before sending). On send, upload (or pre-upload on add) and
  pass the resulting `attachment_ids` to `/run`.

**Viewing (user's spec):**
- **Images** → previewed **inline on the page** (chip → thumbnail/lightbox via the
  `/content` URL).
- **Documents** → opened in a **viewer**. Recommended: an **Anthropic-Claude-style
  right-hand side panel** that slides in on the page (keeps the conversation in view),
  rendering the PDF (`/content` in an iframe) or the parsed text (`extracted_text`).
  A modal or dedicated page are acceptable alternatives — the side panel resonates best
  with Claude's file/artifact panel. (Backend support for this is now in place — the two
  `attachments/{id}` GET endpoints above.)

This input + viewer UX applies to **both** the chat page (which may surface images/docs)
and the Agents page.

---

## 7. Citations — now FOUR source kinds (guide §5 said two)

Citations arrive in the `citations` event and in `done.citations`. Each carries a
**`source_type`** — render each distinctly:

| `source_type` | key fields | chip treatment |
|---|---|---|
| `document` | `source_number, document_name, page_number, chunk_summary, document_id, relevance_score` | the existing rust `[Source N]` chip (stable) |
| `document_full` | `doc_number, document_name, document_id` | a **full-document** chip `[Doc N]` (whole doc pulled in) — rust family, marked as "full document" |
| `live` | `connector_name, retrieved_at, title_or_label, source_object_id, deep_link, mutability_note, is_synthesized` | the **live** chip `[Live N]` — violet-family + clock/"as of {time}" + connector name; click → `deep_link` when present (UI guide §5) |
| `attachment` | `attachment_number, filename` | an **attachment** chip `[Attachment N]` — distinct (user-provided), opens the viewer (§6) |

Inline markers in answer text use `[Source N]`, `[Doc N]`, `[Live N]`, `[Attachment N]`.
The "Sources" section should group by kind (Documents / Full documents / Live / Attached).

---

## 8. Approval-gate modal (the highest-stakes surface — UI guide §6 still applies)

When an agent proposes an action, the run stream emits **`approval_required`** and ends.
Render the modal (UI guide §6 visual spec holds):
- **What** — `preview` (verbatim, the literal action/payload, boxed and prominent).
- **Why** — `reasoning`.
- **On what basis** — `sources` (citation objects; render with the §7 chips).
- **Controls** — Approve (rust primary) / Reject (neutral), one action per modal,
  never auto-confirm.

Resolve via (these return JSON, not SSE):
- `POST /api/agents/actions/{pending_id}/approve` → `{type:"action_result", status:"executed"|"failed", result|error}`.
- `POST /api/agents/actions/{pending_id}/reject` → `{type:"action_result", status:"rejected"}`.

Approve = it executes once (the backend mints the single-use token + executes).
States to show: pending → approving → executed / rejected / failed.

---

## 9. Admin surfaces (Connectors + Skills)

**Connectors** (UI guide §8–11, §14) — endpoints under `/api/connectors/*`:
directory (`GET /directory`, admin), approval queue (`POST /{id}/approve`,
`DELETE /{id}/approve`), user enablement (`GET /available`, `POST /{id}/enable`,
`DELETE /{id}/enable`), OAuth handoff (`POST /{id}/auth/start`, `GET /auth/callback`),
static credentials (`POST /{id}/credentials`), health (`GET /{id}/health`),
deployment mode (`GET /deployment-mode`). Build per the guide.

**OAuth auto-configuration (new — "paste a URL").** For spec-compliant MCP servers the
admin should *not* hand-enter authorize/token endpoints, scopes, or client id/secret.
After registering a connector (http transport + its URL), call
**`POST /api/connectors/{id}/oauth/autoconfigure`** `{scopes?, client_name?}` — the
backend runs the OAuth 2.1 discovery chain (401 → RFC 9728 resource metadata →
RFC 8414 server metadata) and, when the server supports **Dynamic Client Registration**
(Linear/Notion/Asana/Sentry — verified live), registers a public PKCE client
automatically and stores the full `auth_config` (secret, if any, encrypted server-side —
**never returned**). Response: `{authorize_endpoint, token_endpoint, scopes,
supports_dcr, client_id, needs_manual_client, message}`. If `needs_manual_client: true`
(the 🔐 servers — GitHub/Atlassian/Box, no DCR), the discovered endpoints + scopes are
already stored; the UI then shows **only** the client id/secret fields (pre-filled
endpoints) for the manually-created OAuth app. **UX:** the "Add connector" form should
default to *just a URL + Auth method*; the manual OAuth fields (authorize/token/scopes/
client) become a fallback shown only when `needs_manual_client` is true. The existing
`begin/complete` PKCE flow then works unchanged on the auto-configured connector.

**Skills** (UI guide §12–13) — endpoints under `/api/skills/*` (admin):
- `GET /api/skills`, `POST /api/skills` (create from fields or pasted `markdown`),
  `GET /api/skills/{id}` (body + `fact_sections` + `versions` + `dependencies`),
  `POST /api/skills/{id}/rollback` `{version_no}`, `POST /api/skills/{id}/dependencies`.
- **Skill-diff review** (the §12 surface): `GET /api/skills/proposals?status=pending`
  → each `{id, skill_id, fact_section, old_content, new_content, trigger_document_id,
  trigger_summary, confidence, status}`. Render the **before/after diff** (old→new),
  the **trigger** (which document changed + `trigger_summary`), and the **confidence**
  badge (`explicit` = high / `inferred` = "review carefully"). Controls:
  `POST /api/skills/proposals/{id}/approve` (writes a new reversible version) /
  `POST /api/skills/proposals/{id}/reject`. Plus version history + rollback (§13).
- A skill file has two content kinds — **human-intent `body`** (off-limits to sync) and
  **`fact_sections`** (sync-maintained). Distinguish them visually (guide §13).

---

## 10. Divergences from `UI_DESIGN_GUIDE.md` (the guide predates the backend)

1. **Agents is its own page**, not an inline-in-chat progress display (guide §7).
2. **Four citation source-types**, not two (guide §5 had document + live). Add
   `document_full` ([Doc N]) and `attachment` ([Attachment N]).
3. **Direct/general-knowledge answers** exist (no retrieval) — `done.grounded=false`.
   **No "ungrounded" badge** (user decision); citations simply absent.
4. **Attachments** are a first-class feature (upload, chip+×/＋ input, inline image
   preview, document side-panel viewer) — not in the original guide.
5. **Agent conversation history** is a distinct store from chat history.
6. **Thinking/CoT** now streams the model's **real** chain-of-thought via `thinking`
   events (gpt-oss `parsed` reasoning channel), complemented by structured `reasoning`
   events — see §5.
7. Models are **gpt-oss-120b via Groq** (agent) — any "model picker" should read
   `GET /api/agents/health` (`model_slots`, `capabilities`, `deployment_mode`).

Everything else in the guide (tokens, the violet focus ring, calm/rust-led aesthetic,
the approval-modal visual spec, connector/skill screens) still applies.

---

## 11. Run, test, auth, gotchas

- **Start backend** (Docker infra — Redis/Chroma/Neo4j — must be up; not the server):
  ```
  cd backend
  venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8723
  ```
  (Port 8000 is blocked on this machine — Hyper-V reserved range; use 8723 or similar.
  `main.py` now forces UTF-8 stdout, so no encoding env vars needed.)
- **Auth**: `POST /auth/login` `{username,password}` (seeded admin: `admin` / `admin1234`)
  → `access_token`; send `Authorization: Bearer <token>`. SSE: use `fetch` with the
  header and read the stream (EventSource can't set headers — use `fetch` + a reader, or
  pass the token another way).
- **CORS**: `settings.cors_origins` includes `localhost:5173` (Vite) + `:3000`.
- **Interactive API docs**: `http://127.0.0.1:8723/docs`.
- **Roles** are opaque strings (`student/researcher/.../admin`) — don't hard-code the
  academic taxonomy; admin-only surfaces (connectors directory/approval, skills) require
  the `admin` role.
- **Multimodal/images note**: image attachments are **stored** but not yet sent to the
  answer model (gpt-oss-120b is text-only). The image-to-model path is a planned backend
  add (a Gemini multimodal generation path). Images can still be **viewed** in the UI now
  via `/content`. (User is on the Gemini free tier — 20/day, 5/min — so this is later.)
- **Dev DB test artifacts** (harmless): demo skills `policy-bot`/`marine-research-assistant`,
  an `HR-Leave-Policy.pdf` Document row, and enabled `demo-tickets`/`deepwiki` connectors.

---

## 12. Component inventory for the UI session (build order suggestion)

Shared first (reused everywhere): the **input field** with the violet focus ring, the
**modal/side-panel shell**, the **citation chip** (4 variants), the **connector card**.

Then, roughly:
1. **Agents page shell** — conversation list (own history), the SSE run loop, streaming
   answer, the **plan checklist**, the **collapsible thinking/CoT panel**.
2. **Attachments** — `+` button, chips-with-× above the input, image inline preview,
   document **side-panel viewer**; wire upload → `attachment_ids` → run; rehydrate from
   conversation detail.
3. **Multi-source citation chips** (§7) + grouped Sources section.
4. **Approval-gate modal** (§8) — test approve + reject end to end.
5. **Connector** directory / approval queue / enablement / OAuth (§9, guide §8–11).
6. **Skills** management + **skill-diff review** (§9, guide §12–13).
7. Chat-page attachment viewing (images inline, docs in the side panel) — reuse #2.

More UI details (exact layouts, side-panel vs modal final call, etc.) will be decided
live in the UI session.

---

*End of UI Handoff. The backend is feature-complete; this is the last initiative.*

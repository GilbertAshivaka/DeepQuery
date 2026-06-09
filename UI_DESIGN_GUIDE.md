# Deep Query — UI & Design Guide
**Build Guide & Reference — Frontend Design System & New Surfaces**
*This document codifies the Deep Query design system as tokens, then specifies the new frontend surfaces the connector and agent layers require, all in the established visual language. It is referenced by `CONNECTOR_INFRASTRUCTURE_GUIDE.md` and `AGENT_LAYER_GUIDE.md`, which name these components but defer their visual treatment here. All UI lives in the `frontend/` folder. No application code is included.*

---

## Table of Contents

1. [Purpose & Position](#1-purpose--position)
2. [Design Principles](#2-design-principles)
3. [Design Tokens](#3-design-tokens)
4. [The Global Input Focus Rule](#4-the-global-input-focus-rule)
5. [Citation System — Document vs Live](#5-citation-system--document-vs-live)
6. [The Approval-Gate Modal](#6-the-approval-gate-modal)
7. [Agent Plan / Progress Display](#7-agent-plan--progress-display)
8. [Connector Directory & Browser](#8-connector-directory--browser)
9. [Admin Approval Queue](#9-admin-approval-queue)
10. [User Connector List & Enablement](#10-user-connector-list--enablement)
11. [OAuth Consent Handoff](#11-oauth-consent-handoff)
12. [Skill Diff Review Screen](#12-skill-diff-review-screen)
13. [Skill File Management](#13-skill-file-management)
14. [Connector Health & Error States](#14-connector-health--error-states)
15. [Accessibility & Consistency](#15-accessibility--consistency)
16. [Component Inventory & Build Roadmap](#16-component-inventory--build-roadmap)

---

## 1. Purpose & Position

Deep Query already has an established, distinctive visual language — warm, calm, document-tool feel, with a rust/terracotta primary and a sparing violet accent. The connector and agent layers introduce many new surfaces (approval modals, connector directories, skill-diff reviews). This guide ensures every one of them looks and behaves like it was always part of Deep Query, rather than a bolted-on admin panel.

It is built **last**, after the three backend layers, because the components here consume data contracts defined in those guides (citation objects, approval payloads, connector manifests, skill-diff objects). The backend can be built and tested headless; this guide turns those contracts into the human-facing surface.

> **Source of truth:** the tokens in Section 3 are inferred from the live product (the Knowledge Graph page, the chat interface, and the focused-input state). Where a value is approximate, it is marked. During build, wire these to the real design-system values and correct any approximations.

---

## 2. Design Principles

1. **Calm over flashy.** Low contrast, generous whitespace, warm neutrals. This is a tool people work in for hours; it should feel quiet and trustworthy, not like a marketing dashboard.
2. **Rust leads, violet accents.** The terracotta primary carries identity and primary actions. Violet appears only for emphasis and interaction (user messages, the send button, and the focus state on all inputs). Violet is a seasoning, not a base.
3. **Groundedness is visible.** The UI must make it obvious what a claim is grounded in — and must visually distinguish a *stable* document source from a *live, may-have-changed* source. Trust is a design output here, not just a backend property.
4. **Safety reads as clarity.** The highest-stakes surface — the approval-gate modal — must make the consequence of an action unmistakable. Clarity is the safety feature.
5. **Consistency is inheritance.** New components reuse existing tokens and patterns (pill shapes, citation chips, the input focus ring) rather than inventing new ones.

---

## 3. Design Tokens

> Values inferred from screenshots; treat hex codes as close approximations to be reconciled with the real design-system file during build.

### Color — base / neutral
| Token | Approx. value | Usage |
|---|---|---|
| `--bg-canvas` | `#F7F1E8` (warm cream) | Main content background |
| `--bg-sidebar` | `#EADBC8` (deeper tan) | Left sidebar |
| `--bg-surface` | `#FFFFFF` / very light cream | Cards, modals, raised surfaces |
| `--bg-muted` | `#F0E6D8` | Subtle row shading, secondary surfaces |
| `--text-primary` | `#2B2622` (warm near-black) | Body text |
| `--text-secondary` | `#6B5F52` (warm grey-brown) | Secondary text, captions |
| `--text-muted` | `#9A8C7C` | Placeholders, disclaimers, hints |
| `--border-subtle` | `#E0D4C3` | Dividers, card borders |

### Color — primary (rust / terracotta)
| Token | Approx. value | Usage |
|---|---|---|
| `--primary` | `#A6431E` (rust/terracotta) | Wordmark, primary buttons, active nav, citation chip numerals |
| `--primary-hover` | slightly darker rust | Hover state on primary |
| `--primary-soft` | `#F3D9C9` (soft peach) | Active nav pill background, soft primary fills |
| `--focal-ring` | `#D9381E` (warm red) | Knowledge-graph focal-entity ring |

### Color — secondary accent (violet)
| Token | Approx. value | Usage |
|---|---|---|
| `--violet` | `#7C5CE6` | Send button, input focus ring, emphasis interactions |
| `--violet-soft` | `#E8DEF8` (lavender) | User message bubble fill, focus glow |
| `--violet-hover` | slightly deeper violet | Hover on violet controls |

### Color — semantic (Knowledge Graph node palette)
| Token | Value (from legend) | Entity type |
|---|---|---|
| `--node-person` | purple | Person |
| `--node-concept` | green | Concept |
| `--node-organisation` | blue | Organisation |
| `--node-document` | amber/orange | Document |
| `--node-location` | red | Location |
| `--node-event` | violet | Event |

> These semantic colors are reused anywhere entity types appear — graph, entity detail, citation context — for consistency.

### Radius
| Token | Approx. value | Usage |
|---|---|---|
| `--radius-pill` | 9999px | Buttons, chips, nav items, input fields |
| `--radius-card` | 12–16px | Cards, modals, panels |
| `--radius-control` | 8–10px | Small controls, send button square |

### Typography
| Token | Treatment | Usage |
|---|---|---|
| `--font-brand` | monospace / slab | "DeepQuery" wordmark only |
| `--font-body` | clean sans-serif | Everything else |
| Scale | calm, moderate | Headings restrained; body comfortable; captions in `--text-secondary`/`--text-muted` |

### Spacing & elevation
- Generous padding inside cards and modals; airy line-height in answer text.
- Low, soft shadows for raised surfaces (modals, dropdowns); avoid hard or heavy drop shadows — keep the calm feel.

---

## 4. The Global Input Focus Rule

**This is a system-wide behavior, not a per-component decision.** Every text input, search field, and interactive entry control in Deep Query — existing and new — adopts the same focus treatment seen on the chat input:

- **Resting state:** subtle `--border-subtle` border, `--text-muted` placeholder, `--bg-surface` fill, `--radius-pill` (or `--radius-card` for multi-line).
- **Focused state:** border switches to `--violet`, with a soft `--violet-soft` glow/ring around the field. This is the single, consistent signal that a field is active.
- Associated submit affordances (e.g. the send button) may pick up `--violet` in their active state to echo the focus.

Applies to: the chat input, the connector directory search, OAuth/credential entry fields, admin search boxes, skill-file search, any filter inputs, and every future input. Implement it once as a shared input component/style and inherit everywhere — never re-style inputs ad hoc.

> Rationale: the violet focus ring is a recognizable, learned signal in the product. Reusing it everywhere makes the whole interface feel unified and makes "where am I typing" instantly legible.

---

## 5. Citation System — Document vs Live

Deep Query already renders document citations: inline `[Source N]` markers, a "Sources:" breakdown, and rust-accented numbered citation chips (numeral in a rust circle, document name in a pill). The connector layer adds **live citations**, which must sit alongside these **while being visually distinct**, because the user must instantly know which facts are stable and which are a live snapshot that may have changed.

### Document citation (existing — keep as is)
- Inline marker: `[Source N]`.
- Chip: rust numeral circle + truncated document name, pill-shaped, `--bg-surface` with `--border-subtle`.
- Stable; no timestamp.

### Live citation (new)
- **Visually differentiated** from document chips so the distinction is pre-attentive. Recommended differentiation (pick a consistent scheme during build):
  - A **live indicator** — e.g. a small "live"/clock glyph and/or a violet-tinted (not rust) accent on the chip, so document = rust, live = violet-family. This reuses the existing accent system to encode meaning.
  - The **connector name** as the source label (e.g. "Jira", "Slack") instead of a filename.
  - A **retrieval timestamp** shown on the chip or its tooltip: "as of 14:32".
  - An optional **mutability note** in the tooltip ("live status field — may have changed").
- Inline marker may distinguish live sources (e.g. `[Live 1]` vs `[Source 1]`) or share numbering with a distinct chip style — choose one scheme and apply consistently.
- Clicking a live chip opens the deep link to the source object where available.

### Combined source list
When an answer draws on both, the "Sources" section groups or clearly labels the two kinds — document sources (stable) and live sources (with timestamps) — never blending them into an undifferentiated list. The chat answer body and the source list use the same distinction scheme.

> Design intent: a reader skimming an answer should be able to tell, without reading the source list, which sentences rest on stable documents and which rest on live data. The accent-color distinction (rust vs violet-family) carries that meaning.

---

## 6. The Approval-Gate Modal

**The single most important new surface in Deep Query.** It is the human checkpoint before any external state change. Its job is to make the consequence of an action unmistakable so a person can confidently approve or reject. Clarity here *is* the safety mechanism.

### Required contents (from the Agent Layer guide)
1. **What will happen — the concrete preview.** Not "send a message" but the exact payload and exact target: "Send this message: '…' to #research-marine in Slack." The preview comes verbatim from the connector's `preview` method.
2. **Why — the agent's reasoning.** A short statement of why the agent proposes this action.
3. **On what basis — the cited source(s).** The specific document or live source the agent is acting on, rendered with the citation system from Section 5. This is what lets a human catch an action founded on a misread.
4. **Explicit controls:** a clear **Approve** (primary, rust) and **Reject** (secondary/neutral) — never defaulted, never auto-confirmed. One action per modal; no bundling.

### Visual treatment
- A focused, centered modal on a dimmed canvas; `--bg-surface`, `--radius-card`, soft elevation.
- Clear hierarchy: the **action preview** is the visual focus (largest, boxed, unambiguous). Reasoning and sources are secondary supporting context below it.
- The previewed payload sits in a distinct boxed region so the user sees exactly the literal content/target — e.g. the message text rendered as it will be sent.
- **Approve** uses `--primary` (rust); it is deliberate, not pre-selected. **Reject** is neutral and equally reachable. Avoid making approve the path of least resistance — the user should make a real choice.
- If the action targets a live source that has a timestamp, show it, so the user knows how fresh the basis is.

### States
- **Pending:** awaiting decision; controls active.
- **Approving:** brief in-flight state after Approve (token issued, `execute` running).
- **Rejected:** confirmation that nothing happened.
- **Failed:** if `execute` fails downstream, a clear error — the action did not complete.

> Design rule: never let an action feel like an "OK to dismiss" dialog. It is a decision with consequences; the modal's weight and clarity should reflect that, while still being quick to act on for routine approvals.

---

## 7. Agent Plan / Progress Display

For multi-step requests, the user should see what the agent is doing — both for trust and to avoid the "frozen" feeling during longer agentic work.

- A compact, inline progress display in the chat thread showing the orchestrator's plan as ordered steps (e.g. "1. Search documents · 2. Check live Jira status · 3. Draft email (needs approval)").
- Steps show state: pending, in-progress, done, awaiting-approval, failed.
- Steps that will require approval are flagged *before* they run, so the user anticipates the gate.
- Keep it calm and low-noise — a quiet checklist, not a busy spinner-heavy console. Consistent with the document-tool feel.
- Reads stream their results into the answer as today; the plan display is the scaffold around longer multi-step runs, not a replacement for the streaming answer.

---

## 8. Connector Directory & Browser

Where admins discover and inspect connectors (ecosystem MCP servers, submitted custom connectors, self-hosted connectors).

- **Layout:** a searchable, filterable grid/list of **connector cards**. The directory search field uses the global input focus rule (Section 4).
- **Connector card** shows: connector name + icon, short description, maintainer/source, version, a few key capabilities (e.g. "reads: tickets, projects · actions: create ticket"), and deployment-mode compatibility badges (cloud / hybrid / air-gapped).
- **Trust signals:** clearly mark source/maintainer and whether a connector is self-hosted vs ecosystem, so admins weigh trust. Pill-shaped badges in the established style.
- **Detail view:** opening a card reveals the full manifest — all resources and actions (with read/action clearly distinguished, actions visibly marked as "requires approval"), requested auth method and scopes (flagging over-broad scopes), version, and deployment compatibility.
- Filtering by capability, deployment-mode compatibility, and source. In air-gapped deployments, network-dependent connectors are not listed at all (enforced upstream).

---

## 9. Admin Approval Queue

Where admins approve connectors into the institution's allowlist (governance Tier 1).

- A list of connectors **pending review** and a record of **approved/denied** ones.
- Each pending item presents the manifest summary (capabilities, auth scopes, maintainer, deployment compatibility) for a review decision.
- **Approve** (rust primary) / **Deny** controls, plus **role-restriction** controls — the admin can scope a connector to specific roles (e.g. "researchers only").
- **Version pinning is visible:** an approval is tied to a connector version. When a connector's major version changes (crossing the SDK compatibility boundary), it re-enters the queue with a clear "upgrade — needs re-review" flag, showing what changed since the approved version.
- Actions a connector exposes are highlighted in review (they carry the most risk), with their "requires approval at use time" nature shown — so admins understand that approving a connector with actions doesn't bypass the per-action gate.

---

## 10. User Connector List & Enablement

Where end users turn on connectors their admin approved (governance Tier 2).

- Users see **only** connectors approved for their institution and permitted to their role — never the full directory.
- Each connector shows a clear **enable** control; enabling launches the OAuth consent handoff (Section 11).
- Once enabled, a connector shows its **connected** state and the account/identity it's connected as, plus a **disconnect** control (which revokes the credential).
- Calm, list-based; consistent pill/card styling. No exposure of manifests or governance internals — this is a simple "what can I switch on" surface.

---

## 11. OAuth Consent Handoff

The per-user authentication flow when enabling a connector.

- A clear pre-handoff explanation: which connector, what it will be able to access (the scopes, in plain language), and that they're about to authenticate with the external provider.
- Launch into the provider's OAuth screen (external), then a clean return state confirming connection (or a legible failure state with a retry).
- Any credential entry fields (for API-key/basic/mTLS connectors) use the global input focus rule.
- Reassure on scope: show the least-privilege scopes being requested, consistent with the security posture. Never request or display more than needed.
- In air-gapped mode, this surface handles static credential entry from the institution's secret store rather than an external OAuth round-trip.

---

## 12. Skill Diff Review Screen

**The admin surface for the Skill Synchronization Agent** — where proposed changes to agent instructions are reviewed. High-stakes, because approving a diff changes how an agent behaves; designed for careful, confident review.

### Required contents (from the Agent Layer guide)
- **The diff:** the skill file's current instruction vs the proposed new instruction, rendered as a clear before/after diff (additions/removals visually marked). Only the affected portion is highlighted, with surrounding context for orientation.
- **The trigger:** the document change that motivated this proposal — which document changed, and *what specifically changed* in it (the prior-version diff), shown alongside the skill diff so the admin sees cause and proposed effect together.
- **Confidence:** whether this dependency was **explicit** (the skill file declared it — high confidence) or **inferred** (semantic fallback — "possible, needs review"). Inferred proposals are visually marked as lower-confidence so admins scrutinize them harder.
- **Controls:** **Approve** (writes a new reversible skill-file version), **Reject** (nothing changes; dismissal logged), and a path to **view full skill file** and its **version history**.

### Visual treatment
- Two-panel or stacked before/after, in the calm style — diffs use restrained color (a soft green/rust for add/remove rather than harsh red/green) to stay within the warm palette while remaining legible.
- The trigger (document change) and the proposal (skill change) are visually linked — cause on one side, effect on the other — so the relationship is obvious.
- Confidence badge prominent: explicit vs inferred. Inferred = a clear "review carefully" cue.
- Never an auto-apply path; Approve/Reject is always an explicit human action.

---

## 13. Skill File Management

The admin surface for browsing and governing skill files themselves.

- **List** of skill files (which agent each governs), searchable (global input focus rule).
- **Detail view:** the markdown instructions, with the two content kinds visually distinguished where possible — **human intent** (off-limits to the sync agent) vs **corpus-derived facts** (maintained by it) — and the file's **declared dependencies** (documents/entities).
- **Version history:** every version, attributable (including "changed by Skill Sync Agent, triggered by document X"), with a **roll back** control to restore any prior version.
- Reinforces that skill changes are tracked, attributable, and reversible — the governance properties the Agent Layer guide requires.

---

## 14. Connector Health & Error States

Live connectors depend on external systems; failures must be legible, never silent gaps in an answer.

- When a connector is unavailable mid-query, surface it clearly and specifically: "The Jira connector is currently unavailable — this answer may be missing live ticket data." Calm, informative, not alarming.
- Distinguish a connector being **down** from a connector returning **no results** — these mean different things to the user.
- Connector list/admin views show health status (healthy / degraded / unavailable) with restrained status colors.
- Errors never block the rest of an answer: document-grounded content still renders; the live gap is noted. This preserves the groundedness contract (better to say "I couldn't reach the live source" than to silently omit it).

---

## 15. Accessibility & Consistency

- **Contrast:** the warm, low-contrast palette must still meet accessibility contrast minimums for text — verify `--text-secondary`/`--text-muted` on `--bg-canvas`/`--bg-muted` during build and darken if needed.
- **The violet focus ring doubles as the accessibility focus indicator** — ensure it's visible for keyboard navigation, not just mouse focus, across every input and interactive control.
- **Color is never the only signal:** the document-vs-live citation distinction, the explicit-vs-inferred confidence, and connector health must each carry a non-color cue (glyph, label, text) in addition to color, so the meaning survives for color-blind users.
- **The approval gate must be keyboard-operable** with no default/auto-confirm — Approve and Reject are deliberate, equally reachable actions.
- Reuse shared components (citation chip, connector card, input field, modal shell) so behavior and styling stay consistent as surfaces multiply.

---

## 16. Component Inventory & Build Roadmap

Built last, after the three backend layers, since these components consume backend data contracts. Order mirrors the backend phases so the UI lands feature-by-feature alongside its backend.

### Shared components (build first — reused everywhere)
- **Input field** with the global violet focus rule (Section 4) — the foundational shared control.
- **Live citation chip** + the document/live distinction scheme (Section 5).
- **Modal shell** (calm, elevated, dimmed-canvas) reused by the approval gate and others.
- **Connector card** + capability/deployment badges.

### Phase A — Live retrieval surfaces (with Connector Infra Phases 1–3)
- Live citation chips and combined source list (Section 5).
- Connector directory & browser (Section 8).
- User connector list & enablement (Section 10) + OAuth consent handoff (Section 11).
- Admin approval queue (Section 9).
- Connector health/error states (Section 14).

### Phase B — Action surfaces (with Agent Layer Phase 3)
- **The approval-gate modal (Section 6)** — the priority surface; build carefully and test the approve/reject paths thoroughly.
- Agent plan/progress display (Section 7).

### Phase C — Skill surfaces (with Agent Layer Phase 4)
- Skill diff review screen (Section 12).
- Skill file management & version history (Section 13).

### Throughout
- Hold the line on the design language: rust leads, violet accents only on emphasis/interaction, the global input focus rule everywhere, calm low-contrast surfaces, pill/card consistency. Every new surface should look like it was always part of Deep Query.

---

*End of UI & Design Guide.*
*References data contracts from: `DeepQuerySDK/SDK_GUIDE.md`, `CONNECTOR_INFRASTRUCTURE_GUIDE.md`, `AGENT_LAYER_GUIDE.md`. All UI lives in `frontend/`. This completes the connector + agent initiative guide set.*

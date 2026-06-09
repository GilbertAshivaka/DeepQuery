# Deep Query — Connector Infrastructure Guide
**Build Guide & Reference — Live Connectors Layer**
*This document specifies the infrastructure that lets Deep Query agents retrieve live information from, and take actions in, external systems — without compromising the platform's groundedness moat. It builds directly on the DeepQuerySDK (see `DeepQuerySDK/SDK_GUIDE.md`). No application code is included; this is a technical specification to guide implementation.*

---

## Table of Contents

1. [Purpose & Position in the System](#1-purpose--position-in-the-system)
2. [The Groundedness Principle for Live Data](#2-the-groundedness-principle-for-live-data)
3. [Two Retrieval Paths](#3-two-retrieval-paths)
4. [The MCP Client](#4-the-mcp-client)
5. [The Connector Gateway](#5-the-connector-gateway)
6. [Authentication & Credential Management](#6-authentication--credential-management)
7. [The Ephemeral Cache — Storage Without Ingestion](#7-the-ephemeral-cache--storage-without-ingestion)
8. [Live Citation & Provenance Model](#8-live-citation--provenance-model)
9. [Tiered Governance & the Allowlist](#9-tiered-governance--the-allowlist)
10. [Dual-Source Context Assembly](#10-dual-source-context-assembly)
11. [Deployment Modes](#11-deployment-modes)
12. [Security](#12-security)
13. [Backend Components & Data Model](#13-backend-components--data-model)
14. [Frontend Surfaces](#14-frontend-surfaces)
15. [Phased Build Roadmap](#15-phased-build-roadmap)
16. [Glossary](#16-glossary)

---

## 1. Purpose & Position in the System

Up to this point, Deep Query answers questions from a fixed, ingested corpus: documents are processed once, embedded into ChromaDB, and modelled in Neo4j. Every answer is grounded in those stored sources.

The connector infrastructure extends Deep Query to **live information** — data that lives in external systems and changes constantly: a ticket's current status, a recent Slack thread, a row in an internal database, a record in a hospital or case-management system. It also enables agents to **act** in those systems, gated by human approval.

This layer is built **second**, after the DeepQuerySDK and before the Agent Layer. It depends on the SDK's contracts (resources, actions, provenance envelope, manifest) and is in turn depended on by the Agent Layer, which orchestrates when and how connectors are used.

### Position
```
Agent Layer  (decides when to read live data / take action)
      │
      ▼
Connector Infrastructure  ← THIS GUIDE
  ├─ MCP Client            (speaks MCP to every connector)
  ├─ Connector Gateway     (auth, routing, allowlist, cache)
  └─ Ephemeral Cache       (short-lived, never persisted)
      │
      ▼
Connectors (speak MCP)
  ├─ Public MCP servers   (ecosystem, ~10k+)
  └─ Custom connectors    (built with DeepQuerySDK)
```

---

## 2. The Groundedness Principle for Live Data

Deep Query's moat is groundedness: every claim traces to a verifiable source. Live data threatens this in three specific ways, and the infrastructure is designed around neutralizing each:

1. **Ungrounded claims.** Live data that enters an answer without a citation erodes trust. → *Mitigation:* every live record carries a provenance envelope (from the SDK) and is rendered as a citation, exactly like a document chunk.
2. **Staleness.** Cached or ingested live data goes wrong the moment the source changes. → *Mitigation:* live data is never ingested and never persisted; it is fetched at query time and discarded, with a retrieval timestamp on every citation so the answer is honest about *when* it was true.
3. **Injection.** External data and connector descriptions can carry adversarial instructions. → *Mitigation:* all live content is treated as untrusted data, never as instructions, and only allowlisted connectors reach an agent.

> **The rule that governs this whole layer:** live data is *transient context*, not *stored knowledge*. It is allowed to inform a single answer and must leave no persistent trace beyond the provenance needed for that answer's citations.

---

## 3. Two Retrieval Paths

A query in Deep Query can now be served by two parallel, independent retrieval paths whose outputs converge when the agent assembles its context.

### The Document Path (existing, unchanged)
Query → embed (Gemini Embedding 2) → hybrid search over ChromaDB (dense + BM25, fused with RRF) → cross-encoder rerank → Neo4j graph augmentation → top chunks with **stable citations**.

### The Live Path (new, this guide)
Query → the agent (Agent Layer) decides which connectors are relevant → the MCP Client calls those connectors' resources through the Gateway → results return wrapped in provenance envelopes → these become **live citations** with retrieval timestamps.

The two paths are deliberately different in nature: the document path is fast, local, and stable; the live path is slower (external API calls), dependency-bound (connector uptime), and time-sensitive. They are not merged into one index. They converge only at context-assembly time (Section 10), where both sets of citeable material are handed to the answer-generation step and cited together.

---

## 4. The MCP Client

Deep Query implements a single MCP client. Because both ecosystem connectors and SDK-built custom connectors expose themselves as MCP servers, this one client is the universal interface to every connector — there is no separate code path for "official" vs "custom."

### Responsibilities
- **Discovery:** read a connector's advertised resources and actions (and their descriptions and schemas) via the MCP capability handshake.
- **Invocation:** call resources (reads) and actions (the `preview`/`execute` pair) over MCP, passing parameters the agent supplies.
- **Transport handling:** support the MCP transports the ecosystem uses (stdio for local/self-hosted servers, HTTP/SSE and the newer streamable transports for remote servers).
- **Capability negotiation:** detect the MCP spec version a server supports and degrade gracefully; refuse servers that require capabilities Deep Query does not support, with a clear error.
- **Metadata extraction:** read the Deep Query metadata tags the SDK emits (notably `dq.mutates`) so the Gateway knows which calls require the approval gate.

### What it does NOT do
- It does not decide *whether* to call a connector — that is the Agent Layer's job.
- It does not store credentials — that is the Gateway's job.
- It does not enforce the allowlist — that is the Gateway's job. The client is a protocol-faithful transport; policy lives in the Gateway.

> **Performance note:** the MCP JSON-RPC layer adds latency versus an in-process call. The client should support parallel invocation of independent resource reads (e.g. querying three connectors at once) so live retrieval latency is bounded by the slowest connector, not the sum.

---

## 5. The Connector Gateway

The Gateway is the policy and control plane that sits between the MCP Client and the connectors. Every connector call passes through it. It is the single chokepoint where authentication, authorization, routing, caching, and governance are enforced.

### Responsibilities

**Routing.** Maintain the registry of registered connectors (their manifests, endpoints, transports) and route each agent tool-call to the correct connector instance.

**Allowlist enforcement.** Before any call, verify the target connector is on the institution's approved allowlist *and* enabled by the requesting user (Section 9). A call to a non-allowlisted connector is refused before it reaches the MCP Client.

**Credential injection.** At call time, fetch the appropriate credential for the requesting user + connector pair from the credential store and inject it (Section 6). Connectors never see raw credentials beyond what they need to attach to their own outbound request.

**Gating decisions.** Read the `dq.mutates` metadata. For reads, allow the call to proceed. For actions, enforce the `preview` → approval → `execute` sequence: a `preview` call is allowed, but an `execute` call is refused unless it carries a valid approval token issued by the Agent Layer's approval gate (Section 10, Agent Layer guide).

**Caching.** Consult and populate the ephemeral cache for read calls (Section 7).

**Audit logging.** Record every connector call — who, which connector, which resource/action, when, read-or-action, approved-by (for actions), and outcome. The MCP ecosystem lacks a standardized audit trail, so Deep Query supplies its own. This log is essential for the regulated verticals (hospitals, law firms) and for incident investigation.

**Health & isolation.** Track connector health, apply timeouts and circuit-breaking so one slow or failing connector can't stall a whole query, and isolate connector failures into clear, user-legible errors ("the Jira connector is unavailable") rather than silent gaps in an answer.

---

## 6. Authentication & Credential Management

Credentials are owned by the Gateway's credential store — **never by connectors** (per the SDK contract) and never embedded in code or config that ships with a connector.

### Per-user authentication
When a user enables an allowlisted connector, they complete that connector's auth flow (typically OAuth 2.1 authorization-code with PKCE). The resulting grant is bound to *their* identity. Thereafter, when the agent acts on that user's behalf, the Gateway injects *that user's* credential — so the connector sees the user's own permissions in the external system, not a shared service account.

This is what keeps Deep Query's existing RBAC honest across the connector boundary: a user can only ever retrieve or act on external data they personally have access to. The agent cannot be used to escalate privilege.

### Credential storage
- Credentials and refresh tokens are encrypted at rest in a dedicated secret store (e.g. the institution's vault, or an encrypted store within the deployment).
- The store handles token refresh transparently so agents don't fail mid-task on an expired token.
- Revocation is immediate: disabling a connector or deprovisioning a user purges associated credentials.

### Auth methods supported
OAuth 2.1 (primary for SaaS connectors), API keys, basic auth, and mTLS (common for internal enterprise systems). The method is declared in the connector manifest; the Gateway implements the flow.

### Air-gapped auth
In air-gapped mode there is no external OAuth round-trip. Credentials are static secrets (API keys, mTLS certs) sourced from the institution's own secret store and injected the same way. The connector manifest must declare it can operate without external network egress (Section 11).

---

## 7. The Ephemeral Cache — Storage Without Ingestion

This section answers the storage question directly: **where does live data live, and for how long?**

Live data is **not** stored in ChromaDB or Neo4j. It is **not** ingested, embedded, or modelled. The only place it briefly resides is an ephemeral cache whose sole purpose is to avoid redundant identical calls within a short window.

### Design
- **Backing store:** Redis (already in the stack for Celery), used as a short-TTL key-value cache.
- **What's cached:** the result of a *read* (resource) call, keyed by connector + resource + normalized parameters + requesting user.
- **TTL:** short — on the order of seconds to a few minutes, configurable per connector. The default must be short enough that staleness is negligible. Connectors whose data is highly volatile (live status fields) can declare a near-zero TTL or opt out of caching entirely.
- **Scope:** cache entries are scoped to the user (so one user's authorized data never leaks into another user's results) and ideally to the conversation, so the cache primarily serves the "agent reads the same thing twice while reasoning about one query" case.
- **Actions are never cached.** Only reads. An action's `preview` may be recomputed each time; `execute` is never cached.

### What is *not* in the cache
The cache holds content transiently. It is **not** a system of record, **not** searchable, and **not** part of retrieval ranking. When the TTL expires, the content is gone. Nothing about live data survives a cache eviction except entries in the audit log and any citations already rendered into a delivered answer.

### Why this satisfies the cost and freshness goals
- **Cost:** no embedding spend, no vector storage growth, no Neo4j writes for live data. The only cost is transient cache memory and the external API calls themselves.
- **Freshness:** because nothing is persisted, every answer reflects the source as of its retrieval timestamp, never a stale ingested copy.

---

## 8. Live Citation & Provenance Model

Every live record arrives wrapped in the SDK's provenance envelope (`connector_name`, `source_object_id`, `retrieved_at`, `deep_link`, `title_or_label`, optional `mutability_note`). This layer turns that envelope into a citation that sits beside document citations in the final answer.

### Honesty through timestamps
A document citation ("Ethics_Lesson1_Foundations…pdf, Page 15") is stable. A live citation must encode *when* it was true, because the underlying object can change. The rendered form therefore always includes the retrieval time, e.g.:

> *"Jira ticket DQ-431, status 'In Review' — retrieved 2026-06-06 14:32"*

### Distinct rendering
Live citations must be **visually distinguishable** from document citations in the UI, so a reader instantly knows which facts are stable and which are a live snapshot that may have changed. The exact visual treatment (chip style, label, timestamp placement) is specified in the UI/Design guide; this layer's responsibility is to *emit* the structured live-citation object carrying everything the UI needs: source label, connector, timestamp, deep link, and the mutability hint.

### Citation integrity
The Gateway guarantees that a live citation can only be produced from data that actually passed through it for the current query. The Agent Layer (next guide) must not fabricate or reuse a stale live citation; the retrieval timestamp must reflect the actual fetch that informed the answer.

---

## 9. Tiered Governance & the Allowlist

Connectors are powerful and, in the ecosystem case, externally authored. Governance is **tiered**: administrators control what is *possible*, users control what is *active for them*.

### Tier 1 — Admin approval (institution control)
- Admins browse the connector directory (ecosystem MCP servers + submitted custom connectors + the institution's own self-hosted connectors).
- An admin reviews a connector's manifest: its identity, version, the resources and actions it exposes, the auth and scopes it requests, its deployment-mode compatibility, and its maintainer/source.
- The admin approves a connector into the institution's **allowlist**, optionally restricting it to certain roles (e.g. only researchers may use the web-search connector; only billing staff may use the finance connector).
- Approval is **version-pinned**: approving v1 does not auto-approve a future v2. A connector upgrade that crosses the SDK compatibility contract's major boundary re-enters the approval queue (per the SDK versioning contract).

### Tier 2 — User enablement
- A user sees only the connectors their admin approved and their role permits.
- The user enables a connector for themselves, completing its per-user auth flow.
- Only then can the agent use that connector on that user's behalf.

### Why this defends groundedness and safety
- An unvetted, possibly malicious connector never reaches an agent, neutralizing the prompt-injection-via-tool-description risk at the source.
- Per-role scoping means a connector's reach is bounded by institutional policy, not by what any individual user decides to wire up.
- Version pinning means a connector cannot silently change what it does after approval.

---

## 10. Dual-Source Context Assembly

This is where the two retrieval paths converge. When answering, the system assembles a single context containing both document chunks and live records, and the answer cites both together (the confirmed default behavior).

### Assembly steps
1. The Agent Layer determines the query needs document context, live context, or both.
2. The **document path** returns reranked chunks with stable citations.
3. The **live path** returns provenance-wrapped records with timestamped live citations (via Gateway → MCP Client → connectors, with caching).
4. Both sets are merged into one ordered context block handed to answer generation, each item tagged with its citation object (document or live).
5. The answer is generated citing both kinds of source inline, then a combined source list is rendered — document sources and live sources clearly differentiated.
6. The existing self-correction step verifies that every claim — document-grounded or live-grounded — is supported by its cited source.

### Ordering & balance
When both paths return material, neither is privileged by default; relevance governs ordering. (A deployment may later tune whether documents or live data lead, but the default is integrated, relevance-ranked, jointly cited.) Crucially, the self-correction layer treats a live citation's `retrieved_at` as part of the claim's truth conditions — a live claim is "true as of the timestamp," not "true absolutely."

---

## 11. Deployment Modes

The infrastructure supports three deployment modes, because Deep Query targets organizations with very different data-egress constraints — from cloud-comfortable startups to air-gapped hospitals and law firms. The mode constrains which connectors and which models are permissible.

### Cloud
Full access to remote MCP servers, SaaS connectors over OAuth, and cloud LLM APIs. Lowest operational burden; suitable for organizations without strict data-residency rules.

### Hybrid
A mix: some connectors and models run in the cloud, others stay on-premise. The Gateway enforces per-connector and per-model placement policy — e.g. internal records stay on a self-hosted connector while a public web-search connector is allowed to reach out.

### Air-gapped (fully private / on-premise)
No external network egress. This is a core selling point for the most security-conscious verticals.
- Only **self-hosted connectors** are permitted; a connector whose manifest declares it requires external network access is refused.
- Models run locally (Ollama / vLLM); no cloud LLM API calls (this constrains the Agent Layer's model choices too — see Agent Layer guide).
- The MCP ecosystem's self-hosted sandboxes and outbound-only encrypted tunnels are the relevant mechanism for reaching internal data sources without opening inbound firewall rules.
- The Gateway enforces egress prohibition structurally: any attempt by a connector to reach a non-allowlisted host fails.

> **Deployment mode is a first-class system setting.** It is checked at connector-approval time (an air-gapped deployment won't even list network-dependent connectors), at credential-setup time (no external OAuth in air-gapped mode), and at call time (egress enforcement).

---

## 12. Security

The connector layer is the highest-risk surface in Deep Query. Defenses, in depth:

- **Allowlist as primary defense.** Unvetted connectors never reach an agent (Section 9).
- **Untrusted-by-default data handling.** All connector-returned data and all connector descriptions are treated as untrusted content, never as instructions. The Agent Layer must wrap live content so it cannot be interpreted as a directive (detailed in the Agent Layer guide); this layer's job is to preserve the provenance boundary so it's always clear where external content starts and ends.
- **Least-privilege credentials.** Per-user OAuth with minimal scopes; the Gateway and SDK validator flag over-broad scope requests.
- **Action gating is non-bypassable.** `execute` requires a valid approval token; the Gateway refuses ungated mutations even if an agent (or a compromised connector) requests them.
- **Full audit trail.** Every call logged, supplying the enterprise observability the raw MCP ecosystem lacks.
- **Circuit-breaking & timeouts.** A hostile or broken connector cannot hang queries or exfiltrate by stalling; calls are bounded and isolated.
- **Egress control in air-gapped mode.** Structural prohibition of external network access for connectors.
- **Credential isolation.** Encrypted at rest, per-user scoped, immediately revocable.

---

## 13. Backend Components & Data Model

### New backend modules
```
backend/
├── connectors/
│   ├── mcp_client/        MCP client: discovery, invocation, transports
│   ├── gateway/           routing, allowlist, gating, audit, health
│   ├── credentials/       encrypted credential store, OAuth flows, refresh
│   ├── cache/             ephemeral Redis read-cache with TTL policy
│   └── citations/         live-citation object construction from envelopes
```

### New persistent data (control-plane only — never live content)
| Store | Holds | Notes |
|---|---|---|
| Connector registry | Registered connectors, manifests, endpoints, versions | Control plane |
| Allowlist | Per-institution approved connectors + role restrictions + version pin | Governance |
| User enablement | Which users enabled which connectors | Per-user |
| Credential store | Encrypted per-user credentials/tokens | Secret store / vault |
| Audit log | Every connector call (who/what/when/outcome/approver) | Compliance |

### Transient (not a system of record)
| Store | Holds | Lifetime |
|---|---|---|
| Ephemeral cache (Redis) | Read results | Short TTL, evicted |

> Note the clean split: the only *persistent* connector data is control-plane metadata (what connectors exist, who approved/enabled them, the audit trail). **No live business data is ever persisted.**

---

## 14. Frontend Surfaces

This layer introduces several UI surfaces. They are **specified in detail in the UI/Design guide** (built last) and must follow the established Deep Query design system. Listed here so the infrastructure work knows what the frontend must support:

- **Connector directory / browser** — admins browse and review available connectors (manifest, scopes, maintainer, deployment compatibility).
- **Admin approval queue** — approve/deny connectors into the allowlist, set role restrictions, see version-pinned approvals and re-review prompts on major upgrades.
- **User connector list & enablement** — users see approved connectors permitted to their role and enable them.
- **OAuth consent handoff** — the per-user auth flow launch and return.
- **Live citation chips** — visually distinct from document citation chips, carrying source label, connector, and retrieval timestamp (the action/approval modal itself belongs to the Agent Layer guide).
- **Connector health / error states** — surfacing "connector unavailable" cleanly in results.

The data contracts these surfaces consume (manifest fields, allowlist state, live-citation object shape) are defined in this guide and the SDK guide; the visual treatment is defined in the UI/Design guide.

---

## 15. Phased Build Roadmap

Built second, after the SDK. Each phase is a shippable increment; nothing in a later phase is required for an earlier one to be testable.

### Phase 1 — MCP Client & Read Path (Sprints 1–2)
- **Sprint 1:** Implement the MCP client — discovery, capability negotiation, stdio + HTTP/SSE transports, parallel invocation. Connect to one known public MCP server end-to-end as a read-only smoke test.
- **Sprint 2:** Implement the minimal Gateway (routing + audit logging) and wire the MCP client to read a resource from a DeepQuerySDK-built test connector. Confirm the provenance envelope flows through intact.
- **Exit:** an agent-less script can read a resource from both a public MCP server and a custom SDK connector, through the Gateway, with the call audited.

### Phase 2 — Credentials & Per-User Auth (Sprints 3–4)
- **Sprint 3:** Build the encrypted credential store and OAuth 2.1 (auth-code + PKCE) flow; bind grants to user identity; implement transparent token refresh and revocation.
- **Sprint 4:** Add API key / basic / mTLS methods and static-credential injection for air-gapped mode. Enforce per-user credential injection at the Gateway.
- **Exit:** two different users can enable the same connector and each reads only what their own external permissions allow.

### Phase 3 — Cache, Citations & Governance (Sprints 5–6)
- **Sprint 5:** Implement the ephemeral Redis read-cache with per-connector TTL policy, user/conversation scoping, and action-never-cached enforcement. Implement live-citation object construction from provenance envelopes.
- **Sprint 6:** Implement the tiered governance model — connector registry, admin allowlist with role restrictions and version pinning, user enablement. Build the backing APIs for the frontend surfaces.
- **Exit:** an admin can approve a connector, a user can enable it, reads are cached within TTL, and results return with correct, timestamped live-citation objects.

### Phase 4 — Action Gating Hooks & Deployment Modes (Sprints 7–8)
- **Sprint 7:** Implement the Gateway's gating logic — `dq.mutates` detection, `preview` allowed, `execute` refused without a valid approval token. (The approval token *issuer* is the Agent Layer; here we build the *enforcement* side so it's ready.)
- **Sprint 8:** Implement deployment-mode enforcement — cloud / hybrid / air-gapped placement policy, egress prohibition in air-gapped mode, connector refusal based on manifest network declarations. Add circuit-breaking, timeouts, and health tracking.
- **Exit:** the Gateway refuses an ungated `execute`, refuses a network-dependent connector in air-gapped mode, and isolates a failing connector without stalling a query. The layer is ready for the Agent Layer to build on.

---

## 16. Glossary

- **MCP Client** — Deep Query's single universal interface to all connectors; speaks the Model Context Protocol.
- **Connector Gateway** — the policy/control plane: auth, routing, allowlist, gating, caching, audit.
- **Ephemeral cache** — short-TTL Redis cache for read results; never a system of record; holds no persisted live data.
- **Provenance envelope** — SDK-defined metadata wrapping each live record (see SDK guide).
- **Live citation** — a timestamped citation for live data, rendered distinctly from document citations.
- **Allowlist** — the set of admin-approved connectors for an institution, with role restrictions and version pinning.
- **Approval token** — proof from the Agent Layer's approval gate that a human authorized a specific action; required for `execute`.
- **Deployment mode** — cloud / hybrid / air-gapped; constrains permissible connectors and models.
- **Dual-source context** — the merged document + live context block, jointly cited, handed to answer generation.

---

*End of Connector Infrastructure Guide.*
*Depends on: `DeepQuerySDK/SDK_GUIDE.md`. Depended on by: the Agent Layer Guide (next). Build order: DeepQuerySDK → Connector Infrastructure → Agent Layer → UI/Design.*

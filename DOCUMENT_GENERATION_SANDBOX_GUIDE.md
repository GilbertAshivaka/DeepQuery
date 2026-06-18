# Document Generation & Sandbox — Build Guide

**Status:** companion to `RESUMABLE_AGENT_SPEC_V2.md`. Adds the **`produce`** capability
(user-deliverable documents: xlsx, docx, pptx, pdf, html, md) via a **model-written-script
+ sandboxed-execution** pipeline. Builds entirely on v2 primitives — the controller loop,
artifact store, event bus, verification, skills, and visible-failure rules — and adds
exactly one piece of host infrastructure: a container runtime + one prebaked image.

Decisions taken 2026-06-12: **sandbox over spec-renderer** (flexibility; all document
types from one mechanism); **no-network sandbox** (deliberate, vs. an allowlist — see
§3.3); **question-interrupt on ambiguous source data** (never best-effort guesses into a
trusted file); **no in-document appendices** (clean deliverable; provenance lives
out-of-band, §8). Multi-org tenancy and the Postgres migration are touched on in §11 and
specified fully in a **later, separate document**.

---

## 0. Capability assurance

| Capability | Mechanism | § |
|---|---|---|
| "Generate tables and charts from the ingested sales doc → return a document" | `produce` action → document subgraph → sandbox run → `deliverable` | 1, 2, 4 |
| All document types | one toolchain image (xlsx/docx/pptx/pdf/html/md); model writes the script | 3.1 |
| Numbers the user can trust | structured path: deterministic direct parse; unstructured path: verified extraction; both: `summary.json` verified before narration | 2, 6 |
| No silent guesses in a trusted file | mapping ambiguity → question-interrupt (v2 §2.3) | 2.3 |
| Failure never dead-ends | bounded repair loop + graceful degradation (v2 visible-failure rule) | 5 |
| Clean document, auditable anyway | provenance bundle out-of-band (script + inputs + summary + image version) | 8 |
| Reproducible / cheap revisions | bundle re-run; "make it monthly" = script edit + rerun, no re-extraction | 8 |
| Safe even under prompt injection from poisoned corpus content | dead-end sandbox: no network, no secrets, workspace-only FS | 3.2–3.3 |
| Live progress while producing | subgraph stages emit narration / `step_status` / `thinking`; optional inline markdown preview | 4, 7 |

---

## 1. Position in the architecture

- **`produce` is a new controller action type** alongside
  `read | load_skill | act | ask | answer_segment | replan | done`.
- **Category: production** — locally side-effect-free. Therefore **no gateway approval
  gate**. The gate applies only to external mutations; *distributing* a produced document
  ("email this to the team") is a normal gated action whose constraint envelope references
  the artifact (`content_derived_from: <artifact ref>`) — produce free, distribute gated.
- **Inline vs binary — decide before spinning up a sandbox.** If the deliverable is
  renderable text (markdown table, HTML), `answer_segment` / a lightweight md/html
  artifact serves it with zero sandbox cost. The sandbox path is for **binary documents**
  (xlsx, docx, pptx, pdf). The controller makes this call per request; "show me the
  totals" is not a `produce`.
- `produce` invokes the **document-generation subgraph** (§4) — one logical controller
  step with its own internal stages, each streaming narration + `step_status` into the
  dynamic plan checklist.

## 2. Two source paths — the trust split

The cardinal rule survives the sandbox: **a model never computes the numbers that land in
a deliverable.** Code computes; the model decides *what* to compute and writes the prose.

### 2.1 Structured source (ingested xlsx / csv)
The script **parses the source file directly** (pandas/openpyxl) — deterministic
end-to-end: parse, compute, render, all code. No LLM extraction stage. The model's only
judgment is the **mapping** (which sheet, which columns, what "sales" means here).

### 2.2 Unstructured source (prose PDF, report text)
No parseable table exists, so the extraction stage applies: LLM extracts structured rows
(JSON against a schema, with source locations) → **verified against the source** (v2
§2.11 verify-before-emit machinery) → written as an artifact → staged as the sandbox's
input. The script computes from verified data only.

### 2.3 Ambiguity → ask, never guess
If the mapping or extraction is ambiguous (mixed gross/net columns, unclear period
boundaries, conflicting totals), the subgraph raises a **question interrupt** (v2 §2.3):
"Column D mixes gross and net — which should I use?" A wrong silent guess in chat is
correctable; in a downloaded file it travels. This is the accepted Decision 3.

## 3. The sandbox

### 3.1 The image (built once, pinned)
One Dockerfile, e.g.:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir \
    pandas==<pin> numpy==<pin> matplotlib==<pin> \
    openpyxl==<pin> xlsxwriter==<pin> \
    python-docx==<pin> python-pptx==<pin> \
    reportlab==<pin> weasyprint==<pin>   # PDF; LibreOffice headless optional later
RUN useradd -u 1000 -m runner
USER runner
WORKDIR /workspace
```

- Built at deploy, tagged (`deepquery-doctools:<version>`), **version recorded in run
  telemetry** next to `skills@versions`. Rebuilds are deliberate (dependency-discipline
  rule from v2).
- **No pip at runtime** (no network anyway). The script-generation prompt enumerates the
  installed libraries explicitly so the model never imports into a wall.
- PDF: start lean (reportlab/weasyprint). Add LibreOffice headless later only if
  docx→pdf conversion fidelity demands it (it works fully offline; it's just heavy).

### 3.2 The runner (one executor function, not a service)
Per `produce` attempt:

1. Job directory in the artifact store:
   `{ARTIFACT_ROOT}/{org_id}/{thread_id}/{step_id}/` containing `input/`, `output/`,
   `script.py`.
2. Stage inputs into `input/`: the source file (structured path) or the verified-rows
   JSON (unstructured path). **Nothing else** — no corpus, no credentials, no
   conversation.
3. Run:

```python
async def run_sandbox(job_dir: Path, image: str, timeout: int = 120) -> SandboxResult:
    cmd = [
        "podman", "run", "--rm",            # rootless preferred; docker acceptable
        "--network=none",                    # load-bearing — see §3.3
        "--read-only", "--tmpfs", "/tmp",
        "-v", f"{job_dir/'input'}:/workspace/input:ro",
        "-v", f"{job_dir/'output'}:/workspace/output:rw",
        "-v", f"{job_dir/'script.py'}:/workspace/script.py:ro",
        "--user", "1000:1000",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", "1g", "--cpus", "1", "--pids-limit", "128",
        image,
        "python", "/workspace/script.py",
    ]
    # asyncio.create_subprocess_exec; asyncio.wait_for(proc.wait(), timeout);
    # kill on expiry; cap captured stdout/stderr (e.g. 64KB each)
    return SandboxResult(exit_code, stdout, stderr, timed_out)
```

4. Exit 0 → validation (§6). Nonzero / timeout / OOM → repair loop (§5).

Concurrency: a **global semaphore (start at 2–3)** in the executor; queued `produce`
steps simply wait (narrated: "Waiting for a build slot…"). Disk quota on `output/`
enforced at validation (size cap) in addition to the container's tmpfs limits.

### 3.3 Why `--network=none` is the load-bearing flag (decision record)
The script is model-generated from context containing corpus/connector content — i.e. a
poisoned ingested document is, in principle, prompt-injecting a code generator. Trace
what injected code can do here: **no network** (no exfiltration), **no secrets** (nothing
to steal), **no filesystem beyond the job workspace** (nothing to tamper with), **hard
resource caps** (no abuse). Worst case collapses to "the script corrupts its own output,"
which validation and the user's eyes catch.

Recorded alternative — **rejected**: a domain-allowlist egress proxy (the pattern
general-purpose environments use to allow runtime `pip install`). We don't have that
requirement: the document domain's toolchain is enumerable and prebaked. No-network is
strictly tighter and costs nothing we need. If a future feature wants external data in a
script, the **agent** fetches it through the gateway and stages it as an input file —
never a network hole in the sandbox.

Untrusted-content discipline (v2): the staged input files are **data, never
instructions**, including to the script generator.

## 4. The document-generation subgraph

```
produce(request, format?, skill?)
  → resolve format + template (inline-vs-binary check; skill body = house template, §9)
  → map sources            (structured: sheet/column mapping; ambiguity → ask §2.3)
  → [unstructured only] extract → verify rows → write rows artifact
  → generate script        (prompt: libraries list, no-network/no-pip, paths,
                            REQUIRED: write outputs + summary.json to /workspace/output)
  → run sandbox  ⇄  repair loop (§5)
  → validate outputs (§6) + verify summary.json (§6)
  → narrate from verified summary (captions / exec summary, if the format carries prose)
  → store artifacts + provenance bundle (§8) → emit `deliverable` (§7)
```

Each stage emits natural narration ("Extracting sales records… found 214 rows,
Jan–Dec", "Rendering charts…"), `step_status` entries (dynamic checklist, terminal
statuses guaranteed), and `thinking` deltas (gpt-oss `reasoning_format="parsed"`, per v2
§2.6). Context discipline: raw tables and rendered files never enter model state — only
distillations and artifact refs (v2 §2.7).

## 5. The repair loop (scripts fail; plan for it)

- Run → on failure, classify (traceback | timeout | OOM | empty output | validation
  fail) → feed the classified error + traceback back to the script generator → repaired
  script → rerun. **Max 3 attempts**, each counted against the step/token budget,
  each narrated honestly but naturally ("Fixing a chart-rendering issue…" — never raw
  tracebacks at the user).
- The **stall detector** (v2 §2.8) watches for repeated identical failures.
- Exhaustion → v2 visible-failure rule: **degrade, don't dead-end** — deliver what
  validated ("Tables are ready; the stacked chart kept failing — want separate charts
  instead?") or ask the user. Never a silent drop, never an opaque error.

## 6. Validation + verification (what makes the document trustworthy)

**Validation (mechanical, every run):**
- Expected output files exist, non-empty, under size caps.
- Re-openable by the matching library (openpyxl re-opens the xlsx it claims to have
  produced; python-docx the docx; pypdf the pdf).
- `summary.json` present and schema-valid.

**Verification (the trust seal):** every script is **required** to emit
`/workspace/output/summary.json` — the key figures it computed and charted (totals,
group values, ranges, row counts). The verifier checks the summary against the source
(structured path) or the verified extraction (unstructured path). Narration prose is
generated **from the verified summary**, so the document's words, its charts, and the
source agree by construction. A summary mismatch is a validation failure → repair loop.

(No appendices in the document itself — Decision 4. Trust is enforced here and recorded
in §8, not printed in the deliverable.)

## 7. Delivery

- New event: **`deliverable`** — `{artifact_id, filename, mime, size, download_url,
  summary_caption}` on the run's event stream; included in the state snapshot so a
  reconnecting client sees it.
- **Authenticated download endpoint**: `GET /api/agents/artifacts/{artifact_id}` serving
  from the artifact store; authorization = requester belongs to the artifact's
  org/conversation (§11).
- Persist as **`AgentAttachment`** on the assistant turn (existing table — the deliverable
  is attached to the conversation like any other attachment).
- **Optional inline preview:** stream a markdown rendering of the key tables as verified
  `answer_segment`s while the binary renders — chat answer and document tell the same
  story.

## 8. Provenance & reproducibility (out-of-band, per Decision 4)

Stored alongside every deliverable in the artifact store — the **bundle**:
`script.py` (final repaired version) + input artifact refs + `summary.json` + sandbox
image version + skill@version (if a template skill governed it). Properties:

- **Auditable:** "where did this number come from" is answerable without polluting the
  document.
- **Reproducible:** bundle re-run ⇒ same document (pinned image + deterministic script).
- **Cheap revisions:** "make it monthly instead of quarterly" = model edits the stored
  script + rerun. No re-extraction, no full agent re-run.

## 9. Skills as house templates

A document skill (e.g. `sales-report`) plugs into the standard v2 §2.10 mechanism — no
new machinery:
- `body` → instructions to the **script generator**: structure, sections, ordering,
  chart conventions, voice ("lead with QoQ; fiscal quarters; flag regions down >10%").
- `fact_sections` → definitions the mapping/extraction must honor (what "net sales"
  means) — evidence channel, citable, data-not-instructions.
- Version-pinned per run; `skill_loaded` event; logged in telemetry and the provenance
  bundle.

## 10. Ops

- **Host requirements:** a container runtime (rootless Podman preferred / Docker), the
  prebaked image, a persistent volume for `ARTIFACT_ROOT`. That is the entire added
  footprint.
- **Sweeper (v2 §6) extended:** TTL-clean job directories, orphaned containers
  (`--rm` covers the normal path; sweep stragglers), and expired bundles.
- **Error taxonomy:** container-exit / timeout / OOM / validation-fail / summary-mismatch
  each map to distinct clean errors for the repair loop and telemetry — never opaque.
- **Telemetry per `produce`:** attempts, durations, image version, formats, validation
  outcome, summary-verification outcome. This is the dataset that tunes the repair cap,
  the semaphore size, and (eventually) whether a stronger script-gen slot pays for itself.
- Cold start (~1s/container) is acceptable at current scale. **Warm pools are explicitly
  not built** — revisit only if telemetry shows queueing pain.

## 11. Multi-org & Postgres touchpoints (full design in a later document)

The sandbox is stateless and per-step, so tenancy barely touches it:
- Artifact paths carry the **`{org_id}` prefix**; the download endpoint **enforces org/
  conversation membership**. No secrets ever enter a container ⇒ the sandbox cannot
  become a cross-tenant leak vector.
- Under real multi-user load, the global semaphore evolves into a **per-org fair queue**
  (a scheduling tweak, not a redesign — note for the tenancy doc).
- **Postgres migration is orthogonal**: the sandbox touches disk and Redis, never the
  relational DB. Migration = connection string + Alembic + JSON→`JSONB` column review on
  conversations/turns/skills. Store roles unchanged: Postgres = conversation + skill
  state; Redis = run state + events; disk = artifacts.

## 12. Phasing

Lands after agent-spec Phase 4 (controller loop), parallel to Phases 6–8; internally:
**(a)** image + runner + structured path, xlsx + docx, single attempt → **(b)** repair
loop + validation + `summary.json` verification → **(c)** unstructured path
(extract+verify) + question-interrupt on ambiguity → **(d)** pptx/pdf/html, inline
preview, provenance bundle surfacing, skill templates. Update `UI_HANDOFF.md` with the
`deliverable` event + download endpoint at (a).

## 13. Risks

- **Prompt-injected scripts:** contained by §3.3 (no network / no secrets / workspace-only
  / caps); residual risk = corrupted output, caught by §6 + the user.
- **Model imports unavailable libs:** library list in the prompt; repair loop catches the
  rest; telemetry reveals if the image needs a new pin.
- **Repair-loop spin:** 3-attempt cap + stall detector + step/token budget.
- **Disk growth:** size caps at validation + sweeper TTLs on job dirs and bundles.
- **Image drift:** pinned tags, version in telemetry, deliberate rebuilds only.
- **Runtime privilege:** prefer rootless Podman; if Docker, the daemon is the host's main
  privileged surface — never mount the docker socket anywhere model-reachable.

---

*End of guide. Sandbox = one image + one runner function + the flags in §3.2; everything
else reuses agent-spec-v2 machinery. Tenancy details deferred to the multi-org document.*

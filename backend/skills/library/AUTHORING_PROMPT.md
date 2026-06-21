# Skill-authoring prompt (for Claude chat)

Paste the block below into Claude (claude.ai), fill in the two `<…>` placeholders at the
bottom, and it returns a ready-to-use `SKILL.md`. Then add it via the Skills page (Paste
SKILL.md) or drop it in `backend/skills/library/<name>/SKILL.md` and run `seed_library.py`.

The prompt is written so the generated skill steers the model with **principles**, not a
rigid reference script — so produced documents don't all look like one cloned example.

---

You are authoring a **SKILL.md** for DeepQuery's document-generation system ("produce"). I will give you a target document type and optional house style; you return ONE complete SKILL.md and nothing else.

## How DeepQuery "produce" works (so your skill fits the system)
- When a user asks for a document, a controller loads the matching skill and hands its **body** to a *script-generating LLM* as instructions. That LLM writes ONE self-contained script; the script runs in a locked-down sandbox and writes the finished file to `/workspace/output/`.
- The sandbox has **no network, no pip/npm install at runtime, and no input files**. Every piece of data the document needs is embedded in the script as literals. Output goes ONLY to `/workspace/output/<name>.<ext>`.
- Dual runtime — the format dictates the language:
  - **.xlsx → Python** (openpyxl or pandas; matplotlib for chart images)
  - **.pdf → Python** (reportlab, the high-level *platypus* API)
  - **.docx → Node.js** (the `docx` npm library)
  - **.pptx → Node.js** (`pptxgenjs`; icons via `react-icons` + `react-dom/server` + `sharp`)
- Installed libraries ONLY — never reference anything else (it can't be installed):
  - Python: pandas, numpy, matplotlib (headless/Agg), openpyxl, xlsxwriter, python-docx, python-pptx, reportlab
  - Node: pptxgenjs, docx, react, react-dom, react-icons, sharp
- Fonts in the sandbox: DejaVu, Liberation (Arial/Times-compatible), Noto Color Emoji. reportlab built-in fonts are only Helvetica / Times-Roman / Courier.

## SKILL.md format (exact)
YAML frontmatter + a markdown body:
```
---
name: <lowercase letters/numbers/hyphens, <=64 chars, must NOT contain "claude" or "anthropic">
description: >-
  Third person. State WHAT it builds and WHEN to load it (this is the trigger the controller
  matches on). Mention the words a user would say for this format (e.g. "deck / slides /
  presentation"). Keep it strictly to a document DeepQuery can PRODUCE — never imply reading,
  merging, splitting, or OCR of existing files.
deepquery:
  kind: assistant
  produce_format: <xlsx | docx | pptx | pdf>
---

# <body: the instructions the script-generating model will follow>
```

## Authoring philosophy — THIS IS THE POINT
The body is read by a capable model that will WRITE the script. Write it so the model **designs**, not **copies**:
- Lead with a **design system expressed as principles**: how to pick a cohesive 2–3 colour palette that fits the topic; typographic hierarchy; layout/grid and whitespace; and the component *concepts* (title/cover treatment, section header, card, callout, banded table, icon usage, charts).
- Use only **small, illustrative snippets** — a helper signature, a one- or two-line example. Do NOT include a complete end-to-end reference script: a full script makes the model clone it; fragments make it compose its own.
- **Explicitly instruct variation:** tell the model to choose a palette and layout that suit THIS specific topic and to vary the structure per request — "do not reuse a fixed example's colours or layout verbatim." Offering 2–3 distinct stylistic directions to choose from is good.
- Reserve **concrete, must-follow code for the correctness gotchas only** (the things that crash). Everything else is guidance to be interpreted, not copied.
- Close with the hard rules: save to `/workspace/output/<name>.<ext>`; be fully self-contained (embed all data); compute every figure in code; print one confirmation line at the end.

## Correctness gotchas to bake in (state these concretely, for the chosen format)
- **pptx (pptxgenjs):** create ONE `const pres = new pptxgen()`; PASS `pres`/`slide` into any helper functions (referencing an out-of-scope `pres` is the #1 crash); shapes use the string form `slide.addShape('rect', {…})` (also `'ellipse'`, `'line'`); `slide.addText(textOrArray, options)` — options is the SECOND argument; icons are async — make the build function `async`, `await` the react-icons→sharp PNG before `slide.addImage({ data, … })`, and `await pres.writeFile({ fileName: '/workspace/output/<name>.pptx' })`; end with `main().catch(e => { console.error(e); process.exit(1); });`.
- **docx (docx lib):** font `size` is in half-points (28 = 14pt); table widths are in DXA twips; table cells must contain `Paragraph`s (not bare strings); bullet lists need a `numbering` config; finish with `Packer.toBuffer(doc).then(buf => require('fs').writeFileSync('/workspace/output/<name>.docx', buf));`.
- **xlsx (openpyxl):** `merge_cells(...)` then style the TOP-LEFT cell of the merge; keep numbers as numbers and apply `number_format`; set column widths; freeze panes below the header; `wb.save('/workspace/output/<name>.xlsx')`.
- **pdf (reportlab):** use platypus flowables added to a `story`, then `doc.build(story)` — never hand-place on a raw canvas; NEVER use Unicode sub/superscript glyphs (₂ / ²) — they render as black boxes; use `<sub>` / `<super>` inside a `Paragraph`; escape literal `&`, `<`, `>` as `&amp;`, `&lt;`, `&gt;`; only the built-in fonts are available; `SimpleDocTemplate('/workspace/output/<name>.pdf', …)`.

## Your task
- **Target document:** <e.g. "a polished PPTX pitch/teaching deck" — or xlsx workbook / docx report / pdf brief>
- **House style (optional):** <brand colours, tone, any preferences — or write "tasteful, modern; you choose a palette per topic">

Return ONLY the complete SKILL.md (frontmatter + body). No preamble, no explanation.

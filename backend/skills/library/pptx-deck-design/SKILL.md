---
name: pptx-deck-design
description: >-
  House design system for building polished PowerPoint presentations (.pptx). Load this
  whenever the user wants a slide deck, presentation, slides, pitch deck, or a .pptx file.
  It provides the visual design system and proven pptxgenjs code patterns — palette,
  layout grid, reusable slide components, icons, and charts — so generated decks look
  intentionally designed, not like a default template.
deepquery:
  kind: assistant
  produce_format: pptx
---

# Building a polished deck (pptxgenjs / JavaScript)

You are writing a **self-contained Node.js script** that builds a `.pptx` with **pptxgenjs**
and saves it to `/workspace/output/`. Follow this house design system. The goal is a deck
that looks **intentionally designed** — cohesive palette, strong typographic hierarchy,
generous whitespace, and tasteful icons — never a plain default template.

## Setup

```js
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";           // 10 x 5.625 inches; all coords in inches
```

Create exactly **one** `pres`. Coordinates are inches. Keep a consistent left margin
(≈ 0.45–0.55") and align everything to an invisible grid.

## Palette

Define a cohesive palette object near the top and reuse it everywhere — never scatter raw
hex. Pick a palette that fits the topic; 2–3 accent colors maximum. Example shape:

```js
const C = {
  ink:    "1A1A1A",   // headings on light
  body:   "44403C",   // body text
  muted:  "78716C",   // secondary text
  bg:     "FAFAF9",   // light slide background
  card:   "FFFFFF",   // card fill
  line:   "E7E5E4",   // hairline / dividers
  accent: "C0392B",   // primary accent (pick to fit the topic)
  accentLt:"F2D5CF",  // pale accent for chips/labels
  dark:   "1A0A04",   // dark slides (title/closing)
};
```

## Typography

- Headings/titles: a serif display face — **"Georgia"**.
- Body / labels: a clean sans — **"Calibri"** or **"Trebuchet MS"** (Liberation Sans also works).
- Use size + weight + color for hierarchy. Add small UPPERCASE **eyebrow** labels above big
  titles (`charSpacing: 2`), and keep body text ≥ 11pt.

## Reusable components

Define small helpers and reuse them on every slide — consistency is what reads as polished.
**Pass `pres` and `slide` into helpers** — never reference a variable that isn't in scope.

```js
const shadow = () => ({ type: "outer", color: "000000", blur: 8, offset: 3, angle: 135, opacity: 0.12 });

// Left accent bar + title + hairline — the standard content-slide header.
function titleBar(slide, text) {
  slide.addShape("rect", { x: 0.45, y: 0.30, w: 0.06, h: 0.52, fill: { color: C.accent }, line: { type: "none" } });
  slide.addText(text, { x: 0.62, y: 0.24, w: 9.0, h: 0.64, fontSize: 26, bold: true, color: C.ink, fontFace: "Georgia", valign: "middle", margin: 0 });
  slide.addShape("rect", { x: 0.45, y: 0.94, w: 9.1, h: 0.02, fill: { color: C.line }, line: { type: "none" } });
  slide.background = { color: C.card };
}

// A white card with a subtle shadow.
function card(slide, x, y, w, h, fill = C.card) {
  slide.addShape("rect", { x, y, w, h, fill: { color: fill }, line: { color: C.line, width: 0.5 }, shadow: shadow() });
}

// Uppercase chip label.
function chip(slide, text, x, y) {
  const w = text.length * 0.085 + 0.3;
  slide.addShape("rect", { x, y, w, h: 0.26, fill: { color: C.accentLt }, line: { type: "none" } });
  slide.addText(text.toUpperCase(), { x, y, w, h: 0.26, fontSize: 8, bold: true, color: C.accent, align: "center", valign: "middle", charSpacing: 1, margin: 0 });
}

// Render a react-icon to a PNG data URL (icons are ASYNC — await before addImage).
async function icon(IconComp, color, size = 128) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(IconComp, { color: "#" + color, size: String(size) }));
  const png = await sharp(Buffer.from(svg)).resize(size, size).png().toBuffer();
  return "data:image/png;base64," + png.toString("base64");
}
```

## Slide archetypes

1. **Title slide** — dark background (`C.dark`); 1–2 large translucent accent ellipses
   bleeding off a corner (`addShape("ellipse", { fill: { color: C.accent, transparency: 85 } })`);
   a small accent rect; an eyebrow label; a big serif title (≈ 54–64pt, white); an italic
   subtitle in the accent tint; optional presenter/date block.
2. **Section divider** — accent or dark background, a large faint section number, and the
   section title. Use to break the deck into parts.
3. **Content slide** — `titleBar(slide, "…")`, then the body as a **2–3 column grid of cards**
   or an icon list. Each card: an icon (await `icon(...)` → `addImage`), a bold sub-head, a
   short line of body. Keep columns aligned and evenly spaced.
4. **Stats / metrics** — big numbers (Georgia, accent color) in cards, each with a small
   label and an icon.
5. **Closing** — dark background, a thank-you / call-to-action, contact line.

Use icons (`react-icons/fa`, `/md`, `/fi`) to label sections, features, and metrics —
sparingly and at a consistent size/color. Use `pres.addChart(...)` for real data.

## Correctness — avoid the common crashes

- One `pres`; pass `pres`/`slide` into helpers (a bare undefined var is the #1 crash).
- Shapes use the **string** form: `slide.addShape("rect", {…})` (also `"ellipse"`, `"line"`).
- `slide.addText(textOrArray, options)` — options is the **second** arg; rich text is an
  array of `{ text, options }`.
- Icons/`sharp` are async: make your build function `async`, `await` each icon before
  `slide.addImage({ data, x, y, w, h })`.
- Finish with `await pres.writeFile({ fileName: "/workspace/output/<name>.pptx" })`, then
  run `main().catch(e => { console.error(e); process.exit(1); });` and print a confirmation.

## Restraint

2–3 accent colors, consistent margins, plenty of whitespace, everything aligned to the
grid. A clean, confident, well-spaced deck beats a busy one. Make it look designed.

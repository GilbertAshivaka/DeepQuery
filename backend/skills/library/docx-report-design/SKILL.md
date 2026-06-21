---
name: docx-report-design
description: >-
  House design system for building polished Word documents (.docx). Load this whenever the
  user wants a document, report, brief, write-up, memo, letter, overview, or a .docx file.
  Provides the visual design system and proven `docx` (JavaScript) code patterns — heading
  system, cover page, callout boxes, banded tables, running header/footer — so generated
  documents look like a designed report, not raw text.
deepquery:
  kind: assistant
  produce_format: docx
---

# Building a polished Word document (docx / JavaScript)

You are writing a **self-contained Node.js script** that builds a `.docx` with the **`docx`**
library and saves it to `/workspace/output/`. Follow this house design system so the
document reads like a designed report: a cover, clear heading hierarchy, callout boxes,
banded tables, and a running header/footer.

## Units & setup

- Font `size` is in **half-points** (`size: 28` = 14pt). Table widths are in **DXA twips**
  (≈ 1440/inch; a full A4 content width ≈ 9360).
- `require("docx")` for `Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, BorderStyle, WidthType, ShadingType, PageBreak, Header, Footer` and `fs`.

## Palette & borders

```js
const ACCENT = "1B5E20", ACCENT2 = "2E7D32", LIGHT = "E8F5E9";
const INK = "1A1A1A", BODY = "333333", MUTED = "888888";
const WHITE = "FFFFFF", GREY = "F5F5F5", LINE = "CCCCCC";
const FULL = 9360;
const border  = { style: BorderStyle.SINGLE, size: 1, color: LINE };
const borders = { top: border, bottom: border, left: border, right: border };
```

## Reusable helpers (define once, reuse)

```js
const h1 = (t) => new Paragraph({ spacing: { before: 360, after: 140 },
  shading: { fill: ACCENT, type: ShadingType.CLEAR },
  children: [new TextRun({ text: "  " + t, font: "Georgia", size: 28, bold: true, color: WHITE })] });
const h2 = (t) => new Paragraph({ spacing: { before: 260, after: 100 },
  border: { left: { style: BorderStyle.THICK, size: 18, color: ACCENT2, space: 8 } },
  children: [new TextRun({ text: t, font: "Georgia", size: 24, bold: true, color: ACCENT2 })] });
const h3 = (t) => new Paragraph({ spacing: { before: 180, after: 80 },
  children: [new TextRun({ text: t, font: "Calibri", size: 22, bold: true, color: ACCENT })] });
const p  = (t, o = {}) => new Paragraph({ spacing: { before: 60, after: 100 },
  children: [new TextRun({ text: t, font: "Calibri", size: 22, color: o.color || BODY, italics: !!o.italic, bold: !!o.bold })] });
const lv = (label, val) => new Paragraph({ spacing: { before: 50, after: 70 }, children: [
  new TextRun({ text: label + ": ", font: "Calibri", size: 22, bold: true, color: ACCENT2 }),
  new TextRun({ text: val, font: "Calibri", size: 22, color: INK }) ] });
const bull = (t, lvl = 0) => new Paragraph({ numbering: { reference: "bul", level: lvl },
  spacing: { before: 40, after: 55 }, children: [new TextRun({ text: t, font: "Calibri", size: 22, color: BODY })] });

// Callout card (single shaded, bordered cell).
function box(rows) {
  return new Table({ width: { size: FULL, type: WidthType.DXA }, columnWidths: [FULL],
    rows: [new TableRow({ children: [new TableCell({
      shading: { fill: LIGHT, type: ShadingType.CLEAR },
      borders: { top:{style:BorderStyle.SINGLE,size:6,color:ACCENT2}, bottom:{style:BorderStyle.SINGLE,size:6,color:ACCENT2},
                 left:{style:BorderStyle.SINGLE,size:6,color:ACCENT2}, right:{style:BorderStyle.SINGLE,size:6,color:ACCENT2} },
      margins: { top: 150, bottom: 150, left: 220, right: 220 }, children: rows })] })] });
}

// Banded table: accent header row, alternating row fills.
function tbl(headers, rows, colW) {
  const hRow = new TableRow({ children: headers.map((h, i) => new TableCell({
    width: { size: colW[i], type: WidthType.DXA }, shading: { fill: ACCENT, type: ShadingType.CLEAR }, borders,
    margins: { top: 80, bottom: 80, left: 110, right: 110 },
    children: [new Paragraph({ children: [new TextRun({ text: h, font: "Calibri", size: 19, bold: true, color: WHITE })] })] })) });
  const dRows = rows.map((row, ri) => new TableRow({ children: row.map((cell, ci) => new TableCell({
    width: { size: colW[ci], type: WidthType.DXA }, shading: { fill: ri % 2 ? GREY : WHITE, type: ShadingType.CLEAR }, borders,
    margins: { top: 75, bottom: 75, left: 110, right: 110 },
    children: [new Paragraph({ children: [new TextRun({ text: String(cell), font: "Calibri", size: 19, color: INK })] })] })) }));
  return new Table({ width: { size: colW.reduce((a, b) => a + b, 0), type: WidthType.DXA }, columnWidths: colW, rows: [hRow, ...dRows] });
}
```

## Document structure

- **Cover** (top of the first section's `children`): centered big serif title (Georgia ~58
  half-pts, accent color), an italic tagline (muted), a shaded subtitle bar (white on
  accent), then a `box([...])` of key-value metadata, an intro paragraph, then `new
  Paragraph({ children: [new PageBreak()] })`.
- **Body**: alternate `h1` (section) / `h2` (subsection) / `h3`, `p` paragraphs, `bull`
  lists, `box` callouts for highlights, and `tbl` for any tabular data. Keep generous
  spacing; lead sections with a short framing sentence.
- **Header/footer**: a running `Header` (title · doc name · date, with a bottom border) and
  `Footer` (author · contact, with a top border, muted).

Assemble with a numbering config (so `bull` works) and one section:

```js
const doc = new Document({
  numbering: { config: [{ reference: "bul", levels: [
    { level: 0, format: "bullet", text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 560, hanging: 280 } } } },
    { level: 1, format: "bullet", text: "◦", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1000, hanging: 280 } } } } ] }] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 } } },
    headers: { default: new Header({ children: [ /* running header paragraph */ ] }) },
    footers: { default: new Footer({ children: [ /* running footer paragraph */ ] }) },
    children: [ /* cover … body … */ ],
  }],
});
```

## Correctness

- `size` is half-points; table widths are DXA twips — don't mix in points/pixels.
- Build the whole `children` array, then write the file:
  `Packer.toBuffer(doc).then(buf => { require("fs").writeFileSync("/workspace/output/<name>.docx", buf); console.log("done"); });`
- `Table` cells must contain `Paragraph`s (not bare strings). Bullets require the numbering
  config above. End by printing a confirmation line.

## Restraint

One accent color + neutrals, consistent spacing, a clear hierarchy. Use `box` for
highlights and `tbl` for data — avoid long unstyled runs of text.

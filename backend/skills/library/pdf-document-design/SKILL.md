---
name: pdf-document-design
description: >-
  House design system for CREATING polished PDF documents (.pdf) with reportlab. Load this
  when the user wants to generate/produce a PDF — e.g. "as a PDF", "a printable version", "a
  PDF report/one-pager I can share". This builds a NEW PDF from scratch; it does not read,
  merge, split, OCR, or fill existing PDFs (the sandbox has no input files, no network, and
  only reportlab). Otherwise a .docx is the default document format.
deepquery:
  kind: assistant
  produce_format: pdf
---

# Building a polished PDF (reportlab / Python)

You are writing a **self-contained Python script** that builds a `.pdf` with **reportlab**
(the high-level **platypus** API) and saves it to `/workspace/output/`. Use platypus
(flowables) — not the low-level canvas — for real document layout. Compute every figure in
code. Load this only when a PDF is genuinely wanted; otherwise a .docx is the default.

**Scope:** this CREATES a new PDF. The sandbox has no network, no input files, and only
reportlab — so do NOT attempt to read/merge/split/OCR/watermark/encrypt an existing PDF
(none of pypdf, pdfplumber, pytesseract, qpdf, pdftk, poppler are available). Build the
document's content from the data embedded in the script.

## Setup, palette & styles

```python
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                HRFlowable, PageBreak, Image)

ACCENT = colors.HexColor("#1B5E20"); ACCENT2 = colors.HexColor("#2E7D32")
LIGHT = colors.HexColor("#E8F5E9"); INK = colors.HexColor("#1A1A1A")
BODY = colors.HexColor("#333333"); MUTED = colors.HexColor("#777777")
GREY = colors.HexColor("#F5F5F5")

ss = getSampleStyleSheet()
styles = {
    "title": ParagraphStyle("title", parent=ss["Title"], fontName="Times-Bold", fontSize=30, textColor=ACCENT, spaceAfter=6),
    "tag":   ParagraphStyle("tag", parent=ss["Normal"], fontSize=13, textColor=MUTED, alignment=TA_CENTER, spaceAfter=18, fontName="Helvetica-Oblique"),
    "h1":    ParagraphStyle("h1", fontName="Times-Bold", fontSize=15, textColor=colors.white, backColor=ACCENT, leading=22, spaceBefore=16, spaceAfter=8, leftIndent=6),
    "h2":    ParagraphStyle("h2", fontName="Times-Bold", fontSize=12.5, textColor=ACCENT2, spaceBefore=12, spaceAfter=5),
    "body":  ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5, textColor=BODY, leading=15, spaceAfter=7),
    "lv":    ParagraphStyle("lv", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5, textColor=INK, leading=15),
}
```

## Banded table helper

```python
def table(headers, rows, col_widths):
    data = [headers] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY]),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",(0, 0), (-1, -1), 7),
    ]))
    return t
```

## Structure

- **Cover** (first flowables): the `title`, an italic `tag` line, a coloured rule
  (`HRFlowable(width="100%", thickness=2, color=ACCENT)`), a key-value `Table` styled like a
  callout (light fill), then `PageBreak()`.
- **Body**: alternate `h1`/`h2` `Paragraph`s, `body` paragraphs, and `table(...)` for data.
  `Spacer(1, 6*mm)` for breathing room.
- Build:
  ```python
  doc = SimpleDocTemplate("/workspace/output/<name>.pdf", pagesize=A4,
                          topMargin=20*mm, bottomMargin=20*mm, leftMargin=18*mm, rightMargin=18*mm)
  story = [ ... ]   # the flowables above
  doc.build(story)
  print("done")
  ```

## Charts (optional)

We have matplotlib in the sandbox. Render a chart to a PNG in /tmp, then embed it as a
flowable: `Image("/tmp/chart.png", width=150*mm, height=90*mm)`. Use the palette colours.

## reportlab gotchas (these cause real failures — follow them)

- **Subscripts/superscripts: never use Unicode glyphs** (₀₁₂₃…, ⁰¹²³…) — reportlab's built-in
  fonts lack them and they render as black boxes. Use XML markup inside a `Paragraph`:
  `Paragraph("H<sub>2</sub>O", styles["body"])`, `Paragraph("x<super>2</super>", styles["body"])`.
  (Great for scientific/technical content.) Also escape literal `&`, `<`, `>` in body text as
  `&amp;`, `&lt;`, `&gt;` inside Paragraphs.
- **Fonts:** only `Helvetica`, `Times-Roman`, `Courier` (+ `-Bold`, `-Oblique`/`-Italic`) are
  guaranteed — don't reference fonts you haven't registered.
- A `Table` row's cell count must match the column widths; wrap long cell text in a
  `Paragraph` so it flows instead of overflowing.

## Correctness

- Use platypus flowables added to a `story` list, then `doc.build(story)`. Don't hand-place
  text on a raw canvas.
- Save to `/workspace/output/<name>.pdf` (the only writable dir). Embed images via
  `Image(path)`. Print a confirmation line.

## Restraint

One accent + neutrals, a clear type hierarchy, banded tables, generous margins. Aim for a
clean, printable, designed look.

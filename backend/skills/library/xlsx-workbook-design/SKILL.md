---
name: xlsx-workbook-design
description: >-
  House design system for building polished spreadsheets (.xlsx). Load this whenever the
  user wants a spreadsheet, workbook, data table, dataset, budget, register, tracker, or an
  .xlsx file. Provides the visual design system and proven openpyxl (Python) patterns —
  palette, styled headers, banded rows, totals, number formats, conditional colour scales,
  frozen panes, multiple sheets — so the workbook looks designed and is easy to read.
deepquery:
  kind: assistant
  produce_format: xlsx
---

# Building a polished spreadsheet (openpyxl / Python)

You are writing a **self-contained Python script** that builds an `.xlsx` with **openpyxl**
and saves it to `/workspace/output/`. Compute every figure in code. Follow this house
design system so the workbook reads as designed: a summary sheet, styled headers, banded
rows, a bold totals row, sensible number formats, and frozen panes.

## Palette & helpers

```python
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule

DARK = "1B5E20"; MID = "2E7D32"; LIGHT = "E8F5E9"     # accent ramp (pick to fit topic)
WHITE = "FFFFFF"; GREY1 = "F5F5F5"; INK = "212121"; LINE = "BBBBBB"

def _font(bold=False, color=INK, size=10, italic=False):
    return Font(name="Calibri", bold=bold, color=color, size=size, italic=italic)
def _align(where="left"):
    return Alignment(horizontal=where, vertical="center", wrap_text=(where != "right"))
def _border():
    s = Side(style="thin", color=LINE); return Border(left=s, right=s, top=s, bottom=s)

def cell(ws, row, col, value, *, bold=False, bg=None, fg=INK, align="left", size=10, num_fmt=None):
    c = ws.cell(row=row, column=col, value=value)
    c.font = _font(bold, fg, size); c.alignment = _align(align); c.border = _border()
    if bg: c.fill = PatternFill("solid", fgColor=bg)
    if num_fmt: c.number_format = num_fmt
    return c
```

## Conventions

- **One workbook, well-titled sheets.** Lead with a **Summary** sheet, then detail sheets.
  Set `ws.sheet_view.showGridLines = False` for a clean canvas.
- **Title block**: merge across the table width, big bold font on an accent fill
  (`ws.merge_cells("B2:H2")`, then style the anchor cell ~18–28pt white on `DARK`), with an
  italic subtitle row beneath.
- **Header row**: bold `WHITE` on `DARK` fill, wrapped, centered, bordered.
- **Data rows**: alternate fills `WHITE` / `GREY1` (banding); numeric columns get
  `num_fmt='#,##0'` (or `'#,##0.00'`, `'0%'`, `'"KES "#,##0'`). Bold the first column.
- **Totals row**: bold `WHITE` on `DARK`, computed in Python (`sum(...)`) — never hard-coded.
- **Column widths & row heights**: set `ws.column_dimensions[get_column_letter(i)].width`
  to fit content; bump header/title row heights.
- **Freeze panes** below the header (`ws.freeze_panes = "A4"`) so headers stay visible.
- **Conditional formatting** for a key metric column — a colour scale reads instantly:
  `ws.conditional_formatting.add("C16:C34", ColorScaleRule(start_type="min", start_color=LIGHT, end_type="max", end_color=DARK))`.
- **Charts** (optional): `openpyxl.chart` (BarChart/LineChart/PieChart) with a title and
  categories/values references, placed beside the table.

## Sketch

```python
wb = openpyxl.Workbook()
ws = wb.active; ws.title = "Summary"; ws.sheet_view.showGridLines = False
# title block (merged, accent fill) → header row → banded data rows (computed) → totals row
# → number formats → freeze panes → column widths → optional colour scale / chart
wb.save("/workspace/output/<name>.xlsx")
print("done")
```

## Correctness

- Save with `wb.save("/workspace/output/<name>.xlsx")` (the only writable dir). Print a
  confirmation line.
- `merge_cells` then style the **top-left** cell of the merge. Use `get_column_letter` for
  column widths. Keep numeric values as numbers (apply `number_format`), not strings.

## Restraint

One accent ramp + neutral greys, banding for legibility, number formats everywhere,
generous column widths. A clean, aligned sheet beats a colourful busy one.

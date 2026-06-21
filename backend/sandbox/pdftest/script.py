#!/usr/bin/env python3
import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    PageBreak,
)

# ---------- Palette ----------
ACCENT = colors.HexColor("#1B5E20")
ACCENT2 = colors.HexColor("#2E7D32")
LIGHT = colors.HexColor("#E8F5E9")
INK = colors.HexColor("#1A1A1A")
BODY = colors.HexColor("#333333")
MUTED = colors.HexColor("#777777")
GREY = colors.HexColor("#F5F5F5")

# ---------- Styles ----------
ss = getSampleStyleSheet()
styles = {
    "title": ParagraphStyle(
        "title",
        parent=ss["Title"],
        fontName="Times-Bold",
        fontSize=30,
        textColor=ACCENT,
        spaceAfter=6,
        alignment=TA_CENTER,
    ),
    "tag": ParagraphStyle(
        "tag",
        parent=ss["Normal"],
        fontSize=13,
        textColor=MUTED,
        alignment=TA_CENTER,
        spaceAfter=18,
        fontName="Helvetica-Oblique",
    ),
    "h1": ParagraphStyle(
        "h1",
        fontName="Times-Bold",
        fontSize=15,
        textColor=colors.white,
        backColor=ACCENT,
        leading=22,
        spaceBefore=16,
        spaceAfter=8,
        leftIndent=6,
    ),
    "h2": ParagraphStyle(
        "h2",
        fontName="Times-Bold",
        fontSize=12.5,
        textColor=ACCENT2,
        spaceBefore=12,
        spaceAfter=5,
    ),
    "body": ParagraphStyle(
        "body",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        textColor=BODY,
        leading=15,
        spaceAfter=7,
    ),
    "kv": ParagraphStyle(
        "kv",
        parent=ss["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=INK,
        spaceAfter=4,
    ),
}

# ---------- Helpers ----------
def table(headers, rows, col_widths):
    data = [headers] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return t


def build_pdf():
    output_path = "/workspace/output/water_co2_overview.pdf"
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
    )
    story = []

    # ---- Cover ----
    story.append(Paragraph("Water & Carbon Dioxide Overview", styles["title"]))
    story.append(Paragraph("A quick reference guide", styles["tag"]))
    story.append(HRFlowable(width="100%", thickness=2, color=ACCENT, spaceAfter=12))

    # Key‑value table on cover
    kv_data = [
        [Paragraph("Prepared by:", styles["kv"]), Paragraph("Science Team", styles["body"])],
        [
            Paragraph("Date:", styles["kv"]),
            Paragraph(datetime.now().strftime("%B %d, %Y"), styles["body"]),
        ],
    ]
    kv_table = Table(kv_data, colWidths=[30 * mm, 100 * mm])
    kv_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.5, ACCENT),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, ACCENT2),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(kv_table)
    story.append(PageBreak())

    # ---- Water Section ----
    story.append(Paragraph("Water (H<sub>2</sub>O)", styles["h1"]))
    story.append(Paragraph("Key Properties", styles["h2"]))

    water_props = [
        ["Molecular Formula", "H<sub>2</sub>O"],
        ["Molar Mass", "18.015 g·mol<sup>-1</sup>"],
        ["State at 25 °C", "Liquid"],
        ["Boiling Point", "100 °C"],
        ["Freezing Point", "0 °C"],
        ["Density (20 °C)", "0.998 g·cm<sup>-3</sup>"],
    ]
    water_table = table(
        ["Property", "Value"],
        [[Paragraph(p, styles["body"]), Paragraph(v, styles["body"])] for p, v in water_props],
        col_widths=[55 * mm, 80 * mm],
    )
    story.append(water_table)
    story.append(Spacer(1, 6 * mm))

    water_desc = (
        "Water is a polar inorganic compound that is essential for all known forms of life. "
        "Its high specific heat capacity and surface tension make it a unique solvent. "
        "The hydrogen bonds between molecules give water its anomalous expansion upon freezing."
    )
    story.append(Paragraph(water_desc, styles["body"]))
    story.append(Spacer(1, 10 * mm))

    # ---- CO₂ Section ----
    story.append(Paragraph("Carbon Dioxide (CO<sub>2</sub>)", styles["h1"]))
    story.append(Paragraph("Key Properties", styles["h2"]))

    co2_props = [
        ["Molecular Formula", "CO<sub>2</sub>"],
        ["Molar Mass", "44.01 g·mol<sup>-1</sup>"],
        ["State at 25 °C", "Gas"],
        ["Boiling Point", "-78.5 °C (sublimes)"],
        ["Density (1 atm, 25 °C)", "1.977 g·L<sup>-1</sup>"],
        ["Solubility in Water", "1.45 g·L<sup>-1</sup>"],
    ]
    co2_table = table(
        ["Property", "Value"],
        [[Paragraph(p, styles["body"]), Paragraph(v, styles["body"])] for p, v in co2_props],
        col_widths=[55 * mm, 80 * mm],
    )
    story.append(co2_table)
    story.append(Spacer(1, 6 * mm))

    co2_desc = (
        "Carbon dioxide is a colorless gas produced by combustion and respiration. "
        "It is a key greenhouse gas, trapping infrared radiation and contributing to global warming. "
        "In aqueous solution it forms carbonic acid, which plays a crucial role in the buffering "
        "capacity of natural waters."
    )
    story.append(Paragraph(co2_desc, styles["body"]))

    # Build PDF
    doc.build(story)
    print("done")


if __name__ == "__main__":
    try:
        build_pdf()
    except Exception as e:
        print(f"Error: {e}")
        raise
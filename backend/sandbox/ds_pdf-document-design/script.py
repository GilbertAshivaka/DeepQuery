# -*- coding: utf-8 -*-
"""
Generate a printable one‑page PDF summarizing a fictional product launch.
"""

import os
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

# ---------- Palette & Styles ----------
ACCENT = colors.HexColor("#1B5E20")
ACCENT2 = colors.HexColor("#2E7D32")
LIGHT = colors.HexColor("#E8F5E9")
INK = colors.HexColor("#1A1A1A")
BODY = colors.HexColor("#333333")
MUTED = colors.HexColor("#777777")
GREY = colors.HexColor("#F5F5F5")

ss = getSampleStyleSheet()
styles = {
    "title": ParagraphStyle(
        "title",
        parent=ss["Title"],
        fontName="Times-Bold",
        fontSize=30,
        textColor=ACCENT,
        spaceAfter=6,
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
    "lv": ParagraphStyle(
        "lv",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        textColor=INK,
        leading=15,
    ),
}

# ---------- Helper: Banded Table ----------
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


# ---------- Data ----------
product_name = "Nimbus X1"
launch_date = "September 15, 2026"
tagline = "Elevate Your Cloud Experience"
price = 199.99  # USD
target_market = "Enterprise Cloud Services"
forecast_units = 12_500
forecast_revenue = price * forecast_units

def fmt_currency(val):
    return f"${val:,.2f}"

def fmt_int(val):
    return f"{val:,}"

# ---------- Build Document ----------
output_path = "/workspace/output/product_launch.pdf"
doc = SimpleDocTemplate(
    output_path,
    pagesize=A4,
    topMargin=20 * mm,
    bottomMargin=20 * mm,
    leftMargin=18 * mm,
    rightMargin=18 * mm,
)

story = []

# Cover -------------------------------------------------
story.append(Paragraph("Product Launch Overview", styles["title"]))
story.append(Paragraph("Fictional Product – Q3 2026", styles["tag"]))
story.append(HRFlowable(width="100%", thickness=2, color=ACCENT, spaceBefore=6, spaceAfter=12))

# Key‑value callout table (light background)
callout_headers = ["Metric", "Value"]
callout_rows = [
    ["Product Name", product_name],
    ["Launch Date", launch_date],
    ["Tagline", tagline],
    ["Price", fmt_currency(price)],
    ["Target Market", target_market],
    ["Forecast Units", fmt_int(forecast_units)],
    ["Forecast Revenue", fmt_currency(forecast_revenue)],
]
callout_tbl = Table(
    [callout_headers] + callout_rows,
    colWidths=[50 * mm, 100 * mm],
    style=TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("TEXTCOLOR", (0, 0), (-1, 0), INK),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (0, 0), (0, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.5, ACCENT),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, ACCENT2),
            ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
        ]
    ),
)
story.append(callout_tbl)
story.append(PageBreak())

# Body -------------------------------------------------
# Executive Summary
story.append(Paragraph("Executive Summary", styles["h1"]))
summary_text = (
    f"The {product_name} is set to launch on {launch_date}, positioning itself as a "
    f"premium solution within the {target_market} sector. Priced at {fmt_currency(price)} "
    f"and backed by the tagline “{tagline}”, the product aims to capture a significant "
    f"share of the market through its innovative cloud‑optimization features."
)
story.append(Paragraph(summary_text, styles["body"]))
story.append(Spacer(1, 6 * mm))

# Key Metrics
story.append(Paragraph("Key Metrics", styles["h1"]))
story.append(Paragraph("Financial Projections", styles["h2"]))
metrics_headers = ["Metric", "Value"]
metrics_rows = [
    ["Price per Unit", fmt_currency(price)],
    ["Forecast Units Sold", fmt_int(forecast_units)],
    ["Forecast Revenue", fmt_currency(forecast_revenue)],
]
story.append(table(metrics_headers, metrics_rows, [70 * mm, 80 * mm]))
story.append(Spacer(1, 6 * mm))

# Marketing Plan
story.append(Paragraph("Marketing Plan", styles["h1"]))
marketing_text = (
    "A multi‑channel campaign will roll out three weeks prior to launch, leveraging "
    "digital advertising, industry webinars, and strategic partnerships with leading "
    "cloud providers. Early‑bird incentives include a 10% discount for the first 2,000 "
    "customers and exclusive onboarding support."
)
story.append(Paragraph(marketing_text, styles["body"]))
story.append(Spacer(1, 6 * mm))

# Risks & Mitigations
story.append(Paragraph("Risks & Mitigations", styles["h1"]))
risks = [
    "Supply chain delays – Mitigation: Secure secondary suppliers and maintain a 30‑day safety stock.",
    "Competitive response – Mitigation: Accelerate feature releases and offer bundled services.",
    "Adoption lag – Mitigation: Deploy targeted pilot programs with key enterprise accounts.",
]
for r in risks:
    story.append(Paragraph(f"• {r}", styles["lv"]))
story.append(Spacer(1, 6 * mm))

# Build PDF
doc.build(story)

print("done")
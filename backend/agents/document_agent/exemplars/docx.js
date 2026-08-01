// Urban Beekeeping Report – generated docx
const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  Table,
  TableRow,
  TableCell,
  AlignmentType,
  BorderStyle,
  WidthType,
  ShadingType,
  PageBreak,
  Header,
  Footer,
} = require("docx");
const fs = require("fs");

// ---------- Palette & borders ----------
const ACCENT = "1B5E20",
  ACCENT2 = "2E7D32",
  LIGHT = "E8F5E9";
const INK = "1A1A1A",
  BODY = "333333",
  MUTED = "888888";
const WHITE = "FFFFFF",
  GREY = "F5F5F5",
  LINE = "CCCCCC";
const FULL = 9360;
const border = { style: BorderStyle.SINGLE, size: 1, color: LINE };
const borders = { top: border, bottom: border, left: border, right: border };

// ---------- Reusable helpers ----------
const h1 = (t) =>
  new Paragraph({
    spacing: { before: 360, after: 140 },
    shading: { fill: ACCENT, type: ShadingType.CLEAR },
    children: [
      new TextRun({
        text: "  " + t,
        font: "Georgia",
        size: 28,
        bold: true,
        color: WHITE,
      }),
    ],
  });

const h2 = (t) =>
  new Paragraph({
    spacing: { before: 260, after: 100 },
    border: {
      left: { style: BorderStyle.THICK, size: 18, color: ACCENT2, space: 8 },
    },
    children: [
      new TextRun({
        text: t,
        font: "Georgia",
        size: 24,
        bold: true,
        color: ACCENT2,
      }),
    ],
  });

const h3 = (t) =>
  new Paragraph({
    spacing: { before: 180, after: 80 },
    children: [
      new TextRun({
        text: t,
        font: "Calibri",
        size: 22,
        bold: true,
        color: ACCENT,
      }),
    ],
  });

const p = (t, o = {}) =>
  new Paragraph({
    spacing: { before: 60, after: 100 },
    children: [
      new TextRun({
        text: t,
        font: "Calibri",
        size: 22,
        color: o.color || BODY,
        italics: !!o.italic,
        bold: !!o.bold,
      }),
    ],
  });

const lv = (label, val) =>
  new Paragraph({
    spacing: { before: 50, after: 70 },
    children: [
      new TextRun({
        text: label + ": ",
        font: "Calibri",
        size: 22,
        bold: true,
        color: ACCENT2,
      }),
      new TextRun({
        text: val,
        font: "Calibri",
        size: 22,
        color: INK,
      }),
    ],
  });

const bull = (t, lvl = 0) =>
  new Paragraph({
    numbering: { reference: "bul", level: lvl },
    spacing: { before: 40, after: 55 },
    children: [
      new TextRun({
        text: t,
        font: "Calibri",
        size: 22,
        color: BODY,
      }),
    ],
  });

function box(rows) {
  return new Table({
    width: { size: FULL, type: WidthType.DXA },
    columnWidths: [FULL],
    rows: [
      new TableRow({
        children: [
          new TableCell({
            shading: { fill: LIGHT, type: ShadingType.CLEAR },
            borders: {
              top: { style: BorderStyle.SINGLE, size: 6, color: ACCENT2 },
              bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT2 },
              left: { style: BorderStyle.SINGLE, size: 6, color: ACCENT2 },
              right: { style: BorderStyle.SINGLE, size: 6, color: ACCENT2 },
            },
            margins: { top: 150, bottom: 150, left: 220, right: 220 },
            children: rows,
          }),
        ],
      }),
    ],
  });
}

function tbl(headers, rows, colW) {
  const hRow = new TableRow({
    children: headers.map((h, i) =>
      new TableCell({
        width: { size: colW[i], type: WidthType.DXA },
        shading: { fill: ACCENT, type: ShadingType.CLEAR },
        borders,
        margins: { top: 80, bottom: 80, left: 110, right: 110 },
        children: [
          new Paragraph({
            children: [
              new TextRun({
                text: h,
                font: "Calibri",
                size: 19,
                bold: true,
                color: WHITE,
              }),
            ],
          }),
        ],
      })
    ),
  });

  const dRows = rows.map((row, ri) =>
    new TableRow({
      children: row.map((cell, ci) =>
        new TableCell({
          width: { size: colW[ci], type: WidthType.DXA },
          shading: { fill: ri % 2 ? GREY : WHITE, type: ShadingType.CLEAR },
          borders,
          margins: { top: 75, bottom: 75, left: 110, right: 110 },
          children: [
            new Paragraph({
              children: [
                new TextRun({
                  text: String(cell),
                  font: "Calibri",
                  size: 19,
                  color: INK,
                }),
              ],
            }),
          ],
        })
      ),
    })
  );

  return new Table({
    width: { size: colW.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: colW,
    rows: [hRow, ...dRows],
  });
}

// ---------- Data ----------
const cityData = [
  { city: "Portland", hives: 120, honeyKg: 300 },
  { city: "Seattle", hives: 95, honeyKg: 250 },
  { city: "San Francisco", hives: 80, honeyKg: 210 },
  { city: "New York", hives: 150, honeyKg: 380 },
];

const totalHives = cityData.reduce((sum, r) => sum + r.hives, 0);
const totalHoney = cityData.reduce((sum, r) => sum + r.honeyKg, 0);
const avgHoneyPerHive = (totalHoney / totalHives).toFixed(2);

// ---------- Cover ----------
const coverTitle = new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 720, after: 200 },
  children: [
    new TextRun({
      text: "Urban Beekeeping Report",
      font: "Georgia",
      size: 58,
      bold: true,
      color: ACCENT,
    }),
  ],
});

const tagline = new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 300 },
  children: [
    new TextRun({
      text: "Buzzing into the Future",
      font: "Calibri",
      size: 22,
      italics: true,
      color: MUTED,
    }),
  ],
});

const subtitleBar = new Paragraph({
  alignment: AlignmentType.CENTER,
  shading: { fill: ACCENT, type: ShadingType.CLEAR },
  spacing: { before: 200, after: 200 },
  children: [
    new TextRun({
      text: "State of Urban Beekeeping – 2024",
      font: "Calibri",
      size: 24,
      color: WHITE,
      bold: true,
    }),
  ],
});

const metaBox = box([
  lv("Prepared by", "Jane Doe"),
  lv("Date", "2024‑06‑21"),
  lv("Contact", "jane.doe@example.com"),
]);

const introPara = p(
  "This brief report provides an overview of the current state of urban beekeeping across major U.S. cities, highlighting key metrics, trends, and challenges."
);

// ---------- Body ----------
const execSummary = [
  h1("Executive Summary"),
  p(
    "Urban beekeeping continues to grow as cities embrace pollinator-friendly initiatives. Across four major metropolitan areas, a total of " +
      totalHives +
      " hives produce approximately " +
      totalHoney +
      " kg of honey annually, averaging " +
      avgHoneyPerHive +
      " kg per hive."
  ),
];

const landscape = [
  h2("Current Landscape"),
  p(
    "Cities are integrating rooftop apiaries, community gardens, and educational programs to support bee health. Municipal policies vary, but most encourage citizen participation."
  ),
];

const metrics = [
  h2("Key Metrics"),
  box([
    lv("Total Hives", totalHives.toString()),
    lv("Total Honey (kg)", totalHoney.toString()),
    lv("Average Honey per Hive (kg)", avgHoneyPerHive),
  ]),
  p("Detailed city‑level data:"),
  tbl(
    ["City", "Hives", "Honey Production (kg)"],
    cityData.map((r) => [r.city, r.hives, r.honeyKg]),
    [3000, 2000, 3000]
  ),
];

const challenges = [
  h2("Challenges & Opportunities"),
  bull("Limited green space for hive placement."),
  bull("Regulatory hurdles and zoning restrictions."),
  bull("Public awareness and education gaps."),
  bull("Potential for increased pollination services and local honey markets."),
];

const bodyChildren = [
  ...execSummary,
  ...landscape,
  ...metrics,
  ...challenges,
];

// ---------- Header & Footer ----------
const headerPara = new Paragraph({
  alignment: AlignmentType.RIGHT,
  border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: LINE } },
  children: [
    new TextRun({
      text: "Urban Beekeeping Report • 2024‑06‑21",
      font: "Calibri",
      size: 20,
      color: MUTED,
    }),
  ],
});

const footerPara = new Paragraph({
  alignment: AlignmentType.CENTER,
  border: { top: { style: BorderStyle.SINGLE, size: 4, color: LINE } },
  children: [
    new TextRun({
      text: "Jane Doe – jane.doe@example.com",
      font: "Calibri",
      size: 20,
      color: MUTED,
    }),
  ],
});

// ---------- Assemble Document ----------
const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bul",
        levels: [
          {
            level: 0,
            format: "bullet",
            text: "•",
            alignment: AlignmentType.LEFT,
            style: {
              paragraph: { indent: { left: 560, hanging: 280 } },
            },
          },
          {
            level: 1,
            format: "bullet",
            text: "◦",
            alignment: AlignmentType.LEFT,
            style: {
              paragraph: { indent: { left: 1000, hanging: 280 } },
            },
          },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 11906, height: 16838 },
          margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
        },
      },
      headers: { default: new Header({ children: [headerPara] }) },
      footers: { default: new Footer({ children: [footerPara] }) },
      children: [
        coverTitle,
        tagline,
        subtitleBar,
        metaBox,
        introPara,
        new Paragraph({ children: [new PageBreak()] }),
        ...bodyChildren,
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(
    "/workspace/output/urban_beekeeping_report.docx",
    buf
  );
  console.log("Report generated");
});
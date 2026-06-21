const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

// Palette
const C = {
  ink:    "1A1A1A",
  body:   "44403C",
  muted:  "78716C",
  bg:     "FAFAF9",
  card:   "FFFFFF",
  line:   "E7E5E4",
  accent: "0066CC",   // deep blue accent for AI theme
  accentLt:"DDEEFF",
  dark:   "0A1F33",
};

// Icons
const { FaQuestionCircle, FaCog, FaStar, FaHandshake } = require("react-icons/fa");

// Helpers
const shadow = () => ({
  type: "outer",
  color: "000000",
  blur: 8,
  offset: 3,
  angle: 135,
  opacity: 0.12,
});

function titleBar(slide, text) {
  slide.addShape("rect", {
    x: 0.45,
    y: 0.30,
    w: 0.06,
    h: 0.52,
    fill: { color: C.accent },
    line: { type: "none" },
  });
  slide.addText(text, {
    x: 0.62,
    y: 0.24,
    w: 9.0,
    h: 0.64,
    fontSize: 26,
    bold: true,
    color: C.ink,
    fontFace: "Georgia",
    valign: "middle",
    margin: 0,
  });
  slide.addShape("rect", {
    x: 0.45,
    y: 0.94,
    w: 9.1,
    h: 0.02,
    fill: { color: C.line },
    line: { type: "none" },
  });
  slide.background = { color: C.card };
}

function card(slide, x, y, w, h, fill = C.card) {
  slide.addShape("rect", {
    x,
    y,
    w,
    h,
    fill: { color: fill },
    line: { color: C.line, width: 0.5 },
    shadow: shadow(),
  });
}

function chip(slide, text, x, y) {
  const w = text.length * 0.085 + 0.3;
  slide.addShape("rect", {
    x,
    y,
    w,
    h: 0.26,
    fill: { color: C.accentLt },
    line: { type: "none" },
  });
  slide.addText(text.toUpperCase(), {
    x,
    y,
    w,
    h: 0.26,
    fontSize: 8,
    bold: true,
    color: C.accent,
    align: "center",
    valign: "middle",
    charSpacing: 1,
    margin: 0,
  });
}

// Render React icon to PNG data URL
async function icon(IconComp, color, size = 128) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComp, { color: "#" + color, size: String(size) })
  );
  const png = await sharp(Buffer.from(svg)).resize(size, size).png().toBuffer();
  return "data:image/png;base64," + png.toString("base64");
}

// Main async builder
async function main() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";

  // ---------- Title Slide ----------
  const titleSlide = pres.addSlide();
  titleSlide.background = { color: C.dark };
  // Translucent accent ellipses
  titleSlide.addShape("ellipse", {
    x: 6.5,
    y: -0.5,
    w: 5,
    h: 5,
    fill: { color: C.accent, transparency: 85 },
    line: { type: "none" },
  });
  titleSlide.addShape("ellipse", {
    x: -1,
    y: 2,
    w: 4,
    h: 4,
    fill: { color: C.accent, transparency: 85 },
    line: { type: "none" },
  });
  // Accent rect
  titleSlide.addShape("rect", {
    x: 0.45,
    y: 0.30,
    w: 0.06,
    h: 0.52,
    fill: { color: C.accent },
    line: { type: "none" },
  });
  // Eyebrow
  titleSlide.addText("Investor Pitch", {
    x: 0.62,
    y: 0.10,
    w: 9,
    h: 0.3,
    fontSize: 14,
    color: C.accentLt,
    fontFace: "Calibri",
    charSpacing: 2,
    bold: true,
    align: "left",
  });
  // Main title
  titleSlide.addText("DeepQuery", {
    x: 0.62,
    y: 0.5,
    w: 9,
    h: 1,
    fontSize: 58,
    color: "FFFFFF",
    fontFace: "Georgia",
    bold: true,
    align: "left",
  });
  // Subtitle
  titleSlide.addText("AI‑powered knowledge assistant for organizations", {
    x: 0.62,
    y: 1.6,
    w: 9,
    h: 0.5,
    fontSize: 24,
    color: C.accentLt,
    fontFace: "Calibri",
    italic: true,
    align: "left",
  });

  // ---------- Problem Slide ----------
  const problemSlide = pres.addSlide();
  titleBar(problemSlide, "The Problem");
  const probIcon = await icon(FaQuestionCircle, C.accent, 96);
  // Card 1
  const cardX = 0.45;
  const cardY = 1.2;
  const cardW = 4.2;
  const cardH = 2.5;
  card(problemSlide, cardX, cardY, cardW, cardH);
  problemSlide.addImage({ data: probIcon, x: cardX + 0.2, y: cardY + 0.2, w: 0.8, h: 0.8 });
  problemSlide.addText("Information silos", {
    x: cardX + 1.2,
    y: cardY + 0.3,
    w: 2.8,
    h: 0.4,
    fontSize: 18,
    bold: true,
    color: C.ink,
    fontFace: "Georgia",
  });
  problemSlide.addText(
    "Teams waste hours searching across tools and documents, leading to duplicated effort and missed insights.",
    {
      x: cardX + 1.2,
      y: cardY + 0.8,
      w: 2.8,
      h: 1.2,
      fontSize: 12,
      color: C.body,
      fontFace: "Calibri",
    }
  );
  // Card 2 (right column)
  const card2X = 5.0;
  const card2Y = 1.2;
  card(problemSlide, card2X, card2Y, cardW, cardH);
  problemSlide.addImage({ data: probIcon, x: card2X + 0.2, y: card2Y + 0.2, w: 0.8, h: 0.8 });
  problemSlide.addText("Knowledge loss", {
    x: card2X + 1.2,
    y: card2Y + 0.3,
    w: 2.8,
    h: 0.4,
    fontSize: 18,
    bold: true,
    color: C.ink,
    fontFace: "Georgia",
  });
  problemSlide.addText(
    "When employees leave, critical know‑how disappears, slowing projects and increasing onboarding costs.",
    {
      x: card2X + 1.2,
      y: card2Y + 0.8,
      w: 2.8,
      h: 1.2,
      fontSize: 12,
      color: C.body,
      fontFace: "Calibri",
    }
  );

  // ---------- How It Works Slide ----------
  const howSlide = pres.addSlide();
  titleBar(howSlide, "How DeepQuery Works");
  const cogIcon = await icon(FaCog, C.accent, 96);
  // Single wide card explaining flow
  const flowCardX = 0.45;
  const flowCardY = 1.2;
  const flowCardW = 9.1;
  const flowCardH = 3.0;
  card(howSlide, flowCardX, flowCardY, flowCardW, flowCardH);
  howSlide.addImage({ data: cogIcon, x: flowCardX + 0.3, y: flowCardY + 0.3, w: 1.0, h: 1.0 });
  howSlide.addText("AI‑driven Retrieval & Synthesis", {
    x: flowCardX + 1.5,
    y: flowCardY + 0.4,
    w: 7.0,
    h: 0.5,
    fontSize: 20,
    bold: true,
    color: C.ink,
    fontFace: "Georgia",
  });
  howSlide.addText(
    "1️⃣ Ingest data from all enterprise sources (Slack, Confluence, Email, etc.)\n" +
    "2️⃣ Index with large‑language‑model embeddings for semantic search\n" +
    "3️⃣ Answer queries in natural language, citing sources and providing concise summaries",
    {
      x: flowCardX + 1.5,
      y: flowCardY + 1.0,
      w: 7.0,
      h: 1.6,
      fontSize: 12,
      color: C.body,
      fontFace: "Calibri",
      lineSpacing: 120,
    }
  );

  // ---------- Key Benefits Slide ----------
  const benefitsSlide = pres.addSlide();
  titleBar(benefitsSlide, "Key Benefits");
  const starIcon = await icon(FaStar, C.accent, 96);
  const benefitData = [
    {
      title: "Instant Answers",
      body: "Reduce search time by 70% with AI‑powered, context‑aware responses.",
    },
    {
      title: "Knowledge Retention",
      body: "Capture institutional memory, easing onboarding and reducing turnover impact.",
    },
    {
      title: "Productivity Boost",
      body: "Free up 2‑3 hours per employee per week for higher‑value work.",
    },
  ];
  const benefitCardW = 2.9;
  const benefitCardH = 2.2;
  const startX = 0.45;
  const startY = 1.2;
  const gapX = 0.3;
  benefitData.forEach((b, i) => {
    const x = startX + i * (benefitCardW + gapX);
    const y = startY;
    card(benefitsSlide, x, y, benefitCardW, benefitCardH);
    benefitsSlide.addImage({ data: starIcon, x: x + 0.2, y: y + 0.2, w: 0.6, h: 0.6 });
    benefitsSlide.addText(b.title, {
      x: x + 0.9,
      y: y + 0.3,
      w: benefitCardW - 0.9,
      h: 0.4,
      fontSize: 16,
      bold: true,
      color: C.accent,
      fontFace: "Georgia",
    });
    benefitsSlide.addText(b.body, {
      x: x + 0.9,
      y: y + 0.8,
      w: benefitCardW - 0.9,
      h: 1.0,
      fontSize: 11,
      color: C.body,
      fontFace: "Calibri",
    });
  });

  // ---------- Closing Slide ----------
  const closeSlide = pres.addSlide();
  closeSlide.background = { color: C.dark };
  // Accent ellipse
  closeSlide.addShape("ellipse", {
    x: 5,
    y: 0,
    w: 5,
    h: 5,
    fill: { color: C.accent, transparency: 85 },
    line: { type: "none" },
  });
  // Thank you text
  closeSlide.addText("Thank You", {
    x: 0.45,
    y: 1.5,
    w: 9.1,
    h: 1,
    fontSize: 48,
    color: "FFFFFF",
    fontFace: "Georgia",
    bold: true,
    align: "center",
  });
  // Contact
  const handIcon = await icon(FaHandshake, "FFFFFF", 96);
  closeSlide.addImage({ data: handIcon, x: 4.5, y: 3.0, w: 1.0, h: 1.0 });
  closeSlide.addText("Contact: info@deepquery.ai", {
    x: 0.45,
    y: 4.2,
    w: 9.1,
    h: 0.4,
    fontSize: 14,
    color: "FFFFFF",
    fontFace: "Calibri",
    align: "center",
  });

  // Write file
  await pres.writeFile({ fileName: "/workspace/output/deepquery_pitch.pptx" });
  console.log("Deck created at /workspace/output/deepquery_pitch.pptx");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
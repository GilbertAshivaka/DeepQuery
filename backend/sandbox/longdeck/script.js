// Quantum Computing Intro Deck – 12 slides
// Node.js script using pptxgenjs, react-icons, sharp
// Saves to /workspace/output/quantum_computing_deck.pptx

const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const {
  FaAtom,
  FaMicrochip,
  FaWaveSquare,
  FaLink,
  FaCogs,
  FaBrain,
  FaServer,
  FaExclamationTriangle,
  FaLightbulb,
  FaCheckCircle,
} = require("react-icons/fa");

// ---------- Palette ----------
const C = {
  ink: "1A1A1A",
  body: "44403C",
  muted: "78716C",
  bg: "FAFAF9",
  card: "FFFFFF",
  line: "E7E5E4",
  accent: "0A74DA",      // calm tech blue
  accentLt: "DCE9F9",
  dark: "0A1F33",
};

// ---------- Helpers ----------
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

async function icon(IconComp, color, size = 128) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComp, { color: "#" + color, size: String(size) })
  );
  const png = await sharp(Buffer.from(svg)).resize(size, size).png().toBuffer();
  return "data:image/png;base64," + png.toString("base64");
}

// ---------- Slide Builders ----------
async function addTitleSlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: C.dark };
  // Translucent accent ellipses
  slide.addShape("ellipse", {
    x: 6,
    y: -1,
    w: 5,
    h: 5,
    fill: { color: C.accent, transparency: 85 },
    line: { type: "none" },
  });
  slide.addShape("ellipse", {
    x: -1,
    y: 2,
    w: 4,
    h: 4,
    fill: { color: C.accent, transparency: 85 },
    line: { type: "none" },
  });
  // Accent rect
  slide.addShape("rect", {
    x: 0.45,
    y: 0.30,
    w: 0.06,
    h: 0.52,
    fill: { color: C.accent },
    line: { type: "none" },
  });
  // Eyebrow
  slide.addText("Quantum Computing 101", {
    x: 0.62,
    y: 0.10,
    w: 9,
    h: 0.3,
    fontSize: 12,
    color: C.accentLt,
    fontFace: "Calibri",
    charSpacing: 2,
    uppercase: true,
  });
  // Main title
  slide.addText("An Introductory Guide", {
    x: 0.62,
    y: 0.45,
    w: 9,
    h: 1,
    fontSize: 58,
    color: "FFFFFF",
    fontFace: "Georgia",
    bold: true,
  });
  // Subtitle
  slide.addText("Understanding the basics of quantum computers", {
    x: 0.62,
    y: 1.2,
    w: 9,
    h: 0.5,
    fontSize: 20,
    color: C.accentLt,
    fontFace: "Calibri",
    italic: true,
  });
}

async function addClosingSlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: C.dark };
  slide.addShape("rect", {
    x: 0.45,
    y: 0.30,
    w: 0.06,
    h: 0.52,
    fill: { color: C.accent },
    line: { type: "none" },
  });
  slide.addText("Thank You", {
    x: 0.62,
    y: 0.45,
    w: 9,
    h: 1,
    fontSize: 54,
    color: "FFFFFF",
    fontFace: "Georgia",
    bold: true,
  });
  slide.addText("Questions? Reach out at quantum@example.com", {
    x: 0.62,
    y: 1.3,
    w: 9,
    h: 0.5,
    fontSize: 18,
    color: C.accentLt,
    fontFace: "Calibri",
    italic: true,
  });
}

// Generic content slide with icon + bullets
async function addContentSlide(pres, title, bullets, IconComp) {
  const slide = pres.addSlide();
  titleBar(slide, title);
  // Card for body
  const cardX = 0.6,
    cardY = 1.2,
    cardW = 8.5,
    cardH = 3.5;
  card(slide, cardX, cardY, cardW, cardH);
  // Icon
  const iconData = await icon(IconComp, C.accent, 96);
  slide.addImage({
    data: iconData,
    x: cardX + 0.15,
    y: cardY + 0.15,
    w: 0.8,
    h: 0.8,
  });
  // Bullets
  const bulletText = bullets.map((b) => "• " + b).join("\n");
  slide.addText(bulletText, {
    x: cardX + 1.1,
    y: cardY + 0.2,
    w: cardW - 1.3,
    h: cardH - 0.4,
    fontSize: 14,
    color: C.body,
    fontFace: "Calibri",
    lineSpacing: 1.2,
  });
}

// ---------- Main ----------
async function main() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";

  await addTitleSlide(pres);

  await addContentSlide(pres, "What is Quantum Computing?", [
    "Uses quantum bits (qubits) to process information",
    "Leverages quantum phenomena like superposition and entanglement",
    "Promises exponential speed‑ups for certain problems",
  ], FaAtom);

  await addContentSlide(pres, "Qubits", [
    "Basic unit of quantum information",
    "Can represent 0, 1, or both simultaneously",
    "Physical implementations: superconducting circuits, trapped ions, etc.",
  ], FaMicrochip);

  await addContentSlide(pres, "Superposition", [
    "Qubit can be in a linear combination of states",
    "Enables parallel computation paths",
    "Visualized as a vector on the Bloch sphere",
  ], FaWaveSquare);

  await addContentSlide(pres, "Entanglement", [
    "Correlation between qubits stronger than classical physics allows",
    "State of one qubit instantly influences the other",
    "Key resource for quantum algorithms and communication",
  ], FaLink);

  await addContentSlide(pres, "Quantum Gates", [
    "Operations that change qubit states",
    "Common gates: X, H, CNOT, T, etc.",
    "Form quantum circuits analogous to classical logic gates",
  ], FaCogs);

  await addContentSlide(pres, "Algorithms", [
    "Shor’s algorithm – integer factorization",
    "Grover’s algorithm – unstructured search",
    "Both demonstrate quantum advantage over classical methods",
  ], FaBrain);

  await addContentSlide(pres, "Hardware Platforms", [
    "Superconducting qubits (IBM, Google)",
    "Trapped‑ion systems (IonQ, Honeywell)",
    "Photonic and topological approaches under research",
  ], FaServer);

  await addContentSlide(pres, "Challenges", [
    "Decoherence and error rates",
    "Scalability to thousands of qubits",
    "Need for quantum error correction",
  ], FaExclamationTriangle);

  await addContentSlide(pres, "Applications", [
    "Cryptography and security",
    "Materials science and chemistry simulations",
    "Optimization, machine learning, and finance",
  ], FaLightbulb);

  await addContentSlide(pres, "Summary", [
    "Quantum computers process information fundamentally differently",
    "Key concepts: qubits, superposition, entanglement, gates",
    "Rapidly evolving field with transformative potential",
  ], FaCheckCircle);

  await addClosingSlide(pres);

  await pres.writeFile({ fileName: "/workspace/output/quantum_computing_deck.pptx" });
  console.log("Deck created at /workspace/output/quantum_computing_deck.pptx");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
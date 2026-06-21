// DeepQuery Pitch Deck Generator
// Requires: pptxgenjs, fs, path, react, react-dom/server, sharp, react-icons/fa

const PPTXGenJS = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const React = require('react');
const ReactDOMServer = require('react-dom/server');
const sharp = require('sharp');
const {
  FaRocket,
  FaLightbulb,
  FaCog,
  FaStar,
} = require('react-icons/fa');

// ---------- PALETTE ----------
const PALETTE = {
  accent: '#0066CC',          // primary blue
  secondary: '#0099FF',       // lighter blue
  background: '#F7F9FC',      // very light gray-blue
  textPrimary: '#212B36',     // dark charcoal
  textSecondary: '#5A6B7C',   // medium gray
};

// ---------- ICON HELPER ----------
async function iconPng(Comp, color, size = 128) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Comp, { color: color, size: size })
  );
  const buffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return 'data:image/png;base64,' + buffer.toString('base64');
}

// ---------- REUSABLE HELPERS ----------
function addAccentBar(slide) {
  slide.addShape('rect', {
    x: 0,
    y: 0,
    w: '100%',
    h: 0.2,
    fill: { color: PALETTE.accent },
    line: { color: PALETTE.accent },
  });
}

function addTitle(slide, text, opts = {}) {
  slide.addText(text, {
    x: 0.5,
    y: 1.5,
    w: 9,
    fontFace: 'Georgia',
    fontSize: 48,
    color: PALETTE.textPrimary,
    bold: true,
    align: 'center',
    ...opts,
  });
}

function addSubtitle(slide, text, opts = {}) {
  slide.addText(text, {
    x: 0.5,
    y: 3,
    w: 9,
    fontFace: 'Calibri',
    fontSize: 24,
    color: PALETTE.textSecondary,
    align: 'center',
    ...opts,
  });
}

function addSectionHeader(slide, eyebrow, title) {
  // Eyebrow
  slide.addText(eyebrow.toUpperCase(), {
    x: 0.5,
    y: 0.5,
    w: 9,
    fontFace: 'Calibri',
    fontSize: 14,
    color: PALETTE.secondary,
    bold: true,
    letterSpacing: 100,
  });
  // Title
  slide.addText(title, {
    x: 0.5,
    y: 0.9,
    w: 9,
    fontFace: 'Georgia',
    fontSize: 36,
    color: PALETTE.textPrimary,
    bold: true,
  });
}

// ---------- MAIN ----------
async function main() {
  const pres = new PPTXGenJS();
  pres.defineLayout({ name: 'A4', width: 10, height: 5.625 });
  pres.layout = 'A4';
  pres.author = 'DeepQuery Pitch Generator';

  // ---- Slide 1: Cover ----
  const slide1 = pres.addSlide();
  slide1.background = { fill: PALETTE.background };
  addAccentBar(slide1);
  const icon1 = await iconPng(FaRocket, PALETTE.accent, 256);
  slide1.addImage({ data: icon1, x: 4.5, y: 0.8, w: 1, h: 1 });
  addTitle(slide1, 'DeepQuery');
  addSubtitle(slide1, 'AI Knowledge Assistant for Organizations');

  // ---- Slide 2: The Problem ----
  const slide2 = pres.addSlide();
  slide2.background = { fill: PALETTE.background };
  addAccentBar(slide2);
  addSectionHeader(slide2, 'Problem', 'Information Silos Stifle Growth');
  const icon2 = await iconPng(FaLightbulb, PALETTE.secondary, 128);
  slide2.addImage({ data: icon2, x: 0.5, y: 2, w: 0.8, h: 0.8 });
  slide2.addText(
    [
      { text: '• Employees waste up to 30% of their time searching for information.\n', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
      { text: '• Knowledge is trapped in emails, documents, and disparate tools.\n', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
      { text: '• Poor knowledge access leads to slower decisions and missed opportunities.', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
    ],
    { x: 1.5, y: 2, w: 8, lineSpacing: 120 }
  );

  // ---- Slide 3: How It Works ----
  const slide3 = pres.addSlide();
  slide3.background = { fill: PALETTE.background };
  addAccentBar(slide3);
  addSectionHeader(slide3, 'Solution', 'A Unified AI-Powered Knowledge Hub');
  const icon3 = await iconPng(FaCog, PALETTE.secondary, 128);
  slide3.addImage({ data: icon3, x: 0.5, y: 2, w: 0.8, h: 0.8 });
  slide3.addText(
    [
      { text: '1. Centralize all organizational data sources.\n', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
      { text: '2. Apply large‑language‑model AI to index and understand content.\n', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
      { text: '3. Provide a natural‑language chat interface for instant answers.', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
    ],
    { x: 1.5, y: 2, w: 8, lineSpacing: 120 }
  );

  // ---- Slide 4: Key Benefits ----
  const slide4 = pres.addSlide();
  slide4.background = { fill: PALETTE.background };
  addAccentBar(slide4);
  addSectionHeader(slide4, 'Benefits', 'Why Investors Should Care');
  const icon4 = await iconPng(FaStar, PALETTE.secondary, 128);
  slide4.addImage({ data: icon4, x: 0.5, y: 2, w: 0.8, h: 0.8 });
  slide4.addText(
    [
      { text: '• 40% reduction in knowledge‑search time → higher productivity.\n', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
      { text: '• Faster decision‑making accelerates revenue growth.\n', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
      { text: '• Scalable AI platform with low marginal cost per user.\n', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
      { text: '• Strong moat: proprietary data integration & AI tuning.', options: { fontFace: 'Calibri', fontSize: 18, color: PALETTE.textPrimary } },
    ],
    { x: 1.5, y: 2, w: 8, lineSpacing: 120 }
  );

  // ---- Write File ----
  const outPath = '/workspace/output/DeepQueryPitch.pptx';
  await pres.writeFile({ fileName: outPath });
  console.log(`Presentation generated at ${outPath}`);
}

main().catch(e => {
  console.error('Error generating presentation:', e);
  process.exit(1);
});
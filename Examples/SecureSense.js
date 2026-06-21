"use strict";
const path = require("path");
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.title = "SecureSense - Cybersecurity Awareness Training Platform";

// ─── PALETTE ───────────────────────────────────────────────────────────────
const C = {
  orange:     "EA580C",   // primary accent
  orangeLight:"FFF7ED",   // very light orange tint
  orangeMid:  "FED7AA",   // medium orange tint
  white:      "FFFFFF",
  bg:         "FAFAF9",   // light warm gray
  dark:       "1C1917",   // stone-900
  mid:        "44403C",   // stone-700
  muted:      "78716C",   // stone-500
  subtle:     "E7E5E4",   // stone-200
  subtleLight:"F5F5F4",   // stone-100
  green:      "16A34A",
  greenLight: "DCFCE7",
};

// ─── HELPERS ───────────────────────────────────────────────────────────────
function titleBar(slide, text) {
  // Orange left accent + title text
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.45, y: 0.28, w: 0.06, h: 0.52,
    fill: { color: C.orange }, line: { type: "none" }
  });
  slide.addText(text, {
    x: 0.6, y: 0.22, w: 9.0, h: 0.65,
    fontSize: 26, bold: true, color: C.dark,
    fontFace: "Trebuchet MS", valign: "middle", align: "left", margin: 0
  });
  // Subtle separator
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.45, y: 0.92, w: 9.1, h: 0.02,
    fill: { color: C.subtle }, line: { type: "none" }
  });
  slide.background = { color: C.white };
}

function slideNumber(slide, n) {
  slide.addText(`${n} / 14`, {
    x: 8.8, y: 5.3, w: 0.9, h: 0.22,
    fontSize: 9, color: C.muted, align: "right", fontFace: "Calibri"
  });
}

function chip(slide, label, x, y, w, bg, fg) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h: 0.28,
    fill: { color: bg }, line: { type: "none" }, rectRadius: 0.04
  });
  slide.addText(label, {
    x, y, w, h: 0.28,
    fontSize: 8.5, bold: true, color: fg, align: "center",
    fontFace: "Calibri", valign: "middle"
  });
}

function badgeCard(slide, badge, criteria, x, y) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 4.2, h: 0.52,
    fill: { color: C.subtleLight }, line: { color: C.subtle, pt: 0.5 }
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 0.06, h: 0.52,
    fill: { color: C.orange }, line: { type: "none" }
  });
  slide.addText([
    { text: badge, options: { bold: true, color: C.dark, fontSize: 9.5 } },
  ], { x: x + 0.12, y, w: 1.5, h: 0.52, fontFace: "Calibri", valign: "middle", margin: [0,0,0,4] });
  slide.addText(criteria, {
    x: x + 1.62, y, w: 2.52, h: 0.52,
    fontSize: 9, color: C.mid, fontFace: "Calibri", valign: "middle", margin: [0,0,0,4]
  });
}

// ─── SLIDE 1 — TITLE ───────────────────────────────────────────────────────
{
  const s = pres.addSlide();
  s.background = { color: C.dark };

  // Big orange geometric block top-right
  s.addShape(pres.shapes.RECTANGLE, {
    x: 7.4, y: 0, w: 2.6, h: 5.625,
    fill: { color: C.orange }, line: { type: "none" }
  });
  // Lighter overlay strip
  s.addShape(pres.shapes.RECTANGLE, {
    x: 7.1, y: 0, w: 0.4, h: 5.625,
    fill: { color: "C2410C", transparency: 40 }, line: { type: "none" }
  });

  // Logo/Brand mark — shield icon made from shapes
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.55, y: 0.6, w: 0.72, h: 0.78,
    fill: { color: C.orange }, line: { type: "none" }, rectRadius: 0.08
  });
  s.addText("🛡", { x: 0.55, y: 0.58, w: 0.72, h: 0.82, fontSize: 22, align: "center", valign: "middle" });

  // Title
  s.addText("SecureSense", {
    x: 0.5, y: 1.55, w: 6.6, h: 1.1,
    fontSize: 52, bold: true, color: C.white,
    fontFace: "Trebuchet MS", align: "left", charSpacing: -1
  });

  // Orange accent underline
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 2.68, w: 1.4, h: 0.07,
    fill: { color: C.orange }, line: { type: "none" }
  });

  // Subtitle
  s.addText("A Cybersecurity Awareness Training Platform", {
    x: 0.5, y: 2.82, w: 6.6, h: 0.55,
    fontSize: 17, color: "D6D3D1",
    fontFace: "Calibri", align: "left", italic: true
  });

  // Info block
  const infoItems = [
    ["Student Name", "[Your Name]"],
    ["Student ID",   "[Your ID]"],
    ["Supervisor",   "[Your Supervisor's Name]"],
    ["Institution",  "[Your Institution Name]"],
    ["Date",         "22 May 2026"],
  ];
  infoItems.forEach(([label, val], i) => {
    const y = 3.55 + i * 0.36;
    s.addText(label + ":", { x: 0.5, y, w: 1.6, h: 0.3, fontSize: 9.5, color: C.muted, fontFace: "Calibri", bold: true });
    s.addText(val, { x: 2.1, y, w: 4.8, h: 0.3, fontSize: 9.5, color: "D6D3D1", fontFace: "Calibri" });
  });

  // White vertical text on orange block
  s.addText("FINAL YEAR PROJECT DEFENSE", {
    x: 7.42, y: 0.2, w: 2.52, h: 5.2,
    fontSize: 10, color: "FFFFFF", bold: true, align: "center", valign: "middle",
    fontFace: "Trebuchet MS", rotate: 90, charSpacing: 5, transparency: 20
  });
}

// ─── SLIDE 2 — PROBLEM STATEMENT ────────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "The Problem");
  slideNumber(s, 2);

  // Four problem cards
  const problems = [
    { icon: "📈", title: "Rising Threats", body: "Phishing & weak passwords remain the #1 cause of data breaches worldwide" },
    { icon: "🎣", title: "Low Awareness", body: "Most users cannot identify phishing emails or create strong, secure passwords" },
    { icon: "😴", title: "Passive Training", body: "Traditional security training is boring, forgettable, and fails to change behaviour" },
    { icon: "🚫", title: "No Engaging Platform", body: "No widely accessible, gamified platform actively trains everyday users in security hygiene" },
  ];

  problems.forEach((p, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.45 + col * 4.65;
    const y = 1.15 + row * 2.05;

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 4.35, h: 1.82,
      fill: { color: C.subtleLight },
      line: { color: C.subtle, pt: 0.75 },
      shadow: { type: "outer", blur: 6, offset: 2, angle: 135, color: "000000", opacity: 0.07 }
    });
    // Top orange accent
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 4.35, h: 0.07,
      fill: { color: C.orange }, line: { type: "none" }
    });
    s.addText(p.icon, { x: x + 0.18, y: y + 0.18, w: 0.65, h: 0.65, fontSize: 26, align: "center", valign: "middle" });
    s.addText(p.title, {
      x: x + 0.9, y: y + 0.15, w: 3.3, h: 0.4,
      fontSize: 13, bold: true, color: C.dark, fontFace: "Trebuchet MS", valign: "middle"
    });
    s.addText(p.body, {
      x: x + 0.12, y: y + 0.62, w: 4.1, h: 1.0,
      fontSize: 11, color: C.mid, fontFace: "Calibri", wrap: true
    });
  });

  // Presenter note
  s.addNotes("Set up why this project matters. Be direct — this is a real-world problem.");
}

// ─── SLIDE 3 — OBJECTIVES ───────────────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "Project Objectives");
  slideNumber(s, 3);

  s.addText("SecureSense was designed to deliver a web-based cybersecurity awareness platform that:", {
    x: 0.45, y: 1.0, w: 9.1, h: 0.4,
    fontSize: 12, color: C.mid, fontFace: "Calibri", italic: true
  });

  const objectives = [
    "Allows users to identify phishing emails through simulated scenario-based training",
    "Provides a real-time password strength evaluator with actionable feedback",
    "Uses gamification (points, badges, streaks, leaderboard) to drive user engagement",
    "Leverages AI to dynamically generate unlimited, diverse training content",
    "Provides an admin panel for full platform management and oversight",
  ];

  objectives.forEach((obj, i) => {
    const y = 1.52 + i * 0.75;

    // Number circle
    s.addShape(pres.shapes.OVAL, {
      x: 0.45, y: y + 0.02, w: 0.38, h: 0.38,
      fill: { color: C.orange }, line: { type: "none" }
    });
    s.addText(String(i + 1), {
      x: 0.45, y: y + 0.02, w: 0.38, h: 0.38,
      fontSize: 12, bold: true, color: C.white, align: "center", valign: "middle", fontFace: "Trebuchet MS"
    });

    // Row bg
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.92, y, w: 8.63, h: 0.62,
      fill: { color: i % 2 === 0 ? C.subtleLight : C.white },
      line: { color: C.subtle, pt: 0.5 }
    });
    s.addText(obj, {
      x: 1.08, y, w: 8.3, h: 0.62,
      fontSize: 12, color: C.dark, fontFace: "Calibri", valign: "middle"
    });
  });

  s.addNotes("These are your 5 core objectives. You will come back to each of these on the fulfillment slide.");
}

// ─── SLIDE 4 — SYSTEM OVERVIEW ──────────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "What is SecureSense?");
  slideNumber(s, 4);

  // Left column — two core modules
  s.addText("Two Core Training Modules", {
    x: 0.45, y: 1.05, w: 5.6, h: 0.34,
    fontSize: 12, bold: true, color: C.orange, fontFace: "Trebuchet MS"
  });

  const modules = [
    {
      icon: "🎣",
      title: "Phishing Detection Trainer",
      desc: "Users are shown realistic simulated emails and must decide: Phishing or Legitimate? AI-powered feedback follows each answer.",
    },
    {
      icon: "🔑",
      title: "Password Strength Evaluator",
      desc: "Users enter a password and receive a real-time score (0–100), strength label, visual meter, and improvement tips.",
    },
  ];

  modules.forEach((m, i) => {
    const y = 1.46 + i * 1.65;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.45, y, w: 5.5, h: 1.5,
      fill: { color: C.white },
      line: { color: C.orange, pt: 1.5 },
      shadow: { type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.08 }
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.45, y, w: 0.08, h: 1.5,
      fill: { color: C.orange }, line: { type: "none" }
    });
    s.addText(m.icon, { x: 0.6, y: y + 0.3, w: 0.6, h: 0.6, fontSize: 24, align: "center" });
    s.addText(m.title, {
      x: 1.25, y: y + 0.12, w: 4.55, h: 0.38,
      fontSize: 13, bold: true, color: C.dark, fontFace: "Trebuchet MS"
    });
    s.addText(m.desc, {
      x: 1.25, y: y + 0.52, w: 4.55, h: 0.85,
      fontSize: 10.5, color: C.mid, fontFace: "Calibri", wrap: true
    });
  });

  // Right column — supporting features
  s.addText("Supporting Features", {
    x: 6.2, y: 1.05, w: 3.25, h: 0.34,
    fontSize: 12, bold: true, color: C.orange, fontFace: "Trebuchet MS"
  });

  const features = [
    ["🔐", "JWT-secured login & registration"],
    ["📊", "Personal dashboard — stats, streaks, badges"],
    ["🏆", "Global leaderboard — Top 20 users"],
    ["⚙️", "Admin panel — manage users & scenarios"],
  ];
  features.forEach((f, i) => {
    const y = 1.46 + i * 0.88;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 6.2, y, w: 3.25, h: 0.76,
      fill: { color: C.subtleLight }, line: { color: C.subtle, pt: 0.5 }, rectRadius: 0.06
    });
    s.addText(f[0], { x: 6.28, y: y + 0.08, w: 0.42, h: 0.6, fontSize: 18, align: "center", valign: "middle" });
    s.addText(f[1], {
      x: 6.72, y, w: 2.65, h: 0.76,
      fontSize: 10.5, color: C.dark, fontFace: "Calibri", valign: "middle", wrap: true
    });
  });
}

// ─── SLIDE 5 — SYSTEM ARCHITECTURE ─────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "System Architecture");
  slideNumber(s, 5);

  const layers = [
    {
      label: "Frontend",
      tech: "React 19 + Vite + Tailwind CSS",
      color: "1D4ED8",
      lightColor: "EFF6FF",
      borderColor: "BFDBFE",
      icon: "🖥",
      items: ["Single Page Application (SPA)", "Login · Register · Dashboard · Phishing Trainer", "Password Checker · Leaderboard · Admin"],
    },
    {
      label: "Backend",
      tech: "Python + FastAPI",
      color: "059669",
      lightColor: "F0FDF4",
      borderColor: "A7F3D0",
      icon: "⚙️",
      items: ["RESTful API — 6 Routers: Auth, Phishing, Password, Dashboard, Leaderboard, Admin", "JWT Auth · Rate limiting (slowapi) · CORS", "Services: scoring, badge awards, AI generation"],
    },
    {
      label: "Database",
      tech: "SQLite via SQLAlchemy (async)",
      color: "7C3AED",
      lightColor: "F5F3FF",
      borderColor: "DDD6FE",
      icon: "🗄",
      items: ["Tables: Users · PhishingScenarios · UserAttempts", "Badges · UserBadges · PasswordCheckLogs"],
    },
    {
      label: "AI Service",
      tech: "Groq LLM API",
      color: "EA580C",
      lightColor: "FFF7ED",
      borderColor: "FED7AA",
      icon: "🤖",
      items: ["Generates new phishing scenarios on demand", "Personalised feedback referencing specific emails"],
    },
  ];

  layers.forEach((l, i) => {
    const x = 0.45 + i * 2.32;
    const cardH = 3.6;
    const y = 1.1;

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 2.12, h: cardH,
      fill: { color: l.lightColor }, line: { color: l.borderColor, pt: 1 }
    });
    // Header
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 2.12, h: 0.72,
      fill: { color: l.color }, line: { type: "none" }
    });
    s.addText(l.icon + "  " + l.label, {
      x: x + 0.06, y: y + 0.02, w: 2.0, h: 0.36,
      fontSize: 11, bold: true, color: "FFFFFF", fontFace: "Trebuchet MS", valign: "middle"
    });
    s.addText(l.tech, {
      x: x + 0.06, y: y + 0.36, w: 2.0, h: 0.3,
      fontSize: 8.5, color: "FFFFFF", fontFace: "Calibri", valign: "middle", italic: true
    });

    // Items
    l.items.forEach((item, j) => {
      s.addText([{ text: item, options: { bullet: true } }], {
        x: x + 0.1, y: y + 0.82 + j * 0.82, w: 1.9, h: 0.78,
        fontSize: 9, color: C.dark, fontFace: "Calibri", wrap: true
      });
    });
  });

  // Arrows between layers
  [0,1,2].forEach(i => {
    const arrowX = 0.45 + (i + 1) * 2.32 - 0.18;
    s.addShape(pres.shapes.RECTANGLE, {
      x: arrowX - 0.01, y: 2.55, w: 0.18, h: 0.04,
      fill: { color: C.muted }, line: { type: "none" }
    });
  });
}

// ─── SLIDE 6 — PHISHING TRAINER ─────────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "Feature 1 — Phishing Detection Trainer");
  slideNumber(s, 6);

  // Left: How it works — numbered flow
  s.addText("How It Works", {
    x: 0.45, y: 1.05, w: 5.1, h: 0.32,
    fontSize: 11.5, bold: true, color: C.orange, fontFace: "Trebuchet MS"
  });

  const steps = [
    "User is shown a realistic simulated email (subject, sender, HTML body)",
    "Countdown timer adds pressure — faster correct answers earn bonus points",
    "User clicks Phishing or Legitimate",
    "System awards points (10 base + 5 speed bonus) and checks for badges",
    "Groq LLM generates personalised feedback referencing the specific email",
  ];

  steps.forEach((step, i) => {
    const y = 1.42 + i * 0.7;
    s.addShape(pres.shapes.OVAL, {
      x: 0.45, y: y + 0.04, w: 0.32, h: 0.32,
      fill: { color: C.orange }, line: { type: "none" }
    });
    s.addText(String(i + 1), {
      x: 0.45, y: y + 0.04, w: 0.32, h: 0.32,
      fontSize: 10, bold: true, color: C.white, align: "center", valign: "middle", fontFace: "Trebuchet MS"
    });
    // Connector line
    if (i < steps.length - 1) {
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.59, y: y + 0.36, w: 0.04, h: 0.38,
        fill: { color: C.subtle }, line: { type: "none" }
      });
    }
    s.addText(step, {
      x: 0.88, y: y, w: 4.72, h: 0.62,
      fontSize: 10.5, color: C.dark, fontFace: "Calibri", valign: "middle", wrap: true
    });
  });

  // Right: Smart content delivery
  s.addShape(pres.shapes.RECTANGLE, {
    x: 6.0, y: 1.05, w: 3.55, h: 3.6,
    fill: { color: C.orangeLight }, line: { color: C.orangeMid, pt: 1 }
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 6.0, y: 1.05, w: 3.55, h: 0.06,
    fill: { color: C.orange }, line: { type: "none" }
  });
  s.addText("🧠  Smart Content Delivery", {
    x: 6.1, y: 1.12, w: 3.35, h: 0.42,
    fontSize: 12, bold: true, color: C.dark, fontFace: "Trebuchet MS"
  });
  const smartItems = [
    "Serves pre-seeded scenarios the user hasn't yet seen",
    "When all scenarios exhausted → AI generates a brand-new one on the fly",
    "Admin can trigger bulk AI generation (1–20 new scenarios at once)",
    "Difficulty levels: Easy · Medium · Hard",
  ];
  s.addText(smartItems.map(t => ({ text: t, options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } })), {
    x: 6.1, y: 1.62, w: 3.35, h: 2.9,
    fontSize: 10.5, color: C.dark, fontFace: "Calibri", wrap: true
  });

  // Scoring chips
  s.addText("Scoring at a Glance", {
    x: 0.45, y: 4.85, w: 3.5, h: 0.25,
    fontSize: 9, bold: true, color: C.muted, fontFace: "Calibri"
  });
  chip(s, "✅ Correct Answer: +10 pts", 0.45, 5.12, 2.1, C.orange, C.white);
  chip(s, "⚡ Speed Bonus (<15s): +5 pts", 2.65, 5.12, 2.4, C.dark, C.white);
}

// ─── SLIDE 7 — PASSWORD EVALUATOR ───────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "Feature 2 — Password Strength Evaluator");
  slideNumber(s, 7);

  // Left: criteria
  s.addText("7 Real-Time Evaluation Criteria", {
    x: 0.45, y: 1.05, w: 5.5, h: 0.32,
    fontSize: 11.5, bold: true, color: C.orange, fontFace: "Trebuchet MS"
  });

  const criteria = [
    "Minimum length (8–12+ characters)",
    "Uppercase and lowercase letters present",
    "Contains digits",
    "Contains special characters",
    "Not in a common passwords list",
    "No repeating characters (e.g. 'aaa')",
    "Entropy-based scoring component",
  ];
  criteria.forEach((c, i) => {
    const y = 1.44 + i * 0.52;
    s.addShape(pres.shapes.OVAL, {
      x: 0.45, y: y + 0.06, w: 0.26, h: 0.26,
      fill: { color: C.green }, line: { type: "none" }
    });
    s.addText("✓", {
      x: 0.45, y: y + 0.06, w: 0.26, h: 0.26,
      fontSize: 9, bold: true, color: C.white, align: "center", valign: "middle"
    });
    s.addText(c, {
      x: 0.82, y, w: 4.8, h: 0.48,
      fontSize: 11, color: C.dark, fontFace: "Calibri", valign: "middle"
    });
  });

  // Right: strength scale visual
  s.addShape(pres.shapes.RECTANGLE, {
    x: 6.0, y: 1.05, w: 3.55, h: 4.3,
    fill: { color: C.subtleLight }, line: { color: C.subtle, pt: 1 }
  });
  s.addText("Score Scale (0–100)", {
    x: 6.12, y: 1.15, w: 3.3, h: 0.32,
    fontSize: 11.5, bold: true, color: C.dark, fontFace: "Trebuchet MS"
  });

  const bands = [
    { label: "Very Weak",  range: "0–20",   color: "DC2626", light: "FEF2F2" },
    { label: "Weak",       range: "21–40",  color: "EA580C", light: "FFF7ED" },
    { label: "Fair",       range: "41–60",  color: "D97706", light: "FFFBEB" },
    { label: "Strong",     range: "61–80",  color: "16A34A", light: "F0FDF4" },
    { label: "Very Strong",range: "81–100", color: "065F46", light: "ECFDF5" },
  ];
  bands.forEach((b, i) => {
    const y = 1.55 + i * 0.6;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 6.1, y, w: 3.3, h: 0.52,
      fill: { color: b.light }, line: { color: b.color, pt: 0.5 }
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 6.1, y, w: 0.07, h: 0.52,
      fill: { color: b.color }, line: { type: "none" }
    });
    s.addText(b.label, {
      x: 6.25, y: y + 0.01, w: 1.7, h: 0.5,
      fontSize: 11, bold: true, color: b.color, fontFace: "Trebuchet MS", valign: "middle"
    });
    s.addText(b.range, {
      x: 8.0, y: y + 0.01, w: 1.3, h: 0.5,
      fontSize: 10, color: C.muted, fontFace: "Calibri", align: "right", valign: "middle"
    });
  });

  // Bonus features chips
  chip(s, "🎲 Secure Password Generator", 6.1, 4.65, 3.3, C.orange, C.white);
}

// ─── SLIDE 8 — GAMIFICATION ─────────────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "Gamification — Keeping Users Engaged");
  slideNumber(s, 8);

  // Left: points + leaderboard
  s.addText("Points System", {
    x: 0.45, y: 1.05, w: 4.3, h: 0.32,
    fontSize: 11.5, bold: true, color: C.orange, fontFace: "Trebuchet MS"
  });

  // Big stat callouts
  [["+10", "per correct\nphishing answer", 0.45], ["+5", "speed bonus\n(under 15 sec)", 2.6]].forEach(([num, sub, x]) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y: 1.42, w: 1.9, h: 1.22,
      fill: { color: C.dark }, line: { type: "none" }, rectRadius: 0.1
    });
    s.addText(num, {
      x, y: 1.5, w: 1.9, h: 0.62,
      fontSize: 36, bold: true, color: C.orange, fontFace: "Trebuchet MS", align: "center"
    });
    s.addText(sub, {
      x, y: 2.1, w: 1.9, h: 0.48,
      fontSize: 9.5, color: "D6D3D1", fontFace: "Calibri", align: "center", wrap: true
    });
  });

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.45, y: 2.78, w: 4.05, h: 0.72,
    fill: { color: C.subtleLight }, line: { color: C.subtle, pt: 0.5 }, rectRadius: 0.08
  });
  s.addText("🏆  Global Leaderboard — Top 20 users ranked by total score, showing accuracy and badge count", {
    x: 0.55, y: 2.84, w: 3.88, h: 0.6,
    fontSize: 10, color: C.dark, fontFace: "Calibri", valign: "middle", wrap: true
  });

  s.addText("9 Achievement Badges", {
    x: 0.45, y: 3.6, w: 4.3, h: 0.32,
    fontSize: 11.5, bold: true, color: C.orange, fontFace: "Trebuchet MS"
  });

  // Right column: badge cards
  const badges = [
    ["🥇 First Steps",       "Complete 1 scenario"],
    ["⚡ Quick Draw",        "Correct answer in <10 sec"],
    ["🔥 On a Streak",       "5 correct answers in a row"],
    ["💪 Unstoppable",       "10 correct in a row"],
    ["🔑 Password Novice",   "Score 61+ on password check"],
    ["🔐 Password Pro",      "Score 81+ on password check"],
    ["💯 Century Club",      "Accumulate 100 total points"],
    ["🛡 Security Expert",   "Accumulate 500 total points"],
    ["🎯 Perfectionist",     "100% accuracy over 10 scenarios"],
  ];

  badges.forEach((b, i) => {
    const col = i < 5 ? 0 : 1;
    const row = col === 0 ? i : i - 5;
    const x = col === 0 ? 5.0 : 0.45;
    const y = col === 0 ? (1.05 + row * 0.55) : (3.92 + row * 0.46);

    if (col === 1 && row >= 4) return; // only 4 in second column here

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 4.5, h: 0.46,
      fill: { color: i % 2 === 0 ? C.subtleLight : C.white },
      line: { color: C.subtle, pt: 0.5 }
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.05, h: 0.46,
      fill: { color: C.orange }, line: { type: "none" }
    });
    s.addText(b[0], {
      x: x + 0.1, y, w: 2.1, h: 0.46,
      fontSize: 9.5, bold: true, color: C.dark, fontFace: "Calibri", valign: "middle"
    });
    s.addText(b[1], {
      x: x + 2.2, y, w: 2.22, h: 0.46,
      fontSize: 9.5, color: C.mid, fontFace: "Calibri", valign: "middle"
    });
  });

  // Handle bottom row for left side
  const bottomBadges = badges.slice(5, 9);
  bottomBadges.forEach((b, i) => {
    const x = 0.45;
    const y = 3.92 + i * 0.46;
    const globalI = i + 5;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 4.5, h: 0.42,
      fill: { color: globalI % 2 === 0 ? C.subtleLight : C.white },
      line: { color: C.subtle, pt: 0.5 }
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.05, h: 0.42,
      fill: { color: C.orange }, line: { type: "none" }
    });
    s.addText(b[0], {
      x: x + 0.1, y, w: 2.1, h: 0.42,
      fontSize: 9.5, bold: true, color: C.dark, fontFace: "Calibri", valign: "middle"
    });
    s.addText(b[1], {
      x: x + 2.2, y, w: 2.22, h: 0.42,
      fontSize: 9.5, color: C.mid, fontFace: "Calibri", valign: "middle"
    });
  });
}

// ─── SLIDE 9 — ADMIN PANEL ──────────────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "Admin Panel");
  slideNumber(s, 9);

  const adminFeatures = [
    { icon: "👤", title: "Manage Users", items: ["View all users with full profile details", "Edit username, email, and user role", "Delete users from the platform"] },
    { icon: "📧", title: "Manage Scenarios", items: ["Create phishing scenarios manually", "Edit or delete any existing scenario", "Preview how scenarios look to users"] },
    { icon: "🤖", title: "AI Scenario Generator", items: ["Generate 1–20 new scenarios in one click", "Choose difficulty: Easy / Medium / Hard", "Powered by the Groq LLM API"] },
  ];

  adminFeatures.forEach((f, i) => {
    const x = 0.45 + i * 3.22;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y: 1.1, w: 2.98, h: 3.1,
      fill: { color: C.subtleLight },
      line: { color: C.subtle, pt: 0.75 },
      shadow: { type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.07 }
    });
    // Header
    s.addShape(pres.shapes.RECTANGLE, {
      x, y: 1.1, w: 2.98, h: 0.7,
      fill: { color: C.dark }, line: { type: "none" }
    });
    s.addText(f.icon + "  " + f.title, {
      x: x + 0.12, y: 1.13, w: 2.78, h: 0.64,
      fontSize: 12, bold: true, color: C.white, fontFace: "Trebuchet MS", valign: "middle"
    });
    f.items.forEach((item, j) => {
      s.addText([{ text: item, options: { bullet: true } }], {
        x: x + 0.12, y: 1.88 + j * 0.62, w: 2.72, h: 0.58,
        fontSize: 10.5, color: C.dark, fontFace: "Calibri", wrap: true
      });
    });
  });

  // Security controls
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.45, y: 4.35, w: 9.1, h: 0.96,
    fill: { color: "FEF2F2" }, line: { color: "FECACA", pt: 1 }
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.45, y: 4.35, w: 0.07, h: 0.96,
    fill: { color: "DC2626" }, line: { type: "none" }
  });
  s.addText("🔒  Security Controls", {
    x: 0.62, y: 4.38, w: 2.5, h: 0.38,
    fontSize: 11, bold: true, color: "DC2626", fontFace: "Trebuchet MS"
  });
  s.addText([
    { text: "Admin cannot delete or demote their own account (self-protection guard)   •   ", options: {} },
    { text: "All admin endpoints protected by require_admin dependency", options: {} },
    { text: "   •   Default admin account auto-created on first startup via seed service", options: {} },
  ], {
    x: 0.62, y: 4.76, w: 8.82, h: 0.48,
    fontSize: 10, color: C.dark, fontFace: "Calibri"
  });
}

// ─── SLIDE 10 — TECHNOLOGIES ─────────────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "Technologies & Tools");
  slideNumber(s, 10);

  const rows = [
    ["Frontend",  "React 19, Vite, Tailwind CSS", "UI, routing, styling"],
    ["Backend",   "Python + FastAPI",              "REST API, business logic"],
    ["Database",  "SQLite + SQLAlchemy (async)",   "Data persistence"],
    ["Auth",      "JWT (python-jose), bcrypt",     "Secure authentication"],
    ["AI",        "Groq LLM API",                  "Scenario generation & feedback"],
    ["Security",  "slowapi, CORS middleware",       "Rate limiting, request control"],
    ["Icons",     "lucide-react",                  "UI icon set"],
  ];

  const colW = [1.8, 3.4, 3.4];
  const headers = ["Layer", "Technology", "Purpose"];

  // Header row
  const hColors = [C.dark, C.orange, "44403C"];
  let curX = 0.45;
  headers.forEach((h, i) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: curX, y: 1.08, w: colW[i], h: 0.44,
      fill: { color: i === 1 ? C.orange : C.dark }, line: { type: "none" }
    });
    s.addText(h, {
      x: curX, y: 1.08, w: colW[i], h: 0.44,
      fontSize: 11.5, bold: true, color: "FFFFFF", fontFace: "Trebuchet MS",
      align: "left", valign: "middle", margin: [0, 0, 0, 8]
    });
    curX += colW[i] + 0.06;
  });

  rows.forEach((row, i) => {
    const y = 1.58 + i * 0.52;
    const bg = i % 2 === 0 ? C.subtleLight : C.white;
    let curX2 = 0.45;
    row.forEach((cell, j) => {
      s.addShape(pres.shapes.RECTANGLE, {
        x: curX2, y, w: colW[j], h: 0.48,
        fill: { color: j === 0 ? C.orangeLight : bg }, line: { color: C.subtle, pt: 0.5 }
      });
      s.addText(cell, {
        x: curX2, y, w: colW[j], h: 0.48,
        fontSize: j === 0 ? 11 : 10.5,
        bold: j === 0,
        color: j === 0 ? C.orange : C.dark,
        fontFace: "Calibri", valign: "middle", margin: [0, 0, 0, 8]
      });
      curX2 += colW[j] + 0.06;
    });
  });
}

// ─── SLIDE 11 — OBJECTIVES FULFILLMENT ──────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "Did We Meet the Objectives?");
  slideNumber(s, 11);

  const objectives = [
    ["Phishing detection training via simulations",    "Fully Implemented"],
    ["Real-time password strength evaluation",          "Fully Implemented"],
    ["Gamification — points, badges, streaks, leaderboard", "Fully Implemented"],
    ["AI-powered dynamic content generation",           "Integrated with Groq LLM"],
    ["Admin panel for full platform management",        "Fully Implemented"],
  ];

  objectives.forEach((obj, i) => {
    const y = 1.12 + i * 0.82;

    // Row bg
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.45, y, w: 9.1, h: 0.72,
      fill: { color: i % 2 === 0 ? C.subtleLight : C.white },
      line: { color: C.subtle, pt: 0.5 }
    });

    // Number
    s.addShape(pres.shapes.OVAL, {
      x: 0.55, y: y + 0.16, w: 0.38, h: 0.38,
      fill: { color: C.orange }, line: { type: "none" }
    });
    s.addText(String(i + 1), {
      x: 0.55, y: y + 0.16, w: 0.38, h: 0.38,
      fontSize: 11, bold: true, color: C.white, align: "center", valign: "middle", fontFace: "Trebuchet MS"
    });

    // Objective text
    s.addText(obj[0], {
      x: 1.08, y, w: 5.9, h: 0.72,
      fontSize: 12, color: C.dark, fontFace: "Calibri", valign: "middle"
    });

    // Status chip
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 7.1, y: y + 0.14, w: 2.3, h: 0.42,
      fill: { color: C.greenLight }, line: { color: C.green, pt: 0.75 }, rectRadius: 0.06
    });
    s.addText("✅  " + obj[1], {
      x: 7.1, y: y + 0.14, w: 2.3, h: 0.42,
      fontSize: 9.5, bold: true, color: C.green, fontFace: "Calibri", align: "center", valign: "middle"
    });
  });

  // Summary banner
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.45, y: 5.12, w: 9.1, h: 0.36,
    fill: { color: C.orange }, line: { type: "none" }
  });
  s.addText("🎉  All 5 project objectives have been successfully fulfilled.", {
    x: 0.45, y: 5.12, w: 9.1, h: 0.36,
    fontSize: 12, bold: true, color: C.white, fontFace: "Trebuchet MS", align: "center", valign: "middle"
  });
}

// ─── SLIDE 12 — CHALLENGES ──────────────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "Challenges Faced & Solutions");
  slideNumber(s, 12);

  const challenges = [
    {
      challenge: "AI Reliability",
      icon: "🤖",
      problem: "LLM responses sometimes returned malformed JSON, causing parse errors",
      solution: "JSON parsing guards + retry logic with fallback error handling",
    },
    {
      challenge: "Infinite Content",
      icon: "♾",
      problem: "Pre-seeded scenarios would eventually run out for active users",
      solution: "On-demand AI generation triggered when all scenarios are exhausted",
    },
    {
      challenge: "Security",
      icon: "🔒",
      problem: "Sensitive endpoints and user data needed strong protection",
      solution: "JWT auth, bcrypt hashing, rate limiting (slowapi), CORS configuration",
    },
    {
      challenge: "Async Database",
      icon: "🗄",
      problem: "SQLAlchemy async requires careful session lifecycle management",
      solution: "Dependency injection with AsyncSession and scoped session patterns",
    },
  ];

  challenges.forEach((c, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.45 + col * 4.65;
    const y = 1.1 + row * 2.2;

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 4.4, h: 2.0,
      fill: { color: C.white },
      line: { color: C.subtle, pt: 0.75 },
      shadow: { type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.07 }
    });
    // Colored header band
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 4.4, h: 0.58,
      fill: { color: C.dark }, line: { type: "none" }
    });
    s.addText(c.icon + "  " + c.challenge, {
      x: x + 0.12, y, w: 4.2, h: 0.58,
      fontSize: 12.5, bold: true, color: C.white, fontFace: "Trebuchet MS", valign: "middle"
    });

    // Problem
    s.addShape(pres.shapes.RECTANGLE, {
      x: x + 0.12, y: y + 0.65, w: 0.7, h: 0.26,
      fill: { color: "FEE2E2" }, line: { type: "none" }
    });
    s.addText("Issue", {
      x: x + 0.12, y: y + 0.65, w: 0.7, h: 0.26,
      fontSize: 8, bold: true, color: "DC2626", align: "center", valign: "middle", fontFace: "Calibri"
    });
    s.addText(c.problem, {
      x: x + 0.12, y: y + 0.94, w: 4.16, h: 0.38,
      fontSize: 10, color: C.mid, fontFace: "Calibri", wrap: true
    });

    // Solution
    s.addShape(pres.shapes.RECTANGLE, {
      x: x + 0.12, y: y + 1.35, w: 0.85, h: 0.26,
      fill: { color: C.greenLight }, line: { type: "none" }
    });
    s.addText("Solution", {
      x: x + 0.12, y: y + 1.35, w: 0.85, h: 0.26,
      fontSize: 8, bold: true, color: C.green, align: "center", valign: "middle", fontFace: "Calibri"
    });
    s.addText(c.solution, {
      x: x + 0.12, y: y + 1.64, w: 4.16, h: 0.28,
      fontSize: 10, color: C.dark, fontFace: "Calibri", bold: true, wrap: true
    });
  });
}

// ─── SLIDE 13 — DEMO / SCREENSHOTS ──────────────────────────────────────────
{
  const s = pres.addSlide();
  titleBar(s, "System Demo");
  slideNumber(s, 13);

  s.addText("Walk through the live demo or these screenshots:", {
    x: 0.45, y: 1.0, w: 9.1, h: 0.32,
    fontSize: 12, color: C.mid, fontFace: "Calibri", italic: true
  });

  const screens = [
    { n: "1", label: "Login / Register", icon: "🔐" },
    { n: "2", label: "Dashboard", icon: "📊" },
    { n: "3", label: "Phishing Trainer", icon: "🎣" },
    { n: "4", label: "AI Feedback", icon: "🧠" },
    { n: "5", label: "Password Checker", icon: "🔑" },
    { n: "6", label: "Leaderboard", icon: "🏆" },
    { n: "7", label: "Admin Panel", icon: "⚙️" },
  ];

  screens.forEach((sc, i) => {
    const col = i % 4;
    const row = Math.floor(i / 4);
    const x = 0.45 + col * 2.4;
    const y = 1.45 + row * 2.05;
    const cardW = i < 4 ? 2.2 : 2.2;

    // Card
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: cardW, h: 1.82,
      fill: { color: C.subtleLight },
      line: { color: C.subtle, pt: 0.75 },
      shadow: { type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.08 }
    });
    // Top accent
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: cardW, h: 0.06,
      fill: { color: C.orange }, line: { type: "none" }
    });

    // Placeholder mockup area
    s.addShape(pres.shapes.RECTANGLE, {
      x: x + 0.1, y: y + 0.14, w: cardW - 0.2, h: 1.08,
      fill: { color: C.subtle }, line: { type: "none" }
    });
    s.addText(sc.icon, {
      x: x + 0.1, y: y + 0.14, w: cardW - 0.2, h: 1.08,
      fontSize: 30, align: "center", valign: "middle"
    });

    // Screen label
    s.addText(`${sc.n}. ${sc.label}`, {
      x: x + 0.06, y: y + 1.28, w: cardW - 0.12, h: 0.46,
      fontSize: 10, bold: true, color: C.dark, fontFace: "Calibri", align: "center", valign: "middle"
    });
  });

  s.addNotes("Walk through these quickly — spend no more than 60 seconds here if you have a live demo ready.");
}

// ─── SLIDE 14 — CONCLUSION ──────────────────────────────────────────────────
{
  const s = pres.addSlide();
  s.background = { color: C.dark };

  // Orange geometric accent — left third
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.18, h: 5.625,
    fill: { color: C.orange }, line: { type: "none" }
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.18, y: 0, w: 0.1, h: 5.625,
    fill: { color: "C2410C", transparency: 50 }, line: { type: "none" }
  });

  s.addText("Conclusion", {
    x: 0.5, y: 0.3, w: 7.0, h: 0.7,
    fontSize: 30, bold: true, color: C.orange, fontFace: "Trebuchet MS"
  });

  const points = [
    "SecureSense delivers a fully functional, interactive, gamified cybersecurity training platform",
    "Users learn to identify phishing and create strong passwords through active practice — not passive reading",
    "AI integration ensures the platform never runs out of content and provides personalised feedback",
    "The system is scalable, secure, and ready for real-world deployment",
  ];

  points.forEach((pt, i) => {
    const y = 1.15 + i * 0.9;
    s.addShape(pres.shapes.OVAL, {
      x: 0.5, y: y + 0.06, w: 0.32, h: 0.32,
      fill: { color: C.orange }, line: { type: "none" }
    });
    s.addText("✓", {
      x: 0.5, y: y + 0.06, w: 0.32, h: 0.32,
      fontSize: 10, bold: true, color: C.white, align: "center", valign: "middle"
    });
    s.addText(pt, {
      x: 0.96, y, w: 8.52, h: 0.78,
      fontSize: 13, color: "E7E5E4", fontFace: "Calibri", valign: "middle", wrap: true
    });
  });

  // Thank you + questions
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.75, w: 9.0, h: 0.64,
    fill: { color: C.orange }, line: { type: "none" }
  });
  s.addText("Thank you — Open to questions 🙌", {
    x: 0.5, y: 4.75, w: 9.0, h: 0.64,
    fontSize: 18, bold: true, color: C.white, fontFace: "Trebuchet MS", align: "center", valign: "middle"
  });

  slideNumber(s, 14);
}

// ─── WRITE ──────────────────────────────────────────────────────────────────
async function build() {
  await pres.writeFile({
    fileName: path.join(process.cwd(), "SecureSense.pptx"),
  });

  console.log("Done ✓");
}

build().catch(console.error);
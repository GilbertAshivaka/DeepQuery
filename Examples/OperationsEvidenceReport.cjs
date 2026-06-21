"use strict";
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, BorderStyle, WidthType, ShadingType,
  PageBreak, Header, Footer
} = require("docx");
const fs = require("fs");

const GREEN   = "1B5E20", MID = "2E7D32", LIGHT = "E8F5E9";
const DARK = "1A1A1A", GREY = "F5F5F5", MGREY = "CCCCCC";
const WHITE = "FFFFFF", GOLD = "7B5800";
const FULL = 9360;

const border  = { style: BorderStyle.SINGLE, size: 1, color: MGREY };
const borders = { top: border, bottom: border, left: border, right: border };

function h1(text) {
  return new Paragraph({
    spacing: { before: 360, after: 140 },
    shading: { fill: GREEN, type: ShadingType.CLEAR },
    children: [new TextRun({ text: "  " + text, font: "Georgia", size: 28, bold: true, color: WHITE })]
  });
}
function h2(text) {
  return new Paragraph({
    spacing: { before: 260, after: 100 },
    border: { left: { style: BorderStyle.THICK, size: 18, color: MID, space: 8 } },
    children: [new TextRun({ text, font: "Georgia", size: 24, bold: true, color: MID })]
  });
}
function h3(text) {
  return new Paragraph({
    spacing: { before: 180, after: 80 },
    children: [new TextRun({ text, font: "Calibri", size: 22, bold: true, color: GOLD })]
  });
}
function p(text, opts = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 100 },
    children: [new TextRun({ text, font: "Calibri", size: 22,
      bold: opts.bold||false, italics: opts.italic||false, color: opts.color||DARK })]
  });
}
function lv(label, val) {
  return new Paragraph({
    spacing: { before: 50, after: 70 },
    children: [
      new TextRun({ text: label + ": ", font: "Calibri", size: 22, bold: true, color: MID }),
      new TextRun({ text: val, font: "Calibri", size: 22, color: DARK })
    ]
  });
}
function bull(text, lvl = 0) {
  return new Paragraph({
    numbering: { reference: "bul", level: lvl },
    spacing: { before: 40, after: 55 },
    children: [new TextRun({ text, font: "Calibri", size: 22, color: DARK })]
  });
}
function sp(n=1){ return Array.from({length:n},()=>new Paragraph({spacing:{before:0,after:0},children:[new TextRun("")]})); }
function pb(){ return new Paragraph({ children: [new PageBreak()] }); }

function box(rows) {
  return new Table({ width: { size: FULL, type: WidthType.DXA }, columnWidths: [FULL],
    rows: [new TableRow({ children: [new TableCell({
      shading: { fill: LIGHT, type: ShadingType.CLEAR },
      borders: { top:{style:BorderStyle.SINGLE,size:6,color:MID}, bottom:{style:BorderStyle.SINGLE,size:6,color:MID},
                 left:{style:BorderStyle.SINGLE,size:6,color:MID}, right:{style:BorderStyle.SINGLE,size:6,color:MID} },
      margins: { top: 150, bottom: 150, left: 220, right: 220 },
      children: rows
    })]}) ]
  });
}

function tbl(headers, rows, colW) {
  const hRow = new TableRow({ children: headers.map((h,i) => new TableCell({
    width: { size: colW[i], type: WidthType.DXA },
    shading: { fill: GREEN, type: ShadingType.CLEAR }, borders,
    margins: { top: 80, bottom: 80, left: 110, right: 110 },
    children: [new Paragraph({ children: [new TextRun({ text: h, font: "Calibri", size: 19, bold: true, color: WHITE })] })]
  }))});
  const dRows = rows.map((row, ri) => new TableRow({ children: row.map((cell, ci) => new TableCell({
    width: { size: colW[ci], type: WidthType.DXA },
    shading: { fill: ri%2===0 ? WHITE : GREY, type: ShadingType.CLEAR }, borders,
    margins: { top: 75, bottom: 75, left: 110, right: 110 },
    children: [new Paragraph({ children: [new TextRun({ text: cell, font: "Calibri", size: 19, color: DARK })] })]
  }))}));
  return new Table({ width:{size:colW.reduce((a,b)=>a+b,0),type:WidthType.DXA}, columnWidths:colW, rows:[hRow,...dRows] });
}

const doc = new Document({
  numbering: { config: [{ reference:"bul", levels:[
    {level:0,format:"bullet",text:"\u2022",alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:560,hanging:280}}}},
    {level:1,format:"bullet",text:"\u25E6",alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:1000,hanging:280}}}}
  ]}]},
  sections: [{ properties:{page:{size:{width:11906,height:16838},margin:{top:1080,right:1080,bottom:1080,left:1080}}},
    headers:{ default: new Header({ children:[new Paragraph({
      border:{bottom:{style:BorderStyle.SINGLE,size:4,color:MID,space:4}},
      spacing:{before:0,after:120},
      children:[new TextRun({text:"REFORMED CREATIONS  |  Business Operations Evidence Report  |  May 2026",font:"Calibri",size:17,color:MID})]
    })]})},
    footers:{ default: new Footer({ children:[new Paragraph({
      border:{top:{style:BorderStyle.SINGLE,size:4,color:MID,space:4}},
      spacing:{before:80,after:0},
      children:[new TextRun({text:"Samaa Shariff  |  samaa@reformedcreations.co.ke  |  Kilifi, Kenya",font:"Calibri",size:16,color:"888888"})]
    })]})},
    children: [

// ── COVER ────────────────────────────────────────────────────────────────────
new Paragraph({ alignment: AlignmentType.CENTER, spacing:{before:500,after:120},
  children:[new TextRun({text:"REFORMED CREATIONS",font:"Georgia",size:58,bold:true,color:MID})] }),
new Paragraph({ alignment: AlignmentType.CENTER, spacing:{before:0,after:180},
  children:[new TextRun({text:"Transforming Plastic Waste into Sustainable Jewellery",font:"Calibri",size:26,italics:true,color:"555555"})] }),
new Paragraph({ alignment: AlignmentType.CENTER, shading:{fill:GREEN,type:ShadingType.CLEAR},
  spacing:{before:120,after:120},
  children:[new TextRun({text:"  BUSINESS OPERATIONS EVIDENCE REPORT  |  MAY 2026  ",font:"Georgia",size:28,bold:true,color:WHITE})] }),
...sp(2),
box([
  lv("Business Name","Reformed Creations"),
  lv("Founders","Samaa Shariff (Co-Founder & CEO)  |  Fridah Santa (Co-Founder & Operations Lead)"),
  lv("Founded","30 December 2022   |   Revenue commenced: November 2024"),
  lv("Location","Kilifi, Kilifi County, Kenya (Coastal Region)"),
  lv("Sector","Eco-Fashion / Sustainable Accessories / Social Enterprise"),
  lv("Contact","samaa@reformedcreations.co.ke"),
  lv("Purpose","Evidence of Business Operations — Application Submission"),
]),
...sp(2),
p("This document provides structured evidence of Reformed Creations' business operations. It covers sales history, customer and beneficiary relationships, how customers are acquired, what transactions look like, and the roles of all employees. A full production procedure is provided in a separate accompanying document.", {italic:true,color:"555555"}),

pb(),

// ═══════════════════════════════════════════════════════════════════════════
h1("Section 1: Evidence of Sales"),
...sp(1),
p("Reformed Creations first generated revenue in November 2024 and has grown sales consistently every quarter since, entirely without loans, grants or external financial support. All revenue is earned through direct commercial sales of handcrafted eco-jewellery."),
...sp(1),

h2("1.1  Sales Performance by Period"),
...sp(1),
tbl(
  ["Period","Monthly Revenue (KES)","Est. Units Sold","Primary Activity"],
  [
    ["Nov 2024","~10,000","50–60 pieces","First sales — direct to individuals via WhatsApp & in-person"],
    ["Dec 2024","~12,500","60–70 pieces","First boutique trial order placed (Kilifi partner)"],
    ["Q1 2025","~15,000","75–90 pcs/month","Growing Instagram reach; repeat boutique restocks begin"],
    ["Q2 2025","~18,000","90–105 pcs/month","Second boutique partner onboarded in Mombasa"],
    ["Q3 2025","~22,000","110–130 pcs/month","Custom orders increasing; WhatsApp Business set up"],
    ["Q4 2025","~30,000","150–175 pcs/month","Revenue up >50% vs first month; delivery team hired"],
    ["Q1 2026","~38,000","190–220 pcs/month","Production scaled; collector team working regularly"],
    ["May 2026","~45,000+","310+ pcs/month","On track for KES 150,000/month target by Dec 2026"],
  ],
  [1700,2000,1900,3760]
),
...sp(1),
p("Cumulative estimated revenue since first sale (November 2024 to May 2026): approximately KES 300,000 – 350,000, earned entirely through commercial sales."),
...sp(1),

h2("1.2  Revenue by Product Line (Current, May 2026)"),
...sp(1),
tbl(
  ["Product","Monthly Volume","Retail Price","Wholesale Price","Est. Monthly Revenue"],
  [
    ["Jewellery (earrings, necklaces, bracelets, rings)","200 pieces","KES 200","KES 150","KES 30,000 – 40,000"],
    ["Key Holders","65 pieces","KES 150","KES 110","KES 7,200 – 9,750"],
    ["Charms","45 pieces","KES 120","KES 90","KES 4,050 – 5,400"],
    ["Custom Orders","~10 pieces","KES 220–250","KES 175","KES 2,000 – 2,500"],
    ["TOTAL","310–325 pieces","—","—","KES 43,000 – 57,000"],
  ],
  [3200,1500,1400,1600,1960]
),
...sp(1),

h2("1.3  Sample Sales Transaction Log"),
p("The table below is a representative sample of Reformed Creations' sales transactions, showing both direct consumer (B2C) and boutique retail (B2B2C) channel activity. A full transaction log is provided as a separate Excel evidence sheet."),
...sp(1),
tbl(
  ["Txn #","Date","Customer Type","Products","Qty","Amount (KES)","Payment","Channel"],
  [
    ["RC-001","Nov 2024","Individual — repeat buyer","Jewellery earrings × 2","2","400","M-PESA","WhatsApp DM"],
    ["RC-002","Nov 2024","Individual","Key Holder × 1","1","150","Cash","In-person, Kilifi"],
    ["RC-003","Dec 2024","Boutique Partner — Kilifi","Jewellery × 20, Charms × 10","30","4,600","Bank Transfer","B2B2C trade order"],
    ["RC-004","Jan 2025","Individual","Custom earrings × 3","3","720","M-PESA","Instagram DM"],
    ["RC-005","Feb 2025","Individual","Jewellery × 1, Charm × 2","3","440","M-PESA","WhatsApp DM"],
    ["RC-006","Mar 2025","Boutique Partner — Kilifi","Jewellery × 25, Key Holders × 15","40","6,250","Bank Transfer","B2B2C restock"],
    ["RC-007","May 2025","Boutique Partner — Mombasa","Mixed monthly restock","45","7,200","Bank Transfer","B2B2C restock"],
    ["RC-008","Jun 2025","Individual — gift purchase","Key Holders × 3, Charms × 5","8","1,050","M-PESA","WhatsApp DM"],
    ["RC-009","Aug 2025","Individual","Custom necklace × 1","1","250","M-PESA","Instagram DM"],
    ["RC-010","Oct 2025","Boutique Partner — Kilifi","Jewellery × 30, Key Holders × 10","40","7,100","Bank Transfer","B2B2C restock"],
    ["RC-011","Dec 2025","Individual","Jewellery × 2, Charm × 3","5","760","M-PESA","WhatsApp DM"],
    ["RC-012","Jan 2026","Boutique Partner — Mombasa","Monthly mixed restock","55","9,300","Bank Transfer","B2B2C restock"],
    ["RC-013","Mar 2026","Individual","Custom earrings × 2","2","480","M-PESA","Instagram DM"],
    ["RC-014","Apr 2026","Boutique Partner — Kilifi","Jewellery × 40, Charms × 20","60","10,400","Bank Transfer","B2B2C restock"],
    ["RC-015","May 2026","Individual","Jewellery × 3, Key Holder × 1","4","750","M-PESA","WhatsApp DM"],
  ],
  [900,1050,2100,2500,600,1300,1200,1510]
),
...sp(1),
p("All M-PESA transactions are traceable via Safaricom transaction records. Bank transfer orders are supported by boutique purchase orders and transfer confirmations."),

pb(),

// ═══════════════════════════════════════════════════════════════════════════
h1("Section 2: Customers & Beneficiaries"),
...sp(1),

h2("2.1  How Reformed Creations Gets Its Customers"),
...sp(1),
h3("Direct-to-Consumer (B2C) Channel"),
p("The majority of individual customers discover Reformed Creations through:"),
bull("Instagram and Facebook — the business posts product photos, behind-the-scenes content, and sustainability stories 3–4 times per week. Customers send order enquiries via Instagram Direct Message."),
bull("WhatsApp Business — once a customer makes contact, all order communication, pricing, and delivery arrangements happen on WhatsApp. The business maintains a product catalogue on WhatsApp Business for easy browsing."),
bull("Word of mouth — satisfied customers refer friends and family, which has been the primary organic growth driver since launch. No paid advertising has been used to date."),
bull("In-person — the co-founders sell directly at community events, pop-ups and through personal networks in Kilifi."),
...sp(1),
h3("Boutique Retail (B2B2C) Channel"),
p("Boutique partners are acquired through:"),
bull("Direct outreach — the co-founders identify boutiques whose customer base aligns with eco-conscious buyers and approach them in person with a product sample kit and wholesale pricing sheet."),
bull("Referrals from existing boutique partners — satisfied stockists have referred Reformed Creations to peers in other locations."),
bull("Currently 2 active boutique partners: one in Kilifi, one in Mombasa. Target is 7 partners by December 2026, including expansion into Nairobi."),
...sp(1),

h2("2.2  What a Transaction Looks Like"),
...sp(1),
h3("Individual Customer Transaction (B2C)"),
tbl(
  ["Step","What Happens"],
  [
    ["1. Discovery","Customer sees product on Instagram or hears about it from a friend."],
    ["2. Enquiry","Customer sends a WhatsApp or Instagram DM message asking about products, prices and availability."],
    ["3. Order Confirmation","Co-founder (Samaa) confirms product availability, confirms price and shares delivery options. Customer confirms their order in writing via WhatsApp."],
    ["4. Payment","Customer pays via M-PESA (send money to business number) before dispatch, or cash on collection for Kilifi-based customers."],
    ["5. Fulfilment","Order is packaged in branded eco-friendly packaging and either collected in person or dispatched via courier (Kilifi/Mombasa) or third-party delivery service."],
    ["6. Confirmation","Delivery confirmed via WhatsApp. Customer is invited to share a review or photo and refer friends."],
  ],
  [1400,8160]
),
...sp(1),
h3("Boutique Partner Transaction (B2B2C)"),
tbl(
  ["Step","What Happens"],
  [
    ["1. Onboarding","Co-founder visits the boutique in person, presents the product range and sustainability story, and leaves a sample selection. Wholesale pricing and minimum order quantities are agreed."],
    ["2. Purchase Order","Boutique partner places a written purchase order (WhatsApp message or written note) specifying product mix and quantities."],
    ["3. Production","Reformed Creations produces the order, typically within 5–7 working days for orders up to 50 pieces."],
    ["4. Delivery","Gilbert Ashivaka (full-time delivery employee) delivers the order to the boutique directly."],
    ["5. Payment","Boutique partner pays within 14 days of delivery by bank transfer. No credit beyond 14 days is extended."],
    ["6. Restock Cycle","Boutique partners typically reorder every 4–8 weeks. Co-founder follows up proactively before stock runs out."],
  ],
  [1400,8160]
),
...sp(1),

h2("2.3  Beneficiaries"),
p("Reformed Creations creates direct community benefit alongside its commercial activity:"),
...sp(1),
tbl(
  ["Beneficiary","Nature of Benefit","Current Number"],
  [
    ["Direct employees & co-founders","Regular income from business operations","5 people (2 co-founders, 1 FT, 2 PT)"],
    ["Plastic collectors (Agness Kananu, Fahad Hadi)","Consistent part-time income from plastic sourcing; skills in waste management","2 people"],
    ["Kilifi coastal community","Plastic waste removed from beaches and waterways — measurable environmental benefit","Entire community"],
    ["Boutique partner staff","Indirectly supported through sustained boutique revenue from stocking Reformed Creations","~5–10 people"],
    ["Future hires (2026–2027)","As production scales, 3–4 additional community youth will be employed","Target: 3–4 new jobs"],
  ],
  [2400,4800,2160]
),

pb(),

// ═══════════════════════════════════════════════════════════════════════════
h1("Section 3: Team & Employee Evidence"),
...sp(1),
p("Reformed Creations currently employs 5 people: 2 co-founders, 1 full-time delivery employee, and 2 part-time plastic collectors. All team members are based in Kilifi and are under 30 years of age."),
...sp(1),

h2("3.1  Team Structure"),
...sp(1),
tbl(
  ["Name","Role","Employment Type","Key Responsibilities","Since"],
  [
    ["Samaa Shariff","Co-Founder & CEO","Full-time","Sales, marketing, customer relations, financial management, strategic planning, boutique partner development.","Dec 2022"],
    ["Fridah Santa","Co-Founder & Operations Lead","Full-time","Production oversight, plastic collection management, quality control, logistics, delivery scheduling.","Dec 2022"],
    ["Gilbert Ashivaka","Delivery & Fulfilment","Full-time (paid)","All order delivery runs to boutique partners and individual customers. Collection logistics support.","Q4 2025"],
    ["Agness Kananu","Plastic Waste Collector","Part-time (paid)","Sources, sorts and delivers plastic waste from Kilifi community collection points to production workspace.","Q1 2025"],
    ["Fahad Hadi","Plastic Waste Collector","Part-time (paid)","Sources, sorts and delivers plastic waste from Kilifi community collection points to production workspace.","Q1 2025"],
    ["[TBH] Bookkeeper","Part-time Bookkeeper","Part-time (to hire Q2 2026)","Monthly cloud accounting records, P&L reports, KRA tax compliance support.","Planned Q2 2026"],
  ],
  [1700,1900,1500,3460,800]
),
...sp(1),

h2("3.2  Compensation"),
tbl(
  ["Role","Monthly Compensation (KES)","Annual (KES)","Notes"],
  [
    ["Co-Founder × 2 (each)","~10,000","~120,000","Drawn as owner salary from operating revenue"],
    ["Delivery Employee (Gilbert)","~7,000","~84,000","Fixed monthly salary"],
    ["Plastic Collectors × 2 (each)","~5,000","~60,000","Part-time; paid per collection cycle"],
    ["Part-time Bookkeeper (planned)","~3,750","~45,000","8 hrs/month; planned from Q2 2026"],
    ["Total Payroll (current)","~37,000","~444,000","Excluding planned bookkeeper"],
  ],
  [2600,2400,1800,2760]
),
...sp(1),
p("All compensation is paid from commercial revenue. The business has never missed a payment to any employee. Payroll is the single largest operating cost, reflecting the labour-intensive, artisanal nature of the production model.", {italic:true}),

pb(),

// ═══════════════════════════════════════════════════════════════════════════
h1("Section 4: Business Operations Overview"),
...sp(1),

h2("4.1  Operating Location"),
p("Reformed Creations operates from a home-based workspace in Kilifi, Kilifi County. This keeps overhead costs to zero (no rent), which directly contributes to the business's strong margin. A transition to a formal production workshop is planned for 2027 as monthly output exceeds 500 pieces."),
...sp(1),

h2("4.2  Operating Days & Rhythm"),
tbl(
  ["Activity","Frequency","Who"],
  [
    ["Plastic waste collection from community","2–3 times per week","Collectors (Agness & Fahad)"],
    ["Production (crafting jewellery)","Daily, Monday–Saturday","Co-founders"],
    ["Quality control & packaging","Daily, Monday–Saturday","Co-founders"],
    ["Boutique delivery runs","Weekly or as needed","Gilbert Ashivaka"],
    ["Customer order fulfilment (B2C)","Within 24–48 hrs of payment","Co-founders + Gilbert"],
    ["Social media content posting","3–4 times per week","Samaa Shariff"],
    ["Stock level review & production planning","Weekly","Both co-founders"],
    ["Financial record update","Weekly (moving to daily with bookkeeper)","Samaa Shariff"],
  ],
  [2800,2400,4160]
),
...sp(1),

h2("4.3  Tools & Equipment in Use"),
tbl(
  ["Item","Purpose","Owned/Rented"],
  [
    ["Hand-operated cutting tools","Cutting and shaping recycled plastic to size","Owned"],
    ["Heat gun","Softening plastic for moulding and shaping","Owned"],
    ["Moulds (various sizes)","Ensuring consistency of piece dimensions","Owned"],
    ["Pliers, wire cutters, crimping tools","Jewellery assembly with metal findings","Owned"],
    ["Cleaning equipment (basins, brushes)","Washing and preparing raw plastic material","Owned"],
    ["Packaging materials","Branded eco-friendly product packaging","Purchased monthly"],
    ["Smartphone (Samsung)","Photography, social media, WhatsApp Business, records","Personal/Business"],
    ["Laptop","Financial records, order management, communications","Personal/Business"],
    ["Delivery motorbike","Order delivery and boutique runs","Owned (Gilbert)"],
  ],
  [2800,4400,2160]
),
...sp(1),

h2("4.4  Financial Management"),
bull("All income and expenses are currently recorded in a Microsoft Excel spreadsheet updated weekly by Samaa Shariff."),
bull("All customer payments via M-PESA are traceable through Safaricom transaction statements."),
bull("Boutique partner payments are received via bank transfer and reconciled monthly."),
bull("A part-time bookkeeper is being hired in Q2 2026 to migrate all records to a cloud accounting platform and produce formal monthly P&L reports."),
bull("The business has no debt, no overdraft, and no outstanding loans."),
...sp(1),

h2("4.5  Milestones Achieved to Date"),
tbl(
  ["Milestone","Date Achieved","Evidence"],
  [
    ["Business idea developed and tested","Dec 2022","Co-founders begin product development"],
    ["First handcrafted product completed","Early 2023","Product samples created; community feedback gathered"],
    ["First boutique approached with samples","Mid 2024","In-person pitch with sample kit in Kilifi"],
    ["First commercial sale made","November 2024","M-PESA transaction record #RC-001"],
    ["First boutique purchase order received","December 2024","WhatsApp purchase order; bank transfer receipt"],
    ["Second boutique partner onboarded","Q2 2025","Mombasa boutique — ongoing monthly restocks"],
    ["Delivery employee hired","Q4 2025","Gilbert Ashivaka joins full-time"],
    ["Monthly revenue exceeds KES 30,000","Q4 2025","Financial records"],
    ["Production reaches 310 pieces/month","Q1 2026","Production log; sales records"],
    ["Revenue growth >50% from first month","April 2026","Cumulative sales comparison"],
  ],
  [3000,1800,4560]
),

...sp(2),
box([
  p("Reformed Creations is a real, revenue-generating business built from the ground up by two young founders in Kilifi, Kenya, with zero external funding. Every figure in this document reflects actual commercial activity. We are proud of what we have built and the community we are serving — both as customers and as beneficiaries.", {italic:true}),
  ...sp(1),
  new Paragraph({spacing:{before:40,after:40}, children:[
    new TextRun({text:"Samaa Shariff  |  Co-Founder & CEO  |  Reformed Creations",font:"Georgia",size:22,bold:true,color:MID}),
  ]}),
  new Paragraph({spacing:{before:20,after:20}, children:[
    new TextRun({text:"samaa@reformedcreations.co.ke  |  Kilifi, Kenya  |  May 2026",font:"Calibri",size:21,color:"555555"}),
  ]}),
]),

]}]});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(path.join(process.cwd(), "RC_Operations_Evidence_Report.docx"), buf);
  console.log("Doc 1 done ✓");
});
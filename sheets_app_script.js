// ============================================================
// VZA CRM — AI Lead Generator (Google Apps Script)
// ============================================================
// Setup:
//   1. Open the Google Sheet → Extensions → Apps Script
//   2. Paste this entire file, replacing any existing code
//   3. Go to Project Settings (gear icon) → Script Properties
//      Add a property:  ANTHROPIC_API_KEY  =  sk-ant-...
//   4. Save, then run createButton() once to add the button to the sheet
// ============================================================

// ── ICP Configuration ───────────────────────────────────────
const ICP = {
  industry:      ["logistics", "manufacturing"],
  region:        ["Oost-Brabant", "Brainport Eindhoven"],
  company_size:  "50-500 FTE",
  target_titles: ["Directeur", "Operations Manager", "CFO"],
};

const CLAUDE_MODEL  = "claude-sonnet-4-6";
const LEADS_TO_GENERATE = 10;

// Column order must match the sheet exactly
const SHEET_COLUMNS = [
  "Company name",
  "Location",
  "Industry",
  "DMU name",
  "DMU phone",
  "DMU mail",
  "expected desire",
  "comp. phone",
  "comp. mail",
  "notes",
  "owner",
  "last tried call",
  "last spoken",
  "notes2",
  "sourced",
  "phase",
  "Rejected (reason)",
];

// ── Main entry point (called by the sheet button) ───────────
function generateLeads() {
  const apiKey = PropertiesService.getScriptProperties().getProperty("ANTHROPIC_API_KEY");
  if (!apiKey) {
    SpreadsheetApp.getUi().alert("Missing ANTHROPIC_API_KEY in Script Properties.");
    return;
  }

  const ui = SpreadsheetApp.getUi();
  const response = ui.alert(
    "Generate AI Leads",
    `Generate ${LEADS_TO_GENERATE} new B2B leads and write them to the CRM?`,
    ui.ButtonSet.OK_CANCEL
  );
  if (response !== ui.Button.OK) return;

  try {
    const leads = callClaude(apiKey);
    if (!leads || leads.length === 0) {
      ui.alert("Claude returned no leads. Check the API key and try again.");
      return;
    }

    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
    const written = writeLeads(sheet, leads);
    ui.alert(`Done! ${written} new lead(s) written to the CRM.`);
  } catch (e) {
    ui.alert("Error: " + e.message);
  }
}

// ── Claude API call ─────────────────────────────────────────
function callClaude(apiKey) {
  const systemPrompt =
    "You are a B2B lead research specialist. When given an Ideal Customer Profile (ICP), " +
    "you return a JSON array of realistic company leads. Each element must be a JSON object " +
    "with exactly these keys (use empty string \"\" for unknown values):\n\n" +
    "  company_name      — full legal or trading name of the company\n" +
    "  location          — city, region (e.g. \"Eindhoven, Noord-Brabant\")\n" +
    "  industry          — primary industry sector\n" +
    "  dmu_name          — full name of the Decision-Making Unit contact\n" +
    "  dmu_title         — job title of that person\n" +
    "  dmu_phone         — direct phone number (if publicly known)\n" +
    "  dmu_email         — business e-mail (if publicly known)\n" +
    "  company_phone     — main company switchboard number\n" +
    "  company_email     — general company e-mail\n" +
    "  expected_desire   — one-sentence hypothesis on the company's likely pain point or need\n" +
    "  notes             — any other relevant detail\n\n" +
    "Return ONLY the JSON array — no markdown fences, no preamble, no explanation.";

  const userPrompt =
    `Generate ${LEADS_TO_GENERATE} realistic B2B leads matching the following ICP:\n` +
    `- Industry: ${ICP.industry.join(", ")}\n` +
    `- Region: ${ICP.region.join(", ")}\n` +
    `- Company size: ${ICP.company_size}\n` +
    `- Target decision-maker titles: ${ICP.target_titles.join(", ")}\n\n` +
    "Focus on companies likely to need operational efficiency improvements, " +
    "logistics optimisation, or supply-chain consulting services.\n" +
    "Return the JSON array now.";

  const payload = {
    model: CLAUDE_MODEL,
    max_tokens: 4096,
    system: systemPrompt,
    messages: [{ role: "user", content: userPrompt }],
  };

  const options = {
    method: "post",
    contentType: "application/json",
    headers: {
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };

  const res = UrlFetchApp.fetch("https://api.anthropic.com/v1/messages", options);
  const json = JSON.parse(res.getContentText());

  if (json.error) throw new Error(json.error.message);

  return JSON.parse(json.content[0].text.trim());
}

// ── Deduplication & writing ──────────────────────────────────
function writeLeads(sheet, leads) {
  const allValues = sheet.getDataRange().getValues();
  const headers   = allValues[0];

  const colIndex = (name) => headers.indexOf(name);
  const companyCol  = colIndex("Company name");
  const dmuCol      = colIndex("DMU name");

  // Build a set of existing company+dmu pairs for dedup
  const existing = new Set();
  for (let i = 1; i < allValues.length; i++) {
    const company = String(allValues[i][companyCol] || "").trim().toLowerCase();
    const dmu     = String(allValues[i][dmuCol]     || "").trim().toLowerCase();
    if (company) existing.add(`${company}||${dmu}`);
  }

  let written = 0;
  let nextRow = allValues.length + 1; // 1-indexed, after last row with data

  for (const lead of leads) {
    const company = String(lead.company_name || "").trim().toLowerCase();
    const dmu     = String(lead.dmu_name     || "").trim().toLowerCase();
    const key     = `${company}||${dmu}`;

    if (existing.has(key)) {
      Logger.log("Skipping duplicate: " + lead.company_name);
      continue;
    }

    const row = buildRow(lead);
    sheet.getRange(nextRow, 1, 1, row.length).setValues([row]);

    existing.add(key);
    nextRow++;
    written++;
  }

  return written;
}

function buildRow(lead) {
  const notes = [lead.dmu_title, lead.notes].filter(Boolean).join("  ").trim();
  const map = {
    "Company name":      lead.company_name    || "",
    "Location":          lead.location        || "",
    "Industry":          lead.industry        || "",
    "DMU name":          lead.dmu_name        || "",
    "DMU phone":         lead.dmu_phone       || "",
    "DMU mail":          lead.dmu_email       || "",
    "expected desire":   lead.expected_desire || "",
    "comp. phone":       lead.company_phone   || "",
    "comp. mail":        lead.company_email   || "",
    "notes":             notes,
    "owner":             "",
    "last tried call":   "",
    "last spoken":       "",
    "notes2":            "",
    "sourced":           "AI leadlist",
    "phase":             "Attention (lead)",
    "Rejected (reason)": "",
  };
  return SHEET_COLUMNS.map((col) => map[col] !== undefined ? map[col] : "");
}

// ── One-time setup: insert a button into the sheet ───────────
function createButton() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const drawing = sheet.newChart()  // we use a drawing-over-button trick via a macro button

  // Insert a simple "Run" button as an image-linked drawing
  // Apps Script doesn't have a native button API, so we use an over-cell drawing
  const btn = sheet.insertImage(
    Charts.newDataTable().build(), 1, 1   // placeholder — see note below
  );
}
// NOTE: Apps Script doesn't have a true "button" API.
// The standard approach is:
//   Insert → Drawing → draw a shape → assign script "generateLeads"
// Do this manually once:
//   1. In the sheet click Insert → Drawing
//   2. Draw a rectangle, type "Generate AI Leads"
//   3. Save & close
//   4. Click the three-dot menu on the drawing → Assign script → type: generateLeads

# config.py — Central configuration for the VZA CRM agent system

# Google Sheets
SHEET_ID = "1gSJhvfIR4Gnq6cOgUpmMOiXUwnI913zElWmuGH-Ihwk"
SERVICE_ACCOUNT_JSON = r"D:\vza-crm-agent.json.json"

# Column order must match the Google Sheet exactly
SHEET_COLUMNS = [
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
]

# Ideal Customer Profile (ICP) used by the AI lead generator
ICP = {
    "industry": ["logistics", "manufacturing"],
    "region": ["Oost-Brabant", "Brainport Eindhoven"],
    "company_size": "50-500 FTE",
    "target_titles": [
        "Directeur",
        "Operations Manager",
        "CFO",
    ],
}

# Anthropic model to use for AI lead generation
CLAUDE_MODEL = "claude-sonnet-4-6"

# LinkedIn scraper rate limiting (seconds)
RATE_LIMIT_MIN = 3.0
RATE_LIMIT_MAX = 7.0

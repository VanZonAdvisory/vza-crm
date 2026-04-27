"""
ai_lead_generator.py — Generate B2B leads via Claude and push them to the CRM.

Usage:
    python ai_lead_generator.py
    python ai_lead_generator.py --industry "logistics" --region "Eindhoven" --size "50-200 FTE"

The agent sends a structured prompt to the Claude API requesting a JSON list of
B2B leads that match the configured ICP.  Each returned lead is validated and
written to the Google Sheet via append_lead().

The ANTHROPIC_API_KEY environment variable must be set.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

import anthropic

from config import ICP, CLAUDE_MODEL
from sheets_writer import append_lead

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a B2B lead research specialist. When given an Ideal Customer Profile (ICP),
you return a JSON array of realistic company leads. Each element must be a JSON object
with exactly these keys (use empty string "" for unknown values):

  company_name      — full legal or trading name of the company
  location          — city, region (e.g. "Eindhoven, Noord-Brabant")
  industry          — primary industry sector
  dmu_name          — full name of the Decision-Making Unit contact
  dmu_title         — job title of that person
  dmu_phone         — direct phone number (if publicly known)
  dmu_email         — business e-mail (if publicly known)
  company_phone     — main company switchboard number
  company_email     — general company e-mail
  expected_desire   — one-sentence hypothesis on the company's likely pain point or need
  notes             — any other relevant detail

Return ONLY the JSON array — no markdown fences, no preamble, no explanation.
"""


def _build_user_prompt(industry: list[str], region: list[str], size: str, titles: list[str]) -> str:
    return (
        f"Generate 10 realistic B2B leads matching the following ICP:\n"
        f"- Industry: {', '.join(industry)}\n"
        f"- Region: {', '.join(region)}\n"
        f"- Company size: {size}\n"
        f"- Target decision-maker titles: {', '.join(titles)}\n\n"
        "Focus on companies that are likely to need operational efficiency improvements, "
        "logistics optimisation, or supply-chain consulting services.\n"
        "Return the JSON array now."
    )


# ---------------------------------------------------------------------------
# API call and parsing
# ---------------------------------------------------------------------------

def generate_leads(
    industry: list[str] | None = None,
    region: list[str] | None = None,
    size: str | None = None,
    titles: list[str] | None = None,
) -> list[dict]:
    """
    Call the Claude API with an ICP prompt and return a list of lead dicts.
    Falls back to config.ICP values for any parameter not supplied.
    """
    industry = industry or ICP["industry"]
    region = region or ICP["region"]
    size = size or ICP["company_size"]
    titles = titles or ICP["target_titles"]

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Export it before running this agent."
        )

    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = _build_user_prompt(industry, region, size, titles)
    logger.info("Sending ICP prompt to Claude (%s)…", CLAUDE_MODEL)

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = message.content[0].text.strip()
    logger.debug("Raw response:\n%s", raw_text)

    try:
        leads_raw: list[Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("Claude returned invalid JSON: %s\n\nRaw output:\n%s", exc, raw_text)
        raise

    if not isinstance(leads_raw, list):
        raise ValueError(f"Expected a JSON array, got {type(leads_raw).__name__}")

    return leads_raw


def _map_to_sheet_row(raw: dict) -> dict:
    """Convert a raw Claude lead dict to the sheet column schema."""
    return {
        "Company name": raw.get("company_name", ""),
        "Location": raw.get("location", ""),
        "Industry": raw.get("industry", ""),
        "DMU name": raw.get("dmu_name", ""),
        "DMU phone": raw.get("dmu_phone", ""),
        "DMU mail": raw.get("dmu_email", ""),
        "expected desire": raw.get("expected_desire", ""),
        "comp. phone": raw.get("company_phone", ""),
        "comp. mail": raw.get("company_email", ""),
        "notes": f"{raw.get('dmu_title', '')}  {raw.get('notes', '')}".strip(),
        "owner": "",
        "last tried call": "",
        "last spoken": "",
        "notes2": "",
        "sourced": "AI leadlist",
        "phase": "Attention (lead)",
        "Rejected (reason)": "",
        # No linkedin_url — dedup will fall back to Company name + DMU name
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate B2B leads with Claude and push to CRM")
    parser.add_argument("--industry", nargs="+", help="Industry sectors (overrides config)")
    parser.add_argument("--region", nargs="+", help="Target regions (overrides config)")
    parser.add_argument("--size", help="Company size range, e.g. '50-200 FTE' (overrides config)")
    parser.add_argument("--titles", nargs="+", help="Target job titles (overrides config)")
    args = parser.parse_args()

    try:
        raw_leads = generate_leads(
            industry=args.industry,
            region=args.region,
            size=args.size,
            titles=args.titles,
        )
    except Exception as exc:
        logger.error("Lead generation failed: %s", exc)
        sys.exit(1)

    logger.info("Received %d leads from Claude. Writing to CRM…", len(raw_leads))
    written = 0
    skipped = 0

    for raw in raw_leads:
        if not isinstance(raw, dict):
            logger.warning("Skipping non-dict entry: %r", raw)
            continue
        row = _map_to_sheet_row(raw)
        try:
            if append_lead(row):
                written += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("Failed to write lead %r: %s", raw.get("company_name"), exc)

    print(f"\nDone. {written} new lead(s) written, {skipped} duplicate(s) skipped.")


if __name__ == "__main__":
    main()

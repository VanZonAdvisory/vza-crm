"""
linkedin_profile_agent.py — Import a single LinkedIn profile into the CRM.

Accepts a LinkedIn profile PDF (exported via LinkedIn's "Save to PDF" feature),
extracts the key fields using Claude AI, and calls append_lead().

Usage:
    python linkedin_profile_agent.py --pdf "C:/Users/.../peter_janssen.pdf"
    python linkedin_profile_agent.py --pdf "C:/Users/.../peter_janssen.pdf" --url "https://www.linkedin.com/in/janssen-peter/"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

from sheets_writer import append_lead

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(pdf_path: str) -> str:
    """Return all text from a PDF as a single string."""
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed. Run: pip install pdfplumber")
        sys.exit(1)

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)

    return "\n".join(pages)


# ---------------------------------------------------------------------------
# Claude-based extraction (primary)
# ---------------------------------------------------------------------------

def _get_anthropic_api_key() -> str:
    """Return the Anthropic API key from Streamlit secrets or environment."""
    try:
        import streamlit as st
        try:
            key = st.secrets["ANTHROPIC_API_KEY"]
            if key:
                return str(key)
        except KeyError:
            pass
    except Exception:
        pass
    return os.getenv("ANTHROPIC_API_KEY", "")


def _parse_with_claude(text: str) -> dict:
    """
    Use Claude to extract lead fields from raw LinkedIn PDF text.
    Returns a dict with keys: name, title, company, location, phone, email.
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    api_key = _get_anthropic_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""You are extracting contact information from a LinkedIn profile PDF export.

The text below was extracted from the PDF. LinkedIn PDFs often use a two-column layout, so the text may be interleaved from different sections.

Extract the following fields:
- name: The person's full name
- title: Their current job title
- company: Their current employer (the company they work at now)
- location: Their city/region
- phone: Their phone number (if present)
- email: Their email address (if present)

Rules:
- "company" must be an actual company/organisation name, never a section header like "Ervaring", "Vaardigheden", "Belangrijkste vaardigheden", "Skills", "Experience", etc.
- If a field is not found, return an empty string for that field.
- Return ONLY a valid JSON object, no explanation.

LinkedIn PDF text:
{text[:4000]}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    result = json.loads(raw)

    return {
        "name":     str(result.get("name",     "") or ""),
        "title":    str(result.get("title",    "") or ""),
        "company":  str(result.get("company",  "") or ""),
        "location": str(result.get("location", "") or ""),
        "phone":    str(result.get("phone",    "") or ""),
        "email":    str(result.get("email",    "") or ""),
    }


# ---------------------------------------------------------------------------
# Regex-based fallback extraction
# ---------------------------------------------------------------------------

_SECTION_LABEL_PREFIXES = [
    "contactgegevens ",
    "contact details ",
    "profiel ",
    "profile ",
    "samenvatting ",
    "summary ",
]

_SECTION_HEADERS = {
    "contactgegevens", "contact", "contact details",
    "ervaring", "experience", "werkervaring",
    "opleiding", "education",
    "vaardigheden", "skills",
    "belangrijkste vaardigheden", "top skills",
    "alle vaardigheden weergeven",
    "aanbevelingen", "recommendations",
    "certificeringen", "certifications",
    "vrijwilligerswerk", "volunteering",
    "talen", "languages",
    "projecten", "projects",
    "publicaties", "publications",
    "interessen", "interests",
    "activiteiten", "activities",
    "cursussen", "courses",
    "organisaties", "organizations",
    "samenvatting", "summary", "about",
    "onderscheidingen en prijzen", "honors & awards",
    "overige activiteiten", "bijdragen",
}


def _parse_profile_lines(lines: list[str]) -> dict:
    """Regex/heuristic fallback parser for LinkedIn profile text lines."""
    name = title = company = location = phone = email = ""

    # Name — first non-empty, non-header line; strip known label prefixes
    name_idx = 0
    for i, line in enumerate(lines):
        clean = line.strip()
        if clean.lower() in _SECTION_HEADERS:
            continue
        if not clean or clean.startswith("http") or "@" in clean:
            continue
        lower = clean.lower()
        for prefix in _SECTION_LABEL_PREFIXES:
            if lower.startswith(prefix):
                clean = clean[len(prefix):].strip()
                break
        if clean:
            name = clean
            name_idx = i
            break

    # Title (and optionally company) — line after name
    for line in lines[name_idx + 1: name_idx + 4]:
        clean = line.strip()
        if not clean or clean.lower() in _SECTION_HEADERS:
            continue
        for sep in (" at ", " bij ", " @ "):
            if sep in clean:
                parts = clean.split(sep, 1)
                title = parts[0].strip()
                company = parts[1].strip()
                break
        else:
            title = clean
        break

    # Location — short line near the top
    for line in lines[name_idx + 1: name_idx + 10]:
        clean = line.strip()
        if not clean or clean.lower() in _SECTION_HEADERS:
            continue
        if clean == title or clean == company:
            continue
        if any(c in clean for c in ["@", "http", "linkedin"]):
            continue
        if len(clean) < 80:
            location = clean
            break

    # Phone
    phone_re = re.compile(r"(\+?31[\s\-]?|0)[\s\-]?(\d[\s\-]?){8,10}")
    for line in lines:
        m = phone_re.search(line)
        if m:
            phone = re.sub(r"[\s\-]", "", m.group())
            break

    # Email
    email_re = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    for line in lines:
        m = email_re.search(line)
        if m:
            email = m.group()
            break

    # Company fallback — first real line below "Ervaring" / "Werkervaring"
    if not company:
        for i, line in enumerate(lines):
            if line.strip().lower() in ("experience", "werkervaring", "ervaring"):
                for j in range(i + 1, min(i + 15, len(lines))):
                    candidate = lines[j].strip()
                    if (
                        len(candidate) > 2
                        and candidate not in ("·", "-")
                        and candidate.lower() not in _SECTION_HEADERS
                        and "@" not in candidate
                        and not candidate.startswith("http")
                    ):
                        company = candidate
                        break
                break

    return {
        "name":     name,
        "title":    title,
        "company":  company,
        "location": location,
        "phone":    phone,
        "email":    email,
    }


# ---------------------------------------------------------------------------
# URL scraping via Playwright + Claude
# ---------------------------------------------------------------------------

def _ensure_chromium() -> None:
    """Install Playwright's Chromium browser if it is not already present."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.warning("playwright install returned non-zero: %s", result.stderr)


def _extract_from_url(url: str) -> dict:
    """
    Scrape a LinkedIn profile URL and extract fields using Claude.

    Visits both the main profile page and the /overlay/contact-info/ sub-page
    so that email, phone, and website are captured when the user is logged in.
    Requires the Playwright Chromium browser to be installed.
    """
    try:
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    # Normalise URL — strip trailing slash
    url = url.rstrip("/")
    contact_url = f"{url}/overlay/contact-info/"

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def _scrape() -> dict:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context  = browser.new_context(user_agent=USER_AGENT)
            page     = context.new_page()

            # ---- Main profile page ----------------------------------------
            logger.info("Opening LinkedIn profile: %s", url)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)

            # Detect login / auth wall
            if "login" in page.url or "authwall" in page.url:
                browser.close()
                raise RuntimeError(
                    "LinkedIn requires you to be logged in to view this profile. "
                    "Please download the profile as a PDF instead "
                    "(LinkedIn profile → More → Save to PDF)."
                )

            profile_text = page.inner_text("body")

            # ---- Contact-info overlay -------------------------------------
            contact_text = ""
            try:
                logger.info("Checking contact info: %s", contact_url)
                page.goto(contact_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_000)
                # If redirected to login, skip silently
                if "login" not in page.url and "authwall" not in page.url:
                    contact_text = page.inner_text("body")
            except Exception as exc:
                logger.warning("Could not fetch contact-info overlay: %s", exc)

            browser.close()

        # ---- Pass both pages to Claude ------------------------------------
        combined = (
            f"=== LINKEDIN PROFILE ===\n{profile_text[:3000]}\n\n"
            f"=== CONTACT INFO PAGE ===\n{contact_text[:1500]}"
        )
        return _parse_with_claude(combined)

    # First attempt — auto-install Chromium and retry if binary is missing
    try:
        return _scrape()
    except PlaywrightError as exc:
        if "Executable doesn't exist" in str(exc):
            logger.info("Chromium not found — installing now…")
            _ensure_chromium()
            return _scrape()
        raise


# ---------------------------------------------------------------------------
# Public extraction entry point
# ---------------------------------------------------------------------------

def _extract_from_pdf(pdf_path: str) -> dict:
    """
    Extract lead fields from a LinkedIn profile PDF.

    Tries Claude AI first (handles two-column layout correctly).
    Falls back to regex parsing if the API is unavailable.
    """
    text = _extract_text_from_pdf(pdf_path)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    if not lines:
        raise ValueError(f"Could not extract any text from {pdf_path}")

    # Primary: Claude AI
    try:
        fields = _parse_with_claude(text)
        if fields.get("name") or fields.get("company"):
            logger.info("Extracted via Claude: %s", fields)
            return fields
        logger.warning("Claude returned empty result — falling back to regex")
    except Exception as exc:
        logger.warning("Claude extraction failed (%s) — falling back to regex", exc)

    # Fallback: regex / heuristic
    fields = _parse_profile_lines(lines)
    logger.info("Extracted via regex: %s", fields)
    return fields


# ---------------------------------------------------------------------------
# Build CRM row
# ---------------------------------------------------------------------------

def _to_lead_row(fields: dict, linkedin_url: str = "") -> dict:
    return {
        "Company name":      fields.get("company",  ""),
        "Location":          fields.get("location", ""),
        "Industry":          "",
        "DMU name":          fields.get("name",     ""),
        "DMU phone":         fields.get("phone",    ""),
        "DMU mail":          fields.get("email",    ""),
        "expected desire":   "",
        "comp. phone":       "",
        "comp. mail":        "",
        "notes":             fields.get("title",    ""),
        "owner":             "",
        "last tried call":   "",
        "last spoken":       "",
        "notes2":            "",
        "sourced":           "LinkedIn",
        "phase":             "Attention (lead)",
        "Rejected (reason)": "",
        "linkedin_url":      linkedin_url,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a LinkedIn profile PDF into the CRM"
    )
    parser.add_argument("--pdf", required=True, help="Path to a LinkedIn profile PDF")
    parser.add_argument("--url", help="LinkedIn profile URL (used for deduplication)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        logger.error("PDF file not found: %s", args.pdf)
        sys.exit(1)

    fields = _extract_from_pdf(str(pdf_path))

    logger.info(
        "Extracted — name: %r  title: %r  company: %r  phone: %r  email: %r",
        fields.get("name"), fields.get("title"), fields.get("company"),
        fields.get("phone"), fields.get("email"),
    )

    if not fields.get("name") and not fields.get("company"):
        logger.error("Could not extract name or company — aborting.")
        sys.exit(1)

    row = _to_lead_row(fields, linkedin_url=args.url or "")
    written = append_lead(row)

    if written:
        print(f"\nDone. '{fields.get('name')}' at '{fields.get('company')}' written to CRM.")
    else:
        print(f"\nSkipped — '{fields.get('name')}' at '{fields.get('company')}' already exists.")


if __name__ == "__main__":
    main()

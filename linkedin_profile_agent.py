"""
linkedin_profile_agent.py — Import a single LinkedIn profile into the CRM.

Accepts either a LinkedIn profile URL (scraped via Playwright) or a LinkedIn
profile PDF (exported via LinkedIn's "Save to PDF" feature), extracts the
key fields, and calls append_lead().

Usage:
    python linkedin_profile_agent.py --url "https://www.linkedin.com/in/janssen-peter/"
    python linkedin_profile_agent.py --pdf "C:/Users/.../peter_janssen.pdf"
    python linkedin_profile_agent.py --pdf "C:/Users/.../peter_janssen.pdf" --url "https://www.linkedin.com/in/janssen-peter/"
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path

from sheets_writer import append_lead

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known section-label prefixes that LinkedIn sometimes prepends to the name
# line in PDF exports (Dutch and English).
# ---------------------------------------------------------------------------
_SECTION_LABEL_PREFIXES = [
    "contactgegevens ",   # Dutch: "Contact details"
    "contact details ",
    "profiel ",
    "profile ",
    "samenvatting ",
    "summary ",
]

# Section headers that should never be treated as the person's name.
_SECTION_HEADERS = {
    "contactgegevens", "contact", "contact details",
    "ervaring", "experience", "werkervaring",
    "opleiding", "education",
    "vaardigheden", "skills",
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
}


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def _extract_from_pdf(pdf_path: str) -> dict:
    """Extract lead fields from a LinkedIn profile PDF."""
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed. Run: pip install pdfplumber")
        sys.exit(1)

    text_lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_lines.extend(page_text.splitlines())

    # Remove empty lines
    lines = [l.strip() for l in text_lines if l.strip()]

    if not lines:
        raise ValueError(f"Could not extract any text from {pdf_path}")

    logger.debug("PDF lines extracted: %s", lines[:20])
    return _parse_profile_lines(lines)


def _parse_profile_lines(lines: list[str]) -> dict:
    """
    Parse plain-text lines from a LinkedIn profile into a lead dict.

    LinkedIn PDF structure (approximate, Dutch):
      Line 0:  "Contactgegevens Niels van Zon"  (or just the name)
      Line 1:  Job title / headline  (sometimes "Title bij Company")
      Line 2:  Location
      ...
      Section "Ervaring":
        Company name (first line below the header)
        Job title at that company
    """
    name     = ""
    title    = ""
    company  = ""
    location = ""
    phone    = ""
    email    = ""

    # ------------------------------------------------------------------
    # Name — first non-empty line that isn't a pure section header.
    # Strip known Dutch/English label prefixes that LinkedIn prepends.
    # ------------------------------------------------------------------
    name_idx = 0
    for i, line in enumerate(lines):
        clean = line.strip()
        if clean.lower() in _SECTION_HEADERS:
            continue  # pure header like "Contactgegevens" alone — skip
        if not clean or clean.startswith("http") or "@" in clean:
            continue

        # Strip a known prefix if the name was merged with a section label
        lower = clean.lower()
        for prefix in _SECTION_LABEL_PREFIXES:
            if lower.startswith(prefix):
                clean = clean[len(prefix):].strip()
                break

        if clean:
            name     = clean
            name_idx = i
            break

    # ------------------------------------------------------------------
    # Title (and sometimes company) — line immediately after name
    # ------------------------------------------------------------------
    for line in lines[name_idx + 1: name_idx + 4]:
        clean = line.strip()
        if not clean or clean.lower() in _SECTION_HEADERS:
            continue
        raw_title = clean
        # LinkedIn sometimes writes "Title at Company" / "Title bij Company"
        for sep in (" at ", " bij ", " @ "):
            if sep in raw_title:
                parts   = raw_title.split(sep, 1)
                title   = parts[0].strip()
                company = parts[1].strip()
                break
        else:
            title = raw_title
        break

    # ------------------------------------------------------------------
    # Location — short line in the first ~10 lines after the name that
    # looks geographic (or simply isn't a section header / URL / email).
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Phone — search all lines for a phone-like pattern
    # ------------------------------------------------------------------
    phone_pattern = re.compile(
        r"(\+?31[\s\-]?|0)[\s\-]?"   # NL prefix
        r"(\d[\s\-]?){8,10}"          # digits
    )
    for line in lines:
        match = phone_pattern.search(line)
        if match:
            phone = re.sub(r"[\s\-]", "", match.group())
            break

    # ------------------------------------------------------------------
    # Email — search all lines
    # ------------------------------------------------------------------
    email_pattern = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    for line in lines:
        match = email_pattern.search(line)
        if match:
            email = match.group()
            break

    # ------------------------------------------------------------------
    # Company fallback — first non-empty line below "Ervaring" section
    # ------------------------------------------------------------------
    if not company:
        for i, line in enumerate(lines):
            if line.strip().lower() in ("experience", "werkervaring", "ervaring"):
                for j in range(i + 1, min(i + 6, len(lines))):
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
# URL scraping via Playwright
# ---------------------------------------------------------------------------

def _ensure_chromium() -> None:
    """Install Playwright's Chromium browser if it is not already present."""
    logger.info("Ensuring Playwright Chromium is installed…")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("playwright install returned non-zero: %s", result.stderr)


def _extract_from_url(url: str) -> dict:
    """Scrape a LinkedIn profile page and return extracted fields."""
    try:
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
    except ImportError:
        logger.error(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        )
        sys.exit(1)

    def _do_scrape():
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            logger.info("Opening LinkedIn profile: %s", url)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)

            # If redirected to login / auth wall, abort — cannot log in headlessly
            if "login" in page.url or "authwall" in page.url:
                browser.close()
                raise RuntimeError(
                    "LinkedIn requires you to be logged in to view this profile. "
                    "Please download the profile as a PDF (More → Save to PDF) "
                    "and upload it instead."
                )

            def _text(selector: str) -> str:
                el = page.query_selector(selector)
                return el.inner_text().strip() if el else ""

            # Name
            name = _text("h1.text-heading-xlarge") or _text("h1")

            # Headline — LinkedIn shows "Title bij Company" or just a title
            headline = _text("div.text-body-medium.break-words")
            title    = headline
            company  = ""
            for sep in (" at ", " bij ", " @ ", " - ", " | "):
                if sep in headline:
                    parts   = headline.split(sep, 1)
                    title   = parts[0].strip()
                    company = parts[1].strip()
                    break

            # Company from experience section if headline had no separator
            if not company:
                for selector in [
                    "section[id*='experience'] div.t-bold span[aria-hidden='true']",
                    "section[data-section='experience'] span.t-bold",
                    "li[data-view-name='profile-component-entity']:first-child span.t-bold",
                ]:
                    el = page.query_selector(selector)
                    if el:
                        candidate = el.inner_text().strip()
                        if candidate and candidate.lower() != title.lower():
                            company = candidate
                            break

            # Location
            location = _text("span.text-body-small.inline.t-black--light.break-words")

            # Phone & email — try contact-info modal
            phone = ""
            email = ""
            try:
                contact_link = page.query_selector("a[href*='contact-info']")
                if contact_link:
                    contact_link.click()
                    page.wait_for_timeout(1500)
                    phone_el = page.query_selector("section.ci-phone span.t-14")
                    if phone_el:
                        phone = phone_el.inner_text().strip()
                    email_el = page.query_selector("section.ci-email a.t-14")
                    if email_el:
                        email = email_el.inner_text().strip()
                    page.keyboard.press("Escape")
            except Exception:
                pass

            browser.close()

        return {
            "name":     name,
            "title":    title,
            "company":  company,
            "location": location,
            "phone":    phone,
            "email":    email,
        }

    # First attempt — if Chromium is not installed, install it and retry once
    try:
        return _do_scrape()
    except PlaywrightError as exc:
        if "Executable doesn't exist" in str(exc):
            logger.info("Chromium not found — installing now…")
            _ensure_chromium()
            return _do_scrape()   # second attempt after install
        raise


# ---------------------------------------------------------------------------
# Build CRM row and write
# ---------------------------------------------------------------------------

def _to_lead_row(fields: dict, linkedin_url: str = "") -> dict:
    return {
        "Company name":      fields.get("company", ""),
        "Location":          fields.get("location", ""),
        "Industry":          "",
        "DMU name":          fields.get("name", ""),
        "DMU phone":         fields.get("phone", ""),
        "DMU mail":          fields.get("email", ""),
        "expected desire":   "",
        "comp. phone":       "",
        "comp. mail":        "",
        "notes":             fields.get("title", ""),
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
        description="Import a LinkedIn profile (URL or PDF) into the CRM"
    )
    parser.add_argument("--url", help="LinkedIn profile URL")
    parser.add_argument("--pdf", help="Path to a LinkedIn profile PDF")
    args = parser.parse_args()

    if not args.url and not args.pdf:
        parser.error("Provide at least --url or --pdf (or both)")

    fields: dict = {}

    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            logger.error("PDF file not found: %s", args.pdf)
            sys.exit(1)
        logger.info("Extracting from PDF: %s", args.pdf)
        fields = _extract_from_pdf(str(pdf_path))

    if args.url and not fields.get("name"):
        logger.info("Extracting from URL: %s", args.url)
        fields = _extract_from_url(args.url)

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
        print(f"\nDone. Lead '{fields.get('name')}' at '{fields.get('company')}' written to CRM.")
    else:
        print(f"\nSkipped — '{fields.get('name')}' at '{fields.get('company')}' already exists in CRM.")


if __name__ == "__main__":
    main()

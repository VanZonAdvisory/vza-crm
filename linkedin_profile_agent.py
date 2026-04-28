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
import sys
from pathlib import Path

from sheets_writer import append_lead

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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

    LinkedIn PDF structure (approximate):
      Line 0:  Full name
      Line 1:  Job title  (sometimes "Title at Company" or just title)
      Line 2:  Location
      ...      Experience section contains current company details
    """
    name     = ""
    title    = ""
    company  = ""
    location = ""
    phone    = ""

    # Name is almost always the first non-empty line
    if lines:
        name = lines[0]

    # Title is usually the second line
    if len(lines) > 1:
        raw_title = lines[1]
        # LinkedIn sometimes writes "Title at Company"
        if " at " in raw_title:
            parts   = raw_title.split(" at ", 1)
            title   = parts[0].strip()
            company = parts[1].strip()
        elif " bij " in raw_title:  # Dutch LinkedIn
            parts   = raw_title.split(" bij ", 1)
            title   = parts[0].strip()
            company = parts[1].strip()
        else:
            title = raw_title

    # Location — look for a line that looks like a city/region
    location_keywords = ["brabant", "eindhoven", "tilburg", "den bosch", "helmond",
                         "nederland", "netherlands", "noord", "limburg", "gelderland"]
    for line in lines[2:8]:
        if any(kw in line.lower() for kw in location_keywords):
            location = line
            break
        # Fallback: short lines after title are often location
        if len(line) < 60 and not any(c in line for c in ["@", "http", "linkedin"]):
            if location == "":
                location = line

    # Phone — search all lines for a phone-like pattern
    phone_pattern = re.compile(
        r"(\+?31[\s\-]?|0)[\s\-]?"         # NL prefix
        r"(\d[\s\-]?){8,10}"               # digits
    )
    for line in lines:
        match = phone_pattern.search(line)
        if match:
            phone = re.sub(r"[\s\-]", "", match.group())
            break

    # Company fallback — look for "Experience" section header, grab next company
    if not company:
        for i, line in enumerate(lines):
            if line.lower() in ("experience", "werkervaring"):
                # Next non-empty line after "Experience" is often the company or title
                for j in range(i + 1, min(i + 5, len(lines))):
                    candidate = lines[j]
                    if len(candidate) > 2 and candidate not in ("·", "-"):
                        company = candidate
                        break
                break

    return {
        "name":     name,
        "title":    title,
        "company":  company,
        "location": location,
        "phone":    phone,
    }


# ---------------------------------------------------------------------------
# URL scraping via Playwright
# ---------------------------------------------------------------------------

def _extract_from_url(url: str) -> dict:
    """Scrape a LinkedIn profile page and return extracted fields."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

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

        # Wait for login wall or profile to load
        page.wait_for_timeout(3000)

        # If redirected to login page, wait for user to log in manually
        if "login" in page.url or "authwall" in page.url:
            logger.info("LinkedIn login required — please log in in the browser window.")
            page.wait_for_url("**/in/**", timeout=120_000)
            page.wait_for_timeout(2000)

        def _text(selector: str) -> str:
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else ""

        # Name
        name = _text("h1.text-heading-xlarge") or _text("h1")

        # Headline — LinkedIn shows "Title at Company" or just a title
        headline = _text("div.text-body-medium.break-words")

        # Parse title and company from headline
        title   = headline
        company = ""
        for sep in (" at ", " bij ", " @ ", " - ", " | "):
            if sep in headline:
                parts   = headline.split(sep, 1)
                title   = parts[0].strip()
                company = parts[1].strip()
                break

        # If headline didn't contain a separator, try the experience section
        if not company:
            # Modern LinkedIn: first experience card company name
            for selector in [
                "section[id*='experience'] div.t-bold span[aria-hidden='true']",
                "section[data-section='experience'] span.t-bold",
                "li[data-view-name='profile-component-entity']:first-child span.t-bold",
            ]:
                el = page.query_selector(selector)
                if el:
                    candidate = el.inner_text().strip()
                    # Skip if it looks like a job title (same as title)
                    if candidate and candidate.lower() != title.lower():
                        company = candidate
                        break

        # Location
        location = _text("span.text-body-small.inline.t-black--light.break-words")

        # Phone — LinkedIn only shows phone to connections; try contact-info modal
        phone = ""
        try:
            contact_link = page.query_selector("a[href*='contact-info']")
            if contact_link:
                contact_link.click()
                page.wait_for_timeout(1500)
                phone_el = page.query_selector("section.ci-phone span.t-14")
                if phone_el:
                    phone = phone_el.inner_text().strip()
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
    }


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
        "DMU mail":          "",
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

    # PDF takes precedence for field extraction; URL is used for dedup key
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
        "Extracted — name: %r  title: %r  company: %r  phone: %r",
        fields.get("name"), fields.get("title"), fields.get("company"), fields.get("phone"),
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

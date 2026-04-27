"""
linkedin_scraper_agent.py — Scrape LinkedIn search results and push leads to the CRM.

Usage:
    python linkedin_scraper_agent.py "<LinkedIn search URL>"

The script opens the URL in a Playwright browser session (headed by default so
you can complete any login / CAPTCHA challenge manually), then paginates through
results, extracting per-result card data and calling append_lead().

Environment variable LINKEDIN_COOKIES_FILE (optional) can point to a JSON file
that contains previously saved cookies so the session resumes authenticated.
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext

from config import RATE_LIMIT_MIN, RATE_LIMIT_MAX
from sheets_writer import append_lead

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COOKIES_FILE: Optional[str] = os.getenv("LINKEDIN_COOKIES_FILE")

# CSS selectors for LinkedIn people/company search result cards.
# LinkedIn's markup changes frequently — update these if scraping breaks.
RESULT_CARD_SELECTOR = "li.reusable-search__result-container"
NAME_SELECTOR = "span.entity-result__title-text a"
TITLE_SELECTOR = "div.entity-result__primary-subtitle"
LOCATION_SELECTOR = "div.entity-result__secondary-subtitle"
COMPANY_SELECTOR = "div.entity-result__summary"  # may contain current company
PROFILE_LINK_SELECTOR = "span.entity-result__title-text a"

NEXT_BUTTON_SELECTOR = "button[aria-label='Next']"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_delay() -> None:
    """Sleep for a randomised duration to avoid bot detection."""
    delay = random.uniform(RATE_LIMIT_MIN, RATE_LIMIT_MAX)
    logger.debug("Sleeping %.1f s", delay)
    time.sleep(delay)


def _load_cookies(context: BrowserContext) -> None:
    if COOKIES_FILE and Path(COOKIES_FILE).exists():
        with open(COOKIES_FILE, "r", encoding="utf-8") as fh:
            cookies = json.load(fh)
        context.add_cookies(cookies)
        logger.info("Loaded %d cookies from %s", len(cookies), COOKIES_FILE)


def _save_cookies(context: BrowserContext) -> None:
    if COOKIES_FILE:
        cookies = context.cookies()
        with open(COOKIES_FILE, "w", encoding="utf-8") as fh:
            json.dump(cookies, fh, indent=2)
        logger.info("Saved %d cookies to %s", len(cookies), COOKIES_FILE)


# ---------------------------------------------------------------------------
# Scraping logic
# ---------------------------------------------------------------------------

def _extract_cards(page: Page) -> list[dict]:
    """Extract lead dicts from all result cards visible on the current page."""
    leads: list[dict] = []

    cards = page.query_selector_all(RESULT_CARD_SELECTOR)
    logger.info("Found %d result cards on this page", len(cards))

    for card in cards:
        try:
            name_el = card.query_selector(NAME_SELECTOR)
            name = name_el.inner_text().strip() if name_el else ""

            # The anchor href is the profile URL
            profile_url = ""
            if name_el:
                href = name_el.get_attribute("href") or ""
                # Strip query params to get the canonical profile URL
                profile_url = href.split("?")[0]

            title_el = card.query_selector(TITLE_SELECTOR)
            title = title_el.inner_text().strip() if title_el else ""

            location_el = card.query_selector(LOCATION_SELECTOR)
            location = location_el.inner_text().strip() if location_el else ""

            company_el = card.query_selector(COMPANY_SELECTOR)
            company_raw = company_el.inner_text().strip() if company_el else ""
            # LinkedIn often prefixes company with "Current: " or similar
            company = company_raw.replace("Current: ", "").replace("Huidig: ", "").strip()

            if not name:
                continue  # skip empty / ad cards

            lead = {
                "Company name": company,
                "Location": location,
                "Industry": "",          # not available from card view
                "DMU name": name,
                "DMU phone": "",
                "DMU mail": "",
                "expected desire": "",
                "comp. phone": "",
                "comp. mail": "",
                "notes": title,          # store job title in notes
                "owner": "",
                "last tried call": "",
                "last spoken": "",
                "notes2": "",
                "sourced": "LinkedIn",
                "phase": "New",
                "Rejected (reason)": "",
                # Dedup key — not written as its own column
                "linkedin_url": profile_url,
            }
            leads.append(lead)
        except Exception as exc:
            logger.warning("Error parsing card: %s", exc)

    return leads


def scrape_search_url(search_url: str) -> int:
    """
    Open *search_url* in Playwright, paginate through results, and push each
    lead to the CRM via append_lead().

    Returns the total number of leads successfully written.
    """
    total_written = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)  # headed so you can log in
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        _load_cookies(context)
        page = context.new_page()

        logger.info("Navigating to: %s", search_url)
        page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
        _random_delay()

        # If LinkedIn shows a login wall, the user can log in manually in the
        # headed browser; we wait up to 2 minutes for the results to appear.
        page.wait_for_selector(RESULT_CARD_SELECTOR, timeout=120_000)

        page_num = 1
        while True:
            logger.info("Processing results page %d", page_num)
            leads = _extract_cards(page)

            for lead in leads:
                try:
                    written = append_lead(lead)
                    if written:
                        total_written += 1
                except Exception as exc:
                    logger.error("Failed to write lead %r: %s", lead.get("DMU name"), exc)

            _random_delay()

            # Attempt to go to the next page
            next_btn = page.query_selector(NEXT_BUTTON_SELECTOR)
            if not next_btn or not next_btn.is_enabled():
                logger.info("No more pages — done.")
                break

            next_btn.click()
            page.wait_for_load_state("domcontentloaded")
            _random_delay()
            page_num += 1

        _save_cookies(context)
        browser.close()

    return total_written


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python linkedin_scraper_agent.py \"<LinkedIn search URL>\"")
        sys.exit(1)

    url = sys.argv[1]
    written = scrape_search_url(url)
    print(f"\nDone. {written} new lead(s) written to the CRM.")


if __name__ == "__main__":
    main()

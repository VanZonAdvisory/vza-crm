"""
apollo_agent.py — Search Apollo.io for real B2B contacts and push them to the CRM.

Usage:
    python apollo_agent.py
    python apollo_agent.py --titles "Operations Manager" "Directeur" --region "Eindhoven"

The APOLLO_API_KEY environment variable must be set.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import requests

from config import ICP
from sheets_writer import append_lead

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

APOLLO_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"

# ---------------------------------------------------------------------------
# Apollo search
# ---------------------------------------------------------------------------

def search_apollo(
    titles: list[str],
    industries: list[str],
    locations: list[str],
    per_page: int = 10,
    page: int = 1,
) -> dict:
    api_key = os.getenv("APOLLO_API_KEY")
    if not api_key:
        raise EnvironmentError("APOLLO_API_KEY environment variable is not set.")

    # Apollo expects array parameters as repeated query params: person_titles[]=X&person_titles[]=Y
    params = []
    for title in titles:
        params.append(("person_titles[]", title))
    for location in locations:
        params.append(("person_locations[]", location))
    for industry in industries:
        params.append(("q_organization_keyword_tags[]", industry))
    params.append(("organization_num_employees_ranges[]", "50,500"))
    params.append(("page", page))
    params.append(("per_page", per_page))

    headers = {
        "x-api-key": api_key,
        "accept": "application/json",
    }
    response = requests.post(APOLLO_SEARCH_URL, params=params, headers=headers, timeout=30)

    if response.status_code in (401, 403):
        raise PermissionError(f"Apollo access denied ({response.status_code}): {response.text}")
    if response.status_code == 429:
        raise RuntimeError("Apollo rate limit hit — wait a minute and try again.")
    if not response.ok:
        raise RuntimeError(f"Apollo API error {response.status_code}: {response.text}")

    return response.json()


# ---------------------------------------------------------------------------
# Mapping Apollo response to CRM row
# ---------------------------------------------------------------------------

def _safe(value) -> str:
    return str(value or "").strip()


def _map_to_sheet_row(person: dict) -> dict:
    org = person.get("organization") or {}

    # Name
    first  = _safe(person.get("first_name"))
    last   = _safe(person.get("last_name"))
    name   = f"{first} {last}".strip()

    # Location — prefer person location, fall back to org city
    city    = _safe(person.get("city"))
    state   = _safe(person.get("state"))
    country = _safe(person.get("country"))
    location_parts = [p for p in [city, state, country] if p]
    location = ", ".join(location_parts)

    # Phone — take first available
    phone_numbers = person.get("phone_numbers") or []
    dmu_phone = _safe(phone_numbers[0].get("sanitized_number") if phone_numbers else "")

    # Email
    dmu_email = _safe(person.get("email"))

    # Company
    company_name  = _safe(org.get("name"))
    company_phone = _safe(org.get("phone"))
    industry      = _safe(org.get("industry"))
    website       = _safe(org.get("website_url"))

    # LinkedIn
    linkedin_url = _safe(person.get("linkedin_url"))

    return {
        "Company name":      company_name,
        "Location":          location,
        "Industry":          industry,
        "DMU name":          name,
        "DMU phone":         dmu_phone,
        "DMU mail":          dmu_email,
        "expected desire":   "",
        "comp. phone":       company_phone,
        "comp. mail":        website,
        "notes":             _safe(person.get("title")),
        "owner":             "",
        "last tried call":   "",
        "last spoken":       "",
        "notes2":            "",
        "sourced":           "AI leadlist",
        "phase":             "Attention (lead)",
        "Rejected (reason)": "",
        # Used for deduplication only — not written as a column
        "linkedin_url":      linkedin_url,
    }


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def run(
    titles: list[str] | None = None,
    industries: list[str] | None = None,
    locations: list[str] | None = None,
    pages: int = 1,
    per_page: int = 10,
) -> None:
    titles     = titles     or ICP["target_titles"]
    industries = industries or ICP["industry"]
    locations  = locations  or ICP["region"]

    total_written  = 0
    total_skipped  = 0

    for page in range(1, pages + 1):
        logger.info(
            "Searching Apollo — page %d (titles=%s, locations=%s)",
            page, titles, locations,
        )
        try:
            data = search_apollo(titles, industries, locations, per_page=per_page, page=page)
        except Exception as exc:
            logger.error("Apollo search failed: %s", exc)
            sys.exit(1)

        people = data.get("people") or []
        logger.info("Apollo returned %d contacts on page %d", len(people), page)

        if not people:
            logger.info("No more results — stopping.")
            break

        for person in people:
            row = _map_to_sheet_row(person)
            if not row["Company name"] and not row["DMU name"]:
                continue
            try:
                if append_lead(row):
                    total_written += 1
                else:
                    total_skipped += 1
            except Exception as exc:
                logger.error("Failed to write lead %r: %s", row.get("DMU name"), exc)

        if page < pages:
            time.sleep(1)  # be polite to the API

    print(f"\nDone. {total_written} new lead(s) written, {total_skipped} duplicate(s) skipped.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch real B2B leads from Apollo and push to CRM")
    parser.add_argument("--titles",     nargs="+", help="Job titles to search (overrides config)")
    parser.add_argument("--industries", nargs="+", help="Industries to search (overrides config)")
    parser.add_argument("--locations",  nargs="+", help="Locations to search (overrides config)")
    parser.add_argument("--pages",      type=int, default=1, help="Number of result pages to fetch (default 1 = 10 leads)")
    parser.add_argument("--per-page",   type=int, default=10, help="Results per page, max 25 (default 10)")
    args = parser.parse_args()

    run(
        titles=args.titles,
        industries=args.industries,
        locations=args.locations,
        pages=args.pages,
        per_page=min(args.per_page, 25),
    )


if __name__ == "__main__":
    main()

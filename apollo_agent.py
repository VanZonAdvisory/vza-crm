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
    seniorities: list[str] | None = None,
    employee_ranges: list[str] | None = None,
    per_page: int = 25,
    page: int = 1,
    api_key: str = "",
) -> dict:
    if not api_key:
        api_key = os.getenv("APOLLO_API_KEY", "")
    if not api_key:
        raise EnvironmentError("APOLLO_API_KEY is not set.")

    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    }
    body: dict = {
        "api_key":  api_key,
        "page":     page,
        "per_page": per_page,
    }
    if locations:
        body["organization_locations"] = locations
    if titles:
        body["person_titles"] = titles
    if industries:
        body["q_organization_keyword_tags"] = industries
    if seniorities:
        body["person_seniorities"] = seniorities
    if employee_ranges:
        body["organization_num_employees_ranges"] = employee_ranges

    response = requests.post(APOLLO_SEARCH_URL, headers=headers, json=body, timeout=30)

    if response.status_code in (401, 403):
        raise PermissionError(f"Apollo access denied ({response.status_code}): {response.text}")
    if response.status_code == 422:
        raise ValueError(f"Apollo 422 — invalid parameters.\n\nRequest body: {body}\n\nResponse: {response.text}")
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

    # Location — company HQ city/state/country
    city    = _safe(org.get("city"))    or _safe(person.get("city"))
    state   = _safe(org.get("state"))   or _safe(person.get("state"))
    country = _safe(org.get("country")) or _safe(person.get("country"))
    location = ", ".join(p for p in [city, state, country] if p)

    # Phone — take first available
    phone_numbers = person.get("phone_numbers") or []
    dmu_phone = _safe(phone_numbers[0].get("sanitized_number") if phone_numbers else "")

    # Email
    dmu_email = _safe(person.get("email"))

    # Company
    company_name    = _safe(org.get("name"))
    company_phone   = _safe(org.get("phone"))
    company_website = _safe(org.get("website_url"))
    industry        = _safe(org.get("industry"))
    employees       = _safe(org.get("estimated_num_employees"))
    revenue         = _safe(org.get("annual_revenue"))
    company_linkedin = _safe(org.get("linkedin_url"))

    # Person
    dmu_linkedin = _safe(person.get("linkedin_url"))
    seniority    = _safe(person.get("seniority"))
    departments  = ", ".join(person.get("departments") or [])
    apollo_id    = _safe(person.get("id"))
    email_status = _safe(person.get("email_status"))

    return {
        "Company name":         company_name,
        "Location":             location,
        "Industry":             industry,
        "DMU name":             name,
        "DMU title":            _safe(person.get("title")),
        "DMU phone":            dmu_phone,
        "DMU mail":             dmu_email,
        "expected desire":      "",
        "comp. phone":          company_phone,
        "comp. mail":           "",
        "sales notes":          "",
        "owner":                "",
        "last tried call":      "",
        "last spoken":          "",
        "contact notes":        "",
        "source":               "Apollo",
        "phase":                "",
        "Rejected":             "",
        "DMU LI URL":           dmu_linkedin,
        "comp. LI URL":         company_linkedin,
        "website":              company_website,
        "# employees":          employees,
        "annual revenue":       revenue,
        "seniority":            seniority,
        "department":           departments,
        "Apollo contact ID":    apollo_id,
        "email status":         email_status,
        # Deduplication key — not written as a column
        "linkedin_url":         dmu_linkedin,
    }


# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------

_APOLLO_HEADERS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
}


def enrich_person(
    name: str = "",
    company: str = "",
    linkedin_url: str = "",
    email: str = "",
    api_key: str = "",
) -> dict:
    """
    Call Apollo /v1/people/match for a single contact.
    Returns the 'person' dict (empty dict if not found).
    Match priority: LinkedIn URL → email → first+last+company name.
    """
    if not api_key:
        api_key = os.getenv("APOLLO_API_KEY", "")

    hdrs = {**_APOLLO_HEADERS, "X-Api-Key": api_key}
    body: dict = {"api_key": api_key, "reveal_personal_emails": True}

    if linkedin_url:
        body["linkedin_url"] = linkedin_url
    elif email:
        body["email"] = email
    else:
        parts = name.split()
        body["first_name"] = parts[0] if parts else ""
        body["last_name"] = " ".join(parts[1:]) if len(parts) > 1 else ""
        body["organization_name"] = company

    resp = requests.post("https://api.apollo.io/v1/people/match", headers=hdrs, json=body, timeout=20)
    if resp.status_code == 422:
        raise ValueError(f"Apollo people/match 422: {resp.text}")
    if not resp.ok:
        raise RuntimeError(f"Apollo people/match {resp.status_code}: {resp.text}")
    return resp.json().get("person") or {}


def enrich_company(name: str = "", website: str = "", api_key: str = "") -> dict:
    """
    Call Apollo /v1/organizations/enrich for a company.
    Returns the 'organization' dict (empty dict if not found).
    Requires a website/domain — returns empty dict when none is available
    (Apollo does not support name-only lookup on this endpoint).
    """
    if not website:
        return {}

    if not api_key:
        api_key = os.getenv("APOLLO_API_KEY", "")

    domain = website.replace("https://", "").replace("http://", "").split("/")[0]
    hdrs = {**_APOLLO_HEADERS, "X-Api-Key": api_key}
    body: dict = {"api_key": api_key, "domain": domain}

    resp = requests.post("https://api.apollo.io/v1/organizations/enrich", headers=hdrs, json=body, timeout=20)
    if resp.status_code == 422:
        raise ValueError(f"Apollo organizations/enrich 422: {resp.text}")
    if not resp.ok:
        raise RuntimeError(f"Apollo organizations/enrich {resp.status_code}: {resp.text}")
    return resp.json().get("organization") or {}


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

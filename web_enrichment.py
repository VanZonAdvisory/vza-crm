"""
web_enrichment.py — Sequential web-based enrichment via Tavily + Claude.

Enrichment order
----------------
Company (always):
  comp. LI URL → Location → Industry → comp. phone → comp. mail
  → website → # employees → annual revenue → sales notes

DMU (when DMU name is known):
  DMU LI URL → DMU title → DMU mail → DMU phone → seniority → department

No DMU (when company is known but DMU name is blank):
  Search for likely decision-makers and write suggestions to contact notes.

Each phase uses fields already found in earlier phases as search context,
so quality improves as more data becomes available.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field lists (in priority order)
# ---------------------------------------------------------------------------

_COMPANY_FIELDS = [
    "comp. LI URL",
    "Location",
    "Industry",
    "comp. phone",
    "comp. mail",
    "website",
    "# employees",
    "annual revenue",
    "sales notes",
]

_DMU_FIELDS = [
    "DMU LI URL",
    "DMU title",
    "DMU mail",
    "DMU phone",
    "seniority",
    "department",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _needs(lead: dict, fields: list[str]) -> bool:
    """Return True if any field in *fields* is still empty in *lead*."""
    return any(not lead.get(f, "").strip() for f in fields)


def _search(tv_client, query: str, max_results: int = 5) -> tuple[str, list[str]]:
    hits = tv_client.search(query, max_results=max_results)
    snippets = " ".join(r.get("content", "")[:400] for r in hits.get("results", []))
    urls     = [r.get("url", "") for r in hits.get("results", [])]
    return snippets, urls


def _extract(ac_client, system: str, user_msg: str) -> dict:
    """Call Claude Haiku and parse the JSON response."""
    raw = ac_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    ).content[0].text.strip()

    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _linkedin_url_from_results(urls: list[str], pattern: str) -> str:
    """Return the first URL that contains *pattern*, stripped of query params."""
    for url in urls:
        if pattern in url:
            return url.split("?")[0]
    return ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def enrich_from_web(lead: dict, tavily_key: str, anthropic_key: str) -> dict:
    """
    Sequentially find missing fields for *lead* using Tavily + Claude.

    *lead* should already include any fields found by Apollo so that this
    function skips fields that are already populated.

    Returns a dict {field_name: value} containing only newly found values.
    """
    from tavily import TavilyClient
    import anthropic

    tv = TavilyClient(api_key=tavily_key)
    ac = anthropic.Anthropic(api_key=anthropic_key)

    found: dict[str, str] = {}
    company = lead.get("Company name", "").strip()
    dmu     = lead.get("DMU name",     "").strip()

    if not company:
        return found

    # Convenience: merged view of current lead + what we've found so far
    def _ctx() -> dict:
        return {**lead, **found}

    # ------------------------------------------------------------------ #
    # Phase 1 — Company                                                    #
    # ------------------------------------------------------------------ #
    if _needs(_ctx(), _COMPANY_FIELDS):
        # Build context from what is already known
        ctx = _ctx()
        known = " ".join(filter(None, [
            ctx.get("Location", ""),
            ctx.get("Industry", ""),
            ctx.get("website",  ""),
        ]))
        query = f'"{company}" {known} LinkedIn locatie industrie telefoonnummer website medewerkers omzet'.strip()

        try:
            snippets, urls = _search(tv, query)
            if snippets:
                extracted = _extract(
                    ac,
                    system=(
                        f"Extract company information for '{company}' from web snippets. "
                        "Return ONLY a valid JSON object with these exact keys "
                        "(use empty string if unknown): "
                        "comp_li_url, location, industry, comp_phone, comp_mail, "
                        "website, num_employees, annual_revenue, sales_note. "
                        "comp_li_url: full LinkedIn company URL (linkedin.com/company/...). "
                        "sales_note: one Dutch sentence (max 20 words) on why this company "
                        "likely benefits from AI training or process improvement. "
                        "Return ONLY the JSON — no markdown, no explanation."
                    ),
                    user_msg=f"Company: {company}\nSnippets: {snippets}\nURLs: {urls}",
                )
                _company_map = {
                    "comp. LI URL":  "comp_li_url",
                    "Location":      "location",
                    "Industry":      "industry",
                    "comp. phone":   "comp_phone",
                    "comp. mail":    "comp_mail",
                    "website":       "website",
                    "# employees":   "num_employees",
                    "annual revenue":"annual_revenue",
                    "sales notes":   "sales_note",
                }
                for field, key in _company_map.items():
                    val = str(extracted.get(key, "") or "").strip()
                    if val and not _ctx().get(field, "").strip():
                        found[field] = val
        except Exception as exc:
            logger.warning("Company search failed for %s: %s", company, exc)
            raise

        # Targeted LinkedIn fallback if still missing
        if not _ctx().get("comp. LI URL", "").strip():
            try:
                _, li_urls = _search(tv, f"{company} site:linkedin.com/company", max_results=3)
                li_url = _linkedin_url_from_results(li_urls, "linkedin.com/company/")
                if li_url:
                    found["comp. LI URL"] = li_url
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Phase 2 — DMU (when name is known)                                   #
    # ------------------------------------------------------------------ #
    if dmu and _needs(_ctx(), _DMU_FIELDS):
        ctx = _ctx()
        query = f'"{dmu}" "{company}" LinkedIn functie rol e-mail'

        try:
            snippets, urls = _search(tv, query)
            if snippets:
                extracted = _extract(
                    ac,
                    system=(
                        f"Extract contact information for '{dmu}' at '{company}'. "
                        "Return ONLY a valid JSON object with these exact keys "
                        "(use empty string if unknown): "
                        "dmu_li_url, dmu_title, dmu_mail, dmu_phone, seniority, department. "
                        "dmu_li_url: full LinkedIn profile URL (linkedin.com/in/...). "
                        "seniority: one of c_suite / vp / director / manager / senior / entry. "
                        "Return ONLY the JSON — no markdown, no explanation."
                    ),
                    user_msg=(
                        f"Person: {dmu}\nCompany: {company}\n"
                        f"Company website: {ctx.get('website', '')}\n"
                        f"Snippets: {snippets}\nURLs: {urls}"
                    ),
                )
                _dmu_map = {
                    "DMU LI URL": "dmu_li_url",
                    "DMU title":  "dmu_title",
                    "DMU mail":   "dmu_mail",
                    "DMU phone":  "dmu_phone",
                    "seniority":  "seniority",
                    "department": "department",
                }
                for field, key in _dmu_map.items():
                    val = str(extracted.get(key, "") or "").strip()
                    if val and not _ctx().get(field, "").strip():
                        found[field] = val
        except Exception as exc:
            logger.warning("DMU search failed for %s @ %s: %s", dmu, company, exc)
            raise

        # Targeted LinkedIn fallback if still missing
        if not _ctx().get("DMU LI URL", "").strip():
            try:
                _, li_urls = _search(tv, f"{dmu} {company} site:linkedin.com/in", max_results=3)
                li_url = _linkedin_url_from_results(li_urls, "linkedin.com/in/")
                if li_url:
                    found["DMU LI URL"] = li_url
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Phase 3 — DMU suggestions (when no DMU name at all)                  #
    # ------------------------------------------------------------------ #
    elif not dmu and not _ctx().get("contact notes", "").strip():
        try:
            snippets, _ = _search(
                tv,
                f'"{company}" directeur management bestuur operationeel beslisser',
                max_results=3,
            )
            if snippets:
                extracted = _extract(
                    ac,
                    system=(
                        f"Based on web snippets about '{company}', suggest 3–5 likely "
                        "decision-makers (Directeur, Operations Manager, CFO, etc.). "
                        "Return ONLY a valid JSON object with key 'suggestions', "
                        "a list of objects each having 'name' and 'title'. "
                        "Return ONLY the JSON — no markdown, no explanation."
                    ),
                    user_msg=f"Company: {company}\nSnippets: {snippets}",
                )
                suggestions = extracted.get("suggestions", [])
                if suggestions:
                    note = "Mogelijke DMU's: " + "; ".join(
                        f"{s.get('name', '')} ({s.get('title', '')})"
                        for s in suggestions
                        if s.get("name")
                    )
                    found["contact notes"] = note
        except Exception:
            pass

    return found

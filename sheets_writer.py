"""
sheets_writer.py — Shared Google Sheets access layer for the VZA CRM agents.

Responsibilities:
  - Authenticate via the Google Service Account JSON key.
  - Open the configured spreadsheet and assume the first worksheet is the data sheet.
  - Deduplicate before writing:
      • If a row_dict contains 'linkedin_url', match on that field (exact, case-insensitive).
      • Otherwise, match on Company name + DMU name (both case-insensitive).
  - append_lead(row_dict) is the single public entry point used by all agents.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from config import SHEET_ID, SERVICE_ACCOUNT_JSON, SHEET_COLUMNS

logger = logging.getLogger(__name__)

# Scopes required for read + write access to Sheets
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Module-level cache so every agent call within one process reuses the same client
_client: gspread.Client | None = None
_sheet: gspread.Worksheet | None = None


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _get_credentials() -> Credentials:
    """
    Load credentials from Streamlit secrets (Streamlit Cloud) or a local
    JSON key file (local development).

    On Streamlit Cloud add a [gcp_service_account] section to your app
    secrets (Settings → Secrets).  The section must contain all fields
    from the service-account JSON file.
    """
    # ------------------------------------------------------------------ #
    # 1. Streamlit Cloud — secrets injected via the dashboard             #
    # ------------------------------------------------------------------ #
    try:
        import streamlit as st

        # Use [] access — more reliable than .get() across Streamlit versions
        try:
            sa = st.secrets["gcp_service_account"]
        except KeyError:
            sa = None

        if sa is not None:
            # Explicitly pull each field as a plain Python string.
            # Avoids any AttrDict → Credentials conversion issues.
            info = {
                "type":                        str(sa.get("type", "service_account")),
                "project_id":                  str(sa.get("project_id", "")),
                "private_key_id":              str(sa.get("private_key_id", "")),
                "private_key":                 str(sa.get("private_key", "")),
                "client_email":                str(sa.get("client_email", "")),
                "client_id":                   str(sa.get("client_id", "")),
                "auth_uri":                    str(sa.get("auth_uri",    "https://accounts.google.com/o/oauth2/auth")),
                "token_uri":                   str(sa.get("token_uri",   "https://oauth2.googleapis.com/token")),
                "auth_provider_x509_cert_url": str(sa.get("auth_provider_x509_cert_url", "https://www.googleapis.com/oauth2/v1/certs")),
                "client_x509_cert_url":        str(sa.get("client_x509_cert_url", "")),
            }
            logger.info("Loading GCP credentials from Streamlit secrets")
            return Credentials.from_service_account_info(info, scopes=_SCOPES)

        logger.warning("[gcp_service_account] key not found in Streamlit secrets")

    except Exception as exc:
        logger.warning("Streamlit secrets unavailable: %s", exc)

    # ------------------------------------------------------------------ #
    # 2. Local development — JSON key file on disk                        #
    # ------------------------------------------------------------------ #
    if Path(SERVICE_ACCOUNT_JSON).exists():
        logger.info("Loading GCP credentials from %s", SERVICE_ACCOUNT_JSON)
        return Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON, scopes=_SCOPES)

    raise RuntimeError(
        "Google Sheets credentials not found.\n"
        "  • Streamlit Cloud: add a [gcp_service_account] section under Settings → Secrets.\n"
        f"  • Local dev: place the JSON key file at {SERVICE_ACCOUNT_JSON}"
    )


def diagnose_connection() -> dict:
    """
    Return a dict describing the connection status — used by the app sidebar.

    Keys:
      secrets_accessible  bool   whether st.secrets loaded without error
      sa_key_present      bool   whether [gcp_service_account] key exists
      credentials_ok      bool   whether Credentials object was built
      sheet_title         str    spreadsheet title if fully connected, else ""
      error               str    first error message encountered, else ""
    """
    result = {
        "secrets_accessible": False,
        "sa_key_present":     False,
        "credentials_ok":     False,
        "sheet_title":        "",
        "error":              "",
    }
    try:
        import streamlit as st
        result["secrets_accessible"] = True
        try:
            sa = st.secrets["gcp_service_account"]
            result["sa_key_present"] = sa is not None
        except KeyError:
            result["error"] = "[gcp_service_account] not found in Streamlit secrets"
            return result
    except Exception as exc:
        result["error"] = f"Cannot read st.secrets: {exc}"
        return result

    try:
        creds = _get_credentials()
        result["credentials_ok"] = True
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID)
        result["sheet_title"] = sheet.title
    except Exception as exc:
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Sheet access
# ---------------------------------------------------------------------------

def _get_sheet() -> gspread.Worksheet:
    """Return (and lazily initialise) the target worksheet."""
    global _client, _sheet
    if _sheet is None:
        creds = _get_credentials()
        _client = gspread.authorize(creds)
        spreadsheet = _client.open_by_key(SHEET_ID)
        _sheet = spreadsheet.sheet1  # first tab
        logger.info("Connected to spreadsheet '%s'", spreadsheet.title)
    return _sheet


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------
# Phone normalisation helpers
# ---------------------------------------------------------------------------

_MOBILE_NL_RE = re.compile(r'^\+316\d{8}$')


def _normalize_mobile_nl(raw: str) -> str:
    """
    Normalize a Dutch mobile phone number to +316XXXXXXXX.
    Returns the original string unchanged if it is not a recognisable Dutch mobile.

    Accepted input formats (spaces/dashes stripped):
      06XXXXXXXX   →  +316XXXXXXXX
      316XXXXXXXX  →  +316XXXXXXXX
      00316XXXXXXXX → +316XXXXXXXX
      +316XXXXXXXX  → +316XXXXXXXX  (already correct)
    """
    digits = re.sub(r'[^\d]', '', raw.strip().lstrip('+'))

    if re.match(r'^316\d{8}$', digits):          # 316 + 8 digits
        return f'+{digits}'
    if re.match(r'^00316\d{8}$', digits):         # 00316 + 8 digits
        return f'+{digits[2:]}'
    if re.match(r'^06\d{8}$', digits):            # 06 + 8 digits
        return f'+31{digits[1:]}'
    if re.match(r'^6\d{8}$', digits):             # 6 + 8 digits
        return f'+31{digits}'

    return raw  # Not a Dutch mobile — return unchanged


def _is_mobile_nl(phone: str) -> bool:
    """Return True if *phone* is (or normalises to) a Dutch mobile number."""
    return bool(_MOBILE_NL_RE.match(_normalize_mobile_nl(phone.strip())))


def _format_phone_for_sheet(raw: str) -> str:
    """Normalise and prefix Dutch mobile numbers with ' so Sheets treats them as text."""
    normalised = _normalize_mobile_nl(raw)
    if _is_mobile_nl(normalised):
        return f"'{normalised}"
    return normalised


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

def _normalise(value: Any) -> str:
    """Return a lower-cased, stripped string for loose comparison."""
    return str(value or "").strip().lower()


def _find_duplicate(
    existing_rows: list[dict], row: dict
) -> tuple[int, dict] | None:
    """
    Return (0-based index, existing_row) for the first matching duplicate,
    or None if no duplicate is found.

    Two independent checks:
      1. LinkedIn URL — compared against the 'DMU LI URL' sheet column
         (both sides must be non-empty)
      2. Company name + DMU name (both fields must be non-empty)
    """
    new_url     = _normalise(row.get("linkedin_url", ""))
    new_company = _normalise(row.get("Company name", ""))
    new_dmu     = _normalise(row.get("DMU name", ""))

    for i, existing in enumerate(existing_rows):
        existing_url = _normalise(existing.get("DMU LI URL", ""))
        if new_url and existing_url and new_url == existing_url:
            return (i, existing)

        if new_company and new_dmu:
            if (
                _normalise(existing.get("Company name", "")) == new_company
                and _normalise(existing.get("DMU name", "")) == new_dmu
            ):
                return (i, existing)

    return None


def _update_existing_row(
    sheet: gspread.Worksheet,
    sheet_row_num: int,
    headers: list[str],
    existing: dict,
    new_row: dict,
) -> int:
    """
    Enrich an existing sheet row with data from *new_row*.

    Rules:
    - All columns: only fill cells that are currently empty.
    - DMU phone exception: overwrite the existing value when the new value is a
      Dutch mobile number and the existing value is not.

    Returns the number of cells actually updated.
    """
    # Case-insensitive header index: stripped-lower name → 1-based column index
    header_idx = {h.strip().lower(): i + 1 for i, h in enumerate(headers)}
    # Case-insensitive existing-row lookup: stripped-lower name → value
    existing_ci = {k.strip().lower(): str(v).strip() for k, v in existing.items()}

    updates: list[tuple[str, str]] = []

    for col in SHEET_COLUMNS:
        if col == "enrich?":
            continue

        new_val = str(new_row.get(col, "")).strip()
        old_val = existing_ci.get(col.strip().lower(), "")

        if not new_val:
            continue

        if col == "DMU phone":
            normalised = _normalize_mobile_nl(new_val)
            formatted  = _format_phone_for_sheet(new_val)
            if not old_val:
                updates.append((col, formatted))
            elif not _is_mobile_nl(old_val) and _is_mobile_nl(normalised):
                updates.append((col, formatted))
        else:
            if not old_val:
                updates.append((col, new_val))

    for col, val in updates:
        ci = header_idx.get(col.strip().lower())
        if ci is not None:
            sheet.update_cell(sheet_row_num, ci, val)

    logger.info("Enriched row %d: updated %d cell(s)", sheet_row_num, len(updates))
    return len(updates)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_lead(row_dict: dict) -> str:
    """
    Write *row_dict* to the Google Sheet.

    Returns one of:
      "new"       — a new row was appended
      "enriched"  — duplicate found; one or more empty cells were filled
      "duplicate" — duplicate found; nothing new to add
    """
    sheet = _get_sheet()

    try:
        all_values = sheet.get_all_values()
    except gspread.exceptions.GSpreadException as exc:
        logger.error("Failed to fetch existing rows: %s", exc)
        raise

    if len(all_values) > 1:
        headers       = all_values[0]
        existing_rows = [dict(zip(headers, row)) for row in all_values[1:]]
    else:
        headers       = all_values[0] if all_values else list(SHEET_COLUMNS)
        existing_rows = []

    # Normalise and format DMU phone before any processing
    if row_dict.get("DMU phone", "").strip():
        row_dict = {**row_dict, "DMU phone": _format_phone_for_sheet(row_dict["DMU phone"])}

    dup = _find_duplicate(existing_rows, row_dict)
    if dup is not None:
        dup_idx, existing_row = dup
        sheet_row_num = dup_idx + 2  # +1 for header row, +1 for 1-based index
        updated = _update_existing_row(sheet, sheet_row_num, headers, existing_row, row_dict)
        if updated:
            logger.info(
                "Enriched row %d (%d cell(s) updated): company=%r dmu=%r",
                sheet_row_num, updated, row_dict.get("Company name"), row_dict.get("DMU name"),
            )
            return "enriched"
        logger.info(
            "Duplicate, nothing new: company=%r dmu=%r",
            row_dict.get("Company name"), row_dict.get("DMU name"),
        )
        return "duplicate"

    # New row — write from column B onward to leave the enrich? dropdown intact
    data_cols = [c for c in SHEET_COLUMNS if c != "enrich?"]
    ordered_row = [str(row_dict.get(col, "")) for col in data_cols]
    next_row = len(all_values) + 1

    try:
        sheet.update(
            range_name=f"B{next_row}",
            values=[ordered_row],
            value_input_option="RAW",
        )
        logger.info(
            "Written new lead to row %d: company=%r dmu=%r",
            next_row,
            row_dict.get("Company name"),
            row_dict.get("DMU name"),
        )
    except gspread.exceptions.GSpreadException as exc:
        logger.error("Failed to write row: %s", exc)
        raise

    return "new"

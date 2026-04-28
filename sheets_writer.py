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

def _normalise(value: Any) -> str:
    """Return a lower-cased, stripped string for loose comparison."""
    return str(value or "").strip().lower()


def _is_duplicate(existing_rows: list[dict], row: dict) -> bool:
    """
    Return True if *row* already exists in *existing_rows*.

    Matching priority:
      1. linkedin_url  (if present and non-empty in the new row)
      2. Company name + DMU name
    """
    linkedin_url = _normalise(row.get("linkedin_url", ""))

    for existing in existing_rows:
        if linkedin_url:
            if _normalise(existing.get("linkedin_url", "")) == linkedin_url:
                return True
        else:
            same_company = (
                _normalise(existing.get("Company name", ""))
                == _normalise(row.get("Company name", ""))
            )
            same_dmu = (
                _normalise(existing.get("DMU name", ""))
                == _normalise(row.get("DMU name", ""))
            )
            if same_company and same_dmu:
                return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_lead(row_dict: dict) -> bool:
    """
    Write *row_dict* as a new row in the Google Sheet.

    Returns True if the row was written, False if it was skipped as a duplicate.

    *row_dict* keys should match SHEET_COLUMNS entries (case-sensitive).
    An extra 'linkedin_url' key is used for deduplication but is NOT written
    as its own column (LinkedIn URL is not a dedicated column in this sheet).
    """
    sheet = _get_sheet()

    # Fetch all existing data for dedup check.
    # Use get_all_values() instead of get_all_records() to avoid errors when
    # the sheet has duplicate header names (e.g. two "notes" columns).
    try:
        all_values = sheet.get_all_values()
    except gspread.exceptions.GSpreadException as exc:
        logger.error("Failed to fetch existing rows: %s", exc)
        raise

    if len(all_values) > 1:
        headers = all_values[0]
        existing_rows = [dict(zip(headers, row)) for row in all_values[1:]]
    else:
        existing_rows = []

    if _is_duplicate(existing_rows, row_dict):
        logger.info(
            "Skipping duplicate lead: company=%r dmu=%r",
            row_dict.get("Company name"),
            row_dict.get("DMU name"),
        )
        return False

    # Build the row in column order; unknown keys are silently ignored
    ordered_row = [str(row_dict.get(col, "")) for col in SHEET_COLUMNS]

    # Write to the explicit next row rather than using append_row, which can
    # mis-detect the insertion point when only some columns are populated.
    next_row = len(all_values) + 1  # all_values includes the header row

    try:
        sheet.update(
            range_name=f"A{next_row}",
            values=[ordered_row],
            value_input_option="RAW",
        )
        logger.info(
            "Written lead to row %d: company=%r dmu=%r",
            next_row,
            row_dict.get("Company name"),
            row_dict.get("DMU name"),
        )
    except gspread.exceptions.GSpreadException as exc:
        logger.error("Failed to write row: %s", exc)
        raise

    return True

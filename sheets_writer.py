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


def _get_sheet() -> gspread.Worksheet:
    """Return (and lazily initialise) the target worksheet."""
    global _client, _sheet
    if _sheet is None:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON, scopes=_SCOPES)
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

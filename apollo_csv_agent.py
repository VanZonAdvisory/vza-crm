"""
apollo_csv_agent.py — Parse an Apollo.io CSV export and push rows to the CRM.

Apollo CSV columns used:
  First Name + Last Name → DMU name
  Title                  → notes
  Company                → Company name
  City + State           → Location
  Industry               → Industry
  Phone                  → DMU phone
  Email                  → DMU mail
  Company Phone          → comp. phone
  Website                → comp. mail

Source is set to "Apollo", Phase to "Attention (lead)".
"""

from __future__ import annotations

import csv
import io
import logging

logger = logging.getLogger(__name__)


def _safe(value) -> str:
    """Return a clean string, treating None / NaN as empty."""
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() == "nan" else s


def parse_apollo_csv(file_bytes: bytes) -> list[dict]:
    """
    Parse raw bytes from an Apollo.io CSV export.

    Returns a list of CRM row dicts ready to pass to sheets_writer.append_lead().
    """
    # Apollo sometimes exports with a UTF-8 BOM; utf-8-sig handles both cases.
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))

    # Strip any surrounding whitespace from column headers
    reader.fieldnames = (
        [h.strip() for h in reader.fieldnames] if reader.fieldnames else reader.fieldnames
    )

    rows: list[dict] = []
    for record in reader:
        # Clean every value in the record
        rec = {k.strip(): _safe(v) for k, v in record.items()}

        first = rec.get("First Name", "")
        last  = rec.get("Last Name", "")
        name  = f"{first} {last}".strip()

        city  = rec.get("City", "")
        state = rec.get("State", "")
        location = ", ".join(p for p in [city, state] if p)

        rows.append({
            "Company name":      rec.get("Company", ""),
            "Location":          location,
            "Industry":          rec.get("Industry", ""),
            "DMU name":          name,
            "DMU phone":         rec.get("Phone", ""),
            "DMU mail":          rec.get("Email", ""),
            "expected desire":   "",
            "comp. phone":       rec.get("Company Phone", ""),
            "comp. mail":        rec.get("Website", ""),
            "notes":             rec.get("Title", ""),
            "owner":             "",
            "last tried call":   "",
            "last spoken":       "",
            "notes2":            "",
            "sourced":           "Apollo",
            "phase":             "Attention (lead)",
            "Rejected (reason)": "",
        })

    logger.info("Parsed %d row(s) from Apollo CSV", len(rows))
    return rows

"""
app.py — VZA CRM Lead Generation UI (Streamlit)

Run with:
    streamlit run app.py
"""

import os
import sys
import tempfile
import logging
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="VZA CRM — Lead Generator",
    page_icon="🎯",
    layout="centered",
)

st.title("🎯 VZA CRM — Lead Generator")
st.caption("Add leads to the CRM from LinkedIn, Apollo, or AI generation.")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_linkedin, tab_apollo, tab_ai = st.tabs([
    "LinkedIn Profile",
    "Apollo Search",
    "AI Generator",
])


# ===========================================================================
# TAB 1 — LinkedIn Profile
# ===========================================================================
with tab_linkedin:
    st.subheader("Import a LinkedIn profile")
    st.write("Paste a profile URL, upload a PDF, or both.")

    linkedin_url = st.text_input(
        "LinkedIn profile URL",
        placeholder="https://www.linkedin.com/in/peter-janssen/",
    )

    uploaded_pdf = st.file_uploader(
        "Or upload a LinkedIn profile PDF",
        type=["pdf"],
    )

    if st.button("Import profile", type="primary", key="btn_linkedin"):
        if not linkedin_url and not uploaded_pdf:
            st.error("Provide a URL, a PDF, or both.")
        else:
            # Import here so errors surface cleanly in the UI
            from linkedin_profile_agent import (
                _extract_from_pdf,
                _extract_from_url,
                _to_lead_row,
            )
            from sheets_writer import append_lead

            fields = {}

            with st.spinner("Extracting profile data…"):
                # PDF takes priority for field extraction
                if uploaded_pdf:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_pdf.read())
                        tmp_path = tmp.name
                    try:
                        fields = _extract_from_pdf(tmp_path)
                    finally:
                        Path(tmp_path).unlink(missing_ok=True)

                # Fall back to URL scraping if PDF gave no name
                if linkedin_url and not fields.get("name"):
                    fields = _extract_from_url(linkedin_url)

            if not fields.get("name") and not fields.get("company"):
                st.error("Could not extract name or company from the profile.")
            else:
                st.success("Profile extracted!")
                col1, col2 = st.columns(2)
                col1.metric("Name",    fields.get("name", "—"))
                col1.metric("Title",   fields.get("title", "—"))
                col2.metric("Company", fields.get("company", "—"))
                col2.metric("Phone",   fields.get("phone", "—") or "not listed")

                with st.spinner("Writing to CRM…"):
                    row     = _to_lead_row(fields, linkedin_url=linkedin_url or "")
                    written = append_lead(row)

                if written:
                    st.success(f"✅ Lead **{fields.get('name')}** added to the CRM.")
                else:
                    st.warning("⚠️ This lead already exists in the CRM — skipped.")


# ===========================================================================
# TAB 2 — Apollo Search
# ===========================================================================
with tab_apollo:
    st.subheader("Search Apollo for real contacts")

    apollo_key = os.getenv("APOLLO_API_KEY", "") or st.secrets.get("APOLLO_API_KEY", "")
    if not apollo_key:
        st.warning(
            "APOLLO_API_KEY not set. Set it before starting the app:  \n"
            "`set APOLLO_API_KEY=your-key`  then restart with `streamlit run app.py`"
        )

    from config import ICP

    col1, col2 = st.columns(2)
    with col1:
        titles = st.multiselect(
            "Job titles",
            options=["Directeur", "Operations Manager", "CFO", "CEO", "COO",
                     "Supply Chain Manager", "Logistiek Manager", "Plant Manager"],
            default=ICP["target_titles"],
        )
        locations = st.multiselect(
            "Regions",
            options=["Oost-Brabant", "Brainport Eindhoven", "Noord-Brabant",
                     "Eindhoven", "Tilburg", "Den Bosch", "Helmond", "Venlo"],
            default=ICP["region"],
        )
    with col2:
        industries = st.multiselect(
            "Industries",
            options=["logistics", "manufacturing", "supply chain",
                     "warehousing", "automotive", "food processing"],
            default=ICP["industry"],
        )
        pages    = st.slider("Pages to fetch", 1, 5, 1)
        per_page = st.slider("Results per page", 5, 25, 10)

    if st.button("Search Apollo", type="primary", key="btn_apollo"):
        if not apollo_key:
            st.error("Set APOLLO_API_KEY first.")
        elif not titles or not locations or not industries:
            st.error("Fill in all filters.")
        else:
            from apollo_agent import search_apollo, _map_to_sheet_row
            from sheets_writer import append_lead

            written = 0
            skipped = 0
            errors  = 0
            all_people = []

            progress = st.progress(0, text="Contacting Apollo…")

            for page in range(1, pages + 1):
                progress.progress(
                    int((page - 1) / pages * 100),
                    text=f"Fetching page {page} of {pages}…"
                )
                try:
                    data   = search_apollo(titles, industries, locations,
                                           per_page=per_page, page=page)
                    people = data.get("people") or []
                    all_people.extend(people)
                except Exception as exc:
                    st.error(f"Apollo error: {exc}")
                    break

            progress.progress(100, text="Writing to CRM…")

            for person in all_people:
                row = _map_to_sheet_row(person)
                if not row["Company name"] and not row["DMU name"]:
                    continue
                try:
                    if append_lead(row):
                        written += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    st.error(f"Write error: {exc}")
                    errors += 1

            progress.empty()
            st.success(
                f"✅ Done — **{written}** new lead(s) written, "
                f"**{skipped}** duplicate(s) skipped"
                + (f", {errors} error(s)" if errors else "") + "."
            )


# ===========================================================================
# TAB 3 — AI Lead Generator
# ===========================================================================
with tab_ai:
    st.subheader("Generate leads with Claude AI")
    st.caption("Claude generates plausible company profiles matching your ICP. "
               "Use for pipeline inspiration — verify contacts before calling.")

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "") or st.secrets.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        st.warning(
            "ANTHROPIC_API_KEY not set.  \n"
            "`set ANTHROPIC_API_KEY=your-key`  then restart."
        )

    from config import ICP as _ICP

    col1, col2 = st.columns(2)
    with col1:
        ai_industry = st.multiselect(
            "Industry",
            options=["logistics", "manufacturing", "supply chain",
                     "warehousing", "automotive", "food processing"],
            default=_ICP["industry"],
            key="ai_industry",
        )
        ai_region = st.multiselect(
            "Region",
            options=["Oost-Brabant", "Brainport Eindhoven", "Noord-Brabant",
                     "Eindhoven", "Tilburg", "Den Bosch", "Helmond"],
            default=_ICP["region"],
            key="ai_region",
        )
    with col2:
        ai_size = st.text_input("Company size", value=_ICP["company_size"], key="ai_size")
        ai_titles = st.multiselect(
            "Target titles",
            options=["Directeur", "Operations Manager", "CFO", "CEO", "COO",
                     "Supply Chain Manager", "Logistiek Manager"],
            default=_ICP["target_titles"],
            key="ai_titles",
        )

    if st.button("Generate leads", type="primary", key="btn_ai"):
        if not anthropic_key:
            st.error("Set ANTHROPIC_API_KEY first.")
        elif not ai_industry or not ai_region or not ai_titles:
            st.error("Fill in all fields.")
        else:
            from ai_lead_generator import generate_leads, _map_to_sheet_row
            from sheets_writer import append_lead

            with st.spinner("Asking Claude to generate leads…"):
                try:
                    raw_leads = generate_leads(
                        industry=ai_industry,
                        region=ai_region,
                        size=ai_size,
                        titles=ai_titles,
                    )
                except Exception as exc:
                    st.error(f"Claude error: {exc}")
                    raw_leads = []

            if raw_leads:
                written = 0
                skipped = 0
                with st.spinner("Writing to CRM…"):
                    for raw in raw_leads:
                        if not isinstance(raw, dict):
                            continue
                        row = _map_to_sheet_row(raw)
                        try:
                            if append_lead(row):
                                written += 1
                            else:
                                skipped += 1
                        except Exception as exc:
                            st.error(f"Write error: {exc}")

                st.success(
                    f"✅ Done — **{written}** new lead(s) written, "
                    f"**{skipped}** duplicate(s) skipped."
                )

"""
app.py — VZA CRM Lead Generation UI (Streamlit)

Run with:
    python -m streamlit run app.py
"""

import os
import tempfile
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="VZA — Lead Generator",
    page_icon="📋",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Brand styling
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Brand colours */
    :root {
        --teal:      #1B5E5E;
        --teal-mid:  #2A7A7A;
        --gold:      #F0C090;
        --light-bg:  #F4F7F7;
        --border:    #D6E4E4;
    }

    /* Hide default Streamlit header */
    header[data-testid="stHeader"] { background: transparent; }

    /* App background */
    .stApp { background-color: #FFFFFF; }

    /* Top banner */
    .vza-banner {
        background-color: var(--teal);
        padding: 1.4rem 2rem 1.2rem 2rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
        display: flex;
        align-items: center;
        gap: 1.2rem;
    }
    .vza-banner h1 {
        color: #FFFFFF;
        font-size: 1.45rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: 0.02em;
    }
    .vza-banner p {
        color: var(--gold);
        margin: 0.15rem 0 0 0;
        font-size: 0.88rem;
        opacity: 0.9;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        border-bottom: 2px solid var(--border);
    }
    .stTabs [data-baseweb="tab"] {
        background: var(--light-bg);
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 1.2rem;
        color: var(--teal);
        font-weight: 600;
        font-size: 0.9rem;
        border: 1px solid var(--border);
        border-bottom: none;
    }
    .stTabs [aria-selected="true"] {
        background: var(--teal) !important;
        color: #FFFFFF !important;
    }

    /* Section card */
    .vza-card {
        background: var(--light-bg);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 1.2rem 1.4rem;
        margin-bottom: 1rem;
    }

    /* Primary buttons */
    .stButton > button[kind="primary"] {
        background-color: var(--teal) !important;
        border: none !important;
        color: white !important;
        font-weight: 600 !important;
        border-radius: 6px !important;
        padding: 0.5rem 1.6rem !important;
        transition: background 0.2s;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: var(--teal-mid) !important;
    }

    /* Divider colour */
    hr { border-color: var(--border); }

    /* Metric label */
    [data-testid="stMetricLabel"] { color: var(--teal); font-weight: 600; }

    /* Info / warning boxes */
    .stAlert { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
logo_path = Path(__file__).parent / "logo.png"
col_logo, col_title = st.columns([1, 5])
with col_logo:
    if logo_path.exists():
        st.image(str(logo_path), width=72)
with col_title:
    st.markdown("""
        <div style='padding-top:8px'>
            <span style='font-size:1.5rem;font-weight:700;color:#1B5E5E;'>VZA Lead Generator</span><br>
            <span style='font-size:0.88rem;color:#555;'>Add leads to the CRM from LinkedIn, Apollo, or AI company discovery</span>
        </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_linkedin, tab_apollo, tab_ai = st.tabs([
    "🔗  LinkedIn Profile",
    "🔍  Apollo Search",
    "🤖  AI Company Discovery",
])


# ===========================================================================
# TAB 1 — LinkedIn Profile
# ===========================================================================
with tab_linkedin:
    st.markdown("#### Import a LinkedIn profile")
    st.caption("Paste a profile URL, upload a saved PDF, or both. The lead is added to the CRM after deduplication.")

    with st.container(border=True):
        linkedin_url = st.text_input(
            "LinkedIn profile URL",
            placeholder="https://www.linkedin.com/in/peter-janssen/",
        )
        uploaded_pdf = st.file_uploader(
            "Or upload a LinkedIn profile PDF",
            type=["pdf"],
            help="Export a profile as PDF from LinkedIn and upload it here.",
        )

    if st.button("Import profile", type="primary", key="btn_linkedin"):
        if not linkedin_url and not uploaded_pdf:
            st.error("Provide a URL, a PDF, or both.")
        else:
            from linkedin_profile_agent import (
                _extract_from_pdf,
                _extract_from_url,
                _to_lead_row,
            )
            from sheets_writer import append_lead

            fields = {}

            with st.spinner("Extracting profile data…"):
                if uploaded_pdf:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_pdf.read())
                        tmp_path = tmp.name
                    try:
                        fields = _extract_from_pdf(tmp_path)
                    finally:
                        Path(tmp_path).unlink(missing_ok=True)

                if linkedin_url and not fields.get("name"):
                    fields = _extract_from_url(linkedin_url)

            if not fields.get("name") and not fields.get("company"):
                st.error("Could not extract name or company from the profile.")
            else:
                st.success("Profile extracted successfully.")
                col1, col2 = st.columns(2)
                col1.metric("Name",    fields.get("name",  "—"))
                col1.metric("Title",   fields.get("title", "—"))
                col2.metric("Company", fields.get("company", "—"))
                col2.metric("Phone",   fields.get("phone", "—") or "not listed")

                with st.spinner("Writing to CRM…"):
                    row     = _to_lead_row(fields, linkedin_url=linkedin_url or "")
                    written = append_lead(row)

                if written:
                    st.success(f"✅ **{fields.get('name')}** added to the CRM.")
                else:
                    st.warning("⚠️ This lead already exists in the CRM — skipped.")


# ===========================================================================
# TAB 2 — Apollo Search
# ===========================================================================
with tab_apollo:
    st.markdown("#### Search Apollo for verified contacts")
    st.caption("Apollo returns real, verified contacts. Requires an active Apollo paid plan.")

    apollo_key = os.getenv("APOLLO_API_KEY", "") or st.secrets.get("APOLLO_API_KEY", "")
    if not apollo_key:
        st.warning("Apollo API key not configured. Add `APOLLO_API_KEY` to Streamlit secrets.")

    from config import ICP

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            titles_input = st.text_input(
                "Job titles (comma-separated)",
                value=", ".join(ICP["target_titles"]),
                help="e.g. Directeur, Operations Manager, CFO, Plant Manager",
            )
            locations_input = st.text_input(
                "Regions (comma-separated)",
                value=", ".join(ICP["region"]),
                help="e.g. Oost-Brabant, Eindhoven, Noord-Brabant",
            )
        with col2:
            industries_input = st.text_input(
                "Industries (comma-separated)",
                value=", ".join(ICP["industry"]),
                help="e.g. logistics, manufacturing, supply chain",
            )
            col2a, col2b = st.columns(2)
            pages    = col2a.number_input("Pages", min_value=1, max_value=10, value=1)
            per_page = col2b.number_input("Per page", min_value=5, max_value=25, value=10)

    if st.button("Search Apollo", type="primary", key="btn_apollo"):
        titles     = [t.strip() for t in titles_input.split(",")     if t.strip()]
        locations  = [l.strip() for l in locations_input.split(",")  if l.strip()]
        industries = [i.strip() for i in industries_input.split(",") if i.strip()]

        if not apollo_key:
            st.error("Apollo API key not configured.")
        elif not titles or not locations or not industries:
            st.error("Fill in all filter fields.")
        else:
            from apollo_agent import search_apollo, _map_to_sheet_row
            from sheets_writer import append_lead

            written = skipped = errors = 0
            all_people = []
            progress = st.progress(0, text="Contacting Apollo…")

            for page in range(1, int(pages) + 1):
                progress.progress(
                    int((page - 1) / pages * 100),
                    text=f"Fetching page {page} of {int(pages)}…",
                )
                try:
                    data   = search_apollo(titles, industries, locations,
                                           per_page=int(per_page), page=page)
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
# TAB 3 — AI Company Discovery
# ===========================================================================
with tab_ai:
    st.markdown("#### Discover companies with Claude AI")
    st.caption(
        "Claude identifies real companies matching your ICP — industry, region, and size. "
        "**No personal contacts are generated.** Use Apollo or LinkedIn to find DMUs afterwards."
    )

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "") or st.secrets.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        st.warning("Anthropic API key not configured. Add `ANTHROPIC_API_KEY` to Streamlit secrets.")

    from config import ICP as _ICP

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            ai_industry = st.text_input(
                "Industries (comma-separated)",
                value=", ".join(_ICP["industry"]),
                key="ai_industry",
            )
            ai_region = st.text_input(
                "Regions (comma-separated)",
                value=", ".join(_ICP["region"]),
                key="ai_region",
            )
        with col2:
            ai_size = st.text_input(
                "Company size",
                value=_ICP["company_size"],
                key="ai_size",
            )
            ai_count = st.number_input(
                "Number of companies",
                min_value=5, max_value=25, value=10,
                key="ai_count",
            )

    if st.button("Discover companies", type="primary", key="btn_ai"):
        if not anthropic_key:
            st.error("Anthropic API key not configured.")
        elif not ai_industry or not ai_region:
            st.error("Fill in industry and region.")
        else:
            from ai_lead_generator import generate_company_leads, _map_company_to_sheet_row
            from sheets_writer import append_lead

            industries = [i.strip() for i in ai_industry.split(",") if i.strip()]
            regions    = [r.strip() for r in ai_region.split(",")    if r.strip()]

            with st.spinner("Asking Claude to identify companies…"):
                try:
                    raw_leads = generate_company_leads(
                        industry=industries,
                        region=regions,
                        size=ai_size,
                        count=int(ai_count),
                    )
                except Exception as exc:
                    st.error(f"Claude error: {exc}")
                    raw_leads = []

            if raw_leads:
                written = skipped = 0
                with st.spinner("Writing to CRM…"):
                    for raw in raw_leads:
                        if not isinstance(raw, dict):
                            continue
                        row = _map_company_to_sheet_row(raw)
                        try:
                            if append_lead(row):
                                written += 1
                            else:
                                skipped += 1
                        except Exception as exc:
                            st.error(f"Write error: {exc}")

                st.success(
                    f"✅ Done — **{written}** company lead(s) written, "
                    f"**{skipped}** duplicate(s) skipped."
                )
                st.info("💡 Next step: use Apollo Search or LinkedIn to find DMU contacts at these companies.")

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
# Sidebar — Google Sheets connection diagnostic
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Connection status")

    # ---- Google Sheets ----
    if st.button("Test Google Sheets", key="btn_diag"):
        from sheets_writer import diagnose_connection
        with st.spinner("Testing…"):
            d = diagnose_connection()
        if d["sheet_title"]:
            st.success(f"Sheets — **{d['sheet_title']}**")
        else:
            st.error("Sheets — not connected")
            st.write(f"secrets accessible: `{d['secrets_accessible']}`")
            st.write(f"[gcp_service_account] present: `{d['sa_key_present']}`")
            st.write(f"credentials built: `{d['credentials_ok']}`")
            if d["error"]:
                st.code(d["error"])

    # ---- Apollo ----
    if st.button("Test Apollo API", key="btn_apollo_test"):
        import requests as _req
        _key = st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", "")
        if not _key:
            st.error("Apollo — APOLLO_API_KEY not found in secrets")
        else:
            with st.spinner("Testing…"):
                _headers = {"X-Api-Key": _key, "Content-Type": "application/json", "Cache-Control": "no-cache"}
                try:
                    # Step 1: health check — validates the key itself
                    _health = _req.get("https://api.apollo.io/v1/auth/health", headers=_headers, timeout=10)
                    if _health.status_code == 401:
                        st.error("Apollo — invalid API key (401). Check the key in Streamlit secrets.")
                    elif _health.status_code == 403:
                        st.error(
                            "Apollo — key recognised but access denied (403). "
                            "You may be using a **scoped** key. Go to Apollo → Settings → API Keys "
                            "and use the **Master API Key** instead."
                        )
                    elif not _health.ok:
                        st.error(f"Apollo — health check failed ({_health.status_code}): {_health.text[:200]}")
                    else:
                        # Step 2: try both endpoints, key in header AND body
                        _endpoints = [
                            ("v1/people/search",               "https://api.apollo.io/v1/people/search"),
                            ("api/v1/mixed_people/api_search", "https://api.apollo.io/api/v1/mixed_people/api_search"),
                        ]
                        _body = {"api_key": _key, "person_titles": ["CEO"], "per_page": 1, "page": 1}
                        for _ep_name, _ep_url in _endpoints:
                            _resp = _req.post(_ep_url, headers=_headers, json=_body, timeout=15)
                            if _resp.ok:
                                _total = _resp.json().get("pagination", {}).get("total_entries", "?")
                                st.success(f"Apollo — connected via **{_ep_name}** ({_total:,} results for CEO)")
                                break
                            else:
                                st.warning(f"{_ep_name} → {_resp.status_code}: {_resp.text[:120]}")
                        else:
                            st.error("Apollo — both endpoints returned errors (see warnings above).")
                except Exception as _e:
                    st.error(f"Apollo — request failed: {_e}")

    # ---- Tavily ----
    if st.button("Test Tavily API", key="btn_tavily_test"):
        _key = st.secrets.get("TAVILY_API_KEY", "") or os.getenv("TAVILY_API_KEY", "")
        if not _key:
            st.error("Tavily — TAVILY_API_KEY not found in secrets")
        else:
            with st.spinner("Testing…"):
                try:
                    from tavily import TavilyClient
                    _client = TavilyClient(api_key=_key)
                    _result = _client.search("Van Zon Advisory", max_results=1)
                    _n = len(_result.get("results", []))
                    st.success(f"Tavily — connected (returned {_n} result)")
                except Exception as _e:
                    st.error(f"Tavily — failed: {_e}")

    st.markdown("---")
    st.caption(
        "Keys configured via **Settings → Secrets** in Streamlit Cloud."
    )

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_linkedin, tab_apollo, tab_apollo_csv, tab_enrich = st.tabs([
    "🔗  LinkedIn Profile",
    "🔍  Apollo Search",
    "📄  Apollo CSV",
    "✨  Enrich Leads",
])


# ===========================================================================
# TAB 1 — LinkedIn Profile
# ===========================================================================
with tab_linkedin:
    st.markdown("#### Import a LinkedIn profile")
    st.caption("Upload a PDF or paste a URL. The lead is added to the CRM after deduplication.")

    st.info(
        "Open the LinkedIn profile → **More** → **Save to PDF** → upload below.",
        icon="💡",
    )

    with st.container(border=True):
        uploaded_pdf = st.file_uploader(
            "Upload LinkedIn profile PDF",
            type=["pdf"],
            help="Export a profile as PDF from LinkedIn and upload it here.",
        )
        linkedin_url = ""

    if st.button("Import profile", type="primary", key="btn_linkedin"):
        if not uploaded_pdf:
            st.error("Please upload a LinkedIn profile PDF.")
        else:
            from linkedin_profile_agent import _extract_from_pdf, _to_lead_row
            from sheets_writer import append_lead

            with st.spinner("Extracting profile data…"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded_pdf.read())
                    tmp_path = tmp.name
                try:
                    fields = _extract_from_pdf(tmp_path)
                finally:
                    Path(tmp_path).unlink(missing_ok=True)

            if not fields.get("name") and not fields.get("company"):
                st.error("Could not extract name or company from the PDF.")
            else:
                st.success("Profile extracted successfully.")
                col1, col2 = st.columns(2)
                col1.metric("Name",     fields.get("name",     "—"))
                col1.metric("Title",    fields.get("title",    "—"))
                col1.metric("Email",    fields.get("email",    "—") or "not listed")
                col2.metric("Company",  fields.get("company",  "—"))
                col2.metric("Phone",    fields.get("phone",    "—") or "not listed")
                col2.metric("Location", fields.get("location", "—") or "not listed")

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
    st.caption("Fixed filters: verified email, Netherlands. Variable filters below.")

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
            seniority_options = ["c_suite", "vp", "director", "manager", "owner", "founder", "senior"]
            seniority_sel = st.multiselect(
                "Seniority",
                options=seniority_options,
                default=["c_suite", "owner", "founder"],
            )
            size_options = {
                "50–200":   "50,200",
                "201–500":  "201,500",
                "501–1000": "501,1000",
                "1001–5000":"1001,5000",
            }
            size_sel = st.multiselect(
                "Company size (employees)",
                options=list(size_options.keys()),
                default=["50–200", "201–500"],
            )
        with col2:
            industries_input = st.text_input(
                "Industries (comma-separated)",
                value=", ".join(ICP["industry"]),
                help="e.g. logistics, manufacturing, supply chain",
            )
            locations_input = st.text_input(
                "Company locations (comma-separated)",
                value="Netherlands",
                help="e.g. Eindhoven, Noord-Brabant, Netherlands",
            )
            col2a, col2b = st.columns(2)
            per_page = col2a.number_input("Results", min_value=5, max_value=100, value=25)
            pages    = col2b.number_input("Pages",   min_value=1, max_value=10,  value=1)

    if st.button("Search Apollo", type="primary", key="btn_apollo"):
        titles     = [t.strip() for t in titles_input.split(",")     if t.strip()]
        locations  = [l.strip() for l in locations_input.split(",")  if l.strip()]
        industries = [i.strip() for i in industries_input.split(",") if i.strip()]
        sizes      = [size_options[s] for s in size_sel if s in size_options]

        if not apollo_key:
            st.error("Apollo API key not configured.")
        elif not titles:
            st.error("Enter at least one job title.")
        else:
            from apollo_agent import search_apollo, _map_to_sheet_row
            from sheets_writer import append_lead

            all_people = []
            progress = st.progress(0, text="Contacting Apollo…")

            for page in range(1, int(pages) + 1):
                progress.progress(
                    int((page - 1) / pages * 100),
                    text=f"Fetching page {page} of {int(pages)}…",
                )
                try:
                    data = search_apollo(
                        titles=titles,
                        industries=industries,
                        locations=locations,
                        seniorities=seniority_sel,
                        employee_ranges=sizes,
                        per_page=int(per_page),
                        page=page,
                        api_key=apollo_key,
                    )
                    people = data.get("people") or []
                    all_people.extend(people)
                    if not people:
                        break
                except Exception as exc:
                    st.error(f"Apollo error: {exc}")
                    break

            progress.empty()

            if all_people:
                total_found = data.get("pagination", {}).get("total_entries", len(all_people))
                st.info(f"Found **{total_found:,}** total matches — fetched **{len(all_people)}**.")

                # Preview
                preview = []
                for p in all_people[:10]:
                    org = p.get("organization") or {}
                    preview.append({
                        "Name":    f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
                        "Title":   p.get("title", "—"),
                        "Company": org.get("name", "—"),
                        "Email":   p.get("email", "—") or "—",
                        "Location": org.get("city", "—"),
                    })
                st.table(preview)

                if st.button("Write all to CRM", type="primary", key="btn_apollo_write"):
                    written = skipped = errors = 0
                    bar = st.progress(0, text="Writing to Google Sheets…")
                    for i, person in enumerate(all_people):
                        bar.progress(int((i + 1) / len(all_people) * 100))
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
                    bar.empty()
                    st.success(
                        f"✅ Done — **{written}** new lead(s) written, "
                        f"**{skipped}** duplicate(s) skipped"
                        + (f", {errors} error(s)" if errors else "") + "."
                    )
            else:
                st.warning("No results returned. Try broadening your filters.")


# ===========================================================================
# TAB 3 — Apollo CSV Import
# ===========================================================================
with tab_apollo_csv:
    import csv as _csv
    import io as _io

    def _parse_csv(file_bytes: bytes) -> list[dict]:
        """Convert Apollo CSV bytes to a list of CRM row dicts."""
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")

        def _clean(val: str) -> str:
            """Strip whitespace and the leading ' that Apollo adds for Excel."""
            return val.strip().lstrip("'").strip()

        reader = _csv.DictReader(_io.StringIO(text))
        rows = []
        for rec in reader:
            rec = {k.strip(): _clean(v or "") for k, v in rec.items()}

            # Name
            first = rec.get("First Name", "")
            last  = rec.get("Last Name",  "")
            name  = f"{first} {last}".strip()

            # Location — company city/state/country, fall back to person location
            city    = rec.get("Company City",    "") or rec.get("City",    "")
            state   = rec.get("Company State",   "") or rec.get("State",   "")
            country = rec.get("Company Country", "") or rec.get("Country", "")
            location = ", ".join(p for p in [city, state, country] if p)

            # Phone — prefer enriched mobile, then work direct, then corporate
            dmu_phone = (
                rec.get("Mobile Phone",      "")
                or rec.get("Work Direct Phone", "")
                or rec.get("Corporate Phone",   "")
                or rec.get("Home Phone",        "")
                or rec.get("Other Phone",       "")
            )

            dmu_linkedin = rec.get("Person Linkedin Url", "")

            rows.append({
                "Company name":      rec.get("Company Name",   ""),
                "Location":          location,
                "Industry":          rec.get("Industry",       ""),
                "DMU name":          name,
                "DMU title":         rec.get("Title",          ""),
                "DMU phone":         dmu_phone,
                "DMU mail":          rec.get("Email",          ""),
                "expected desire":   "",
                "comp. phone":       _clean(rec.get("Company Phone", "")),
                "comp. mail":        "",
                "sales notes":       "",
                "owner":             rec.get("Contact Owner",  ""),
                "last tried call":   "",
                "last spoken":       "",
                "contact notes":     "",
                "source":            "Apollo",
                "phase":             "",
                "Rejected":          "",
                "DMU LI URL":        dmu_linkedin,
                "comp. LI URL":      rec.get("Company Linkedin Url", ""),
                "website":           rec.get("Website",        ""),
                "# employees":       rec.get("# Employees",   ""),
                "annual revenue":    rec.get("Annual Revenue", ""),
                "seniority":         rec.get("Seniority",      ""),
                "department":        rec.get("Departments",    ""),
                "Apollo contact ID": rec.get("Apollo Contact Id", ""),
                "email status":      rec.get("Email Status",  ""),
                # Deduplication key — not written as a column
                "linkedin_url":      dmu_linkedin,
            })
        return rows

    st.markdown("#### Import an Apollo.io CSV export")
    st.caption(
        "Export contacts from Apollo and upload the CSV here. "
        "Each row is mapped to the correct CRM column and duplicates are skipped."
    )

    st.info(
        "**How to export from Apollo:**  \n"
        "People → select contacts → **Export** → **Export to CSV** → upload the file below.",
        icon="💡",
    )

    with st.container(border=True):
        uploaded_csv = st.file_uploader(
            "Upload Apollo CSV",
            type=["csv"],
            key="csv_uploader",
        )

    # Show a live preview as soon as a file is selected
    if uploaded_csv is not None:
        try:
            preview_rows = _parse_csv(uploaded_csv.read())
            uploaded_csv.seek(0)
        except Exception as exc:
            st.error(f"Could not read the CSV: {exc}")
            preview_rows = []

        if preview_rows:
            st.markdown(f"**{len(preview_rows)} row(s) detected** — preview of first 5:")
            st.table([
                {
                    "Name":    r["DMU name"]     or "—",
                    "Company": r["Company name"] or "—",
                    "Title":   r["DMU title"]    or "—",
                    "Email":   r["DMU mail"]     or "—",
                    "Phone":   r["DMU phone"]    or "—",
                }
                for r in preview_rows[:5]
            ])

    if st.button("Import to Google Sheets", type="primary", key="btn_apollo_csv"):
        if uploaded_csv is None:
            st.error("Upload a CSV file first.")
        else:
            from sheets_writer import append_lead

            try:
                uploaded_csv.seek(0)
                rows = _parse_csv(uploaded_csv.read())
            except Exception as exc:
                st.error(f"Could not read the CSV: {exc}")
                rows = []

            if rows:
                written = skipped = errors = 0
                bar = st.progress(0, text="Writing to Google Sheets…")

                for i, row in enumerate(rows):
                    bar.progress(
                        int((i + 1) / len(rows) * 100),
                        text=f"Row {i + 1} of {len(rows)}…",
                    )
                    if not row["Company name"] and not row["DMU name"]:
                        skipped += 1
                        continue
                    try:
                        if append_lead(row):
                            written += 1
                        else:
                            skipped += 1
                    except Exception as exc:
                        st.error(f"Row {i + 1} failed: {exc}")
                        errors += 1

                bar.empty()
                st.success(
                    f"✅ Done — **{written}** new lead(s) added, "
                    f"**{skipped}** duplicate(s) / empty row(s) skipped"
                    + (f", {errors} error(s)" if errors else "") + "."
                )


# ===========================================================================
# TAB 4 — Enrich Leads
# ===========================================================================
with tab_enrich:
    st.markdown("#### Enrich existing leads via Apollo")
    st.caption(
        "Reads leads from the CRM that are missing data, looks them up in Apollo "
        "by email or LinkedIn URL, and fills in the blanks."
    )

    _apollo_key = os.getenv("APOLLO_API_KEY", "") or st.secrets.get("APOLLO_API_KEY", "")
    if not _apollo_key:
        st.warning("Apollo API key not configured. Add `APOLLO_API_KEY` to Streamlit secrets.")

    with st.container(border=True):
        enrich_field = st.radio(
            "Match leads on",
            ["Email", "LinkedIn URL"],
            horizontal=True,
            help="Apollo uses this field to find the contact record.",
        )
        enrich_limit = st.number_input(
            "Max leads to enrich per run",
            min_value=1, max_value=50, value=10,
            help="Apollo enrichment uses 1 credit per contact.",
        )

    if st.button("Enrich leads", type="primary", key="btn_enrich"):
        if not _apollo_key:
            st.error("Apollo API key not configured.")
        else:
            import requests as _req
            from sheets_writer import _get_sheet, _normalise

            with st.spinner("Reading CRM…"):
                _sheet = _get_sheet()
                _all   = _sheet.get_all_values()

            if len(_all) < 2:
                st.warning("No leads found in the CRM.")
            else:
                _headers = _all[0]
                _rows    = [dict(zip(_headers, r)) for r in _all[1:]]

                # Find rows missing key fields
                _match_col = "DMU mail" if enrich_field == "Email" else "DMU LI URL"
                _candidates = [
                    (i + 2, r) for i, r in enumerate(_rows)
                    if r.get(_match_col, "").strip()
                    and not r.get("DMU phone", "").strip()
                ][:int(enrich_limit)]

                if not _candidates:
                    st.info("No leads need enrichment (all already have a phone, or no match field found).")
                else:
                    st.info(f"Enriching **{len(_candidates)}** lead(s)…")
                    _hdrs = {
                        "X-Api-Key": _apollo_key,
                        "Content-Type": "application/json",
                        "Cache-Control": "no-cache",
                    }
                    enriched = skipped_e = errors_e = 0
                    bar = st.progress(0)

                    for idx, (sheet_row, lead) in enumerate(_candidates):
                        bar.progress(int((idx + 1) / len(_candidates) * 100))
                        body: dict = {"api_key": _apollo_key, "reveal_personal_emails": True}
                        if enrich_field == "Email":
                            body["email"] = lead[_match_col]
                        else:
                            body["linkedin_url"] = lead[_match_col]

                        try:
                            _r = _req.post(
                                "https://api.apollo.io/v1/people/match",
                                headers=_hdrs, json=body, timeout=15,
                            )
                            if not _r.ok:
                                errors_e += 1
                                continue
                            _person = _r.json().get("person") or {}
                            if not _person:
                                skipped_e += 1
                                continue

                            # Build update values for the columns we want to fill
                            _phone_nums = _person.get("phone_numbers") or []
                            _phone = (_phone_nums[0].get("sanitized_number") if _phone_nums else "") or ""
                            _updates = {
                                "DMU phone":    _phone or lead.get("DMU phone", ""),
                                "seniority":    _person.get("seniority", "") or lead.get("seniority", ""),
                                "department":   ", ".join(_person.get("departments") or []) or lead.get("department", ""),
                                "email status": _person.get("email_status", "") or lead.get("email status", ""),
                                "DMU LI URL":   _person.get("linkedin_url", "") or lead.get("DMU LI URL", ""),
                            }
                            org = _person.get("organization") or {}
                            _updates["# employees"] = str(org.get("estimated_num_employees", "") or lead.get("# employees", ""))
                            _updates["annual revenue"] = str(org.get("annual_revenue", "") or lead.get("annual revenue", ""))
                            _updates["website"]       = org.get("website_url", "") or lead.get("website", "")
                            _updates["comp. LI URL"]  = org.get("linkedin_url", "") or lead.get("comp. LI URL", "")

                            # Write back only changed cells
                            from config import SHEET_COLUMNS as _COLS
                            for col_name, new_val in _updates.items():
                                if col_name in _COLS and new_val and not lead.get(col_name, "").strip():
                                    col_idx = _COLS.index(col_name) + 1  # 1-based
                                    _sheet.update_cell(sheet_row, col_idx, new_val)

                            enriched += 1
                        except Exception as _e:
                            st.warning(f"Row {sheet_row}: {_e}")
                            errors_e += 1

                    bar.empty()
                    st.success(
                        f"✅ Done — **{enriched}** lead(s) enriched, "
                        f"**{skipped_e}** not found in Apollo"
                        + (f", {errors_e} error(s)" if errors_e else "") + "."
                    )

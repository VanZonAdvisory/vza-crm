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
                        # Step 2: try the current search endpoint
                        _body = {"api_key": _key, "person_titles": ["CEO"], "per_page": 1, "page": 1}
                        _ep_url = "https://api.apollo.io/api/v1/mixed_people/api_search"
                        _resp = _req.post(_ep_url, headers=_headers, json=_body, timeout=15)
                        if _resp.ok:
                            _total = _resp.json().get("pagination", {}).get("total_entries", 0)
                            _total_fmt = f"{_total:,}" if isinstance(_total, int) else str(_total)
                            st.success(f"Apollo — connected ({_total_fmt} results for CEO)")
                        else:
                            st.error(f"Apollo search failed ({_resp.status_code})")
                            st.code(_resp.text[:600])
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
                    st.error(f"Apollo error (page {page}):")
                    st.code(str(exc))
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
    st.markdown("#### Enrich leads from Google Sheets")
    st.caption(
        "Mark leads for enrichment by typing any value (e.g. **x**) in the **enrich?** column "
        "of the Google Sheet. The app reads up to 10 marked rows and fills in missing fields via Apollo."
    )

    _apollo_key = st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", "")
    _tavily_key = st.secrets.get("TAVILY_API_KEY", "") or os.getenv("TAVILY_API_KEY", "")
    _ant_key    = st.secrets.get("ANTHROPIC_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")

    if not _apollo_key:
        st.warning("Apollo API key not configured. Add `APOLLO_API_KEY` to Streamlit secrets.")

    st.info(
        "**How to mark a lead:**  \n"
        "Open the Google Sheet → find the lead row → type **yes** in the **enrich?** column (column A).  \n"
        "The cell is cleared automatically after enrichment.",
        icon="💡",
    )

    if st.button("Load marked leads", key="btn_load_enrich"):
        from sheets_writer import _get_sheet as _gs

        with st.spinner("Reading sheet…"):
            _ws   = _gs()
            _all  = _ws.get_all_values()

        if len(_all) < 2:
            st.warning("Sheet is empty.")
        else:
            _hdrs = _all[0]
            if "enrich?" not in _hdrs:
                st.error(
                    "Column **enrich?** not found in your Google Sheet.  \n"
                    "Please add it as the header of **column A** (the very first column). "
                    "All existing data columns should be shifted one column to the right."
                )
            else:
                _ecol = _hdrs.index("enrich?")
                _candidates = [
                    (i + 2, dict(zip(_hdrs, row)))
                    for i, row in enumerate(_all[1:])
                    if len(row) > _ecol and row[_ecol].strip()
                ][:10]

                if not _candidates:
                    st.info("No rows marked for enrichment. Add **x** to the **enrich?** column in the sheet.")
                else:
                    st.session_state["_enrich_cands"]  = _candidates
                    st.session_state["_enrich_headers"] = _hdrs

    # ---- Preview and confirm ----
    if st.session_state.get("_enrich_cands"):
        _cands  = st.session_state["_enrich_cands"]
        _hdrs   = st.session_state["_enrich_headers"]

        st.markdown(f"**{len(_cands)} lead(s) queued for enrichment:**")
        _preview = []
        for _sr, _lead in _cands:
            _has_dmu = bool(_lead.get("DMU name", "").strip())
            _preview.append({
                "Row":              _sr,
                "Company":          _lead.get("Company name", "—") or "—",
                "DMU name":         _lead.get("DMU name",    "—") or "—",
                "DMU enrichment":   "phone · email · LinkedIn" if _has_dmu else "—",
                "Company enrichment": "phone · LinkedIn · website · employees · revenue",
            })
        st.table(_preview)

        _notes_note = " + AI sales notes" if (_tavily_key and _ant_key) else ""
        st.caption(f"Source: Apollo{_notes_note}. Only **empty** cells are filled. Existing values are never overwritten.")

        if st.button("Enrich marked leads", type="primary", key="btn_run_enrich"):
            if not _apollo_key:
                st.error("Apollo API key not configured.")
            else:
                from apollo_agent import enrich_person, enrich_company
                from sheets_writer import _get_sheet as _gs2

                _ws2     = _gs2()
                _ok      = 0
                _err     = 0
                _bar     = st.progress(0)

                for _idx, (_sr, _lead) in enumerate(_cands):
                    _bar.progress(int((_idx + 1) / len(_cands) * 100))
                    try:
                        _person_data = {}
                        _org_data    = {}

                        # --- Person enrichment ---
                        if _lead.get("DMU name", "").strip():
                            _person_data = enrich_person(
                                name        = _lead.get("DMU name",   ""),
                                company     = _lead.get("Company name", ""),
                                linkedin_url= _lead.get("DMU LI URL", ""),
                                email       = _lead.get("DMU mail",   ""),
                                api_key     = _apollo_key,
                            )
                            _org_data = _person_data.get("organization") or {}

                        # --- Company enrichment (standalone or supplement) ---
                        if not _org_data:
                            _org_data = enrich_company(
                                name    = _lead.get("Company name", ""),
                                website = _lead.get("website",      ""),
                                api_key = _apollo_key,
                            )

                        # --- Build update map (only empty target cells) ---
                        _upd: dict[str, str] = {}

                        if _person_data:
                            _phones = _person_data.get("phone_numbers") or []
                            _ph     = (_phones[0].get("sanitized_number") if _phones else "") or ""
                            if not _lead.get("DMU phone", "").strip() and _ph:
                                _upd["DMU phone"] = _ph
                            if not _lead.get("DMU mail", "").strip() and _person_data.get("email"):
                                _upd["DMU mail"] = _person_data["email"]
                            if not _lead.get("DMU LI URL", "").strip() and _person_data.get("linkedin_url"):
                                _upd["DMU LI URL"] = _person_data["linkedin_url"]

                        if _org_data:
                            if not _lead.get("comp. phone", "").strip() and _org_data.get("phone"):
                                _upd["comp. phone"] = _org_data["phone"]
                            if not _lead.get("comp. LI URL", "").strip() and _org_data.get("linkedin_url"):
                                _upd["comp. LI URL"] = _org_data["linkedin_url"]
                            if not _lead.get("website", "").strip() and _org_data.get("website_url"):
                                _upd["website"] = _org_data["website_url"]
                            if not _lead.get("# employees", "").strip() and _org_data.get("estimated_num_employees"):
                                _upd["# employees"] = str(_org_data["estimated_num_employees"])
                            if not _lead.get("annual revenue", "").strip() and _org_data.get("annual_revenue"):
                                _upd["annual revenue"] = str(_org_data["annual_revenue"])

                        # --- Sales notes via Tavily + Claude (best-effort) ---
                        if _tavily_key and _ant_key and not _lead.get("sales notes", "").strip():
                            try:
                                from tavily import TavilyClient
                                import anthropic as _ant_mod
                                _co = _lead.get("Company name", "")
                                if _co:
                                    _tv   = TavilyClient(api_key=_tavily_key)
                                    _hits = _tv.search(
                                        f"{_co} uitdagingen AI digitalisering operationeel",
                                        max_results=3,
                                    )
                                    _snip = " ".join(
                                        r.get("content", "")[:300]
                                        for r in _hits.get("results", [])
                                    )
                                    if _snip:
                                        _ac  = _ant_mod.Anthropic(api_key=_ant_key)
                                        _msg = _ac.messages.create(
                                            model="claude-haiku-4-5-20251001",
                                            max_tokens=120,
                                            system=(
                                                "Schrijf één korte Nederlandse zin (max 20 woorden) over waarom "
                                                "dit bedrijf waarschijnlijk baat heeft bij AI-training of procesverbetering, "
                                                "op basis van de aangeleverde websnippets."
                                            ),
                                            messages=[{"role": "user", "content": f"Bedrijf: {_co}\nSnippets: {_snip}"}],
                                        )
                                        _note = _msg.content[0].text.strip()
                                        if _note:
                                            _upd["sales notes"] = _note
                            except Exception:
                                pass  # sales notes are best-effort

                        # --- Write updates ---
                        for _col, _val in _upd.items():
                            if _col in _hdrs:
                                _ci = _hdrs.index(_col) + 1  # 1-based
                                _ws2.update_cell(_sr, _ci, _val)

                        # Clear enrich? flag
                        _ws2.update_cell(_sr, _hdrs.index("enrich?") + 1, "")
                        _ok += 1

                    except Exception as _ex:
                        st.warning(f"Row {_sr} ({_lead.get('Company name', '?')}): {_ex}")
                        _err += 1

                _bar.empty()
                del st.session_state["_enrich_cands"]
                del st.session_state["_enrich_headers"]

                st.success(
                    f"✅ Done — **{_ok}** lead(s) enriched"
                    + (f", {_err} error(s)" if _err else "") + "."
                )

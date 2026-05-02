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
    st.warning("🔒 Apollo Search is temporarily unavailable. Use the **Apollo CSV** tab to import contacts in the meantime.")


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
    _ant_key    = str(st.secrets.get("ANTHROPIC_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")).strip()

    if _ant_key and not _ant_key.startswith("sk-ant-"):
        st.warning(f"⚠️ ANTHROPIC_API_KEY looks wrong — starts with `{_ant_key[:12]}…` instead of `sk-ant-`. Check your Streamlit secrets.")
    elif not _ant_key:
        st.warning("⚠️ ANTHROPIC_API_KEY not found in Streamlit secrets.")

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
            # Case-insensitive match so "Enrich?", "enrich?" etc. all work
            _ecol = next(
                (i for i, h in enumerate(_hdrs) if h.strip().lower() == "enrich?"),
                None,
            )
            if _ecol is None:
                st.error(
                    "Column **enrich?** not found in your Google Sheet.  \n"
                    "Please add `enrich?` as the header of **column A**. "
                    "Check for typos or extra spaces in the header cell."
                )
            else:
                _candidates = [
                    (i + 2, dict(zip(_hdrs, row)))
                    for i, row in enumerate(_all[1:])
                    if len(row) > _ecol and row[_ecol].strip()
                ][:10]

                if not _candidates:
                    st.info("No rows marked for enrichment. Add **yes** to the **enrich?** column in the sheet.")
                else:
                    st.session_state["_enrich_cands"]   = _candidates
                    st.session_state["_enrich_headers"]  = _hdrs
                    st.session_state["_enrich_ecol"]     = _ecol

    # ---- Preview and confirm ----
    if st.session_state.get("_enrich_cands"):
        _cands  = st.session_state["_enrich_cands"]
        _hdrs   = st.session_state["_enrich_headers"]
        _ecol   = st.session_state["_enrich_ecol"]

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

        _web_note = " + web fallback" if (_tavily_key and _ant_key) else ""
        st.caption(f"Source: Apollo{_web_note}. Only **empty** cells are filled. Existing values are never overwritten.")

        if st.button("Enrich marked leads", type="primary", key="btn_run_enrich"):
            if not _apollo_key:
                st.error("Apollo API key not configured.")
            else:
                from apollo_agent import enrich_person, enrich_company
                from sheets_writer import _get_sheet as _gs2

                _ws2      = _gs2()
                _ok       = 0
                _nothing  = 0
                _err      = 0
                _bar      = st.progress(0)
                _log      = st.empty()

                for _idx, (_sr, _lead) in enumerate(_cands):
                    _co_name = _lead.get("Company name", f"row {_sr}")
                    _bar.progress(int((_idx + 1) / len(_cands) * 100),
                                  text=f"Processing {_co_name}…")
                    try:
                        _person_data = {}
                        _org_data    = {}

                        # --- Apollo: person ---
                        if _lead.get("DMU name", "").strip():
                            _person_data = enrich_person(
                                name        = _lead.get("DMU name",     ""),
                                company     = _lead.get("Company name", ""),
                                linkedin_url= _lead.get("DMU LI URL",   ""),
                                email       = _lead.get("DMU mail",     ""),
                                api_key     = _apollo_key,
                            )
                            _org_data = _person_data.get("organization") or {}

                        # --- Apollo: company (domain required) ---
                        if not _org_data:
                            _org_data = enrich_company(
                                name    = _lead.get("Company name", ""),
                                website = _lead.get("website",      ""),
                                api_key = _apollo_key,
                            )

                        # --- Build update map (only fill empty cells) ---
                        _upd: dict[str, str] = {}

                        if _person_data:
                            _phones = _person_data.get("phone_numbers") or []
                            _ph = (_phones[0].get("sanitized_number") if _phones else "") or ""
                            if not _lead.get("DMU phone",  "").strip() and _ph:
                                _upd["DMU phone"]  = _ph
                            if not _lead.get("DMU mail",   "").strip() and _person_data.get("email"):
                                _upd["DMU mail"]   = _person_data["email"]
                            if not _lead.get("DMU LI URL","").strip() and _person_data.get("linkedin_url"):
                                _upd["DMU LI URL"] = _person_data["linkedin_url"]

                        if _org_data:
                            if not _lead.get("comp. phone", "").strip() and _org_data.get("phone"):
                                _upd["comp. phone"] = _org_data["phone"]
                            if not _lead.get("comp. LI URL","").strip() and _org_data.get("linkedin_url"):
                                _upd["comp. LI URL"]= _org_data["linkedin_url"]
                            if not _lead.get("website",    "").strip() and _org_data.get("website_url"):
                                _upd["website"]     = _org_data["website_url"]
                            if not _lead.get("# employees","").strip() and _org_data.get("estimated_num_employees"):
                                _upd["# employees"] = str(_org_data["estimated_num_employees"])
                            if not _lead.get("annual revenue","").strip() and _org_data.get("annual_revenue"):
                                _upd["annual revenue"] = str(_org_data["annual_revenue"])

                        # --- Tavily + Claude sequential web enrichment ---
                        _web_fields = [
                            "comp. LI URL", "Location", "Industry", "comp. phone",
                            "comp. mail", "website", "# employees", "annual revenue",
                            "sales notes", "DMU LI URL", "DMU title", "DMU mail",
                            "DMU phone", "seniority", "department",
                        ]
                        _needs_web = _tavily_key and _ant_key and any(
                            not {**_lead, **_upd}.get(f, "").strip() for f in _web_fields
                        )
                        if _needs_web:
                            try:
                                from web_enrichment import enrich_from_web
                                _web_found = enrich_from_web(
                                    {**_lead, **_upd},  # pass Apollo results as context
                                    _tavily_key,
                                    _ant_key,
                                )
                                for _wf, _wv in _web_found.items():
                                    if _wv and not {**_lead, **_upd}.get(_wf, "").strip():
                                        _upd[_wf] = _wv
                            except Exception as _web_err:
                                _em = str(_web_err)
                                if "401" in _em or "authentication_error" in _em or "invalid x-api-key" in _em:
                                    st.warning("⚠️ ANTHROPIC_API_KEY in Streamlit secrets is invalid or expired. Update it under Settings → Secrets.")
                                else:
                                    st.caption(f"↳ Web enrichment for {_co_name}: {_web_err}")

                        # --- Write to sheet ---
                        _written_cols = []
                        for _col, _val in _upd.items():
                            if _col in _hdrs and _val:
                                _ci = _hdrs.index(_col) + 1
                                _ws2.update_cell(_sr, _ci, _val)
                                _written_cols.append(_col)

                        # Clear enrich? flag
                        _ws2.update_cell(_sr, _ecol + 1, "")

                        if _written_cols:
                            st.caption(f"✅ {_co_name}: filled {', '.join(_written_cols)}")
                            _ok += 1
                        else:
                            st.caption(f"⚠️ {_co_name}: nothing found to fill")
                            _nothing += 1

                    except Exception as _ex:
                        st.warning(f"❌ Row {_sr} ({_co_name}): {_ex}")
                        _err += 1

                _bar.empty()
                _log.empty()
                del st.session_state["_enrich_cands"]
                del st.session_state["_enrich_headers"]
                del st.session_state["_enrich_ecol"]

                _summary = f"**{_ok}** lead(s) enriched"
                if _nothing:
                    _summary += f", **{_nothing}** lead(s) — nothing found"
                if _err:
                    _summary += f", **{_err}** error(s)"
                st.success(f"✅ Done — {_summary}.")

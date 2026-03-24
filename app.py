"""
app.py
------
KKC Journal Entry Testing Tool — Main Streamlit Application.

SA 240 compliant, fully offline, audit-grade JE analytics tool for
KKC & Associates LLP, Chartered Accountants.

Run with:  streamlit run app.py
"""

import io
from datetime import datetime

import pandas as pd
import streamlit as st

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="KKC JE Testing Tool",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Source Sans Pro with system fallbacks */
    html, body, [class*="css"] {
        font-family: "Source Sans Pro", Arial, sans-serif;
    }
    /* Risk badge helper classes */
    .badge-high   { background:#FF0000; color:white; padding:2px 10px;
                    border-radius:4px; font-weight:bold; font-size:0.85em; }
    .badge-medium { background:#FFA500; color:white; padding:2px 10px;
                    border-radius:4px; font-weight:bold; font-size:0.85em; }
    .badge-low    { background:#7CB542; color:white; padding:2px 10px;
                    border-radius:4px; font-weight:bold; font-size:0.85em; }
    /* Tighter expander header */
    .streamlit-expanderHeader { font-size:1rem !important; font-weight:600; }
    /* Reduce top padding */
    .block-container { padding-top: 1.5rem !important; }
    /* KKC green accent on sidebar header */
    .kkc-header { color:#7CB542; font-size:1.4rem; font-weight:700;
                  letter-spacing:0.5px; margin-bottom:0; }
    .kkc-sub    { color:#808285; font-size:0.78rem; margin-top:0; }
</style>
""", unsafe_allow_html=True)

# ── Module imports ────────────────────────────────────────────────────────────
from utils.column_mapper import (
    auto_map_columns,
    get_mapping_confidence,
    apply_overrides,
    validate_minimum_fields,
    get_mapped_df,
    render_mapping_table,
    STANDARD_FIELDS,
)
from modules.benfords       import run as run_benfords
from modules.duplicates     import run as run_duplicates
from modules.round_numbers  import run as run_round_numbers
from modules.after_hours    import run as run_after_hours
from modules.period_end     import run as run_period_end
from modules.no_narration   import run as run_no_narration
from modules.account_combos import run as run_account_combos
from modules.user_analysis  import run as run_user_analysis
from modules.keywords       import run as run_keywords
from utils.excel_exporter   import build_workbook, generate_filename

# ── Constants ─────────────────────────────────────────────────────────────────
_VERSION = "1.0.0"

# Ordered module definitions — (display_name, session_key, run_fn)
# kwargs_extra is built at run-time from session state
_MODULES = [
    ("Benford's Law",                  "benfords",       run_benfords),
    ("Duplicate Detection",            "duplicates",     run_duplicates),
    ("Round Number Detection",         "round_numbers",  run_round_numbers),
    ("After-Hours & Weekend Postings", "after_hours",    run_after_hours),
    ("Period-End Entry Concentration", "period_end",     run_period_end),
    ("Missing Narration",              "no_narration",   run_no_narration),
    ("Unusual Account Combinations",   "account_combos", run_account_combos),
    ("User Analysis",                  "user_analysis",  run_user_analysis),
    ("Keyword Flags",                  "keywords",       run_keywords),
]

_RISK_COLOURS = {"High": "#FF0000", "Medium": "#FFA500", "Low": "#7CB542"}


# ── UI helpers ────────────────────────────────────────────────────────────────

def _risk_badge(risk: str) -> str:
    """Return an HTML coloured risk badge string."""
    cls = {"High": "badge-high", "Medium": "badge-medium", "Low": "badge-low"}.get(
        risk, "badge-low"
    )
    return f'<span class="{cls}">{risk}</span>'


def _inr(amount: float) -> str:
    """
    Format a number in Indian notation with ₹ prefix.

    Examples: 1,23,45,678 → ₹1.23 Cr; 4,50,000 → ₹4.50 L; 12,500 → ₹12.5 K
    """
    a = abs(amount)
    sign = "-" if amount < 0 else ""
    if a >= 1e7:
        return f"{sign}₹{a/1e7:.2f} Cr"
    if a >= 1e5:
        return f"{sign}₹{a/1e5:.2f} L"
    if a >= 1e3:
        return f"{sign}₹{a/1e3:.1f} K"
    return f"{sign}₹{a:,.0f}"


def _overall_risk(results: dict) -> str:
    """Return the worst risk rating across all module results."""
    ratings = [r["risk_rating"] for r in results.values()]
    if "High"   in ratings: return "High"
    if "Medium" in ratings: return "Medium"
    return "Low"


def _load_uploaded_file(uploaded) -> pd.DataFrame:
    """
    Read an uploaded Streamlit file object into a DataFrame.

    Supports .csv, .xlsx, .xls.

    Args:
        uploaded: Streamlit UploadedFile object.

    Returns:
        Loaded DataFrame.

    Raises:
        ValueError: If the file extension is not recognised.
    """
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded, low_memory=False)
    elif name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded)
    else:
        raise ValueError(f"Unsupported file type: {uploaded.name}")


def _load_holiday_csv(uploaded) -> list[str]:
    """
    Parse an uploaded holiday CSV into a list of 'YYYY-MM-DD' date strings.

    The CSV should have dates in the first column.  Mixed date formats are
    accepted via pandas.

    Args:
        uploaded: Streamlit UploadedFile.

    Returns:
        List of 'YYYY-MM-DD' strings.
    """
    df = pd.read_csv(uploaded, header=None)
    raw = pd.to_datetime(df.iloc[:, 0], errors="coerce").dropna()
    return [d.strftime("%Y-%m-%d") for d in raw]


# ── Session state initialisation ─────────────────────────────────────────────

def _init_state() -> None:
    """Initialise all session state keys to safe defaults on first load."""
    defaults = {
        "df_raw":            None,
        "df_mapped":         None,
        "upload_filename":   "",
        "confirmed_mapping": {},
        "module_results":    {},
        "analysis_run":      False,
        "extra_keywords":    [],
        "holiday_dates":     None,
        "coa_df":            None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

_init_state()


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="kkc-header">KKC & Associates LLP</p>', unsafe_allow_html=True)
    st.markdown('<p class="kkc-sub">Chartered Accountants</p>', unsafe_allow_html=True)
    st.divider()

    st.subheader("Engagement Details")
    client_name    = st.text_input("Client Name *", placeholder="e.g. Shriram Finance Ltd")
    audit_period   = st.text_input("Audit Period *", placeholder="e.g. March 2025")
    financial_year = st.text_input("Financial Year", placeholder="e.g. FY 2024-25")
    prepared_by    = st.text_input("Prepared By", placeholder="CA / Audit Assistant name")
    materiality    = st.number_input(
        "Materiality (₹)", min_value=0, value=0, step=10_000,
        help="Optional — for workpaper reference only",
    )

    st.divider()
    st.caption(f"KKC JE Testing Tool  v{_VERSION}")
    st.caption(f"Run date: {datetime.today().strftime('%d %B %Y')}")

# ── Main tabs ─────────────────────────────────────────────────────────────────
tab_upload, tab_run, tab_results, tab_export = st.tabs([
    "📁 Upload & Map",
    "⚙️ Run Analysis",
    "📊 Results",
    "📥 Export",
])


# =============================================================================
# TAB 1 — Upload & Map
# =============================================================================
with tab_upload:
    st.header("Step 1 — Upload GL Export")

    uploaded_file = st.file_uploader(
        "Upload your GL journal entry export",
        type=["csv", "xlsx", "xls"],
        help="Accepted formats: CSV, Excel (.xlsx / .xls)",
    )

    if uploaded_file is not None:
        # Only reload if it's a new file
        if uploaded_file.name != st.session_state.upload_filename:
            with st.spinner("Reading file…"):
                try:
                    df_raw = _load_uploaded_file(uploaded_file)
                    st.session_state.df_raw          = df_raw
                    st.session_state.upload_filename  = uploaded_file.name
                    st.session_state.analysis_run     = False
                    st.session_state.module_results   = {}
                    # Auto-map columns
                    mapping_detail = get_mapping_confidence(list(df_raw.columns))
                    st.session_state.mapping_detail   = mapping_detail
                    # Build initial confirmed_mapping from auto-map
                    st.session_state.confirmed_mapping = {
                        f: d["mapped_to"] for f, d in mapping_detail.items()
                    }
                except Exception as exc:
                    st.error(f"Could not read file: {exc}")
                    st.stop()

        df_raw = st.session_state.df_raw

        # ── File summary ─────────────────────────────────────────────────────
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Entries loaded", f"{len(df_raw):,}")
        col_b.metric("Columns found",  f"{len(df_raw.columns)}")
        col_c.metric("File", uploaded_file.name)

        # ── Preview ───────────────────────────────────────────────────────────
        with st.expander("Preview first 10 rows", expanded=False):
            st.dataframe(df_raw.head(10), use_container_width=True)

        # ── Column mapping ────────────────────────────────────────────────────
        st.divider()
        st.header("Step 2 — Review Column Mapping")
        st.info(
            "The tool has automatically matched your column names to the "
            "standard field names.  Scores ≥ 85 are shown in green.  "
            "Use the dropdowns to correct any mismatches."
        )

        mapping_detail = st.session_state.get("mapping_detail", {})
        render_mapping_table(mapping_detail, list(df_raw.columns))

        # confirmed_mapping is written live by render_mapping_table
        mapping = st.session_state.get("confirmed_mapping", {})

        # ── Validation ────────────────────────────────────────────────────────
        is_valid, missing = validate_minimum_fields(mapping)
        if is_valid:
            df_mapped = get_mapped_df(df_raw, mapping)
            st.session_state.df_mapped = df_mapped
            mapped_count = sum(1 for v in mapping.values() if v)
            st.success(
                f"✅ Mapping confirmed — {mapped_count} of "
                f"{len(STANDARD_FIELDS)} fields mapped.  "
                f"Proceed to **Run Analysis**."
            )
        else:
            st.error(
                "❌ Minimum required fields are not mapped.  "
                f"Missing: {', '.join(missing)}"
            )
    else:
        st.info("👆 Upload a CSV or Excel GL export to begin.")


# =============================================================================
# TAB 2 — Run Analysis
# =============================================================================
with tab_run:
    st.header("Step 3 — Select & Run Modules")

    if st.session_state.df_mapped is None:
        st.warning("⬅️ Upload a file and confirm the column mapping in **Upload & Map** first.")
    else:
        df_mapped = st.session_state.df_mapped
        pop_count = len(df_mapped)

        st.info(
            f"**{pop_count:,}** entries ready for analysis from "
            f"**{st.session_state.upload_filename}**"
        )

        # ── Module selection ──────────────────────────────────────────────────
        st.subheader("Select Modules to Run")

        # Handle Select All / Deselect All BEFORE widgets are rendered
        col_all, col_none = st.columns([1, 1])
        if col_all.button("Select All"):
            for _, key, _ in _MODULES:
                st.session_state[f"chk_{key}"] = True
        if col_none.button("Deselect All"):
            for _, key, _ in _MODULES:
                st.session_state[f"chk_{key}"] = False

        cols_sel = st.columns(2)
        module_checks = {}
        for i, (name, key, _) in enumerate(_MODULES):
            with cols_sel[i % 2]:
                module_checks[key] = st.checkbox(name, value=True, key=f"chk_{key}")

        # ── Optional inputs ───────────────────────────────────────────────────
        st.divider()
        st.subheader("Optional Inputs")

        with st.expander("🔑 Extra Keywords (Keyword Flags module)"):
            raw_kw = st.text_area(
                "Add extra keywords (one per line)",
                height=100,
                placeholder="e.g.\nmanagement approval\nCFO instruction",
                help="These are added on top of the default keyword list in config.py",
            )
            st.session_state.extra_keywords = [
                kw.strip() for kw in raw_kw.splitlines() if kw.strip()
            ]
            if st.session_state.extra_keywords:
                st.caption(f"{len(st.session_state.extra_keywords)} extra keyword(s) will be used.")

        with st.expander("📅 Holiday Calendar (After-Hours module)"):
            holiday_file = st.file_uploader(
                "Upload holiday dates CSV (one date per row, first column)",
                type=["csv"],
                key="holiday_upload",
                help="Optional — entries on these dates will be flagged as Holiday postings",
            )
            if holiday_file:
                try:
                    st.session_state.holiday_dates = _load_holiday_csv(holiday_file)
                    st.success(f"✅ {len(st.session_state.holiday_dates)} holiday dates loaded.")
                except Exception as exc:
                    st.error(f"Could not parse holiday file: {exc}")

        with st.expander("📋 Chart of Accounts (Unusual Combos module)"):
            coa_file = st.file_uploader(
                "Upload Chart of Accounts CSV (columns: account_code, account_type)",
                type=["csv", "xlsx"],
                key="coa_upload",
                help="Optional — improves account-type classification in the Unusual Combos module",
            )
            if coa_file:
                try:
                    coa_df = _load_uploaded_file(coa_file)
                    st.session_state.coa_df = coa_df
                    st.success(f"✅ COA loaded — {len(coa_df):,} accounts.")
                    st.dataframe(coa_df.head(5), use_container_width=True)
                except Exception as exc:
                    st.error(f"Could not parse COA file: {exc}")

        # ── Run button ────────────────────────────────────────────────────────
        st.divider()
        selected_modules = [
            (name, key, fn)
            for name, key, fn in _MODULES
            if module_checks.get(key, False)
        ]

        if not selected_modules:
            st.warning("Select at least one module to run.")
        else:
            if st.button(
                f"▶ Run {len(selected_modules)} Selected Test(s)",
                type="primary",
                use_container_width=True,
            ):
                # ── Build extra kwargs per module ─────────────────────────────
                def _extra_kwargs(key: str) -> dict:
                    if key == "after_hours":
                        return {"holiday_dates": st.session_state.holiday_dates}
                    if key == "account_combos":
                        return {"coa_df": st.session_state.coa_df}
                    if key == "keywords":
                        return {"extra_keywords": st.session_state.extra_keywords}
                    return {}

                # ── Execute modules with progress bar ─────────────────────────
                progress_bar = st.progress(0.0)
                status_text  = st.empty()
                results: dict[str, dict] = {}
                n = len(selected_modules)

                for i, (name, key, fn) in enumerate(selected_modules):
                    status_text.markdown(f"Running **{name}** ...  ({i+1}/{n})")
                    try:
                        result = fn(df_mapped, **_extra_kwargs(key))
                        results[result["module_name"]] = result
                    except Exception as exc:
                        st.error(f"❌ {name} failed: {exc}")
                    progress_bar.progress((i + 1) / n)

                st.session_state.module_results = results
                st.session_state.analysis_run   = True
                progress_bar.progress(1.0)

                # ── Completion summary ─────────────────────────────────────────
                total_flags  = sum(r["flag_count"] for r in results.values())
                overall      = _overall_risk(results)
                status_text.empty()
                colour       = _RISK_COLOURS.get(overall, "#7CB542")
                st.success(
                    f"**Analysis complete** — "
                    f"{pop_count:,} entries tested | "
                    f"{total_flags:,} flags raised | "
                    f"Overall Risk: **{overall.upper()}**"
                )
                st.balloons()


# =============================================================================
# TAB 3 — Results
# =============================================================================
with tab_results:
    st.header("Analysis Results")

    if not st.session_state.analysis_run or not st.session_state.module_results:
        st.info("Run the analysis in **Run Analysis** to see results here.")
    else:
        results     = st.session_state.module_results
        overall     = _overall_risk(results)
        pop_count   = next(iter(results.values()))["population_count"]
        total_flags = sum(r["flag_count"] for r in results.values())

        # ── Overall banner ────────────────────────────────────────────────────
        banner_colour = _RISK_COLOURS.get(overall, "#7CB542")
        st.markdown(
            f"""
            <div style="background:{banner_colour};color:white;padding:16px 24px;
                        border-radius:8px;margin-bottom:16px;">
                <span style="font-size:1.5rem;font-weight:700;">
                    Overall Engagement Risk: {overall.upper()}
                </span>
                &nbsp;&nbsp;
                <span style="font-size:1rem;opacity:0.9;">
                    {pop_count:,} entries tested &nbsp;|&nbsp;
                    {total_flags:,} flags raised
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── Summary table ─────────────────────────────────────────────────────
        st.subheader("Module Summary")

        summary_rows = []
        for name, key, _ in _MODULES:
            result = results.get(name)
            if result is None:
                continue
            summary_rows.append({
                "Module":          result["module_name"],
                "Flagged":         result["flag_count"],
                "% of Population": f"{result['flag_pct']*100:.1f}%",
                "Risk":            result["risk_rating"],
            })

        if summary_rows:
            # Render as an HTML table with risk badges
            rows_html = ""
            for i, row in enumerate(summary_rows):
                bg = "#F2F2F2" if i % 2 == 1 else "#FFFFFF"
                risk = row["Risk"]
                badge = _risk_badge(risk)
                rows_html += (
                    f'<tr style="background:{bg}">'
                    f'<td style="padding:6px 12px">{row["Module"]}</td>'
                    f'<td style="padding:6px 12px;text-align:center">{row["Flagged"]:,}</td>'
                    f'<td style="padding:6px 12px;text-align:center">{row["% of Population"]}</td>'
                    f'<td style="padding:6px 12px;text-align:center">{badge}</td>'
                    f'</tr>'
                )
            # Total row
            rows_html += (
                f'<tr style="background:#7CB542;color:white;font-weight:bold">'
                f'<td style="padding:6px 12px">TOTAL</td>'
                f'<td style="padding:6px 12px;text-align:center">{total_flags:,}</td>'
                f'<td style="padding:6px 12px;text-align:center">'
                f'{total_flags/pop_count*100:.1f}%</td>'
                f'<td style="padding:6px 12px;text-align:center">'
                f'{_risk_badge(overall)}</td>'
                f'</tr>'
            )
            st.markdown(
                f"""
                <table style="width:100%;border-collapse:collapse;
                              font-family:Arial,sans-serif;font-size:0.9rem">
                    <thead>
                        <tr style="background:#7CB542;color:white;font-weight:bold">
                            <th style="padding:8px 12px;text-align:left">Module</th>
                            <th style="padding:8px 12px;text-align:center">Flagged</th>
                            <th style="padding:8px 12px;text-align:center">% of Population</th>
                            <th style="padding:8px 12px;text-align:center">Risk</th>
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
                """,
                unsafe_allow_html=True,
            )

        st.divider()

        # ── Per-module expandable sections ────────────────────────────────────
        st.subheader("Detailed Module Results")

        for name, key, _ in _MODULES:
            result = results.get(name)
            if result is None:
                continue

            risk       = result["risk_rating"]
            flag_count = result["flag_count"]
            flag_pct   = result["flag_pct"] * 100
            icon = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}.get(risk, "⚪")

            with st.expander(
                f"{icon} {result['module_name']} — "
                f"{flag_count:,} flagged ({flag_pct:.1f}%)  |  Risk: {risk}",
                expanded=(risk == "High"),
            ):
                col_l, col_r = st.columns([3, 1])

                with col_r:
                    st.markdown(
                        f'<div style="text-align:center;padding:12px">'
                        f'{_risk_badge(risk)}</div>',
                        unsafe_allow_html=True,
                    )
                    st.metric("Flagged",    f"{flag_count:,}")
                    st.metric("Population", f"{result['population_count']:,}")
                    st.metric("Flag %",     f"{flag_pct:.1f}%")

                with col_l:
                    # Chart
                    chart = result.get("chart")
                    if chart is not None:
                        try:
                            st.plotly_chart(chart, use_container_width=True,
                                            config={"displayModeBar": False})
                        except Exception:
                            pass

                # Flagged entries table
                flagged_df = result.get("flagged_df", pd.DataFrame())
                if not flagged_df.empty:
                    st.caption(
                        f"Showing first {min(500, len(flagged_df)):,} of "
                        f"{len(flagged_df):,} flagged entries"
                    )
                    display_df = flagged_df.head(500).reset_index(drop=True)
                    # Format amount column for display
                    if "amount" in display_df.columns:
                        display_df = display_df.copy()
                        display_df["amount"] = display_df["amount"].apply(
                            lambda v: _inr(float(v)) if pd.notna(v) else ""
                        )
                    st.dataframe(display_df, use_container_width=True, height=300)
                else:
                    st.success("No entries flagged by this module.")

                # Module-specific extra stats
                stats = result.get("summary_stats", {})

                # Benford's — show chi-square summary
                if name == "Benford's Law" and stats:
                    p = stats.get("p_value")
                    chi2 = stats.get("chi2")
                    if p is not None:
                        st.caption(
                            f"Chi-square: {chi2:.4f}  |  p-value: {p:.6f}  |  "
                            f"Result: {'FAIL (p < 0.05)' if p < 0.05 else 'PASS'}"
                        )

                # User Analysis — show top-10 tables
                if name == "User Analysis" and stats:
                    t10v = stats.get("top10_by_volume", pd.DataFrame())
                    t10a = stats.get("top10_by_amount", pd.DataFrame())
                    if not t10v.empty:
                        with st.expander("Top 10 Users by Entry Volume"):
                            st.dataframe(t10v, use_container_width=True)
                    if not t10a.empty:
                        with st.expander("Top 10 Users by Total Amount"):
                            st.dataframe(t10a, use_container_width=True)

                # Period-End — show month table
                if name == "Period-End Entry Concentration" and stats:
                    month_tbl = stats.get("month_table", pd.DataFrame())
                    if not month_tbl.empty:
                        with st.expander("Month-wise Concentration Table"):
                            st.dataframe(month_tbl, use_container_width=True)

                # Keywords — show keyword hit counts
                if name == "Keyword Flags" and stats:
                    kc = stats.get("keyword_counts", {})
                    if kc:
                        kc_df = (
                            pd.DataFrame(list(kc.items()), columns=["Keyword", "Hits"])
                            .sort_values("Hits", ascending=False)
                            .reset_index(drop=True)
                        )
                        with st.expander("Keyword Hit Counts"):
                            st.dataframe(kc_df, use_container_width=True)


# =============================================================================
# TAB 4 — Export
# =============================================================================
with tab_export:
    st.header("Step 4 — Export Workpaper")

    if not st.session_state.analysis_run or not st.session_state.module_results:
        st.warning(
            "⬅️ Run the analysis in **Run Analysis** before exporting.\n\n"
            "The Excel workpaper will be available once at least one module "
            "has been executed."
        )
    else:
        results   = st.session_state.module_results
        overall   = _overall_risk(results)
        pop_count = next(iter(results.values()))["population_count"]

        # ── Engagement parameters confirmation ────────────────────────────────
        st.subheader("Engagement Parameters")

        if not client_name:
            st.error("Please enter a **Client Name** in the sidebar before exporting.")
        if not audit_period:
            st.error("Please enter an **Audit Period** in the sidebar before exporting.")

        params = {
            "client_name":    client_name    or "Unknown Client",
            "period":         audit_period   or "Unknown Period",
            "financial_year": financial_year or "",
            "prepared_by":    prepared_by    or "",
            "materiality":    materiality    or None,
            "run_date":       datetime.today(),
        }

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown(f"**Client:** {params['client_name']}")
            st.markdown(f"**Period:** {params['period']}")
            st.markdown(f"**Financial Year:** {params['financial_year'] or '—'}")
        with col_p2:
            st.markdown(f"**Prepared By:** {params['prepared_by'] or '—'}")
            mat_display = _inr(float(params["materiality"])) if params["materiality"] else "Not specified"
            st.markdown(f"**Materiality:** {mat_display}")
            st.markdown(f"**Run Date:** {params['run_date'].strftime('%d %B %Y')}")

        # ── Workbook details ──────────────────────────────────────────────────
        st.divider()
        filename = generate_filename(
            params["client_name"], params["period"], params["run_date"]
        )
        total_flags = sum(r["flag_count"] for r in results.values())

        st.subheader("Workpaper Summary")
        col_e1, col_e2, col_e3 = st.columns(3)
        col_e1.metric("Sheets",       "12")
        col_e2.metric("Total Flags",  f"{total_flags:,}")
        col_e3.metric("Overall Risk", overall)

        st.caption(f"Output filename: **{filename}**")

        # ── Sheets that will be included ──────────────────────────────────────
        with st.expander("Sheets included in workpaper"):
            sheets_info = [
                ("1",  "Summary Dashboard",   "Overall risk table + engagement details"),
                ("2",  "Benfords Analysis",   "Expected vs observed digit distribution"),
                ("3",  "Duplicates",          "Exact & near-duplicate JE entries"),
                ("4",  "Round Numbers",       "Round lakh / crore / thousand entries"),
                ("5",  "After Hours Weekend", "Entries posted outside business hours"),
                ("6",  "Period End Entries",  "Entries in last 3–5 days of month"),
                ("7",  "Missing Narration",   "Blank or generic narration entries"),
                ("8",  "Unusual Acct Combos", "Rare or rule-based account combinations"),
                ("9",  "User Analysis",       "Outlier users + self-approvals"),
                ("10", "Keyword Flags",       "High-risk keyword matches"),
                ("11", "Full Population",     "All entries with pipe-separated Flags column"),
                ("12", "Parameters",          "Run parameters & thresholds for audit trail"),
            ]
            for num, name, desc in sheets_info:
                st.markdown(f"**Sheet {num}** — {name}: _{desc}_")

        # ── Generate and download ─────────────────────────────────────────────
        st.divider()

        if st.button("Generate Excel Workpaper", type="secondary", use_container_width=True):
            with st.spinner("Building workpaper (this may take a few seconds)…"):
                try:
                    buf = io.BytesIO()
                    build_workbook(
                        full_df=st.session_state.df_mapped,
                        module_results=results,
                        params=params,
                        output_path=buf,
                    )
                    buf.seek(0)
                    st.session_state["excel_bytes"]    = buf.getvalue()
                    st.session_state["excel_filename"] = filename
                    st.success("Workpaper generated — click **Download** below.")
                except Exception as exc:
                    st.error(f"Failed to generate workpaper: {exc}")
                    import traceback
                    st.code(traceback.format_exc())

        if st.session_state.get("excel_bytes"):
            st.download_button(
                label="📥 Download Excel Workpaper",
                data=st.session_state["excel_bytes"],
                file_name=st.session_state["excel_filename"],
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )
            st.caption(
                "This file contains client data. "
                "Store it in a secure, access-controlled location per your firm's data policy."
            )


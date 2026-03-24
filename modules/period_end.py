"""
modules/period_end.py
---------------------
Module 5: Period-End Entry Concentration for the KKC JE Testing Tool.

SA Reference: SA 240.A36

Entries clustered in the last few days of a month (or financial year) are
a classic earnings-management indicator.  Management may:
  - Record provisions or accruals at period-end to hit a target
  - Reverse prior-period entries just before the books close
  - Post backdated entries dated to the last day of a month

Two concentration bands (per CLAUDE.md):
  High Risk entries   — fall in the last 3 calendar days of their month
  Medium Risk entries — fall in the last 4–5 calendar days (days 4–5 from month-end)

Year-end cut-off risk:
  Entries dated March 29, 30 or 31 receive an additional "Year-End" flag
  regardless of which band they fall into.  These are highlighted
  separately in the output and the Excel workpaper.

Month-wise concentration chart:
  A bar chart shows, for each calendar month in the dataset, the
  percentage of that month's entries that fall in the last-3-days
  (High) band.  Months where this exceeds 10% are visually highlighted.

Risk Rating (per CLAUDE.md):
  High   — any month where last-3-days entries > 10% of that month's total
  Medium — any month where last-3-to-5-days entries > 5% of that month's
           total (but no month breaches the High threshold)
  Low    — all months below 5%
"""

from __future__ import annotations

import calendar
import pandas as pd
import plotly.graph_objects as go
from typing import Optional

try:
    from config import (
        PERIOD_END_HIGH_DAYS,
        PERIOD_END_MEDIUM_DAYS,
        KKC_GREEN,
        KKC_GREY,
        KKC_LIGHT_GREY,
        RISK_RED,
        RISK_ORANGE,
    )
except ImportError:
    PERIOD_END_HIGH_DAYS   = 3
    PERIOD_END_MEDIUM_DAYS = 5
    KKC_GREEN              = "#7CB542"
    KKC_GREY               = "#808285"
    KKC_LIGHT_GREY         = "#F2F2F2"
    RISK_RED               = "#FF0000"
    RISK_ORANGE            = "#FFA500"

# Risk thresholds for month-wise concentration
_HIGH_PCT_THRESHOLD   = 0.10   # > 10% of month entries in last 3 days → High
_MEDIUM_PCT_THRESHOLD = 0.05   # > 5%  of month entries in last 5 days → Medium

# Year-end risk: final 3 days of March (Indian FY ends 31-Mar)
_YEAR_END_MONTH  = 3
_YEAR_END_DAYS   = {29, 30, 31}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_dates(series: pd.Series) -> pd.Series:
    """
    Coerce a date-like column to pandas Timestamps (date-normalised to midnight).

    Args:
        series: Raw posting_date column from the uploaded dataframe.

    Returns:
        Series of Timestamps at midnight, NaT for unparseable values.
    """
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def _month_last_day(ts: pd.Timestamp) -> int:
    """
    Return the last calendar day number of the month containing `ts`.

    Args:
        ts: A pandas Timestamp.

    Returns:
        Integer day, e.g. 28 / 29 / 30 / 31.  Returns 0 for NaT.
    """
    if pd.isna(ts):
        return 0
    return calendar.monthrange(ts.year, ts.month)[1]


def _days_from_month_end(ts: pd.Timestamp) -> Optional[int]:
    """
    Return how many calendar days before (or on) the last day of the month.

    Convention:
      - Last day of month  → 0  (e.g. March 31 → 0)
      - One day before     → 1  (e.g. March 30 → 1)
      - Two days before    → 2  (e.g. March 29 → 2)

    Args:
        ts: A pandas Timestamp.

    Returns:
        Non-negative integer, or None if ts is NaT.
    """
    if pd.isna(ts):
        return None
    last = _month_last_day(ts)
    return last - ts.day


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify_entry(ts: pd.Timestamp) -> Optional[str]:
    """
    Return the period-end risk band for a single posting date.

    Classification (mutually exclusive, most severe wins):
      "High"   — days_from_month_end in {0, 1, 2}  (last 3 days)
      "Medium" — days_from_month_end in {3, 4}     (4th / 5th day from end)
      None     — earlier in the month

    Args:
        ts: A pandas Timestamp representing the posting date.

    Returns:
        "High", "Medium", or None.
    """
    days = _days_from_month_end(ts)
    if days is None:
        return None
    if days <= PERIOD_END_HIGH_DAYS - 1:       # 0, 1, 2
        return "High"
    if days <= PERIOD_END_MEDIUM_DAYS - 1:     # 3, 4
        return "Medium"
    return None


def _is_year_end(ts: pd.Timestamp) -> bool:
    """
    Return True if the posting date falls in the Indian FY year-end window.

    Year-end window: March 29, 30, 31 (Indian financial year closes 31-Mar).

    Args:
        ts: A pandas Timestamp.

    Returns:
        Boolean.
    """
    if pd.isna(ts):
        return False
    return ts.month == _YEAR_END_MONTH and ts.day in _YEAR_END_DAYS


# ---------------------------------------------------------------------------
# Month-wise concentration analysis
# ---------------------------------------------------------------------------

def _month_concentration(
    df_working: pd.DataFrame,
    date_col: str = "_date",
) -> pd.DataFrame:
    """
    Compute per-month statistics: total entries, High-band entries, and
    High-band percentage.

    Args:
        df_working: Working dataframe containing "_date", "_band",
                    and "_year_end" columns added by run().
        date_col:   Internal parsed date column name.

    Returns:
        DataFrame with columns:
          Month_Label   — e.g. "Mar-2025"
          Year_Month    — pd.Period for sorting
          Total_Entries — total entries in that month
          High_Entries  — entries in last-3-days band
          Medium_Entries— entries in 4th–5th day band
          High_Pct      — High_Entries / Total_Entries (%)
          Medium_Pct    — Medium_Entries / Total_Entries (%)
        Sorted chronologically.
    """
    working = df_working.dropna(subset=[date_col]).copy()
    working["_ym"] = working[date_col].dt.to_period("M")

    grp = working.groupby("_ym")

    total  = grp.size().rename("Total_Entries")
    high   = grp["_band"].apply(lambda s: (s == "High").sum()).rename("High_Entries")
    medium = grp["_band"].apply(lambda s: (s == "Medium").sum()).rename("Medium_Entries")

    table = pd.concat([total, high, medium], axis=1).reset_index()
    table["High_Pct"]   = (table["High_Entries"]   / table["Total_Entries"] * 100).round(2)
    table["Medium_Pct"] = (table["Medium_Entries"]  / table["Total_Entries"] * 100).round(2)
    table["Month_Label"] = table["_ym"].dt.strftime("%b-%Y")
    table["Year_Month"]  = table["_ym"]

    return (
        table[["Month_Label", "Year_Month", "Total_Entries",
               "High_Entries", "Medium_Entries", "High_Pct", "Medium_Pct"]]
        .sort_values("Year_Month")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def _build_chart(
    month_table: pd.DataFrame,
    population_count: int,
    flag_count: int,
) -> go.Figure:
    """
    Build a grouped bar chart showing per-month period-end concentration.

    Each month has two bars:
      - KKC Green bar  : High-band entries (last 3 days) as % of month total
      - Orange bar     : Medium-band entries (4th–5th day) as % of month total

    A red dashed reference line marks the 10% High-risk threshold.
    Months that breach the threshold have their High bar coloured red.

    Args:
        month_table:      Output of _month_concentration().
        population_count: Total rows in the input dataframe.
        flag_count:       Total flagged entries.

    Returns:
        Plotly Figure.
    """
    if month_table.empty:
        fig = go.Figure()
        fig.update_layout(title="No date data available for period-end chart.")
        return fig

    months      = month_table["Month_Label"].tolist()
    high_pcts   = month_table["High_Pct"].tolist()
    medium_pcts = month_table["Medium_Pct"].tolist()

    # Colour the High bar red where it exceeds the 10% threshold
    bar_colours = [
        RISK_RED if p > _HIGH_PCT_THRESHOLD * 100 else KKC_GREEN
        for p in high_pcts
    ]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name="Last 3 days (High)",
        x=months,
        y=high_pcts,
        marker_color=bar_colours,
        hovertemplate="%{x}<br>Last 3 days: %{y:.1f}%<extra></extra>",
    ))

    fig.add_trace(go.Bar(
        name="4th–5th day (Medium)",
        x=months,
        y=medium_pcts,
        marker_color=RISK_ORANGE,
        opacity=0.75,
        hovertemplate="%{x}<br>4th–5th day: %{y:.1f}%<extra></extra>",
    ))

    # 10% threshold reference line
    fig.add_hline(
        y=_HIGH_PCT_THRESHOLD * 100,
        line_dash="dot",
        line_color=RISK_RED,
        line_width=1.5,
        annotation_text="10% High threshold",
        annotation_position="top right",
        annotation_font_color=RISK_RED,
    )

    pct_flagged = flag_count / population_count * 100 if population_count else 0
    fig.update_layout(
        barmode="group",
        title=dict(
            text=(
                f"Period-End Entry Concentration  —  "
                f"{flag_count:,} of {population_count:,} entries flagged "
                f"({pct_flagged:.1f}%)"
            ),
            font=dict(size=14),
        ),
        xaxis_title="Month",
        yaxis_title="% of Month's Entries",
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Source Sans Pro, Arial, sans-serif", size=12),
        yaxis=dict(gridcolor=KKC_LIGHT_GREY, ticksuffix="%"),
        margin=dict(t=80, b=60, l=60, r=20),
        bargap=0.2,
        bargroupgap=0.05,
    )

    return fig


# ---------------------------------------------------------------------------
# Risk rating
# ---------------------------------------------------------------------------

def _determine_risk(month_table: pd.DataFrame) -> str:
    """
    Determine module risk rating from the month-wise concentration table.

    Rules (per CLAUDE.md):
      High   — any month where High-band entries > 10% of that month's total
      Medium — any month where combined (High + Medium) entries > 5% of that
               month's total, but no High breach exists
      Low    — all months below 5%

    Args:
        month_table: Output of _month_concentration().

    Returns:
        "High", "Medium", or "Low".
    """
    if month_table.empty:
        return "Low"

    if (month_table["High_Pct"] > _HIGH_PCT_THRESHOLD * 100).any():
        return "High"

    combined_pct = month_table["High_Pct"] + month_table["Medium_Pct"]
    if (combined_pct > _MEDIUM_PCT_THRESHOLD * 100).any():
        return "Medium"

    return "Low"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    df: pd.DataFrame,
    date_col: str = "posting_date",
) -> dict:
    """
    Execute period-end entry concentration analysis on a JE population.

    Classifies each entry by how close its posting_date is to the last day
    of its calendar month:
      High   — last 3 days  (days 0–2 before month-end)
      Medium — 4th–5th day  (days 3–4 before month-end)

    Additionally flags entries in the Indian FY year-end window
    (March 29–31) as "Year-End" regardless of their primary band.

    Computes month-wise concentration statistics and determines an overall
    risk rating based on the worst month observed.

    Args:
        df:       Full population DataFrame with standard column names
                  (output of column_mapper.get_mapped_df()).
        date_col: Column name for posting date. Defaults to "posting_date".

    Returns:
        Standard module result dict:
        {
            "module_name":       str — "Period-End Entry Concentration",
            "flagged_df":        pd.DataFrame — flagged entries with added
                                  columns: PE_Band ("High"/"Medium"),
                                  Days_From_Month_End (int),
                                  Year_End_Flag (bool),
                                  Month_Label (str, e.g. "Mar-2025"),
            "flag_count":        int — High + Medium entries combined,
            "population_count":  int,
            "flag_pct":          float,
            "risk_rating":       str — "High" / "Medium" / "Low",
            "summary_stats":     dict — high_count, medium_count,
                                  year_end_count, month_table (DataFrame),
                                  worst_month (str), worst_month_high_pct (float),
            "chart":             plotly Figure (month-wise concentration bars),
        }

    Raises:
        ValueError: If date_col is not present in df.
    """
    if date_col not in df.columns:
        raise ValueError(
            f"Column '{date_col}' not found in dataframe. "
            f"Available columns: {list(df.columns)}"
        )

    population_count = len(df)
    working = df.copy()

    # ── 1. Parse dates ───────────────────────────────────────────────────────
    working["_date"] = _parse_dates(working[date_col])

    # ── 2. Classify each entry ───────────────────────────────────────────────
    working["_band"]     = working["_date"].apply(_classify_entry)
    working["_year_end"] = working["_date"].apply(_is_year_end)
    working["_days_out"] = working["_date"].apply(_days_from_month_end)

    # ── 3. Month-wise concentration table ────────────────────────────────────
    month_table = _month_concentration(working)

    # ── 4. Risk rating ────────────────────────────────────────────────────────
    risk_rating = _determine_risk(month_table)

    # ── 5. Assemble flagged dataframe ─────────────────────────────────────────
    flagged_mask = working["_band"].notna()
    flagged = working[flagged_mask].copy()

    flagged["PE_Band"]             = flagged["_band"]
    flagged["Days_From_Month_End"] = flagged["_days_out"].astype("Int64")
    flagged["Year_End_Flag"]       = flagged["_year_end"]
    flagged["Month_Label"]         = flagged["_date"].dt.strftime("%b-%Y")

    # Drop internal helper columns
    for tmp in ("_date", "_band", "_year_end", "_days_out"):
        if tmp in flagged.columns:
            flagged.drop(columns=[tmp], inplace=True)

    flag_count = len(flagged)
    flag_pct   = round(flag_count / population_count, 6) if population_count else 0.0

    high_count   = int((flagged["PE_Band"] == "High").sum())
    medium_count = int((flagged["PE_Band"] == "Medium").sum())
    year_end_count = int(flagged["Year_End_Flag"].sum())

    # Worst month by High-band %
    if not month_table.empty:
        worst_idx        = month_table["High_Pct"].idxmax()
        worst_month      = month_table.loc[worst_idx, "Month_Label"]
        worst_month_high_pct = float(month_table.loc[worst_idx, "High_Pct"])
    else:
        worst_month          = None
        worst_month_high_pct = 0.0

    # ── 6. Chart ──────────────────────────────────────────────────────────────
    chart = _build_chart(month_table, population_count, flag_count)

    summary_stats = {
        "high_count":           high_count,
        "medium_count":         medium_count,
        "year_end_count":       year_end_count,
        "month_table":          month_table,
        "worst_month":          worst_month,
        "worst_month_high_pct": worst_month_high_pct,
        "high_threshold_pct":   _HIGH_PCT_THRESHOLD * 100,
        "medium_threshold_pct": _MEDIUM_PCT_THRESHOLD * 100,
    }

    return {
        "module_name":      "Period-End Entry Concentration",
        "flagged_df":       flagged,
        "flag_count":       flag_count,
        "population_count": population_count,
        "flag_pct":         flag_pct,
        "risk_rating":      risk_rating,
        "summary_stats":    summary_stats,
        "chart":            chart,
    }

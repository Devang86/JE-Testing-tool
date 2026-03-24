"""
modules/after_hours.py
----------------------
Module 4: After-Hours & Weekend Posting Detection for the KKC JE Testing Tool.

SA Reference: SA 240.A35

Journal entries posted outside normal business hours or on weekends and
public holidays warrant attention because:
  - They may bypass normal authorisation workflows (supervisors absent)
  - They can indicate backdated or fabricated entries
  - Legitimate business rarely requires GL postings at 2 AM on a Sunday

Three flag categories (a single entry can trigger more than one):

  Weekend       — posting_date falls on Saturday (weekday=5) or Sunday (weekday=6)
  After Hours   — entry_time falls outside BUSINESS_HOURS_START–BUSINESS_HOURS_END
                  (default 09:00–19:00).  Skipped gracefully if entry_time absent.
  Holiday       — posting_date falls on a date in the optional holiday list.
                  Skipped gracefully if no holiday list is provided.

Sub-analysis: the top-10 users by after-hours/weekend entry count are
identified to highlight individuals who post disproportionately outside
normal hours — a segregation-of-duties signal.

Risk Rating (per CLAUDE.md):
  High   — flagged entries > 5% of population
  Medium — flagged entries 2–5%
  Low    — flagged entries < 2%
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from typing import Optional

try:
    from config import (
        BUSINESS_HOURS_START,
        BUSINESS_HOURS_END,
        RISK_HIGH,
        KKC_GREEN,
        KKC_GREY,
        KKC_LIGHT_GREY,
        RISK_RED,
        RISK_ORANGE,
    )
except ImportError:
    BUSINESS_HOURS_START = 9
    BUSINESS_HOURS_END   = 19
    RISK_HIGH            = 0.05
    KKC_GREEN            = "#7CB542"
    KKC_GREY             = "#808285"
    KKC_LIGHT_GREY       = "#F2F2F2"
    RISK_RED             = "#FF0000"
    RISK_ORANGE          = "#FFA500"

# Medium risk threshold (2 %)
_RISK_MEDIUM_THRESHOLD = 0.02


# ---------------------------------------------------------------------------
# Date / time parsing helpers
# ---------------------------------------------------------------------------

def _parse_dates(series: pd.Series) -> pd.Series:
    """
    Coerce a date-like column to pandas Timestamps (date-normalised).

    Handles string dates, Python date objects, and mixed types.
    Unparseable values become NaT.

    Args:
        series: Raw posting_date column from the uploaded dataframe.

    Returns:
        Series of Timestamps normalised to midnight (time component stripped).
    """
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def _parse_times(series: pd.Series) -> pd.Series:
    """
    Coerce a time-like column to a Series of pandas Timedelta (time-of-day).

    Accepts several common formats produced by GL exports:
      - "HH:MM:SS"  (most common)
      - "HH:MM"
      - Full datetime strings — time component extracted
      - datetime.time objects

    Unparseable values become NaT.

    Args:
        series: Raw entry_time column from the uploaded dataframe.

    Returns:
        Series of Timedelta representing the time-of-day, or NaT.
    """
    def _to_td(val):
        if pd.isna(val):
            return pd.NaT
        if hasattr(val, "hour"):
            # datetime.time or datetime.datetime
            return pd.Timedelta(hours=val.hour, minutes=val.minute,
                                seconds=getattr(val, "second", 0))
        s = str(val).strip()
        # Try parsing as a full datetime string first
        try:
            dt = pd.to_datetime(s, errors="raise")
            return pd.Timedelta(hours=dt.hour, minutes=dt.minute,
                                seconds=dt.second)
        except Exception:
            pass
        # Try HH:MM:SS or HH:MM
        parts = s.split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            sec = int(parts[2]) if len(parts) > 2 else 0
            return pd.Timedelta(hours=h, minutes=m, seconds=sec)
        except (ValueError, IndexError):
            return pd.NaT

    return series.apply(_to_td)


def _parse_holidays(holiday_dates) -> set:
    """
    Normalise a collection of holiday dates to a set of date strings (YYYY-MM-DD).

    Accepts:
      - list / array of date strings or datetime objects
      - pandas Series
      - None or empty → returns empty set

    Args:
        holiday_dates: Collection of holiday date values, or None.

    Returns:
        Set of date strings in "YYYY-MM-DD" format.
    """
    if holiday_dates is None:
        return set()
    parsed = pd.to_datetime(pd.Series(list(holiday_dates)), errors="coerce").dropna()
    return set(parsed.dt.strftime("%Y-%m-%d").tolist())


# ---------------------------------------------------------------------------
# Flag detectors
# ---------------------------------------------------------------------------

def _flag_weekends(dates: pd.Series) -> pd.Series:
    """
    Return a boolean mask for entries whose posting_date falls on a weekend.

    Saturday = weekday 5, Sunday = weekday 6 (pandas convention).
    NaT values are treated as False (not flagged).

    Args:
        dates: Series of Timestamps (output of _parse_dates).

    Returns:
        Boolean Series aligned to the input index.
    """
    return dates.dt.dayofweek.isin([5, 6]).fillna(False)


def _flag_after_hours(times: pd.Series) -> pd.Series:
    """
    Return a boolean mask for entries posted outside business hours.

    Business hours are defined by BUSINESS_HOURS_START (inclusive) and
    BUSINESS_HOURS_END (exclusive) in config.py.  An entry at exactly
    BUSINESS_HOURS_END (19:00:00) is treated as after-hours.

    NaT values are treated as False.

    Args:
        times: Series of Timedelta (output of _parse_times).

    Returns:
        Boolean Series aligned to the input index.
    """
    start = pd.Timedelta(hours=BUSINESS_HOURS_START)
    end   = pd.Timedelta(hours=BUSINESS_HOURS_END)
    valid = times.notna()
    return valid & ((times < start) | (times >= end))


def _flag_holidays(dates: pd.Series, holiday_set: set) -> pd.Series:
    """
    Return a boolean mask for entries whose posting_date is in the holiday set.

    Args:
        dates:       Series of Timestamps (output of _parse_dates).
        holiday_set: Set of "YYYY-MM-DD" strings from _parse_holidays.

    Returns:
        Boolean Series aligned to the input index.
    """
    if not holiday_set:
        return pd.Series(False, index=dates.index)
    date_strs = dates.dt.strftime("%Y-%m-%d")
    return date_strs.isin(holiday_set)


# ---------------------------------------------------------------------------
# User sub-analysis
# ---------------------------------------------------------------------------

def _build_user_table(
    flagged: pd.DataFrame,
    prepared_by_col: Optional[str],
) -> pd.DataFrame:
    """
    Build a frequency table of the top-10 users by after-hours entry count.

    Includes each user's count of flagged entries, percentage of all flagged
    entries, and the breakdown by flag type (Weekend / After Hours / Holiday).

    Args:
        flagged:         DataFrame of flagged entries with an "AH_Flag_Type" column.
        prepared_by_col: Name of the prepared_by column, or None if not mapped.

    Returns:
        DataFrame with columns: User, Flagged_Count, Pct_of_Flagged,
        Weekend_Count, AfterHours_Count, Holiday_Count.
        Empty DataFrame if prepared_by_col is absent.
    """
    if prepared_by_col is None or prepared_by_col not in flagged.columns:
        return pd.DataFrame()

    total_flagged = len(flagged)
    if total_flagged == 0:
        return pd.DataFrame()

    grp = flagged.groupby(prepared_by_col, dropna=False)

    user_counts = grp.size().rename("Flagged_Count")
    weekend_cnt = grp["AH_Flag_Type"].apply(
        lambda s: s.str.contains("Weekend").sum()
    ).rename("Weekend_Count")
    ah_cnt = grp["AH_Flag_Type"].apply(
        lambda s: s.str.contains("After Hours").sum()
    ).rename("AfterHours_Count")
    hol_cnt = grp["AH_Flag_Type"].apply(
        lambda s: s.str.contains("Holiday").sum()
    ).rename("Holiday_Count")

    table = pd.concat([user_counts, weekend_cnt, ah_cnt, hol_cnt], axis=1).reset_index()
    table.rename(columns={prepared_by_col: "User"}, inplace=True)
    table["Pct_of_Flagged"] = (
        (table["Flagged_Count"] / total_flagged * 100).round(1)
    )
    table = table.sort_values("Flagged_Count", ascending=False).head(10).reset_index(drop=True)
    return table[["User", "Flagged_Count", "Pct_of_Flagged",
                  "Weekend_Count", "AfterHours_Count", "Holiday_Count"]]


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def _build_chart(
    flagged: pd.DataFrame,
    population_count: int,
    user_table: pd.DataFrame,
) -> go.Figure:
    """
    Build a two-panel Plotly figure:
      Left  — Stacked bar: Weekend / After Hours / Holiday vs total population.
      Right — Horizontal bar: top-10 users by flagged entry count (if available).

    Args:
        flagged:          DataFrame of flagged entries with "AH_Flag_Type".
        population_count: Total rows in the full population.
        user_table:       Output of _build_user_table().

    Returns:
        Plotly Figure object.
    """
    flag_type_col = "AH_Flag_Type"
    total_flagged = len(flagged)
    unflagged     = population_count - total_flagged

    # Count each flag category (an entry may appear in multiple)
    weekend_cnt = int(flagged[flag_type_col].str.contains("Weekend").sum())
    ah_cnt      = int(flagged[flag_type_col].str.contains("After Hours").sum())
    hol_cnt     = int(flagged[flag_type_col].str.contains("Holiday").sum())

    has_users = not user_table.empty

    cols = 2 if has_users else 1
    specs = [[{"type": "bar"}, {"type": "bar"}]] if has_users else [[{"type": "bar"}]]
    subplot_titles = (
        ["Entry Distribution", "Top Users by Flagged Count"]
        if has_users else ["Entry Distribution"]
    )

    from plotly.subplots import make_subplots
    fig = make_subplots(rows=1, cols=cols, subplot_titles=subplot_titles)

    # ── Left panel: stacked population bar ──────────────────────────────────
    for label, count, colour in [
        ("Weekend",     weekend_cnt, RISK_ORANGE),
        ("After Hours", ah_cnt,      RISK_RED),
        ("Holiday",     hol_cnt,     "#9B59B6"),
        ("Not Flagged", unflagged,   KKC_LIGHT_GREY),
    ]:
        fig.add_trace(
            go.Bar(
                name=label,
                x=["Journal Entries"],
                y=[count],
                marker_color=colour,
                marker_line_color=KKC_GREY,
                marker_line_width=0.4,
                text=[str(count) if count > 0 else ""],
                textposition="inside",
                hovertemplate=f"{label}: {count}<extra></extra>",
            ),
            row=1, col=1,
        )

    # ── Right panel: top-users horizontal bar ───────────────────────────────
    if has_users:
        top = user_table.head(10)
        fig.add_trace(
            go.Bar(
                name="Flagged Entries",
                x=top["Flagged_Count"],
                y=top["User"].astype(str),
                orientation="h",
                marker_color=KKC_GREEN,
                hovertemplate="%{y}: %{x} flagged entries<extra></extra>",
                showlegend=False,
            ),
            row=1, col=2,
        )
        fig.update_yaxes(autorange="reversed", row=1, col=2)
        fig.update_xaxes(title_text="Flagged Entries", row=1, col=2)

    pct = total_flagged / population_count * 100 if population_count else 0
    fig.update_layout(
        barmode="stack",
        title=dict(
            text=(
                f"After-Hours & Weekend Analysis  —  "
                f"{total_flagged:,} of {population_count:,} entries flagged "
                f"({pct:.1f}%)"
            ),
            font=dict(size=14),
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Source Sans Pro, Arial, sans-serif", size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.06,
                    xanchor="right", x=1),
        margin=dict(t=100, b=40, l=60, r=20),
    )
    fig.update_yaxes(gridcolor=KKC_LIGHT_GREY, row=1, col=1)

    return fig


# ---------------------------------------------------------------------------
# Risk rating
# ---------------------------------------------------------------------------

def _determine_risk(flag_pct: float) -> str:
    """
    Map the overall flag percentage to a risk rating per CLAUDE.md.

    Args:
        flag_pct: Fraction of population flagged (0.0 – 1.0).

    Returns:
        "High"   if flag_pct > 5%
        "Medium" if flag_pct > 2% and <= 5%
        "Low"    if flag_pct <= 2%
    """
    if flag_pct > RISK_HIGH:
        return "High"
    if flag_pct > _RISK_MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    df: pd.DataFrame,
    date_col: str           = "posting_date",
    time_col: str           = "entry_time",
    prepared_by_col: str    = "prepared_by",
    holiday_dates           = None,
) -> dict:
    """
    Execute after-hours and weekend posting detection on a JE population.

    Flags entries whose posting_date is a weekend or public holiday, and
    entries whose entry_time falls outside business hours (if time data
    is available).  A per-user frequency table identifies the top-10
    users by number of after-hours entries.

    All three checks degrade gracefully:
      - entry_time absent   → after-hours check skipped (noted in summary_stats)
      - holiday_dates None  → holiday check skipped
      - prepared_by absent  → user table empty

    Args:
        df:              Full population DataFrame with standard column names.
        date_col:        Column name for posting date. Defaults to "posting_date".
        time_col:        Column name for entry time. Defaults to "entry_time".
        prepared_by_col: Column name for the posting user. Defaults to "prepared_by".
        holiday_dates:   Optional iterable of holiday dates (strings, date objects,
                         or a pandas Series).  Dates in any parseable format are
                         accepted.

    Returns:
        Standard module result dict:
        {
            "module_name":       str — "After-Hours & Weekend Postings",
            "flagged_df":        pd.DataFrame — flagged entries with added
                                  columns: AH_Flag_Type (pipe-separated),
                                  Day_of_Week, Entry_Hour (if time available),
            "flag_count":        int,
            "population_count":  int,
            "flag_pct":          float,
            "risk_rating":       str — "High" / "Medium" / "Low",
            "summary_stats":     dict — weekend_count, after_hours_count,
                                  holiday_count, user_table (DataFrame),
                                  time_check_skipped (bool),
                                  holiday_check_skipped (bool),
                                  business_hours (str),
            "chart":             plotly Figure,
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

    # ── 2. Parse times (optional) ────────────────────────────────────────────
    time_available = time_col in working.columns
    if time_available:
        working["_time"] = _parse_times(working[time_col])

    # ── 3. Parse holidays (optional) ─────────────────────────────────────────
    holiday_set       = _parse_holidays(holiday_dates)
    holiday_available = len(holiday_set) > 0

    # ── 4. Run detectors ─────────────────────────────────────────────────────
    mask_weekend  = _flag_weekends(working["_date"])
    mask_ah       = _flag_after_hours(working["_time"]) if time_available \
                    else pd.Series(False, index=working.index)
    mask_holiday  = _flag_holidays(working["_date"], holiday_set)

    any_flag = mask_weekend | mask_ah | mask_holiday

    # ── 5. Build pipe-separated flag-type label ───────────────────────────────
    flag_labels = pd.Series("", index=working.index)
    for mask, label in [
        (mask_weekend, "Weekend"),
        (mask_ah,      "After Hours"),
        (mask_holiday, "Holiday"),
    ]:
        flag_labels[mask] = flag_labels[mask].apply(
            lambda x, lbl=label: x + (lbl if x == "" else f" | {lbl}")
        )

    # ── 6. Assemble flagged dataframe ─────────────────────────────────────────
    flagged = working[any_flag].copy()
    flagged["AH_Flag_Type"] = flag_labels[any_flag]

    # Convenience columns for the Excel workpaper
    flagged["Day_of_Week"] = flagged["_date"].dt.day_name()
    if time_available:
        valid_times = flagged["_time"].notna()
        flagged["Entry_Hour"] = pd.NA
        flagged.loc[valid_times, "Entry_Hour"] = (
            flagged.loc[valid_times, "_time"]
            .apply(lambda td: f"{int(td.total_seconds() // 3600):02d}:00")
        )

    # Drop internal parse columns
    for tmp in ("_date", "_time"):
        if tmp in flagged.columns:
            flagged.drop(columns=[tmp], inplace=True)

    # ── 7. User sub-analysis ──────────────────────────────────────────────────
    actual_by_col = prepared_by_col if prepared_by_col in flagged.columns else None
    user_table    = _build_user_table(flagged, actual_by_col)

    # ── 8. Metrics ────────────────────────────────────────────────────────────
    flag_count    = int(any_flag.sum())
    flag_pct      = round(flag_count / population_count, 6) if population_count else 0.0
    risk_rating   = _determine_risk(flag_pct)

    weekend_count  = int(mask_weekend.sum())
    after_hrs_count = int(mask_ah.sum())
    holiday_count  = int(mask_holiday.sum())

    # ── 9. Chart ──────────────────────────────────────────────────────────────
    chart = _build_chart(flagged, population_count, user_table)

    # ── 10. Summary stats ────────────────────────────────────────────────────
    summary_stats = {
        "weekend_count":        weekend_count,
        "after_hours_count":    after_hrs_count,
        "holiday_count":        holiday_count,
        "time_check_skipped":   not time_available,
        "holiday_check_skipped": not holiday_available,
        "business_hours":       (
            f"{BUSINESS_HOURS_START:02d}:00 – {BUSINESS_HOURS_END:02d}:00"
        ),
        "user_table":           user_table,
    }

    return {
        "module_name":      "After-Hours & Weekend Postings",
        "flagged_df":       flagged,
        "flag_count":       flag_count,
        "population_count": population_count,
        "flag_pct":         flag_pct,
        "risk_rating":      risk_rating,
        "summary_stats":    summary_stats,
        "chart":            chart,
    }

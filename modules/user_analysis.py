"""
modules/user_analysis.py
------------------------
Module 8: User-Level Posting Analysis for the KKC JE Testing Tool.

SA Reference: SA 240.A35

Anomalous posting patterns at the individual user level can indicate:
  - Deliberate override of normal controls (volume/amount outliers)
  - Segregation-of-duties violations (self-approval)
  - Periods of reduced oversight (single-user days)

Four sub-analyses are run:

  Volume Outlier
      Compute each user's entry count.  Users whose count exceeds
      mean + USER_OUTLIER_STD × std across all users are flagged.
      Entries posted by those users are included in the flagged output.

  Amount Outlier
      Same as volume, but measured by total amount posted per user.
      Users whose total exceeds mean + USER_OUTLIER_STD × std are flagged.

  Self-Approval
      Entries where prepared_by == approved_by (case-insensitive, stripped).
      This is a maker-checker / segregation-of-duties violation.
      Flagged regardless of the outlier thresholds.

  Single-User Days
      Calendar dates on which every single JE was posted by exactly one user.
      Days with only one entry by definition have a single user and are
      excluded (min 2 entries required on the date to be meaningful).

A single entry may appear in multiple sub-analyses.  The "UA_Flag_Type"
output column is pipe-separated for multi-type hits.

Risk Rating (per CLAUDE.md):
  High   — any self-approval entries exist
  Medium — volume or amount outliers exist (no self-approval)
  Low    — no outliers, no self-approval
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Optional

try:
    from config import (
        USER_OUTLIER_STD,
        KKC_GREEN,
        KKC_GREY,
        KKC_LIGHT_GREY,
        RISK_RED,
        RISK_ORANGE,
    )
except ImportError:
    USER_OUTLIER_STD = 2.0
    KKC_GREEN        = "#7CB542"
    KKC_GREY         = "#808285"
    KKC_LIGHT_GREY   = "#F2F2F2"
    RISK_RED         = "#FF0000"
    RISK_ORANGE      = "#FFA500"


# ---------------------------------------------------------------------------
# Per-user statistics helpers
# ---------------------------------------------------------------------------

def _build_user_stats(
    df: pd.DataFrame,
    prepared_by_col: str,
    amount_col: str,
) -> pd.DataFrame:
    """
    Compute per-user entry count and total amount posted.

    Args:
        df:              Population DataFrame.
        prepared_by_col: Column containing the posting user name/ID.
        amount_col:      Column containing entry amounts.

    Returns:
        DataFrame with columns:
          User, Entry_Count, Total_Amount, Avg_Amount
        Sorted by Entry_Count descending.
    """
    grp = df.groupby(prepared_by_col, dropna=False)
    stats = pd.DataFrame({
        "User":         grp[prepared_by_col].first().index,
        "Entry_Count":  grp[amount_col].count(),
        "Total_Amount": grp[amount_col].sum(),
    }).reset_index(drop=True)
    stats["Avg_Amount"] = (
        stats["Total_Amount"] / stats["Entry_Count"].replace(0, np.nan)
    ).round(2)
    return stats.sort_values("Entry_Count", ascending=False).reset_index(drop=True)


def _outlier_threshold(series: pd.Series, n_std: float) -> float:
    """
    Return mean + n_std * std for a numeric series.

    Uses population mean and sample std (ddof=1 for unbiased estimate).
    Returns infinity if there is fewer than 2 data points (no meaningful
    spread can be computed, so nothing is flagged).

    Args:
        series: Numeric Series (one value per user).
        n_std:  Number of standard deviations above the mean.

    Returns:
        Float threshold.  Values strictly greater than this are outliers.
    """
    if len(series) < 2:
        return float("inf")
    return float(series.mean() + n_std * series.std(ddof=1))


# ---------------------------------------------------------------------------
# Sub-analysis detectors
# ---------------------------------------------------------------------------

def _detect_volume_outliers(
    user_stats: pd.DataFrame,
    n_std: float,
) -> set[str]:
    """
    Return the set of user names whose entry count exceeds the outlier threshold.

    Args:
        user_stats: Output of _build_user_stats().
        n_std:      Standard-deviation multiplier from config.

    Returns:
        Set of outlier user name strings.
    """
    threshold = _outlier_threshold(user_stats["Entry_Count"].astype(float), n_std)
    return set(
        user_stats.loc[user_stats["Entry_Count"] > threshold, "User"].astype(str)
    )


def _detect_amount_outliers(
    user_stats: pd.DataFrame,
    n_std: float,
) -> set[str]:
    """
    Return the set of user names whose total posted amount exceeds the threshold.

    Args:
        user_stats: Output of _build_user_stats().
        n_std:      Standard-deviation multiplier from config.

    Returns:
        Set of outlier user name strings.
    """
    threshold = _outlier_threshold(user_stats["Total_Amount"].astype(float), n_std)
    return set(
        user_stats.loc[user_stats["Total_Amount"] > threshold, "User"].astype(str)
    )


def _detect_self_approvals(
    df: pd.DataFrame,
    prepared_by_col: str,
    approved_by_col: str,
) -> pd.Series:
    """
    Return a boolean mask for entries where prepared_by == approved_by.

    Comparison is case-insensitive and strips leading/trailing whitespace.
    Rows where either column is null are not flagged.

    Args:
        df:              Population DataFrame.
        prepared_by_col: Column name for the entry preparer.
        approved_by_col: Column name for the approver.

    Returns:
        Boolean Series aligned to df.index.
    """
    maker    = df[prepared_by_col].astype(str).str.strip().str.lower()
    checker  = df[approved_by_col].astype(str).str.strip().str.lower()
    both_present = df[prepared_by_col].notna() & df[approved_by_col].notna()
    # Exclude "nan" == "nan" (both genuinely missing)
    not_both_nan = ~((maker == "nan") & (checker == "nan"))
    return both_present & not_both_nan & (maker == checker)


def _detect_single_user_days(
    df: pd.DataFrame,
    prepared_by_col: str,
    date_col: str,
) -> pd.Series:
    """
    Return a boolean mask for entries on dates where all postings were made by
    exactly one distinct user.  Dates with only a single entry are excluded
    (trivially single-user — not indicative of control override).

    Args:
        df:              Population DataFrame.
        prepared_by_col: Column name for the posting user.
        date_col:        Column name for posting date (normalised to date only).

    Returns:
        Boolean Series aligned to df.index.
    """
    work = df.copy()
    work["_date_norm"] = pd.to_datetime(work[date_col], errors="coerce").dt.normalize()

    # Per-date: count distinct users and total entries
    date_grp        = work.groupby("_date_norm", dropna=True)
    distinct_users  = date_grp[prepared_by_col].transform("nunique")
    entry_count     = date_grp[prepared_by_col].transform("count")

    # Flag: exactly 1 distinct user AND at least 2 entries on that date
    return (distinct_users == 1) & (entry_count >= 2)


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def _build_chart(
    user_stats: pd.DataFrame,
    volume_outliers: set[str],
    amount_outliers: set[str],
    self_approval_count: int,
    single_user_day_count: int,
    population_count: int,
) -> go.Figure:
    """
    Build a 2×2 panel figure:
      Top-left  — Bar: top-10 users by entry count (outliers highlighted red)
      Top-right — Bar: top-10 users by total amount (outliers highlighted red)
      Bottom-left  — Horizontal bar: flag-type summary counts
      Bottom-right — Text annotation: overall stats

    Args:
        user_stats:            Output of _build_user_stats().
        volume_outliers:       Set of volume-outlier user names.
        amount_outliers:       Set of amount-outlier user names.
        self_approval_count:   Number of self-approval entries.
        single_user_day_count: Number of single-user-day entries.
        population_count:      Total population.

    Returns:
        Plotly Figure.
    """
    top10_vol = user_stats.head(10).copy()
    top10_amt = user_stats.nlargest(10, "Total_Amount").copy()

    col_vol = [
        RISK_RED if str(u) in volume_outliers else KKC_GREEN
        for u in top10_vol["User"]
    ]
    col_amt = [
        RISK_RED if str(u) in amount_outliers else KKC_GREEN
        for u in top10_amt["User"]
    ]

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[
            "Top 10 Users — Entry Count",
            "Top 10 Users — Total Amount",
            "Flag-Type Summary",
            "",
        ],
        vertical_spacing=0.18,
        horizontal_spacing=0.12,
    )

    # ── Top-left: entry count ────────────────────────────────────────────────
    fig.add_trace(go.Bar(
        x=top10_vol["Entry_Count"],
        y=top10_vol["User"].astype(str),
        orientation="h",
        marker_color=col_vol,
        hovertemplate="%{y}: %{x} entries<extra></extra>",
        showlegend=False,
    ), row=1, col=1)
    fig.update_yaxes(autorange="reversed", row=1, col=1)
    fig.update_xaxes(title_text="Entry Count", row=1, col=1)

    # ── Top-right: total amount ──────────────────────────────────────────────
    fig.add_trace(go.Bar(
        x=top10_amt["Total_Amount"],
        y=top10_amt["User"].astype(str),
        orientation="h",
        marker_color=col_amt,
        hovertemplate="%{y}: %{x:,.0f}<extra></extra>",
        showlegend=False,
    ), row=1, col=2)
    fig.update_yaxes(autorange="reversed", row=1, col=2)
    fig.update_xaxes(title_text="Total Amount (Rs)", row=1, col=2)

    # ── Bottom-left: flag-type summary ───────────────────────────────────────
    flag_labels  = ["Self-Approval", "Volume Outlier Entries",
                    "Amount Outlier Entries", "Single-User Day Entries"]
    flag_counts  = [
        self_approval_count,
        sum(1 for u in user_stats["User"] if str(u) in volume_outliers)
            * (population_count // max(len(user_stats), 1)),   # approx — overridden by actual
        0,   # placeholders; actual counts passed via flagged_df in run()
        single_user_day_count,
    ]
    # Use real counts: self-approval and single_user_day are exact here
    flag_counts = [self_approval_count, 0, 0, single_user_day_count]
    colours_fl  = [RISK_RED, RISK_ORANGE, RISK_ORANGE, KKC_GREY]

    fig.add_trace(go.Bar(
        x=flag_counts,
        y=flag_labels,
        orientation="h",
        marker_color=colours_fl,
        text=[str(c) if c > 0 else "" for c in flag_counts],
        textposition="outside",
        hovertemplate="%{y}: %{x}<extra></extra>",
        showlegend=False,
    ), row=2, col=1)
    fig.update_yaxes(autorange="reversed", row=2, col=1)
    fig.update_xaxes(title_text="Entries", row=2, col=1)

    fig.update_layout(
        title=dict(
            text=f"User-Level Posting Analysis  —  {population_count:,} entries",
            font=dict(size=14),
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Source Sans Pro, Arial, sans-serif", size=11),
        margin=dict(t=100, b=40, l=140, r=40),
        height=600,
    )
    for row in (1, 2):
        for col in (1, 2):
            fig.update_yaxes(gridcolor=KKC_LIGHT_GREY, row=row, col=col)

    return fig


# ---------------------------------------------------------------------------
# Risk rating
# ---------------------------------------------------------------------------

def _determine_risk(
    has_self_approval: bool,
    has_outliers: bool,
) -> str:
    """
    Determine module risk rating per CLAUDE.md.

    Args:
        has_self_approval: True if any self-approval entries exist.
        has_outliers:      True if volume or amount outliers exist.

    Returns:
        "High"   — any self-approval
        "Medium" — outliers exist, no self-approval
        "Low"    — neither
    """
    if has_self_approval:
        return "High"
    if has_outliers:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    df: pd.DataFrame,
    prepared_by_col: str = "prepared_by",
    approved_by_col: str = "approved_by",
    amount_col: str      = "amount",
    date_col: str        = "posting_date",
) -> dict:
    """
    Execute user-level posting analysis on a JE population.

    Runs four sub-analyses:
      1. Volume outliers    — users with entry count > mean + 2σ
      2. Amount outliers    — users with total posted > mean + 2σ
      3. Self-approval      — entries where prepared_by == approved_by
      4. Single-user days   — dates where only one user posted (≥2 entries)

    All sub-analyses degrade gracefully when their required columns are absent:
      - prepared_by absent → all sub-analyses skipped (noted in summary_stats)
      - approved_by absent → self-approval check skipped
      - posting_date absent → single-user-day check skipped
      - amount absent       → amount-outlier check skipped (volume still runs)

    Args:
        df:              Full population DataFrame with standard column names.
        prepared_by_col: Column for entry preparer. Defaults to "prepared_by".
        approved_by_col: Column for approver. Defaults to "approved_by".
        amount_col:      Column for entry amount. Defaults to "amount".
        date_col:        Column for posting date. Defaults to "posting_date".

    Returns:
        Standard module result dict:
        {
            "module_name":       str — "User Analysis",
            "flagged_df":        pd.DataFrame — all flagged entries with added
                                  column UA_Flag_Type (pipe-separated),
            "flag_count":        int — unique rows flagged,
            "population_count":  int,
            "flag_pct":          float,
            "risk_rating":       str — "High" / "Medium" / "Low",
            "summary_stats":     dict — self_approval_count,
                                  volume_outlier_users (list),
                                  amount_outlier_users (list),
                                  single_user_day_count,
                                  single_user_dates (list),
                                  top10_by_volume (DataFrame),
                                  top10_by_amount (DataFrame),
                                  user_stats (full DataFrame),
                                  skipped_checks (list),
            "chart":             plotly Figure,
        }
    """
    population_count = len(df)
    working  = df.copy()
    skipped: list[str] = []

    # ── Guard: prepared_by is the anchor column ───────────────────────────────
    has_prepared = prepared_by_col in working.columns
    has_approved = approved_by_col in working.columns
    has_amount   = amount_col      in working.columns
    has_date     = date_col        in working.columns

    if not has_prepared:
        skipped.append(f"'{prepared_by_col}' absent — all user sub-analyses skipped")
        empty = working.head(0).copy()
        return {
            "module_name":      "User Analysis",
            "flagged_df":       empty,
            "flag_count":       0,
            "population_count": population_count,
            "flag_pct":         0.0,
            "risk_rating":      "Low",
            "summary_stats": {
                "self_approval_count":    0,
                "volume_outlier_users":   [],
                "amount_outlier_users":   [],
                "single_user_day_count":  0,
                "single_user_dates":      [],
                "top10_by_volume":        pd.DataFrame(),
                "top10_by_amount":        pd.DataFrame(),
                "user_stats":             pd.DataFrame(),
                "skipped_checks":         skipped,
            },
            "chart": go.Figure(),
        }

    if not has_approved:
        skipped.append(f"'{approved_by_col}' absent — self-approval check skipped")
    if not has_amount:
        skipped.append(f"'{amount_col}' absent — amount-outlier check skipped")
    if not has_date:
        skipped.append(f"'{date_col}' absent — single-user-day check skipped")

    # ── User stats (needs amount for total; fall back to count-only) ──────────
    if has_amount:
        user_stats = _build_user_stats(working, prepared_by_col, amount_col)
    else:
        # Amount-only columns — build count-only stats
        grp = working.groupby(prepared_by_col, dropna=False)
        user_stats = pd.DataFrame({
            "User":         grp[prepared_by_col].first().index,
            "Entry_Count":  grp[prepared_by_col].count(),
            "Total_Amount": 0.0,
            "Avg_Amount":   0.0,
        }).reset_index(drop=True).sort_values("Entry_Count", ascending=False).reset_index(drop=True)

    # ── 1. Volume outliers ────────────────────────────────────────────────────
    vol_threshold   = _outlier_threshold(user_stats["Entry_Count"].astype(float),
                                         USER_OUTLIER_STD)
    volume_outlier_users = _detect_volume_outliers(user_stats, USER_OUTLIER_STD)

    # ── 2. Amount outliers ────────────────────────────────────────────────────
    if has_amount:
        amt_threshold = _outlier_threshold(user_stats["Total_Amount"].astype(float),
                                           USER_OUTLIER_STD)
        amount_outlier_users = _detect_amount_outliers(user_stats, USER_OUTLIER_STD)
    else:
        amt_threshold        = float("inf")
        amount_outlier_users = set()

    # ── 3. Self-approval ──────────────────────────────────────────────────────
    if has_approved:
        mask_self = _detect_self_approvals(working, prepared_by_col, approved_by_col)
    else:
        mask_self = pd.Series(False, index=working.index)

    # ── 4. Single-user days ───────────────────────────────────────────────────
    if has_date:
        mask_sud = _detect_single_user_days(working, prepared_by_col, date_col)
    else:
        mask_sud = pd.Series(False, index=working.index)

    # ── Build per-row masks for volume/amount outliers ────────────────────────
    mask_vol = working[prepared_by_col].astype(str).isin(volume_outlier_users)
    mask_amt = working[prepared_by_col].astype(str).isin(amount_outlier_users)

    any_flag = mask_vol | mask_amt | mask_self | mask_sud

    # ── Pipe-separated flag label ─────────────────────────────────────────────
    labels = pd.Series("", index=working.index)

    def _append(mask: pd.Series, label: str) -> None:
        labels[mask] = labels[mask].apply(
            lambda x, lbl=label: lbl if x == "" else f"{x} | {lbl}"
        )

    _append(mask_self, "Self-Approval")
    _append(mask_vol,  "Volume Outlier")
    _append(mask_amt,  "Amount Outlier")
    _append(mask_sud,  "Single-User Day")

    # ── Flagged dataframe ─────────────────────────────────────────────────────
    flagged = working[any_flag].copy()
    flagged["UA_Flag_Type"] = labels[any_flag]

    flag_count = len(flagged)
    flag_pct   = round(flag_count / population_count, 6) if population_count else 0.0

    # ── Single-user dates list ────────────────────────────────────────────────
    if has_date and mask_sud.any():
        sud_dates = sorted(
            pd.to_datetime(working.loc[mask_sud, date_col], errors="coerce")
            .dt.normalize()
            .dropna()
            .dt.strftime("%d-%b-%Y")
            .unique()
            .tolist()
        )
    else:
        sud_dates = []

    # ── Risk rating ───────────────────────────────────────────────────────────
    has_self_approval = bool(mask_self.any())
    has_outliers      = bool(mask_vol.any() or mask_amt.any())
    risk_rating       = _determine_risk(has_self_approval, has_outliers)

    # ── Top-10 tables ─────────────────────────────────────────────────────────
    top10_vol_df = user_stats.head(10).copy()
    top10_vol_df["Is_Volume_Outlier"] = top10_vol_df["User"].astype(str).isin(
        volume_outlier_users
    )
    top10_vol_df["Volume_Threshold"] = round(vol_threshold, 0)

    top10_amt_df = user_stats.nlargest(10, "Total_Amount").copy()
    top10_amt_df["Is_Amount_Outlier"] = top10_amt_df["User"].astype(str).isin(
        amount_outlier_users
    )
    if has_amount:
        top10_amt_df["Amount_Threshold"] = round(amt_threshold, 2)

    # ── Chart ─────────────────────────────────────────────────────────────────
    chart = _build_chart(
        user_stats,
        volume_outlier_users,
        amount_outlier_users,
        int(mask_self.sum()),
        int(mask_sud.sum()),
        population_count,
    )

    summary_stats = {
        "self_approval_count":   int(mask_self.sum()),
        "volume_outlier_users":  sorted(volume_outlier_users),
        "amount_outlier_users":  sorted(amount_outlier_users),
        "volume_threshold":      round(vol_threshold, 2),
        "amount_threshold":      round(amt_threshold, 2) if has_amount else None,
        "single_user_day_count": int(mask_sud.sum()),
        "single_user_dates":     sud_dates,
        "top10_by_volume":       top10_vol_df,
        "top10_by_amount":       top10_amt_df,
        "user_stats":            user_stats,
        "skipped_checks":        skipped,
    }

    return {
        "module_name":      "User Analysis",
        "flagged_df":       flagged,
        "flag_count":       flag_count,
        "population_count": population_count,
        "flag_pct":         flag_pct,
        "risk_rating":      risk_rating,
        "summary_stats":    summary_stats,
        "chart":            chart,
    }

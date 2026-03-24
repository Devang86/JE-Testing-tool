"""
modules/round_numbers.py
------------------------
Module 3: Round Number Detection for the KKC JE Testing Tool.

SA Reference: SA 240.A37

Round-number journal entries — amounts that are exactly divisible by
1,000, 1,00,000 (one lakh), or 1,00,00,000 (one crore) — are a common
indicator of manipulation.  Legitimate business transactions almost never
produce perfectly round amounts; such entries may represent estimates,
provisions booked to a convenient figure, or amounts chosen to stay just
below an approval threshold.

Detection rules (Indian number system):
  Round Thousand  — amount % 1,000 == 0   AND amount >= min_amount  → Medium
  Round Lakh      — amount % 1,00,000 == 0 AND amount >= min_amount  → High
  Round Crore     — amount % 1,00,00,000 == 0 AND amount >= min_amount → High

Classification hierarchy: every Round Crore is also a Round Lakh, and
every Round Lakh is also a Round Thousand.  A single entry receives the
most-severe applicable label only (Crore > Lakh > Thousand), so counts
are mutually exclusive.

Entries below ROUND_MINIMUM_AMOUNT (default ₹10,000) are excluded to
avoid noise from petty-cash and low-value postings.

Risk Rating (per CLAUDE.md):
  High   — Round Lakh or Crore entries  > 5%  of population, OR any
            Round Crore entry exists
  Medium — Round Thousand entries       > 10% of population, OR any
            Round Lakh entry exists (but no Crore)
  Low    — Below all thresholds
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

try:
    from config import (
        ROUND_THOUSAND,
        ROUND_LAKH,
        ROUND_CRORE,
        ROUND_MINIMUM_AMOUNT,
        RISK_HIGH,
        RISK_MEDIUM,
        KKC_GREEN,
        KKC_GREY,
        KKC_LIGHT_GREY,
        RISK_RED,
        RISK_ORANGE,
    )
except ImportError:
    ROUND_THOUSAND       = 1_000
    ROUND_LAKH           = 1_00_000
    ROUND_CRORE          = 1_00_00_000
    ROUND_MINIMUM_AMOUNT = 10_000
    RISK_HIGH            = 0.05
    RISK_MEDIUM          = 0.01
    KKC_GREEN            = "#7CB542"
    KKC_GREY             = "#808285"
    KKC_LIGHT_GREY       = "#F2F2F2"
    RISK_RED             = "#FF0000"
    RISK_ORANGE          = "#FFA500"


# ---------------------------------------------------------------------------
# Indian number formatting helpers
# ---------------------------------------------------------------------------

def _format_inr(amount: float) -> str:
    """
    Format a numeric amount in the Indian numbering system.

    Produces strings like:
        500        → "₹500"
        15000      → "₹15,000"
        250000     → "₹2,50,000"
        10000000   → "₹1,00,00,000"

    Args:
        amount: Numeric value to format.

    Returns:
        String with rupee symbol and Indian-style comma grouping.
    """
    amount = int(round(amount))
    if amount < 0:
        return "-" + _format_inr(-amount)
    s = str(amount)
    if len(s) <= 3:
        return f"\u20b9{s}"
    # Last 3 digits, then groups of 2
    last3  = s[-3:]
    rest   = s[:-3]
    groups = []
    while len(rest) > 2:
        groups.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.append(rest)
    groups.reverse()
    return f"\u20b9{','.join(groups)},{last3}"


def _label_inr(amount: float) -> str:
    """
    Return a human-readable crore / lakh / thousand label for an amount.

    Examples:
        10_00_000  → "10 Lakh"
        5_00_00_000 → "5 Crore"
        50_000      → "50 Thousand"

    Args:
        amount: Numeric value.

    Returns:
        Label string in Indian denomination.
    """
    amount = abs(amount)
    if amount >= ROUND_CRORE:
        val = amount / ROUND_CRORE
        label = f"{val:g} Crore"
    elif amount >= ROUND_LAKH:
        val = amount / ROUND_LAKH
        label = f"{val:g} Lakh"
    elif amount >= ROUND_THOUSAND:
        val = amount / ROUND_THOUSAND
        label = f"{val:g} Thousand"
    else:
        label = _format_inr(amount)
    return label


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _classify_amount(amount: float) -> str | None:
    """
    Return the highest applicable round-number category for an amount.

    Amounts below ROUND_MINIMUM_AMOUNT, non-positive values, and amounts
    that are not divisible by ROUND_THOUSAND return None (not flagged).

    Classification hierarchy (most severe first):
        "Round Crore"    — divisible by 1,00,00,000
        "Round Lakh"     — divisible by 1,00,000 (but not by 1,00,00,000)
        "Round Thousand" — divisible by 1,000     (but not by 1,00,000)

    Args:
        amount: Numeric entry amount (absolute value is used internally).

    Returns:
        Category string, or None if the entry should not be flagged.
    """
    if pd.isna(amount) or amount <= 0:
        return None
    abs_amt = abs(amount)
    if abs_amt < ROUND_MINIMUM_AMOUNT:
        return None

    # Amounts with paise (fractional part) are never round numbers.
    # Check this BEFORE any rounding so that 50000.50 is never mistaken
    # for 50000.  float.is_integer() returns True only when the value has
    # no fractional component (e.g. 50000.0 → True, 50000.5 → False).
    if not float(abs_amt).is_integer():
        return None

    int_amt = int(abs_amt)

    if int_amt % ROUND_CRORE == 0:
        return "Round Crore"
    if int_amt % ROUND_LAKH == 0:
        return "Round Lakh"
    if int_amt % ROUND_THOUSAND == 0:
        return "Round Thousand"
    return None


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def _build_chart(
    flagged: pd.DataFrame,
    population_count: int,
    amount_col: str,
) -> go.Figure:
    """
    Build a stacked bar chart showing the count of round-number entries
    by category (Thousand / Lakh / Crore) against total population.

    Args:
        flagged:          DataFrame of flagged entries with a "Round_Type" column.
        population_count: Total rows in the full population.
        amount_col:       Name of the amount column (used for hover text).

    Returns:
        Plotly Figure object.
    """
    cat_order   = ["Round Crore", "Round Lakh", "Round Thousand"]
    cat_colours = {
        "Round Crore":    RISK_RED,
        "Round Lakh":     RISK_ORANGE,
        "Round Thousand": KKC_GREEN,
    }

    counts = flagged["Round_Type"].value_counts().reindex(cat_order, fill_value=0)
    unflagged = population_count - len(flagged)

    fig = go.Figure()

    # Stacked bars: one trace per round category
    for cat in cat_order:
        cnt = counts[cat]
        fig.add_trace(go.Bar(
            name=cat,
            x=["Journal Entries"],
            y=[cnt],
            marker_color=cat_colours[cat],
            text=[f"{cnt}" if cnt > 0 else ""],
            textposition="inside",
            hovertemplate=f"{cat}: {cnt} entries<extra></extra>",
        ))

    # Clean/unflagged bar
    fig.add_trace(go.Bar(
        name="Not Round",
        x=["Journal Entries"],
        y=[unflagged],
        marker_color=KKC_LIGHT_GREY,
        marker_line_color=KKC_GREY,
        marker_line_width=0.5,
        hovertemplate=f"Not flagged: {unflagged} entries<extra></extra>",
    ))

    total_flagged = len(flagged)
    pct = total_flagged / population_count * 100 if population_count else 0

    fig.update_layout(
        barmode="stack",
        title=dict(
            text=(
                f"Round Number Analysis  —  "
                f"{total_flagged:,} of {population_count:,} entries flagged "
                f"({pct:.1f}%)"
            ),
            font=dict(size=14),
        ),
        xaxis_title="",
        yaxis_title="Number of Entries",
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Source Sans Pro, Arial, sans-serif", size=12),
        yaxis=dict(gridcolor=KKC_LIGHT_GREY),
        margin=dict(t=80, b=40, l=60, r=20),
        bargap=0.5,
    )

    return fig


# ---------------------------------------------------------------------------
# Risk rating
# ---------------------------------------------------------------------------

def _determine_risk(
    population_count: int,
    crore_count: int,
    lakh_count: int,
    thousand_count: int,
) -> str:
    """
    Determine the module risk rating based on CLAUDE.md rules.

    Rules (evaluated in priority order):
      High   — any Round Crore entry exists
      High   — (Round Lakh + Round Crore) count > 5% of population
      Medium — any Round Lakh entry exists
      Medium — Round Thousand count > 10% of population
      Low    — all below thresholds

    Args:
        population_count: Total entries in the analysis population.
        crore_count:      Entries classified as Round Crore.
        lakh_count:       Entries classified as Round Lakh (excl. Crore).
        thousand_count:   Entries classified as Round Thousand (excl. Lakh/Crore).

    Returns:
        "High", "Medium", or "Low".
    """
    if population_count == 0:
        return "Low"

    high_value_count = lakh_count + crore_count

    if crore_count > 0:
        return "High"
    if high_value_count / population_count > RISK_HIGH:
        return "High"
    if lakh_count > 0:
        return "Medium"
    if thousand_count / population_count > 0.10:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    df: pd.DataFrame,
    amount_col: str = "amount",
) -> dict:
    """
    Execute round-number detection on a journal entry population.

    Classifies each positive entry >= ROUND_MINIMUM_AMOUNT as:
      - Round Crore    (highest severity, flagged High)
      - Round Lakh     (flagged High/Medium depending on prevalence)
      - Round Thousand (flagged Medium if > 10% of population)
      - Not flagged

    Amounts with paise (e.g. ₹50,000.50) are never classified as round.
    Negative amounts and zeros are excluded from analysis.
    Entries below ROUND_MINIMUM_AMOUNT (₹10,000) are excluded to reduce noise.

    Args:
        df:          Full population DataFrame with standard column names.
        amount_col:  Name of the amount column. Defaults to "amount".

    Returns:
        Standard module result dict:
        {
            "module_name":       str — "Round Number Detection",
            "flagged_df":        pd.DataFrame — flagged entries with added
                                  columns: Round_Type, Amount_Label,
            "flag_count":        int,
            "population_count":  int — total rows in input df,
            "flag_pct":          float,
            "risk_rating":       str — "High" / "Medium" / "Low",
            "summary_stats":     dict — per-category counts, thresholds,
                                  below_minimum_count, formatting samples,
            "chart":             plotly Figure,
        }

    Raises:
        ValueError: If amount_col is not present in df.
    """
    if amount_col not in df.columns:
        raise ValueError(
            f"Column '{amount_col}' not found in dataframe. "
            f"Available columns: {list(df.columns)}"
        )

    population_count = len(df)

    # ── 1. Classify every row ────────────────────────────────────────────────
    working = df.copy()
    working["Round_Type"] = working[amount_col].apply(_classify_amount)

    # Count entries excluded due to being below minimum threshold
    eligible_mask    = working[amount_col].notna() & (working[amount_col] > 0)
    below_min_mask   = eligible_mask & (working[amount_col].abs() < ROUND_MINIMUM_AMOUNT)
    below_min_count  = int(below_min_mask.sum())

    # ── 2. Separate by category ──────────────────────────────────────────────
    flagged    = working[working["Round_Type"].notna()].copy()
    crore_mask = flagged["Round_Type"] == "Round Crore"
    lakh_mask  = flagged["Round_Type"] == "Round Lakh"
    thou_mask  = flagged["Round_Type"] == "Round Thousand"

    crore_count    = int(crore_mask.sum())
    lakh_count     = int(lakh_mask.sum())
    thousand_count = int(thou_mask.sum())

    # ── 3. Add human-readable amount label (Indian denomination) ────────────
    flagged["Amount_Label"] = flagged[amount_col].apply(_label_inr)

    # ── 4. Risk rating ───────────────────────────────────────────────────────
    risk_rating = _determine_risk(
        population_count, crore_count, lakh_count, thousand_count
    )

    flag_count = len(flagged)
    flag_pct   = round(flag_count / population_count, 6) if population_count else 0.0

    # ── 5. Chart ─────────────────────────────────────────────────────────────
    chart = _build_chart(flagged, population_count, amount_col)

    # ── 6. Summary stats ─────────────────────────────────────────────────────
    high_value_pct = (
        round((lakh_count + crore_count) / population_count * 100, 2)
        if population_count else 0.0
    )
    thousand_pct = (
        round(thousand_count / population_count * 100, 2)
        if population_count else 0.0
    )

    summary_stats = {
        "crore_count":          crore_count,
        "lakh_count":           lakh_count,
        "thousand_count":       thousand_count,
        "high_value_pct":       high_value_pct,
        "thousand_pct":         thousand_pct,
        "below_minimum_count":  below_min_count,
        "minimum_amount":       ROUND_MINIMUM_AMOUNT,
        "thresholds": {
            "round_thousand":   ROUND_THOUSAND,
            "round_lakh":       ROUND_LAKH,
            "round_crore":      ROUND_CRORE,
            "risk_high_pct":    RISK_HIGH * 100,
            "risk_medium_pct":  10.0,
        },
        # Top-5 largest flagged amounts for the workpaper narrative
        "top_flagged_amounts":  (
            flagged[amount_col]
            .nlargest(5)
            .apply(_format_inr)
            .tolist()
        ) if flag_count > 0 else [],
    }

    return {
        "module_name":      "Round Number Detection",
        "flagged_df":       flagged,
        "flag_count":       flag_count,
        "population_count": population_count,
        "flag_pct":         flag_pct,
        "risk_rating":      risk_rating,
        "summary_stats":    summary_stats,
        "chart":            chart,
    }

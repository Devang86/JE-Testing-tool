"""
modules/benfords.py
-------------------
Module 1: Benford's Law Analysis for KKC JE Testing Tool.

SA Reference: SA 240.A3

Benford's Law states that in many naturally occurring datasets the leading
(first significant) digit d follows the distribution:

    P(d) = log10(1 + 1/d)   for d in {1, 2, ..., 9}

Manipulation of journal entry amounts (e.g. amounts clustered just below an
approval threshold) distorts this natural distribution. A statistically
significant departure — measured by chi-square goodness-of-fit — is a red
flag warranting further investigation.

Workflow:
    1. Strip negative/zero amounts (only positive amounts follow Benford's Law).
    2. Extract the first significant digit from each amount.
    3. Compute observed vs expected frequencies.
    4. Run scipy chi-square goodness-of-fit test.
    5. Flag individual entries whose leading digit falls in an over-represented
       bucket (observed frequency > expected + 2 standard deviations).
    6. Return the standard module result dict consumed by excel_exporter.py.
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy import stats
from typing import Optional

# Config constants — imported lazily to keep module testable standalone.
# Fallback values mirror the config.py spec exactly.
try:
    from config import (
        BENFORD_SIGNIFICANCE,
        KKC_GREEN,
        KKC_GREY,
        KKC_LIGHT_GREY,
        RISK_RED,
        RISK_ORANGE,
    )
except ImportError:
    BENFORD_SIGNIFICANCE = 0.05
    KKC_GREEN = "#7CB542"
    KKC_GREY = "#808285"
    KKC_LIGHT_GREY = "#F2F2F2"
    RISK_RED = "#FF0000"
    RISK_ORANGE = "#FFA500"


# ---------------------------------------------------------------------------
# Benford expected probabilities for digits 1–9
# ---------------------------------------------------------------------------
BENFORD_EXPECTED: dict[int, float] = {
    d: math.log10(1 + 1 / d) for d in range(1, 10)
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _first_significant_digit(value: float) -> Optional[int]:
    """
    Extract the first significant (non-zero) digit from a positive number.

    Handles very small decimals correctly: 0.00456 → 4, 0.1 → 1, 123 → 1.
    Returns None if the value is zero, negative, or not finite.

    Args:
        value: A numeric amount from the journal entry dataset.

    Returns:
        Integer digit 1–9, or None if the value cannot be used.
    """
    if not math.isfinite(value) or value <= 0:
        return None
    # Shift to the form d.ddd by taking log10 and flooring
    digit = int(str(abs(value)).lstrip("0").replace(".", "").lstrip("0")[0])
    return digit if 1 <= digit <= 9 else None


def _extract_digits_series(amounts: pd.Series) -> pd.Series:
    """
    Apply first-significant-digit extraction to an entire Series of amounts.

    Excludes nulls, zeros, and negatives. Returns an integer Series
    containing only valid digit values (1–9).

    Args:
        amounts: pandas Series of numeric journal entry amounts.

    Returns:
        Integer Series of first significant digits (no nulls, only 1–9).
    """
    positive = amounts.dropna()
    positive = positive[positive > 0]
    digits = positive.apply(_first_significant_digit)
    return digits.dropna().astype(int)


def _compute_frequencies(
    digits: pd.Series,
    n: int,
) -> pd.DataFrame:
    """
    Build a comparison table of observed vs expected Benford frequencies.

    Args:
        digits: Integer Series of first significant digits (1–9).
        n:      Total count of valid (positive) amounts used in the analysis.

    Returns:
        DataFrame with columns:
            digit            — int, 1 to 9
            expected_pct     — float, Benford's expected proportion (0–1)
            expected_count   — float, expected count given n
            observed_count   — int, actual count in dataset
            observed_pct     — float, actual proportion (0–1)
            deviation        — float, observed_pct minus expected_pct
            deviation_pct    — float, relative deviation as a percentage
    """
    rows = []
    digit_counts = digits.value_counts().reindex(range(1, 10), fill_value=0)

    # Compute raw expected counts first (unrounded) so scipy's sum-check passes.
    # The sum of log10(1 + 1/d) for d=1..9 equals exactly 1.0, so
    # sum(exp_pct * n) == n — but floating-point rounding of individual rows
    # would break scipy's tolerance check.  We keep expected_count unrounded.
    for d in range(1, 10):
        exp_pct = BENFORD_EXPECTED[d]
        exp_cnt = exp_pct * n          # deliberately NOT rounded
        obs_cnt = int(digit_counts[d])
        obs_pct = obs_cnt / n if n > 0 else 0.0
        rows.append(
            {
                "digit": d,
                "expected_pct": round(exp_pct, 6),
                "expected_count": exp_cnt,
                "observed_count": obs_cnt,
                "observed_pct": round(obs_pct, 6),
                "deviation": round(obs_pct - exp_pct, 6),
                "deviation_pct": round((obs_pct - exp_pct) / exp_pct * 100, 2)
                if exp_pct > 0
                else 0.0,
            }
        )

    return pd.DataFrame(rows)


def _flag_individual_entries(
    df: pd.DataFrame,
    amount_col: str,
    freq_table: pd.DataFrame,
) -> pd.DataFrame:
    """
    Flag individual journal entries whose leading digit is in an
    over-represented bucket (observed > expected + 2 std deviations).

    The standard deviation used is the Benford's expected proportion ± 2σ
    where σ = sqrt(p * (1-p) / n) — the standard error of the proportion.

    Args:
        df:          Full population DataFrame (must contain amount_col).
        amount_col:  Column name holding numeric amounts.
        freq_table:  Output of _compute_frequencies() for this population.

    Returns:
        Filtered DataFrame of entries whose digit is over-represented,
        with an added 'first_digit' column.
    """
    n = freq_table["observed_count"].sum()
    if n == 0:
        return df.head(0).copy()

    # Compute 2-sigma upper bound for each digit
    over_represented_digits: set[int] = set()
    for _, row in freq_table.iterrows():
        p = row["expected_pct"]
        sigma = math.sqrt(p * (1 - p) / n) if n > 0 else 0
        upper_bound = p + 2 * sigma
        if row["observed_pct"] > upper_bound:
            over_represented_digits.add(int(row["digit"]))

    if not over_represented_digits:
        return df.head(0).copy()

    # Assign first digit to every row and filter
    working = df.copy()
    working = working[working[amount_col].notna() & (working[amount_col] > 0)]
    working["first_digit"] = working[amount_col].apply(_first_significant_digit)
    flagged = working[working["first_digit"].isin(over_represented_digits)].copy()
    return flagged


def _build_chart(freq_table: pd.DataFrame) -> go.Figure:
    """
    Build a Plotly bar + line chart comparing observed vs expected Benford
    distribution.

    Bars: Observed % per digit in KKC Green (#7CB542).
    Line: Expected Benford % in KKC Grey (#808285) with markers.
    Red dashed line marks the 2-sigma upper bound for each digit.

    Args:
        freq_table: Output of _compute_frequencies().

    Returns:
        Plotly Figure object (not rendered — caller displays via st.plotly_chart).
    """
    digits = freq_table["digit"].tolist()
    observed_pct = (freq_table["observed_pct"] * 100).round(2).tolist()
    expected_pct = (freq_table["expected_pct"] * 100).round(2).tolist()
    n = freq_table["observed_count"].sum()

    # Compute 2-sigma upper bounds
    upper_bounds = []
    for _, row in freq_table.iterrows():
        p = row["expected_pct"]
        sigma = math.sqrt(p * (1 - p) / n) if n > 0 else 0
        upper_bounds.append(round((p + 2 * sigma) * 100, 2))

    fig = go.Figure()

    # Observed bars
    fig.add_trace(
        go.Bar(
            x=[str(d) for d in digits],
            y=observed_pct,
            name="Observed %",
            marker_color=KKC_GREEN,
            opacity=0.85,
            hovertemplate="Digit %{x}<br>Observed: %{y:.2f}%<extra></extra>",
        )
    )

    # Expected Benford line
    fig.add_trace(
        go.Scatter(
            x=[str(d) for d in digits],
            y=expected_pct,
            name="Benford Expected %",
            mode="lines+markers",
            line=dict(color=KKC_GREY, width=2, dash="dash"),
            marker=dict(size=7, color=KKC_GREY),
            hovertemplate="Digit %{x}<br>Expected: %{y:.2f}%<extra></extra>",
        )
    )

    # 2-sigma upper bound line
    fig.add_trace(
        go.Scatter(
            x=[str(d) for d in digits],
            y=upper_bounds,
            name="Expected + 2\u03c3",
            mode="lines",
            line=dict(color=RISK_RED, width=1.5, dash="dot"),
            hovertemplate="Digit %{x}<br>+2\u03c3: %{y:.2f}%<extra></extra>",
        )
    )

    fig.update_layout(
        title=dict(
            text="Benford's Law Analysis — Observed vs Expected Distribution",
            font=dict(size=14),
        ),
        xaxis_title="First Significant Digit",
        yaxis_title="Frequency (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Source Sans Pro, Arial, sans-serif", size=12),
        yaxis=dict(gridcolor=KKC_LIGHT_GREY),
        margin=dict(t=80, b=40, l=50, r=20),
        bargap=0.25,
    )

    return fig


def _determine_risk(p_value: float) -> str:
    """
    Map the chi-square p-value to a risk rating per the CLAUDE.md spec.

    Args:
        p_value: p-value from scipy chi-square goodness-of-fit test.

    Returns:
        "High"   if p_value < 0.05
        "Medium" if 0.05 <= p_value < 0.10
        "Low"    if p_value >= 0.10
    """
    if p_value < BENFORD_SIGNIFICANCE:
        return "High"
    elif p_value < 0.10:
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
    Execute Benford's Law analysis on a journal entry population.

    Extracts first significant digits from the `amount` column, computes
    observed vs expected Benford frequencies, runs a chi-square
    goodness-of-fit test, and flags individual entries in over-represented
    digit buckets.

    Args:
        df:          Full population DataFrame with standardised column names
                     (output of column_mapper.get_mapped_df()).
        amount_col:  Name of the amount column. Defaults to "amount".

    Returns:
        Standard module result dict:
        {
            "module_name":       str  — "Benford's Law",
            "flagged_df":        pd.DataFrame  — entries in over-represented buckets,
            "flag_count":        int  — number of flagged entries,
            "population_count":  int  — total positive-amount entries analysed,
            "flag_pct":          float  — flag_count / population_count,
            "risk_rating":       str  — "High" / "Medium" / "Low",
            "summary_stats":     dict — chi2, p_value, degrees_of_freedom,
                                        pass_fail, freq_table (DataFrame),
                                        over_represented_digits (list),
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

    # ── 1. Extract digits ────────────────────────────────────────────────────
    digits = _extract_digits_series(df[amount_col])
    n = len(digits)

    # Edge case: not enough data for a meaningful test
    if n < 10:
        empty_df = df.head(0).copy()
        return {
            "module_name": "Benford's Law",
            "flagged_df": empty_df,
            "flag_count": 0,
            "population_count": n,
            "flag_pct": 0.0,
            "risk_rating": "Low",
            "summary_stats": {
                "chi2": None,
                "p_value": None,
                "degrees_of_freedom": 8,
                "pass_fail": "INSUFFICIENT DATA",
                "freq_table": pd.DataFrame(),
                "over_represented_digits": [],
                "note": f"Only {n} positive-amount entries found; minimum 10 required.",
            },
            "chart": None,
        }

    # ── 2. Frequency table ───────────────────────────────────────────────────
    freq_table = _compute_frequencies(digits, n)

    # ── 3. Chi-square goodness-of-fit test ───────────────────────────────────
    observed_counts = freq_table["observed_count"].values.astype(float)
    expected_counts = freq_table["expected_count"].values.astype(float)

    chi2_stat, p_value = stats.chisquare(
        f_obs=observed_counts,
        f_exp=expected_counts,
    )
    degrees_of_freedom = 8  # 9 digits - 1

    # ── 4. Risk rating ───────────────────────────────────────────────────────
    risk_rating = _determine_risk(p_value)
    pass_fail = "FAIL" if risk_rating in ("High", "Medium") else "PASS"

    # ── 5. Flag individual entries ───────────────────────────────────────────
    flagged_df = _flag_individual_entries(df, amount_col, freq_table)
    flag_count = len(flagged_df)
    flag_pct = round(flag_count / n, 6) if n > 0 else 0.0

    # ── 6. Over-represented digits list (for summary stats) ─────────────────
    over_represented_digits: list[int] = []
    for _, row in freq_table.iterrows():
        p = row["expected_pct"]
        sigma = math.sqrt(p * (1 - p) / n) if n > 0 else 0
        if row["observed_pct"] > p + 2 * sigma:
            over_represented_digits.append(int(row["digit"]))

    # ── 7. Build chart ───────────────────────────────────────────────────────
    chart = _build_chart(freq_table)

    return {
        "module_name": "Benford's Law",
        "flagged_df": flagged_df,
        "flag_count": flag_count,
        "population_count": n,
        "flag_pct": flag_pct,
        "risk_rating": risk_rating,
        "summary_stats": {
            "chi2": round(float(chi2_stat), 4),
            "p_value": round(float(p_value), 6),
            "degrees_of_freedom": degrees_of_freedom,
            "pass_fail": pass_fail,
            "freq_table": freq_table,
            "over_represented_digits": over_represented_digits,
        },
        "chart": chart,
    }

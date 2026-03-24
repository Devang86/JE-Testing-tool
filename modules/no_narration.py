"""
modules/no_narration.py
-----------------------
Module 6: Missing / Generic Narration Detection for the KKC JE Testing Tool.

SA Reference: SA 315.A51

A narration (description / remarks field) is the auditor's primary window
into the business purpose of a journal entry.  Entries with no narration,
a single punctuation character, or a generic placeholder like "NA" or "misc"
provide no audit trail and make it impossible to assess whether the posting
is legitimate without obtaining additional evidence.

Flag conditions (per CLAUDE.md) — an entry is flagged if its narration is:
  1. NaN / None / null  (truly absent)
  2. Blank string or whitespace-only  ("   ", "\t", etc.)
  3. Single noise character: ".", "-", "/"
  4. Generic placeholder (case-insensitive, exact match after stripping):
       NA, N/A, NIL, NONE, TEST, TEMP
  5. Any combination of the above after stripping

The flag reason is recorded so the Excel workpaper shows exactly why each
entry was flagged (e.g. "Null/Blank", "Single Character", "Generic Placeholder").

Risk Rating (per CLAUDE.md):
  High   — > 10% of entries flagged
  Medium — 5–10%
  Low    — < 5%
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

try:
    from config import (
        KKC_GREEN,
        KKC_GREY,
        KKC_LIGHT_GREY,
        RISK_RED,
        RISK_ORANGE,
    )
except ImportError:
    KKC_GREEN      = "#7CB542"
    KKC_GREY       = "#808285"
    KKC_LIGHT_GREY = "#F2F2F2"
    RISK_RED       = "#FF0000"
    RISK_ORANGE    = "#FFA500"

# ── Flag-condition constants ─────────────────────────────────────────────────

# Single characters that, on their own, indicate a meaningless narration
_NOISE_CHARS: frozenset[str] = frozenset({".", "-", "/"})

# Exact-match placeholders (compared case-insensitively after stripping)
_GENERIC_PLACEHOLDERS: frozenset[str] = frozenset({
    "na", "n/a", "nil", "none", "test", "temp",
})

# ── Risk thresholds ──────────────────────────────────────────────────────────
_HIGH_THRESHOLD   = 0.10   # > 10%
_MEDIUM_THRESHOLD = 0.05   # > 5%


# ---------------------------------------------------------------------------
# Per-entry classification
# ---------------------------------------------------------------------------

def _flag_reason(value) -> str | None:
    """
    Determine whether a narration value should be flagged and return the reason.

    Evaluation order:
      1. Null / NaN / None                → "Null/Blank"
      2. Whitespace-only string           → "Null/Blank"
      3. Single noise character (., -, /) → "Single Character"
      4. Generic placeholder (NA, NIL, …) → "Generic Placeholder"
      5. Otherwise                        → None (not flagged)

    The comparison for generic placeholders is case-insensitive and is
    performed on the stripped value, so "  N/A  " and "Nil" are both caught.

    Args:
        value: Raw cell value from the narration column.

    Returns:
        A non-empty reason string if the entry should be flagged, else None.
    """
    # 1. Null / missing
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Null/Blank"

    # 2. Coerce to string and strip
    stripped = str(value).strip()

    # 3. Empty after stripping
    if stripped == "":
        return "Null/Blank"

    # 4. Single noise character
    if stripped in _NOISE_CHARS:
        return "Single Character"

    # 5. Generic placeholder
    if stripped.lower() in _GENERIC_PLACEHOLDERS:
        return "Generic Placeholder"

    return None


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def _build_chart(
    flag_count: int,
    population_count: int,
    reason_counts: dict[str, int],
) -> go.Figure:
    """
    Build a two-part Plotly figure:
      Left  — Donut chart: flagged vs not-flagged population split.
      Right — Horizontal bar: breakdown of flagged entries by reason.

    Args:
        flag_count:       Total flagged entries.
        population_count: Total population.
        reason_counts:    Dict mapping flag reason → count.

    Returns:
        Plotly Figure.
    """
    from plotly.subplots import make_subplots

    not_flagged = population_count - flag_count
    pct = flag_count / population_count * 100 if population_count else 0

    reason_order  = ["Null/Blank", "Single Character", "Generic Placeholder"]
    reason_colours = {
        "Null/Blank":           RISK_RED,
        "Single Character":     RISK_ORANGE,
        "Generic Placeholder":  KKC_GREY,
    }

    has_breakdown = flag_count > 0
    cols  = 2 if has_breakdown else 1
    specs = [[{"type": "pie"}, {"type": "bar"}]] if has_breakdown \
            else [[{"type": "pie"}]]
    subplot_titles = (
        ["Population Split", "Flag Reason Breakdown"]
        if has_breakdown else ["Population Split"]
    )

    fig = make_subplots(
        rows=1, cols=cols,
        specs=specs,
        subplot_titles=subplot_titles,
    )

    # ── Left: donut ──────────────────────────────────────────────────────────
    fig.add_trace(
        go.Pie(
            labels=["Flagged", "Not Flagged"],
            values=[flag_count, not_flagged],
            hole=0.55,
            marker_colors=[RISK_RED, KKC_LIGHT_GREY],
            textinfo="label+percent",
            hovertemplate="%{label}: %{value}<extra></extra>",
        ),
        row=1, col=1,
    )

    # ── Right: reason bars ───────────────────────────────────────────────────
    if has_breakdown:
        reasons = [r for r in reason_order if reason_counts.get(r, 0) > 0]
        counts  = [reason_counts.get(r, 0) for r in reasons]
        colours = [reason_colours[r] for r in reasons]

        fig.add_trace(
            go.Bar(
                x=counts,
                y=reasons,
                orientation="h",
                marker_color=colours,
                text=[str(c) for c in counts],
                textposition="outside",
                hovertemplate="%{y}: %{x} entries<extra></extra>",
                showlegend=False,
            ),
            row=1, col=2,
        )
        fig.update_xaxes(title_text="Entries", row=1, col=2)
        fig.update_yaxes(autorange="reversed", row=1, col=2)

    fig.update_layout(
        title=dict(
            text=(
                f"Missing / Generic Narration  —  "
                f"{flag_count:,} of {population_count:,} entries flagged "
                f"({pct:.1f}%)"
            ),
            font=dict(size=14),
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Source Sans Pro, Arial, sans-serif", size=12),
        margin=dict(t=80, b=40, l=60, r=40),
        showlegend=False,
    )

    return fig


# ---------------------------------------------------------------------------
# Risk rating
# ---------------------------------------------------------------------------

def _determine_risk(flag_pct: float) -> str:
    """
    Map the flagged percentage to a risk rating per CLAUDE.md.

    Args:
        flag_pct: Fraction of population flagged (0.0 – 1.0).

    Returns:
        "High"   if flag_pct > 10%
        "Medium" if flag_pct > 5% and <= 10%
        "Low"    if flag_pct <= 5%
    """
    if flag_pct > _HIGH_THRESHOLD:
        return "High"
    if flag_pct > _MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    df: pd.DataFrame,
    narration_col: str = "narration",
) -> dict:
    """
    Execute missing / generic narration detection on a JE population.

    Each entry is tested against five flag conditions (null, whitespace,
    single noise character, generic placeholder).  The first matching
    condition is recorded as the flag reason.

    If the narration column is absent, the module returns a zero-flag
    result with a note in summary_stats rather than raising an error,
    because narration is an optional field per the CLAUDE.md spec.

    Args:
        df:             Full population DataFrame with standard column names.
        narration_col:  Column name for the narration / description field.
                        Defaults to "narration".

    Returns:
        Standard module result dict:
        {
            "module_name":       str — "Missing Narration",
            "flagged_df":        pd.DataFrame — flagged entries with added
                                  column: Narration_Flag_Reason,
            "flag_count":        int,
            "population_count":  int,
            "flag_pct":          float,
            "risk_rating":       str — "High" / "Medium" / "Low",
            "summary_stats":     dict — null_blank_count, single_char_count,
                                  generic_placeholder_count,
                                  column_absent (bool),
                                  reason_counts (dict),
            "chart":             plotly Figure,
        }
    """
    population_count = len(df)

    # ── Graceful skip if column is absent ────────────────────────────────────
    if narration_col not in df.columns:
        empty_chart = _build_chart(0, population_count, {})
        return {
            "module_name":      "Missing Narration",
            "flagged_df":       df.head(0).copy(),
            "flag_count":       0,
            "population_count": population_count,
            "flag_pct":         0.0,
            "risk_rating":      "Low",
            "summary_stats": {
                "null_blank_count":          0,
                "single_char_count":         0,
                "generic_placeholder_count": 0,
                "reason_counts":             {},
                "column_absent":             True,
                "note": (
                    f"Column '{narration_col}' not found — "
                    "Missing Narration module skipped."
                ),
            },
            "chart": empty_chart,
        }

    # ── Classify every row ────────────────────────────────────────────────────
    working = df.copy()
    working["Narration_Flag_Reason"] = working[narration_col].apply(_flag_reason)

    flagged    = working[working["Narration_Flag_Reason"].notna()].copy()
    flag_count = len(flagged)
    flag_pct   = round(flag_count / population_count, 6) if population_count else 0.0

    # ── Per-reason breakdown ──────────────────────────────────────────────────
    reason_counts = (
        flagged["Narration_Flag_Reason"]
        .value_counts()
        .to_dict()
    )
    null_blank_count          = reason_counts.get("Null/Blank", 0)
    single_char_count         = reason_counts.get("Single Character", 0)
    generic_placeholder_count = reason_counts.get("Generic Placeholder", 0)

    # ── Risk rating ───────────────────────────────────────────────────────────
    risk_rating = _determine_risk(flag_pct)

    # ── Chart ─────────────────────────────────────────────────────────────────
    chart = _build_chart(flag_count, population_count, reason_counts)

    summary_stats = {
        "null_blank_count":          null_blank_count,
        "single_char_count":         single_char_count,
        "generic_placeholder_count": generic_placeholder_count,
        "reason_counts":             reason_counts,
        "column_absent":             False,
    }

    return {
        "module_name":      "Missing Narration",
        "flagged_df":       flagged,
        "flag_count":       flag_count,
        "population_count": population_count,
        "flag_pct":         flag_pct,
        "risk_rating":      risk_rating,
        "summary_stats":    summary_stats,
        "chart":            chart,
    }

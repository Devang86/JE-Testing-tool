"""
modules/keywords.py
-------------------
Module 9: High-Risk Keyword Flagging for the KKC JE Testing Tool.

SA Reference: SA 240.A37

The narration (description / remarks) field of a journal entry often
contains the clearest signal of management intent.  Entries that reference
"backdated", "director instruction", "override", "suspense", "dummy", etc.
are audit red flags that warrant immediate investigation.

Two tiers of keywords (defined in config.py):
  HIGH_RISK_KEYWORDS  — full list; triggers a flag on any match
  ALWAYS_HIGH_KEYWORDS — subset; a single hit in this tier raises the
                          overall module risk rating to High regardless of
                          what percentage of the population is flagged

Matching rules:
  - Case-insensitive substring search within the narration field
  - A single entry can match multiple keywords; all matched keywords are
    recorded (comma-separated) in the output column Keyword_Matches
  - Entries with blank / null narrations are skipped (not double-flagged
    here — the no_narration module handles those)

Risk Rating (per CLAUDE.md):
  High   — keyword flags > 3% of population, OR any entry contains an
            ALWAYS_HIGH keyword (override, backdated, director instruction,
            boss instruction, management override)
  Medium — keyword flags 1–3%
  Low    — < 1%
"""

from __future__ import annotations

import re
from collections import Counter

import pandas as pd
import plotly.graph_objects as go

try:
    from config import (
        HIGH_RISK_KEYWORDS,
        ALWAYS_HIGH_KEYWORDS,
        KKC_GREEN,
        KKC_GREY,
        KKC_LIGHT_GREY,
        RISK_RED,
        RISK_ORANGE,
    )
except ImportError:
    HIGH_RISK_KEYWORDS = [
        "adjustment", "adjusted", "correcting entry", "correction",
        "write-off", "write off", "reversal", "reversed", "reverse",
        "override", "overriding", "one-time", "one time",
        "misc", "miscellaneous", "suspense", "clearing entry",
        "rectification", "rectify", "error correction", "prior period",
        "back date", "backdated", "reclass", "reclassification",
        "provision reversal", "manual entry", "direct entry",
        "management override", "boss instruction", "director instruction",
        "off balance", "testing", "test entry", "dummy", "trial",
    ]
    ALWAYS_HIGH_KEYWORDS = [
        "override", "backdated", "director instruction",
        "boss instruction", "management override",
    ]
    KKC_GREEN      = "#7CB542"
    KKC_GREY       = "#808285"
    KKC_LIGHT_GREY = "#F2F2F2"
    RISK_RED       = "#FF0000"
    RISK_ORANGE    = "#FFA500"

# ── Risk thresholds ──────────────────────────────────────────────────────────
_HIGH_THRESHOLD   = 0.03   # > 3% of population flagged
_MEDIUM_THRESHOLD = 0.01   # 1–3%


# ---------------------------------------------------------------------------
# Keyword matching helpers
# ---------------------------------------------------------------------------

def _compile_patterns(keywords: list[str]) -> list[tuple[str, re.Pattern]]:
    """
    Pre-compile case-insensitive regex patterns for each keyword.

    Multi-word phrases like "correcting entry" use a simple substring
    search (re.search) so they match anywhere within the narration text.

    Args:
        keywords: List of keyword strings from config.

    Returns:
        List of (keyword, compiled_pattern) tuples.
    """
    return [
        (kw, re.compile(re.escape(kw), re.IGNORECASE))
        for kw in keywords
    ]


# Pre-compile once at module load
_ALL_PATTERNS:        list[tuple[str, re.Pattern]] = _compile_patterns(HIGH_RISK_KEYWORDS)
_ALWAYS_HIGH_SET:     frozenset[str]               = frozenset(
    kw.lower() for kw in ALWAYS_HIGH_KEYWORDS
)


def _match_keywords(text: str) -> list[str]:
    """
    Return the list of HIGH_RISK_KEYWORDS that appear in *text*.

    Matching is case-insensitive substring search.  Null / non-string
    values return an empty list (no match).

    Args:
        text: Raw narration cell value.

    Returns:
        Possibly-empty list of matched keyword strings (in config order).
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    s = str(text)
    return [kw for kw, pat in _ALL_PATTERNS if pat.search(s)]


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def _build_chart(
    keyword_counts: dict[str, int],
    flag_count: int,
    population_count: int,
    always_high_set: frozenset[str],
) -> go.Figure:
    """
    Build a horizontal bar chart showing match frequency per keyword.

    Bars for keywords in ALWAYS_HIGH are coloured red; all others are
    KKC Green.  Only keywords with at least one hit are shown, sorted
    descending by count.

    Args:
        keyword_counts:   Dict of keyword → hit count (only matched ones).
        flag_count:       Total flagged entries.
        population_count: Total population.
        always_high_set:  Frozenset of always-high keyword strings (lower).

    Returns:
        Plotly Figure.
    """
    if not keyword_counts:
        fig = go.Figure()
        fig.update_layout(
            title="No keyword matches found.",
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        return fig

    sorted_items = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
    keywords = [k for k, _ in sorted_items]
    counts   = [c for _, c in sorted_items]
    colours  = [
        RISK_RED if kw.lower() in always_high_set else KKC_GREEN
        for kw in keywords
    ]

    pct = flag_count / population_count * 100 if population_count else 0

    fig = go.Figure(go.Bar(
        x=counts,
        y=keywords,
        orientation="h",
        marker_color=colours,
        text=[str(c) for c in counts],
        textposition="outside",
        hovertemplate="%{y}: %{x} entries<extra></extra>",
    ))

    fig.update_layout(
        title=dict(
            text=(
                f"High-Risk Keyword Flagging  —  "
                f"{flag_count:,} of {population_count:,} entries flagged "
                f"({pct:.1f}%)"
            ),
            font=dict(size=14),
        ),
        xaxis_title="Entries",
        yaxis=dict(autorange="reversed"),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Source Sans Pro, Arial, sans-serif", size=12),
        margin=dict(t=80, b=40, l=220, r=60),
        showlegend=False,
    )

    return fig


# ---------------------------------------------------------------------------
# Risk rating
# ---------------------------------------------------------------------------

def _determine_risk(
    flag_pct: float,
    keyword_counts: dict[str, int],
    always_high_set: frozenset[str],
) -> str:
    """
    Determine module risk rating.

    Rules (per CLAUDE.md):
      High   — flag_pct > 3%, OR any ALWAYS_HIGH keyword was matched
      Medium — flag_pct 1–3%
      Low    — flag_pct < 1%

    Args:
        flag_pct:        Fraction of population flagged (0.0 – 1.0).
        keyword_counts:  Dict of keyword → count (only matched keywords).
        always_high_set: Frozenset of always-high keyword strings (lower).

    Returns:
        "High", "Medium", or "Low".
    """
    # Any always-high keyword hit → immediate High
    if any(kw.lower() in always_high_set for kw in keyword_counts):
        return "High"

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
    extra_keywords: list[str] | None = None,
) -> dict:
    """
    Execute high-risk keyword flagging on a JE population.

    Scans the narration column for keywords defined in HIGH_RISK_KEYWORDS
    (config.py).  Additional keywords can be injected at runtime via
    *extra_keywords* (from the Streamlit UI keyword editor).

    If the narration column is absent the module returns a zero-flag
    result with a note, rather than raising an error.

    Args:
        df:             Full population DataFrame with standard column names.
        narration_col:  Column name for the narration field.
                        Defaults to "narration".
        extra_keywords: Optional list of additional keywords supplied by the
                        user at runtime.  These are appended to the compiled
                        pattern list and treated identically to config
                        keywords (but NOT added to the always-high set).

    Returns:
        Standard module result dict:
        {
            "module_name":       str — "Keyword Flags",
            "flagged_df":        pd.DataFrame — flagged entries with added
                                  column: Keyword_Matches (comma-separated
                                  list of matched keywords),
            "flag_count":        int,
            "population_count":  int,
            "flag_pct":          float,
            "risk_rating":       str — "High" / "Medium" / "Low",
            "summary_stats":     dict — keyword_counts (Counter),
                                  always_high_triggered (list of triggered
                                  always-high keywords),
                                  unique_keywords_matched (int),
                                  column_absent (bool),
                                  extra_keywords_used (list),
            "chart":             plotly Figure,
        }
    """
    population_count = len(df)

    # ── Graceful skip if narration column is absent ───────────────────────
    if narration_col not in df.columns:
        empty_chart = _build_chart({}, 0, population_count, _ALWAYS_HIGH_SET)
        return {
            "module_name":      "Keyword Flags",
            "flagged_df":       df.head(0).copy(),
            "flag_count":       0,
            "population_count": population_count,
            "flag_pct":         0.0,
            "risk_rating":      "Low",
            "summary_stats": {
                "keyword_counts":           {},
                "always_high_triggered":    [],
                "unique_keywords_matched":  0,
                "column_absent":            True,
                "extra_keywords_used":      [],
                "note": (
                    f"Column '{narration_col}' not found — "
                    "Keyword Flags module skipped."
                ),
            },
            "chart": empty_chart,
        }

    # ── Build effective pattern list (config + extra) ─────────────────────
    effective_patterns = list(_ALL_PATTERNS)
    extra_used: list[str] = []
    if extra_keywords:
        for kw in extra_keywords:
            kw = kw.strip()
            if kw:
                effective_patterns.append(
                    (kw, re.compile(re.escape(kw), re.IGNORECASE))
                )
                extra_used.append(kw)

    # ── Classify every row ────────────────────────────────────────────────
    def _match_all(text) -> list[str]:
        if text is None or (isinstance(text, float) and pd.isna(text)):
            return []
        s = str(text)
        return [kw for kw, pat in effective_patterns if pat.search(s)]

    working = df.copy()
    working["_kw_list"] = working[narration_col].apply(_match_all)
    working["_has_match"] = working["_kw_list"].apply(lambda x: len(x) > 0)

    flagged = working[working["_has_match"]].copy()
    flagged["Keyword_Matches"] = flagged["_kw_list"].apply(
        lambda lst: ", ".join(lst)
    )

    # Drop internal helper columns
    for tmp in ("_kw_list", "_has_match"):
        if tmp in flagged.columns:
            flagged.drop(columns=[tmp], inplace=True)

    flag_count = len(flagged)
    flag_pct   = round(flag_count / population_count, 6) if population_count else 0.0

    # ── Keyword frequency counts ──────────────────────────────────────────
    all_matched: list[str] = []
    for lst in working.loc[working["_has_match"] if "_has_match" in working.columns
                           else working["_kw_list"].apply(bool), "_kw_list"]:
        all_matched.extend(lst)

    # Recompute from flagged to keep it clean
    all_matched = []
    for row_list in working.loc[working["_kw_list"].apply(bool), "_kw_list"]:
        all_matched.extend(row_list)

    keyword_counts = dict(Counter(all_matched))

    # ── Always-high triggers ──────────────────────────────────────────────
    always_high_triggered = [
        kw for kw in keyword_counts
        if kw.lower() in _ALWAYS_HIGH_SET
    ]

    # ── Risk rating ───────────────────────────────────────────────────────
    risk_rating = _determine_risk(flag_pct, keyword_counts, _ALWAYS_HIGH_SET)

    # ── Chart ─────────────────────────────────────────────────────────────
    chart = _build_chart(keyword_counts, flag_count, population_count, _ALWAYS_HIGH_SET)

    # Drop internal helpers from working before returning
    for tmp in ("_kw_list", "_has_match"):
        if tmp in working.columns:
            working.drop(columns=[tmp], inplace=True)

    summary_stats = {
        "keyword_counts":          keyword_counts,
        "always_high_triggered":   always_high_triggered,
        "unique_keywords_matched": len(keyword_counts),
        "column_absent":           False,
        "extra_keywords_used":     extra_used,
    }

    return {
        "module_name":      "Keyword Flags",
        "flagged_df":       flagged,
        "flag_count":       flag_count,
        "population_count": population_count,
        "flag_pct":         flag_pct,
        "risk_rating":      risk_rating,
        "summary_stats":    summary_stats,
        "chart":            chart,
    }

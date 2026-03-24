"""
modules/duplicates.py
---------------------
Module 2: Duplicate Journal Entry Detection for the KKC JE Testing Tool.

SA Reference: SA 240.A37

Duplicate or near-duplicate journal entries may indicate:
  - Accidental double-posting (data entry error)
  - Deliberate inflation of expenses or revenues
  - System migration artefacts requiring explanation

Three duplicate types are detected:

  Type A — Exact Duplicate (High Risk)
      Same amount + same debit_account + same credit_account + same
      posting_date (calendar day).  Most likely an accidental or
      deliberate double-post.

  Type B — Near Duplicate (Medium Risk)
      Same amount + same debit_account + same credit_account but on a
      different day within the same calendar month.  Could indicate
      split-period manipulation or a re-posting error.

  Type C — JE Number Duplicate (Medium Risk)
      The same je_number appears on more than one row.  This is a data
      integrity flag — a journal number should uniquely identify a
      posting.  Requires explanation even if amounts differ.

A single entry can be flagged by more than one type.  The "Duplicate Type"
output column is pipe-separated for multi-type hits (e.g. "Type A | Type C").

Risk Rating logic (per CLAUDE.md):
  High   — any Type A duplicates exist
  Medium — only Type B or Type C duplicates exist (no Type A)
  Low    — no duplicates of any kind
"""

from __future__ import annotations

import pandas as pd
from typing import Optional

try:
    from config import KKC_GREEN, KKC_GREY
except ImportError:
    KKC_GREEN = "#7CB542"
    KKC_GREY  = "#808285"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_date(series: pd.Series) -> pd.Series:
    """
    Coerce a date-like Series to pandas Timestamps (date only, no time).

    Handles strings, datetime objects, and mixed types gracefully.
    Rows that cannot be parsed become NaT.

    Args:
        series: Raw posting_date column from the uploaded dataframe.

    Returns:
        Series of pandas Timestamp (date only) or NaT.
    """
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def _detect_type_a(
    df: pd.DataFrame,
    amount_col: str,
    debit_col: Optional[str],
    credit_col: Optional[str],
    date_col: str,
) -> pd.Series:
    """
    Identify Type A — Exact Duplicates.

    A group of rows shares the same amount, debit_account, credit_account,
    and posting_date (same calendar day).  Every row in such a group is
    flagged (including the original, because the auditor must investigate
    all occurrences).

    Args:
        df:         Working dataframe with normalised date column.
        amount_col: Name of the amount column.
        debit_col:  Name of the debit_account column, or None if absent.
        credit_col: Name of the credit_account column, or None if absent.
        date_col:   Name of the normalised posting_date column.

    Returns:
        Boolean Series — True where the row is part of a Type A group.
    """
    key_cols = [c for c in [amount_col, debit_col, credit_col, date_col]
                if c is not None]
    if len(key_cols) < 2:
        return pd.Series(False, index=df.index)

    dup_mask = df.duplicated(subset=key_cols, keep=False)
    return dup_mask


def _detect_type_b(
    df: pd.DataFrame,
    amount_col: str,
    debit_col: Optional[str],
    credit_col: Optional[str],
    date_col: str,
) -> pd.Series:
    """
    Identify Type B — Near Duplicates (same month, different day).

    Rows that share amount + debit_account + credit_account within the
    same calendar month (year-month), but do NOT share the exact date
    (i.e. are not already Type A exact duplicates).

    Strategy:
      1. Add a year-month key column.
      2. Group by (amount, debit, credit, year-month).
      3. Any group with > 1 distinct posting_date is a near-duplicate group.
      4. Exclude rows that are already Type A (same-day duplicates) —
         those are the more severe classification and should not be
         double-counted in the Type B flagged set.

    Args:
        df:         Working dataframe with normalised date column.
        amount_col: Name of the amount column.
        debit_col:  Name of the debit_account column, or None if absent.
        credit_col: Name of the credit_account column, or None if absent.
        date_col:   Name of the normalised posting_date column.

    Returns:
        Boolean Series — True where the row is part of a Type B group
        (and is NOT already a Type A exact duplicate).
    """
    key_cols = [c for c in [amount_col, debit_col, credit_col]
                if c is not None]
    if not key_cols or date_col not in df.columns:
        return pd.Series(False, index=df.index)

    working = df.copy()
    working["_ym"] = working[date_col].dt.to_period("M")

    month_key_cols = key_cols + ["_ym"]

    # For each (amount, accounts, year-month) group, count distinct dates
    group_date_counts = (
        working.groupby(month_key_cols, dropna=False)[date_col]
        .transform("nunique")
    )

    # Near-duplicate: same amount+accounts+month, but more than one distinct date
    in_near_dup_group = group_date_counts > 1

    # Exclude Type A (same-day exact duplicates) — they are the stricter flag
    type_a_mask = _detect_type_a(df, amount_col, debit_col, credit_col, date_col)

    return in_near_dup_group & ~type_a_mask


def _detect_type_c(
    df: pd.DataFrame,
    je_number_col: Optional[str],
) -> pd.Series:
    """
    Identify Type C — JE Number Duplicates.

    Any je_number that appears more than once in the population is flagged.
    This is a data integrity check — journal numbers should be unique
    identifiers.  NaN/null je_numbers are excluded from this check.

    Args:
        df:             Working dataframe.
        je_number_col:  Name of the je_number column, or None if not mapped.

    Returns:
        Boolean Series — True where the row has a duplicated je_number.
    """
    if je_number_col is None or je_number_col not in df.columns:
        return pd.Series(False, index=df.index)

    valid_mask = df[je_number_col].notna()
    dup_mask   = df.duplicated(subset=[je_number_col], keep=False) & valid_mask
    return dup_mask


def _build_occurrence_count(
    df: pd.DataFrame,
    key_cols: list[str],
) -> pd.Series:
    """
    Return a Series with the count of occurrences for each row's key group.

    Used to populate the "Occurrences" column in the flagged output.

    Args:
        df:        Working dataframe.
        key_cols:  Columns that define the duplicate key for this type.

    Returns:
        Integer Series aligned to df.index.
    """
    if not key_cols:
        return pd.Series(1, index=df.index)
    return df.groupby(key_cols, dropna=False)[key_cols[0]].transform("count")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    df: pd.DataFrame,
    amount_col: str    = "amount",
    debit_col: str     = "debit_account",
    credit_col: str    = "credit_account",
    date_col: str      = "posting_date",
    je_number_col: str = "je_number",
) -> dict:
    """
    Execute duplicate journal entry detection on a JE population.

    Detects three types of duplicates:
      Type A — exact same amount + accounts + date  (High Risk)
      Type B — same amount + accounts, different day same month  (Medium Risk)
      Type C — same JE number appears more than once  (Medium Risk)

    Columns not present in df are silently skipped; the relevant detection
    type is omitted rather than raising an error, and a note is included in
    summary_stats.

    Args:
        df:             Full population DataFrame with standard column names
                        (output of column_mapper.get_mapped_df()).
        amount_col:     Column name for entry amount.
        debit_col:      Column name for debit account.
        credit_col:     Column name for credit account.
        date_col:       Column name for posting date.
        je_number_col:  Column name for journal entry number.

    Returns:
        Standard module result dict:
        {
            "module_name":       str  — "Duplicate Detection",
            "flagged_df":        pd.DataFrame  — all flagged rows with added
                                  columns: Duplicate_Type, Occurrences,
            "flag_count":        int  — unique rows flagged (deduplicated),
            "population_count":  int  — total rows in input df,
            "flag_pct":          float,
            "risk_rating":       str  — "High" / "Medium" / "Low",
            "summary_stats":     dict — counts per type, skipped fields,
            "chart":             None  (no chart for this module),
        }
    """
    population_count = len(df)

    # ── Resolve actual column names present in df ────────────────────────────
    def _col(name: str) -> Optional[str]:
        return name if name in df.columns else None

    amt  = _col(amount_col)
    dr   = _col(debit_col)
    cr   = _col(credit_col)
    dt   = _col(date_col)
    je   = _col(je_number_col)

    skipped: list[str] = []
    if amt is None:  skipped.append(f"'{amount_col}' not found — Type A/B skipped")
    if dt  is None:  skipped.append(f"'{date_col}' not found — Type A/B skipped")
    if je  is None:  skipped.append(f"'{je_number_col}' not found — Type C skipped")

    # ── Prepare working copy with normalised date ────────────────────────────
    working = df.copy()
    if dt is not None:
        working[dt] = _normalise_date(working[dt])

    # ── Run detectors ────────────────────────────────────────────────────────
    can_run_ab = (amt is not None) and (dt is not None)

    if can_run_ab:
        mask_a = _detect_type_a(working, amt, dr, cr, dt)
        mask_b = _detect_type_b(working, amt, dr, cr, dt)
    else:
        mask_a = pd.Series(False, index=working.index)
        mask_b = pd.Series(False, index=working.index)

    mask_c = _detect_type_c(working, je)

    # ── Build combined Duplicate_Type label ─────────────────────────────────
    type_labels = pd.Series("", index=working.index)
    type_labels[mask_a] = type_labels[mask_a].apply(
        lambda x: x + ("Type A" if x == "" else " | Type A")
    )
    type_labels[mask_b] = type_labels[mask_b].apply(
        lambda x: x + ("Type B" if x == "" else " | Type B")
    )
    type_labels[mask_c] = type_labels[mask_c].apply(
        lambda x: x + ("Type C" if x == "" else " | Type C")
    )

    any_flag = mask_a | mask_b | mask_c

    # ── Occurrence counts ────────────────────────────────────────────────────
    # Use the tightest key per row for occurrence count:
    # Type A rows → keyed on (amount, debit, credit, date)
    # Type B rows → keyed on (amount, debit, credit, year-month)
    # Type C rows → keyed on (je_number)
    occ = pd.Series(1, index=working.index)

    if can_run_ab and mask_a.any():
        a_key = [c for c in [amt, dr, cr, dt] if c is not None]
        occ[mask_a] = _build_occurrence_count(working, a_key)[mask_a]

    if can_run_ab and mask_b.any():
        working["_ym_occ"] = working[dt].dt.to_period("M") if dt else None
        b_key = [c for c in [amt, dr, cr] if c is not None] + ["_ym_occ"]
        occ[mask_b & ~mask_a] = _build_occurrence_count(working, b_key)[mask_b & ~mask_a]

    if mask_c.any() and je is not None:
        occ[mask_c & ~mask_a & ~mask_b] = _build_occurrence_count(
            working, [je]
        )[mask_c & ~mask_a & ~mask_b]

    # ── Assemble flagged dataframe ───────────────────────────────────────────
    flagged = working[any_flag].copy()
    flagged["Duplicate_Type"] = type_labels[any_flag]
    flagged["Occurrences"]    = occ[any_flag]

    # Drop internal helper columns if they crept in
    for _tmp in ("_ym", "_ym_occ"):
        if _tmp in flagged.columns:
            flagged.drop(columns=[_tmp], inplace=True)

    flag_count = int(any_flag.sum())
    flag_pct   = round(flag_count / population_count, 6) if population_count else 0.0

    # ── Risk rating ──────────────────────────────────────────────────────────
    if mask_a.any():
        risk_rating = "High"
    elif mask_b.any() or mask_c.any():
        risk_rating = "Medium"
    else:
        risk_rating = "Low"

    # ── Summary stats ────────────────────────────────────────────────────────
    summary_stats = {
        "type_a_count": int(mask_a.sum()),
        "type_b_count": int(mask_b.sum()),
        "type_c_count": int(mask_c.sum()),
        "type_a_groups": int(
            working[mask_a].groupby(
                [c for c in [amt, dr, cr, dt] if c is not None]
            ).ngroups
        ) if can_run_ab and mask_a.any() else 0,
        "type_b_groups": int(
            working[mask_b].assign(
                _ym=working[dt].dt.to_period("M") if dt else None
            ).groupby(
                [c for c in [amt, dr, cr, "_ym"] if c is not None]
            ).ngroups
        ) if can_run_ab and mask_b.any() else 0,
        "type_c_groups": int(
            working[mask_c][je].nunique()
        ) if mask_c.any() and je else 0,
        "skipped_fields": skipped,
    }

    return {
        "module_name":      "Duplicate Detection",
        "flagged_df":       flagged,
        "flag_count":       flag_count,
        "population_count": population_count,
        "flag_pct":         flag_pct,
        "risk_rating":      risk_rating,
        "summary_stats":    summary_stats,
        "chart":            None,
    }

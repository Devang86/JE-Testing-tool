"""
modules/account_combos.py
-------------------------
Module 7: Unusual Account Combination Detection for the KKC JE Testing Tool.

SA Reference: SA 315

Journal entries with unusual debit/credit account pairings may indicate:
  - Misclassification of transactions
  - Earnings management (provision reversals into income)
  - Bypassing normal procurement controls (expense direct to cash)
  - Deliberate obfuscation through suspense/clearing accounts

Two detection approaches are applied simultaneously:

  Part A — Statistical Rarity
      Build a frequency table of all (debit_account, credit_account) pairs
      across the full population.  Any pair that appears fewer than
      RARE_COMBO_THRESHOLD (default 3) times is flagged as unusual.
      Rare does not necessarily mean wrong — but it warrants explanation.

  Part B — Rule-Based High-Risk Flags
      Flag entries matching specific risky patterns regardless of frequency:
        B1. Suspense / Clearing keywords in either account name
            ("suspense", "clearing", "adjustment", "transit")
        B2. Income/Revenue account on the debit side → Cash/Bank on credit
            (unusual: cash receipt of revenue is typically a credit entry)
        B3. Expense/P&L account on the debit side → Cash/Bank on credit
            (possible direct payment bypassing procurement workflow)
        B4. Provision account on the debit side → Income account on credit
            (provision reversal directly into income — earnings-management risk)

  Account Classification
      Type is determined in this priority order:
        1. User-supplied Chart of Accounts (COA) mapping CSV
           Columns: account_code, account_type
           Valid types: Revenue, Expense, Asset, Liability, Equity, Provision, Cash
        2. Account-code range inference (numeric codes, Indian CoA convention):
           1xxx–3xxx  → Asset / Liability
           4xxx       → Revenue
           5xxx–8xxx  → Expense
           9xxx       → Provision / Reserve
        3. Account-name keyword inference (always applied as a fallback):
           Keywords are matched case-insensitively against the account name.

Risk Rating (per CLAUDE.md):
  High   — any Part B rule-based flag exists
  Medium — Part A rare combinations > 2% of population (no Part B flags)
  Low    — rare combos <= 2%, no Part B flags
"""

from __future__ import annotations

import re
import pandas as pd
import plotly.graph_objects as go
from typing import Optional

try:
    from config import (
        RARE_COMBO_THRESHOLD,
        KKC_GREEN,
        KKC_GREY,
        KKC_LIGHT_GREY,
        RISK_RED,
        RISK_ORANGE,
    )
except ImportError:
    RARE_COMBO_THRESHOLD = 3
    KKC_GREEN            = "#7CB542"
    KKC_GREY             = "#808285"
    KKC_LIGHT_GREY       = "#F2F2F2"
    RISK_RED             = "#FF0000"
    RISK_ORANGE          = "#FFA500"

_MEDIUM_THRESHOLD = 0.02   # Part A rare combos > 2% of population → Medium

# ── Account-type keyword maps ────────────────────────────────────────────────
# Each key is a canonical type; value is a list of substrings matched
# case-insensitively anywhere in the account name.

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "Revenue": [
        "income", "revenue", "sales", "turnover", "receipts",
        "interest income", "dividend income", "other income",
        "commission income", "fees earned",
    ],
    "Expense": [
        "expense", "expenditure", "cost", "depreciation", "amortisation",
        "amortization", "wages", "salary", "salaries", "rent expense",
        "insurance expense", "repairs", "utilities", "freight",
        "professional fee", "audit fee", "advertisement",
    ],
    "Provision": [
        "provision", "reserve", "allowance", "impairment",
        "bad debt", "doubtful",
    ],
    "Cash": [
        "cash", "bank", "petty cash", "current account", "savings account",
        "overdraft", "cash in hand", "cash at bank",
    ],
    "Suspense": [
        "suspense", "clearing", "adjustment", "transit",
        "inter-company", "intercompany", "bridge account",
    ],
}

# Numeric account-code ranges (Indian CoA convention — leading digit only)
_CODE_RANGE_TYPE: dict[str, str] = {
    "1": "Asset",
    "2": "Liability",
    "3": "Equity",
    "4": "Revenue",
    "5": "Expense",
    "6": "Expense",
    "7": "Expense",
    "8": "Expense",
    "9": "Provision",
}


# ---------------------------------------------------------------------------
# Account classification helpers
# ---------------------------------------------------------------------------

def _classify_by_coa(
    account: str,
    coa_map: dict[str, str],
) -> Optional[str]:
    """
    Look up account type from a user-supplied COA mapping dict.

    Args:
        account: Account code or name string from the journal entry.
        coa_map: Dict of {account_code: account_type} from the uploaded COA CSV.

    Returns:
        Account type string, or None if not found in the mapping.
    """
    return coa_map.get(str(account).strip()) if coa_map else None


def _classify_by_code_range(account: str) -> Optional[str]:
    """
    Infer account type from the leading digit of a numeric account code.

    Only applies when the account value is (or starts with) a digit.
    Uses the Indian Chart of Accounts convention where:
      1xxx–3xxx = Balance Sheet, 4xxx = Revenue, 5–8xxx = Expense, 9xxx = Provision.

    Args:
        account: Account code string.

    Returns:
        Account type string, or None if the code is not numeric / unrecognised.
    """
    stripped = str(account).strip()
    # Extract a leading digit sequence (ignore alpha prefixes like "ACC-4001")
    match = re.search(r"\d", stripped)
    if not match:
        return None
    leading = stripped[match.start()]
    return _CODE_RANGE_TYPE.get(leading)


def _classify_by_keywords(account: str) -> Optional[str]:
    """
    Infer account type by matching the account name against keyword lists.

    Each canonical type in _TYPE_KEYWORDS is checked in priority order:
    Suspense > Cash > Provision > Revenue > Expense.
    The first match wins.

    Args:
        account: Account name or code string.

    Returns:
        Account type string, or None if no keywords match.
    """
    lower = str(account).strip().lower()
    # Priority order: Suspense first (always high-risk regardless of other types)
    for acct_type in ["Suspense", "Cash", "Provision", "Revenue", "Expense"]:
        for kw in _TYPE_KEYWORDS[acct_type]:
            if kw in lower:
                return acct_type
    return None


def classify_account(
    account: str,
    coa_map: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """
    Determine the account type using the three-tier classification cascade.

    Priority:
      1. User-supplied COA mapping (most authoritative)
      2. Numeric code-range inference
      3. Account-name keyword matching (most flexible fallback)

    Args:
        account: Account code or name value from the journal entry.
        coa_map: Optional dict {account_code: account_type}.

    Returns:
        Account type string (e.g. "Revenue", "Expense", "Cash", "Provision",
        "Suspense", "Asset", "Liability", "Equity"), or None if unknown.
    """
    if not account or pd.isna(account):
        return None

    # Tier 1: COA mapping (most authoritative — explicit user classification)
    t = _classify_by_coa(str(account), coa_map or {})
    if t:
        return t

    # Tier 2: keyword inference (more specific than code ranges — e.g.
    # "1001 Cash in Hand" should be "Cash", not the generic "Asset" that
    # code-range 1xxx would return; "9001 Provision Bad Debts" → "Provision"
    # rather than the ambiguous "Provision/Reserve" from 9xxx range).
    t = _classify_by_keywords(str(account))
    if t:
        return t

    # Tier 3: numeric code-range (broad fallback for bare account codes
    # that carry no descriptive name, e.g. plain "4001" → Revenue)
    return _classify_by_code_range(str(account))


def load_coa_mapping(coa_df: Optional[pd.DataFrame]) -> dict[str, str]:
    """
    Convert a user-uploaded COA DataFrame into a {account_code: type} dict.

    The DataFrame must contain at least two columns.  The function looks
    for columns named (case-insensitively) "account_code" and "account_type"
    (or their common aliases).  If exact names are not found, the first two
    columns are used as (code, type) respectively.

    Args:
        coa_df: DataFrame from the uploaded COA CSV, or None.

    Returns:
        Dict mapping account code string → account type string.
        Returns empty dict if coa_df is None or malformed.
    """
    if coa_df is None or coa_df.empty:
        return {}

    cols = [c.lower().strip() for c in coa_df.columns]

    code_aliases = {"account_code", "account", "code", "acc_code", "gl_code"}
    type_aliases = {"account_type", "type", "classification", "category"}

    code_col = next((coa_df.columns[i] for i, c in enumerate(cols)
                     if c in code_aliases), coa_df.columns[0])
    type_col = next((coa_df.columns[i] for i, c in enumerate(cols)
                     if c in type_aliases), coa_df.columns[1])

    return {
        str(row[code_col]).strip(): str(row[type_col]).strip()
        for _, row in coa_df.iterrows()
        if pd.notna(row[code_col]) and pd.notna(row[type_col])
    }


# ---------------------------------------------------------------------------
# Part A — Statistical rarity
# ---------------------------------------------------------------------------

def _detect_rare_combos(
    df: pd.DataFrame,
    debit_col: str,
    credit_col: str,
    threshold: int,
) -> pd.Series:
    """
    Flag entries whose (debit_account, credit_account) pair appears fewer
    than `threshold` times in the full population.

    Args:
        df:         Working dataframe.
        debit_col:  Column name for debit account.
        credit_col: Column name for credit account.
        threshold:  Minimum occurrences to be considered "normal".

    Returns:
        Boolean Series — True where the combo is rare.
    """
    pair_counts = df.groupby([debit_col, credit_col], dropna=False).transform("count")
    # groupby+transform returns a DataFrame; take the first column
    counts_series = pair_counts.iloc[:, 0]
    return counts_series < threshold


# ---------------------------------------------------------------------------
# Part B — Rule-based high-risk flags
# ---------------------------------------------------------------------------

def _b1_suspense_keywords(
    dr_type: pd.Series,
    cr_type: pd.Series,
    dr_col: pd.Series,
    cr_col: pd.Series,
) -> pd.Series:
    """
    Flag entries where either account is of type "Suspense" (keyword match
    for suspense / clearing / adjustment / transit in the account name or
    classification).

    Args:
        dr_type: Series of classified debit account types.
        cr_type: Series of classified credit account types.
        dr_col:  Raw debit account name/code column (used for direct keyword scan).
        cr_col:  Raw credit account name/code column.

    Returns:
        Boolean Series.
    """
    # Type-based detection (catches COA-mapped and keyword-inferred Suspense)
    type_flag = (dr_type == "Suspense") | (cr_type == "Suspense")

    # Direct keyword scan on raw account name as additional safety net
    suspense_kws = _TYPE_KEYWORDS["Suspense"]
    def _has_kw(val) -> bool:
        if pd.isna(val):
            return False
        lower = str(val).lower()
        return any(kw in lower for kw in suspense_kws)

    name_flag = dr_col.apply(_has_kw) | cr_col.apply(_has_kw)
    return type_flag | name_flag


def _b2_income_dr_cash_cr(
    dr_type: pd.Series,
    cr_type: pd.Series,
) -> pd.Series:
    """
    Flag entries where a Revenue/Income account is debited and Cash/Bank is
    credited.  This pattern (e.g. DR Income / CR Cash) is highly unusual —
    it would represent a cash payment of income, which is almost never a
    legitimate business transaction without specific explanation.

    Args:
        dr_type: Series of classified debit account types.
        cr_type: Series of classified credit account types.

    Returns:
        Boolean Series.
    """
    return (dr_type == "Revenue") & (cr_type == "Cash")


def _b3_expense_dr_cash_cr(
    dr_type: pd.Series,
    cr_type: pd.Series,
) -> pd.Series:
    """
    Flag entries where an Expense/P&L account is debited and Cash/Bank is
    credited.  While direct cash payments do occur legitimately (petty cash),
    a high prevalence of such entries may indicate bypassing of the normal
    procurement / accounts-payable workflow.

    Args:
        dr_type: Series of classified debit account types.
        cr_type: Series of classified credit account types.

    Returns:
        Boolean Series.
    """
    return (dr_type == "Expense") & (cr_type == "Cash")


def _b4_provision_dr_income_cr(
    dr_type: pd.Series,
    cr_type: pd.Series,
) -> pd.Series:
    """
    Flag entries where a Provision account is debited and an Income/Revenue
    account is credited.  This pattern — reversing a provision directly into
    income — is an earnings-management red flag and may indicate cut-off
    manipulation.

    Args:
        dr_type: Series of classified debit account types.
        cr_type: Series of classified credit account types.

    Returns:
        Boolean Series.
    """
    return (dr_type == "Provision") & (cr_type == "Revenue")


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def _build_chart(
    flagged: pd.DataFrame,
    population_count: int,
) -> go.Figure:
    """
    Build a horizontal bar chart showing the count of flagged entries by
    flag type (Part A Rare Combo / Part B rule categories).

    Args:
        flagged:          Flagged entries DataFrame with "Combo_Flag_Type" column.
        population_count: Total population size.

    Returns:
        Plotly Figure.
    """
    if flagged.empty:
        fig = go.Figure()
        fig.update_layout(title="No unusual account combinations detected.")
        return fig

    # Count distinct flag-type labels
    all_labels: dict[str, int] = {}
    for cell in flagged["Combo_Flag_Type"]:
        for part in str(cell).split(" | "):
            part = part.strip()
            all_labels[part] = all_labels.get(part, 0) + 1

    label_order = sorted(all_labels.keys(),
                         key=lambda x: (0 if x.startswith("Part B") else 1, x))
    counts  = [all_labels[l] for l in label_order]
    colours = [
        RISK_RED if l.startswith("Part B") else RISK_ORANGE
        for l in label_order
    ]

    pct = len(flagged) / population_count * 100 if population_count else 0

    fig = go.Figure(go.Bar(
        x=counts,
        y=label_order,
        orientation="h",
        marker_color=colours,
        text=[str(c) for c in counts],
        textposition="outside",
        hovertemplate="%{y}: %{x} entries<extra></extra>",
    ))

    fig.update_layout(
        title=dict(
            text=(
                f"Unusual Account Combinations  —  "
                f"{len(flagged):,} of {population_count:,} entries flagged "
                f"({pct:.1f}%)"
            ),
            font=dict(size=14),
        ),
        xaxis_title="Number of Entries",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Source Sans Pro, Arial, sans-serif", size=12),
        xaxis=dict(gridcolor=KKC_LIGHT_GREY),
        yaxis=dict(autorange="reversed"),
        margin=dict(t=80, b=40, l=200, r=60),
    )

    return fig


# ---------------------------------------------------------------------------
# Risk rating
# ---------------------------------------------------------------------------

def _determine_risk(
    has_part_b: bool,
    rare_pct: float,
) -> str:
    """
    Determine the module risk rating per CLAUDE.md.

    Args:
        has_part_b: True if any Part B rule-based flag exists.
        rare_pct:   Fraction of population flagged by Part A alone (0.0–1.0).

    Returns:
        "High"   — any Part B flag exists
        "Medium" — no Part B, but rare combos > 2% of population
        "Low"    — no Part B, rare combos <= 2%
    """
    if has_part_b:
        return "High"
    if rare_pct > _MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    df: pd.DataFrame,
    debit_col: str       = "debit_account",
    credit_col: str      = "credit_account",
    coa_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Execute unusual account combination detection on a JE population.

    Runs two passes:
      Part A — flags statistically rare (debit, credit) pairs
      Part B — flags entries matching four high-risk rule patterns

    A single entry may be flagged by both Part A and one or more Part B
    rules.  The "Combo_Flag_Type" output column is pipe-separated for
    multi-label hits (e.g. "Part A: Rare Combo | Part B1: Suspense/Clearing").

    The module requires at least one of debit_col or credit_col to be
    present.  If both are absent it returns a zero-flag result with a
    note in summary_stats.

    Args:
        df:         Full population DataFrame with standard column names.
        debit_col:  Column name for the debit account. Defaults to "debit_account".
        credit_col: Column name for the credit account. Defaults to "credit_account".
        coa_df:     Optional DataFrame from a user-uploaded Chart of Accounts CSV
                    containing (account_code, account_type) columns.  When supplied,
                    account classification uses this mapping first before falling
                    back to code-range and keyword inference.

    Returns:
        Standard module result dict:
        {
            "module_name":       str — "Unusual Account Combinations",
            "flagged_df":        pd.DataFrame — flagged entries with added columns:
                                  Combo_Flag_Type  (pipe-separated label),
                                  DR_Account_Type  (inferred type),
                                  CR_Account_Type  (inferred type),
                                  Pair_Frequency   (how often this combo appears),
            "flag_count":        int,
            "population_count":  int,
            "flag_pct":          float,
            "risk_rating":       str — "High" / "Medium" / "Low",
            "summary_stats":     dict — part_a_count, part_b_count,
                                  part_b_breakdown (dict per rule),
                                  rare_combo_threshold,
                                  top_rare_combos (DataFrame),
                                  columns_absent (list),
            "chart":             plotly Figure,
        }
    """
    population_count = len(df)
    coa_map = load_coa_mapping(coa_df)

    # ── Check required columns ────────────────────────────────────────────────
    has_dr = debit_col  in df.columns
    has_cr = credit_col in df.columns
    columns_absent = (
        ([debit_col]  if not has_dr else []) +
        ([credit_col] if not has_cr else [])
    )

    if not has_dr and not has_cr:
        empty_chart = _build_chart(df.head(0), population_count)
        return {
            "module_name":      "Unusual Account Combinations",
            "flagged_df":       df.head(0).copy(),
            "flag_count":       0,
            "population_count": population_count,
            "flag_pct":         0.0,
            "risk_rating":      "Low",
            "summary_stats": {
                "part_a_count": 0, "part_b_count": 0,
                "part_b_breakdown": {},
                "rare_combo_threshold": RARE_COMBO_THRESHOLD,
                "top_rare_combos": pd.DataFrame(),
                "columns_absent": columns_absent,
                "note": "Both debit_account and credit_account columns absent — module skipped.",
            },
            "chart": empty_chart,
        }

    working = df.copy()

    # ── Fill missing account column with a placeholder ────────────────────────
    if not has_dr:
        working[debit_col]  = "(no debit column)"
    if not has_cr:
        working[credit_col] = "(no credit column)"

    # ── Classify account types ────────────────────────────────────────────────
    working["DR_Account_Type"] = working[debit_col].apply(
        lambda x: classify_account(x, coa_map)
    )
    working["CR_Account_Type"] = working[credit_col].apply(
        lambda x: classify_account(x, coa_map)
    )

    dr_type = working["DR_Account_Type"]
    cr_type = working["CR_Account_Type"]

    # ── Part A: statistical rarity ────────────────────────────────────────────
    mask_rare = _detect_rare_combos(
        working, debit_col, credit_col, RARE_COMBO_THRESHOLD
    )

    # Pair frequency column (for output)
    pair_freq = working.groupby(
        [debit_col, credit_col], dropna=False
    )[debit_col].transform("count")

    # ── Part B: rule-based ────────────────────────────────────────────────────
    mask_b1 = _b1_suspense_keywords(
        dr_type, cr_type, working[debit_col], working[credit_col]
    )
    mask_b2 = _b2_income_dr_cash_cr(dr_type, cr_type)
    mask_b3 = _b3_expense_dr_cash_cr(dr_type, cr_type)
    mask_b4 = _b4_provision_dr_income_cr(dr_type, cr_type)

    any_part_b = mask_b1 | mask_b2 | mask_b3 | mask_b4
    any_flag   = mask_rare | any_part_b

    # ── Build pipe-separated flag label ──────────────────────────────────────
    labels = pd.Series("", index=working.index)

    def _append(mask: pd.Series, label: str) -> None:
        labels[mask] = labels[mask].apply(
            lambda x, lbl=label: lbl if x == "" else f"{x} | {lbl}"
        )

    _append(mask_rare, "Part A: Rare Combo")
    _append(mask_b1,   "Part B1: Suspense/Clearing")
    _append(mask_b2,   "Part B2: Income DR / Cash CR")
    _append(mask_b3,   "Part B3: Expense DR / Cash CR")
    _append(mask_b4,   "Part B4: Provision DR / Income CR")

    # ── Assemble flagged dataframe ────────────────────────────────────────────
    flagged = working[any_flag].copy()
    flagged["Combo_Flag_Type"] = labels[any_flag]
    flagged["Pair_Frequency"]  = pair_freq[any_flag].astype(int)

    # Drop internal type columns that were added to working (keep on flagged)
    flag_count = len(flagged)
    flag_pct   = round(flag_count / population_count, 6) if population_count else 0.0

    # ── Part A only count (rare but no Part B) ────────────────────────────────
    part_a_only_mask = mask_rare & ~any_part_b
    rare_only_pct    = round(part_a_only_mask.sum() / population_count, 6) \
                       if population_count else 0.0

    # ── Risk rating ───────────────────────────────────────────────────────────
    risk_rating = _determine_risk(bool(any_part_b.any()), rare_only_pct)

    # ── Top rare combos summary (Part A) ─────────────────────────────────────
    if mask_rare.any():
        rare_pairs = (
            working[mask_rare]
            .groupby([debit_col, credit_col], dropna=False)
            .size()
            .reset_index(name="Count")
            .sort_values("Count")
            .head(10)
        )
    else:
        rare_pairs = pd.DataFrame(columns=[debit_col, credit_col, "Count"])

    # ── Chart ─────────────────────────────────────────────────────────────────
    chart = _build_chart(flagged, population_count)

    summary_stats = {
        "part_a_count":        int(mask_rare.sum()),
        "part_b_count":        int(any_part_b.sum()),
        "part_b_breakdown": {
            "B1_suspense_clearing":   int(mask_b1.sum()),
            "B2_income_dr_cash_cr":   int(mask_b2.sum()),
            "B3_expense_dr_cash_cr":  int(mask_b3.sum()),
            "B4_provision_dr_income": int(mask_b4.sum()),
        },
        "rare_combo_threshold": RARE_COMBO_THRESHOLD,
        "top_rare_combos":      rare_pairs,
        "columns_absent":       columns_absent,
        "coa_map_loaded":       len(coa_map) > 0,
    }

    return {
        "module_name":      "Unusual Account Combinations",
        "flagged_df":       flagged,
        "flag_count":       flag_count,
        "population_count": population_count,
        "flag_pct":         flag_pct,
        "risk_rating":      risk_rating,
        "summary_stats":    summary_stats,
        "chart":            chart,
    }

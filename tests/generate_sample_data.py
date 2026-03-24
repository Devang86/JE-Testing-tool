"""
tests/generate_sample_data.py
------------------------------
Generates a 5,000-row synthetic journal-entry dataset with precisely
planted anomalies for testing the KKC JE Testing Tool.

Anomaly manifest (per CLAUDE.md):
  ┌──────────────────────────────────────────┬───────┬──────────────────────────────────────┐
  │ Anomaly type                             │ Count │ Notes                                │
  ├──────────────────────────────────────────┼───────┼──────────────────────────────────────┤
  │ Exact duplicate entries                  │   50  │ Same amount, accounts, date          │
  │ Near-duplicate entries                   │   30  │ Same amount/accounts, different day  │
  │ Round lakh entries                       │   80  │ Divisible by ₹1,00,000 exactly       │
  │ Weekend postings                         │   60  │ Saturday or Sunday                   │
  │ After-hours postings                     │   80  │ Before 09:00 or after 19:00          │
  │ Period-end entries (last 3 days)         │  100  │ Spread across months                 │
  │ Blank narration                          │  120  │ Null / empty string                  │
  │ Generic narration                        │   30  │ "NA", "NIL", "misc", etc.            │
  │ Benford's anomalies (digit 5 & 7)        │   40  │ Amounts starting with 5 or 7         │
  │ Keyword hits                             │   50  │ Mix of HIGH_RISK_KEYWORDS            │
  │ Self-approved entries                    │    8  │ prepared_by == approved_by           │
  │ Unusual account combos (Dr P&L / Cr Cash)│   20  │ Part-B rule-based flag               │
  └──────────────────────────────────────────┴───────┴──────────────────────────────────────┘

Some entries are deliberately multi-anomaly (e.g., a weekend + after-hours entry,
or a period-end + blank narration entry).  The printed summary shows the planted
index ranges so you can validate module output against known ground truth.

Usage:
    cd "JE testing tool"
    python tests/generate_sample_data.py

Output:
    tests/sample_je_data.xlsx   — ready to upload into the Streamlit app
"""

from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

# ── Reproducibility ───────────────────────────────────────────────────────────
SEED = 42
rng  = np.random.default_rng(SEED)
random.seed(SEED)

# ── Output path ───────────────────────────────────────────────────────────────
_HERE        = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH  = os.path.join(_HERE, "sample_je_data.xlsx")

# ── Population parameters ─────────────────────────────────────────────────────
TOTAL_ROWS   = 5_000
FY_START     = date(2024, 4, 1)    # Indian FY 2024-25
FY_END       = date(2025, 3, 31)
FY_DAYS      = (FY_END - FY_START).days + 1

# ── Anomaly counts (per CLAUDE.md) ────────────────────────────────────────────
N_EXACT_DUP    = 50
N_NEAR_DUP     = 30
N_ROUND_LAKH   = 80
N_WEEKEND      = 60
N_AFTER_HOURS  = 80
N_PERIOD_END   = 100
N_BLANK_NARR   = 120
N_GENERIC_NARR = 30
N_BENFORD      = 40
N_KEYWORDS     = 50
N_SELF_APPR    = 8
N_UNUSUAL_COMBO= 20


# ── Reference data ─────────────────────────────────────────────────────────────

USERS = [
    "Amit Sharma", "Priya Mehta", "Rahul Joshi", "Sunita Patel",
    "Deepak Nair",  "Neha Gupta",  "Ravi Kumar",  "Manish Singh",
    "Kavita Desai", "Arjun Rao",
]
APPROVERS = [
    "CA Prakash", "CA Desai", "CA Verma", "Manager Finance",
]

# Realistic Indian GL account structure
ASSET_ACCOUNTS = [
    "1001 Cash in Hand", "1002 HDFC Bank A/c", "1003 ICICI Bank A/c",
    "1010 Petty Cash",   "1101 Trade Receivables", "1102 Advance to Staff",
    "1103 Security Deposits", "1201 Raw Material Stock", "1202 WIP Stock",
    "1203 Finished Goods",   "1301 Prepaid Expenses",  "1302 Advance Tax",
]
LIABILITY_ACCOUNTS = [
    "2001 Trade Payables",     "2002 Expense Payables",
    "2003 TDS Payable",        "2004 GST Payable",
    "2005 Salary Payable",     "2006 Advance from Customers",
    "2101 Bank OD – Axis",     "2201 Long-term Loan – SBI",
]
EQUITY_ACCOUNTS = [
    "3001 Share Capital",  "3002 Securities Premium",
    "3003 General Reserve","3004 Retained Earnings",
]
REVENUE_ACCOUNTS = [
    "4001 Domestic Sales",      "4002 Export Sales",
    "4003 Service Income",      "4004 Commission Income",
    "4005 Interest Income",     "4006 Misc Income",
]
EXPENSE_ACCOUNTS = [
    "5001 Rent Expense",       "5002 Salary & Wages",
    "5003 Electricity Charges","5004 Office Supplies",
    "5005 Travel & Conveyance","5006 Professional Fees",
    "5007 Printing & Stationery","5008 Telephone Charges",
    "5009 Repairs & Maintenance","5010 Advertisement Expense",
    "5011 Insurance Premium",   "5012 Bank Charges",
    "5013 Freight & Forwarding","5014 Miscellaneous Expense",
]
PROVISION_ACCOUNTS = [
    "9001 Provision for Bad Debts",
    "9002 Provision for Gratuity",
    "9003 Provision for Taxation",
    "9004 Provision for Warranty",
]
SUSPENSE_ACCOUNTS = [
    "8001 Suspense A/c",
    "8002 Clearing Account",
    "8003 Adjustment A/c",
]

# "Normal" debit/credit pairs for clean transactions
NORMAL_PAIRS = [
    # Operating expenses
    ("5001 Rent Expense",       "1002 HDFC Bank A/c"),
    ("5002 Salary & Wages",     "2005 Salary Payable"),
    ("5003 Electricity Charges","2002 Expense Payables"),
    ("5004 Office Supplies",    "1002 HDFC Bank A/c"),
    ("5005 Travel & Conveyance","1001 Cash in Hand"),
    ("5006 Professional Fees",  "2002 Expense Payables"),
    ("5009 Repairs & Maintenance","1002 HDFC Bank A/c"),
    ("5010 Advertisement Expense","2001 Trade Payables"),
    ("5011 Insurance Premium",  "1002 HDFC Bank A/c"),
    ("5012 Bank Charges",       "1002 HDFC Bank A/c"),
    ("5013 Freight & Forwarding","2001 Trade Payables"),
    # Revenue recognition
    ("1101 Trade Receivables",  "4001 Domestic Sales"),
    ("1101 Trade Receivables",  "4002 Export Sales"),
    ("1002 HDFC Bank A/c",      "4003 Service Income"),
    ("1002 HDFC Bank A/c",      "4004 Commission Income"),
    # Payments
    ("2001 Trade Payables",     "1002 HDFC Bank A/c"),
    ("2001 Trade Payables",     "1003 ICICI Bank A/c"),
    ("2005 Salary Payable",     "1002 HDFC Bank A/c"),
    ("2003 TDS Payable",        "1002 HDFC Bank A/c"),
    ("2004 GST Payable",        "1002 HDFC Bank A/c"),
    # Asset movements
    ("1201 Raw Material Stock", "2001 Trade Payables"),
    ("1301 Prepaid Expenses",   "1002 HDFC Bank A/c"),
    ("1103 Security Deposits",  "1002 HDFC Bank A/c"),
    # Provisions
    ("5002 Salary & Wages",     "9002 Provision for Gratuity"),
    ("5014 Miscellaneous Expense","9001 Provision for Bad Debts"),
]

NORMAL_NARRATIONS = [
    "Monthly rent payment for {mon}",
    "Salary disbursement for {mon}",
    "Electricity bill payment for {mon}",
    "Purchase of office supplies",
    "Travel reimbursement – {user}",
    "Professional fees for audit",
    "Repair and maintenance of office premises",
    "Advertisement in Economic Times",
    "Insurance premium for FY 2024-25",
    "Bank charges for {mon}",
    "Freight charges on inward shipment",
    "Trade receivable booked for invoice #{inv}",
    "Export sales booking – shipment #{inv}",
    "Service income from contract #{inv}",
    "Commission income from agent",
    "Payment to vendor – bill #{inv}",
    "Salary payable cleared for {mon}",
    "TDS deposited for {mon}",
    "GST payment for {mon}",
    "Raw material purchased from supplier",
    "Prepaid insurance adjusted",
    "Security deposit paid to landlord",
    "Gratuity provision for {mon}",
    "Interest received from FD",
    "Advance recovered from staff",
]

KEYWORD_NARRATIONS = [
    "Adjustment entry for depreciation reversal",
    "Correcting entry for prior period error",
    "Write-off of bad debts per management approval",
    "Reversal of opening provision",
    "One-time misc charge for quarter end",
    "Reclassification of expense account",
    "Manual entry for off balance sheet item",
    "Rectification entry as per boss instruction",
    "Suspense account clearing for March",
    "Prior period adjustment per CA review",
    "Direct entry approved by director",
    "Dummy entry for system testing",
    "Back date correction for April 2024",
    "Error correction in debit account",
    "Override entry as per management override",
    "Provision reversal for FY 2023-24",
    "Test entry – to be reversed",
    "Trial balance adjustment",
    "Reclass of advance to expense",
    "Management override for year-end entry",
]

GENERIC_NARRATIONS = ["NA", "N/A", "NIL", "NONE", "misc", "Misc", "Test", "TEMP", "na", "-"]


# ── Helper functions ───────────────────────────────────────────────────────────

def _random_weekday(start: date, end: date) -> date:
    """Return a random weekday (Mon–Fri) within [start, end]."""
    while True:
        d = start + timedelta(days=int(rng.integers(0, (end - start).days + 1)))
        if d.weekday() < 5:
            return d


def _random_weekend(start: date, end: date) -> date:
    """Return a random Saturday or Sunday within [start, end]."""
    while True:
        d = start + timedelta(days=int(rng.integers(0, (end - start).days + 1)))
        if d.weekday() >= 5:
            return d


def _month_last_day(y: int, m: int) -> int:
    """Return the last calendar day of the given year/month."""
    import calendar
    return calendar.monthrange(y, m)[1]


def _period_end_date() -> date:
    """Return a random date in the last 3 days of a random month in the FY."""
    months = list(range(4, 13)) + list(range(1, 4))  # Apr 2024 – Mar 2025
    years  = [2024] * 9 + [2025] * 3
    idx    = int(rng.integers(0, 12))
    m, y   = months[idx], years[idx]
    last   = _month_last_day(y, m)
    day    = int(rng.integers(last - 2, last + 1))  # last-2, last-1, last
    return date(y, m, day)


def _business_time() -> str:
    """Return a random time within business hours (09:00–18:59)."""
    h = int(rng.integers(9, 19))
    m = int(rng.integers(0, 60))
    return f"{h:02d}:{m:02d}:00"


def _after_hours_time() -> str:
    """Return a random time outside business hours (before 09:00 or ≥ 19:00)."""
    if rng.random() < 0.5:
        h = int(rng.integers(0, 9))   # 00:00 – 08:59
    else:
        h = int(rng.integers(19, 24)) # 19:00 – 23:59
    m = int(rng.integers(0, 60))
    return f"{h:02d}:{m:02d}:00"


def _normal_amount() -> float:
    """Return a realistic non-round transaction amount."""
    while True:
        # Log-normal centred around ₹50,000, range roughly ₹5K – ₹25L
        raw = float(np.exp(rng.normal(10.8, 1.2)))
        raw = round(raw, 2)
        # Reject exact round thousands/lakhs to keep clean rows clean
        if raw % 1000 != 0:
            return raw


def _round_lakh_amount() -> float:
    """Return an amount that is exactly divisible by ₹1,00,000."""
    lakhs = int(rng.integers(1, 51))   # ₹1L – ₹50L
    return float(lakhs * 100_000)


def _benford_amount() -> float:
    """Return an amount whose first significant digit is 5 or 7."""
    digit = rng.choice([5, 7])
    # Produce amounts in the range where the digit is leading
    # e.g. digit=5 → 50,000–59,999 or 5,00,000–5,99,999
    magnitude = rng.choice([10_000, 100_000, 1_000_000])
    raw = digit * magnitude + int(rng.integers(0, magnitude))
    return float(round(raw + rng.uniform(0.01, 0.99), 2))


def _narration(user: str) -> str:
    """Return a realistic normal narration string."""
    template = random.choice(NORMAL_NARRATIONS)
    mon = FY_START.strftime("%B %Y")
    inv = str(int(rng.integers(1000, 9999)))
    return template.format(mon=mon, user=user.split()[0], inv=inv)


def _je_number(idx: int) -> str:
    return f"JE-{2024:04d}-{idx:05d}"


# ── Base population builder ────────────────────────────────────────────────────

def _build_base(n: int) -> pd.DataFrame:
    """
    Build n clean, realistic journal entry rows.

    Each row gets a weekday posting date, a business-hours time, a normal
    (non-round) amount, a realistic debit/credit pair, and a meaningful
    narration.  All users are paired with an independent approver.

    Args:
        n: Number of rows to generate.

    Returns:
        DataFrame with standard column names.
    """
    rows = []
    for i in range(n):
        dr, cr   = random.choice(NORMAL_PAIRS)
        user     = random.choice(USERS)
        approver = random.choice(APPROVERS)   # never same as user in base
        post_dt  = _random_weekday(FY_START, FY_END)
        rows.append({
            "je_number":     _je_number(i + 1),
            "posting_date":  post_dt,
            "entry_date":    post_dt,
            "entry_time":    _business_time(),
            "prepared_by":   user,
            "approved_by":   approver,
            "debit_account": dr,
            "credit_account":cr,
            "amount":        _normal_amount(),
            "narration":     _narration(user),
            "entry_type":    "Manual",
            "period":        post_dt.strftime("%b-%Y"),
        })
    return pd.DataFrame(rows)


# ── Anomaly planting functions ─────────────────────────────────────────────────

def _plant_exact_duplicates(df: pd.DataFrame, n: int = 50) -> tuple[pd.DataFrame, list[int]]:
    """
    Plant n exact-duplicate entries.

    Selects n/2 existing rows and appends an identical copy of each
    (same amount, debit_account, credit_account, posting_date).
    Also resets the je_number so they look like separate vouchers.

    Returns:
        Updated DataFrame + list of new row indices.
    """
    sources = df.sample(n // 2, random_state=SEED).copy()
    copies  = sources.copy()
    copies["je_number"] = [
        f"JE-DUP-{i+1:04d}" for i in range(len(copies))
    ]
    new_df = pd.concat([df, copies], ignore_index=True)
    new_idx = list(range(len(df), len(new_df)))
    return new_df, new_idx


def _plant_near_duplicates(df: pd.DataFrame, n: int = 30) -> tuple[pd.DataFrame, list[int]]:
    """
    Plant n near-duplicate entries.

    Same amount, debit_account, credit_account but different day within
    the same calendar month.  The day is shifted by 1–10 days.

    Returns:
        Updated DataFrame + list of new row indices.
    """
    sources = df.sample(n, random_state=SEED + 1).copy()
    copies  = sources.copy()

    new_dates = []
    for _, row in copies.iterrows():
        original: date = row["posting_date"]
        # Shift by 1–10 days while staying in same month
        for delta in range(1, 11):
            candidate = original + timedelta(days=delta)
            if candidate.month == original.month and candidate <= FY_END:
                new_dates.append(candidate)
                break
        else:
            # Shift backwards if forward goes out of month
            candidate = original - timedelta(days=1)
            new_dates.append(max(candidate, FY_START))

    copies["posting_date"] = new_dates
    copies["je_number"] = [f"JE-NDU-{i+1:04d}" for i in range(len(copies))]
    new_df = pd.concat([df, copies], ignore_index=True)
    new_idx = list(range(len(df), len(new_df)))
    return new_df, new_idx


def _plant_round_lakhs(df: pd.DataFrame, n: int = 80) -> list[int]:
    """
    Overwrite n random rows with round-lakh amounts in-place.

    Returns:
        List of modified row indices.
    """
    idxs = rng.choice(len(df), size=n, replace=False).tolist()
    for i in idxs:
        df.at[i, "amount"] = _round_lakh_amount()
    return list(map(int, idxs))


def _plant_weekend_postings(df: pd.DataFrame, n: int = 60) -> list[int]:
    """
    Overwrite posting_date on n rows to a weekend date.

    Returns:
        List of modified row indices.
    """
    idxs = rng.choice(len(df), size=n, replace=False).tolist()
    for i in idxs:
        df.at[i, "posting_date"] = _random_weekend(FY_START, FY_END)
    return list(map(int, idxs))


def _plant_after_hours(df: pd.DataFrame, n: int = 80) -> list[int]:
    """
    Overwrite entry_time on n rows to an after-hours time.

    Returns:
        List of modified row indices.
    """
    idxs = rng.choice(len(df), size=n, replace=False).tolist()
    for i in idxs:
        df.at[i, "entry_time"] = _after_hours_time()
    return list(map(int, idxs))


def _plant_period_end(df: pd.DataFrame, n: int = 100) -> list[int]:
    """
    Overwrite posting_date on n rows to a period-end date (last 3 days of month).

    Returns:
        List of modified row indices.
    """
    idxs = rng.choice(len(df), size=n, replace=False).tolist()
    for i in idxs:
        df.at[i, "posting_date"] = _period_end_date()
    return list(map(int, idxs))


def _plant_blank_narrations(df: pd.DataFrame, n: int = 120) -> list[int]:
    """
    Set narration to NaN or empty string on n rows.

    Returns:
        List of modified row indices.
    """
    idxs = rng.choice(len(df), size=n, replace=False).tolist()
    for i in idxs:
        df.at[i, "narration"] = None if rng.random() < 0.7 else ""
    return list(map(int, idxs))


def _plant_generic_narrations(df: pd.DataFrame, n: int = 30,
                               exclude: list[int] = None) -> list[int]:
    """
    Set narration to a generic placeholder on n rows (avoiding already-blanked rows).

    Returns:
        List of modified row indices.
    """
    exclude_set = set(exclude or [])
    candidates  = [i for i in range(len(df)) if i not in exclude_set]
    idxs = random.sample(candidates, n)
    for i in idxs:
        df.at[i, "narration"] = random.choice(GENERIC_NARRATIONS)
    return idxs


def _plant_benford_anomalies(df: pd.DataFrame, n: int = 40) -> list[int]:
    """
    Overwrite amount on n rows with values whose leading digit is 5 or 7,
    creating an over-representation of those digits for Benford's detection.

    Returns:
        List of modified row indices.
    """
    idxs = rng.choice(len(df), size=n, replace=False).tolist()
    for i in idxs:
        df.at[i, "amount"] = _benford_amount()
    return list(map(int, idxs))


def _plant_keyword_narrations(df: pd.DataFrame, n: int = 50,
                               exclude: list[int] = None) -> list[int]:
    """
    Overwrite narration with high-risk keyword phrases on n rows.

    Returns:
        List of modified row indices.
    """
    exclude_set = set(exclude or [])
    candidates  = [i for i in range(len(df)) if i not in exclude_set]
    idxs = random.sample(candidates, n)
    for i in idxs:
        df.at[i, "narration"] = random.choice(KEYWORD_NARRATIONS)
    return idxs


def _plant_self_approvals(df: pd.DataFrame, n: int = 8) -> list[int]:
    """
    Set approved_by = prepared_by on n rows (exact match or case variant).

    Returns:
        List of modified row indices.
    """
    idxs = rng.choice(len(df), size=n, replace=False).tolist()
    for i in idxs:
        user = df.at[i, "prepared_by"]
        # Occasionally use case variant to test case-insensitive detection
        df.at[i, "approved_by"] = user.upper() if rng.random() < 0.3 else user
    return list(map(int, idxs))


def _plant_unusual_combos(df: pd.DataFrame, n: int = 20) -> list[int]:
    """
    Overwrite debit/credit accounts on n rows with rule-B combinations:
      - Expense DR / Cash CR  (B3 rule)
      - Revenue DR / Cash CR  (B2 rule)
      - Suspense DR / any CR  (B1 rule)

    These are the most clearly flaggable Part-B combos in account_combos.py.

    Returns:
        List of modified row indices.
    """
    idxs = rng.choice(len(df), size=n, replace=False).tolist()
    cash_accounts  = ["1001 Cash in Hand", "1002 HDFC Bank A/c", "1003 ICICI Bank A/c"]
    combo_choices  = [
        # (debit, credit) — all are Part-B flags
        (random.choice(EXPENSE_ACCOUNTS),   random.choice(cash_accounts)),   # B3
        (random.choice(REVENUE_ACCOUNTS),   random.choice(cash_accounts)),   # B2
        (random.choice(SUSPENSE_ACCOUNTS),  random.choice(LIABILITY_ACCOUNTS)), # B1
        (random.choice(PROVISION_ACCOUNTS), random.choice(REVENUE_ACCOUNTS)), # B4
    ]
    for i in idxs:
        dr, cr = random.choice(combo_choices)
        df.at[i, "debit_account"]  = dr
        df.at[i, "credit_account"] = cr
        df.at[i, "narration"]      = "Adjustment entry per management approval"
    return list(map(int, idxs))


# ── Manifest printer ──────────────────────────────────────────────────────────

def _print_manifest(manifest: dict, df: pd.DataFrame) -> None:
    """
    Print a structured summary of all planted anomalies to stdout.

    Args:
        manifest: Dict of anomaly_name → list of row indices.
        df:       Final DataFrame (used for spot-check values).
    """
    W = 72
    print("=" * W)
    print(" KKC JE Testing Tool — Sample Data Generator")
    print(f" Output: tests/sample_je_data.xlsx")
    print(f" Total rows: {len(df):,}  |  FY: Apr 2024 – Mar 2025")
    print("=" * W)
    print()
    print(f"{'Anomaly Type':<42} {'Count':>7}  {'Row range (0-indexed)'}")
    print("-" * W)

    total = 0
    for name, idxs in manifest.items():
        if not idxs:
            continue
        rng_str = f"{min(idxs)}–{max(idxs)}"
        print(f"  {name:<40} {len(idxs):>7,}  rows {rng_str}")
        total += len(idxs)

    print("-" * W)
    print(f"  {'Total planted anomaly instances':<40} {total:>7,}")
    print()

    # Spot-checks
    print("SPOT-CHECK VALUES (verify tool flags these exactly)")
    print("-" * W)

    # Exact duplicates
    dup_idxs = manifest.get("Exact Duplicates (appended rows)", [])
    if dup_idxs:
        r = df.iloc[dup_idxs[0]]
        print(f"  Exact dup sample  je={r['je_number']}  "
              f"date={r['posting_date']}  amt={r['amount']:,.0f}")

    # Round lakhs
    rl_idxs = manifest.get("Round Lakh Amounts", [])
    if rl_idxs:
        r = df.iloc[rl_idxs[0]]
        print(f"  Round lakh sample je={r['je_number']}  "
              f"amt=₹{r['amount']/1e5:.0f}L  ({r['amount']:,.0f})")

    # Weekend
    wk_idxs = manifest.get("Weekend Postings", [])
    if wk_idxs:
        r = df.iloc[wk_idxs[0]]
        day_name = r['posting_date'].strftime("%A")
        print(f"  Weekend sample    je={r['je_number']}  "
              f"date={r['posting_date']}  ({day_name})")

    # After-hours
    ah_idxs = manifest.get("After-Hours Postings", [])
    if ah_idxs:
        r = df.iloc[ah_idxs[0]]
        print(f"  After-hours sample je={r['je_number']}  "
              f"time={r['entry_time']}")

    # Period-end
    pe_idxs = manifest.get("Period-End (last 3 days)", [])
    if pe_idxs:
        r = df.iloc[pe_idxs[0]]
        print(f"  Period-end sample  je={r['je_number']}  "
              f"date={r['posting_date']}")

    # Self-approvals
    sa_idxs = manifest.get("Self-Approvals", [])
    if sa_idxs:
        r = df.iloc[sa_idxs[0]]
        print(f"  Self-approval      je={r['je_number']}  "
              f"maker={r['prepared_by']}  checker={r['approved_by']}")

    # Keywords
    kw_idxs = manifest.get("Keyword Narrations", [])
    if kw_idxs:
        r = df.iloc[kw_idxs[0]]
        print(f"  Keyword sample     je={r['je_number']}  "
              f"narration='{r['narration']}'")

    # Unusual combos
    uc_idxs = manifest.get("Unusual Account Combos", [])
    if uc_idxs:
        r = df.iloc[uc_idxs[0]]
        print(f"  Unusual combo      je={r['je_number']}  "
              f"dr={r['debit_account'][:20]}  cr={r['credit_account'][:20]}")

    print()
    print("EXPECTED MODULE RESULTS (minimum thresholds)")
    print("-" * W)

    # Work out how many are in each module's detection zone
    # Benford: 40 planted, but 80 round lakhs also start with known digits
    n_total = len(df)
    items = [
        ("Benford's Law",                 "High",   "p-value < 0.05 (digit 5 & 7 over-represented)"),
        ("Duplicate Detection",           "High",   f"≥ {N_EXACT_DUP} exact dups + {N_NEAR_DUP} near-dups"),
        ("Round Number Detection",        "Medium", f"{N_ROUND_LAKH} round-lakh entries ({N_ROUND_LAKH/n_total*100:.1f}% of pop)"),
        ("After-Hours & Weekend Postings","High",   f"≥ {N_WEEKEND+N_AFTER_HOURS} entries (> 5% of {n_total:,})"),
        ("Period-End Entry Concentration","High",   f"≥ {N_PERIOD_END} entries in last-3-days band"),
        ("Missing Narration",             "High",   f"{N_BLANK_NARR+N_GENERIC_NARR} blank/generic ({(N_BLANK_NARR+N_GENERIC_NARR)/n_total*100:.1f}%)"),
        ("Unusual Account Combinations",  "High",   f"{N_UNUSUAL_COMBO} Part-B rule-based combos"),
        ("User Analysis",                 "High",   f"{N_SELF_APPR} self-approval entries"),
        ("Keyword Flags",                 "High",   f"≥ {N_KEYWORDS} keyword-narration entries"),
    ]
    for mod, risk, note in items:
        print(f"  {mod:<42} {risk:<8}  {note}")

    print()
    print("=" * W)


# ── Main ──────────────────────────────────────────────────────────────────────

def generate(output_path: str = OUTPUT_PATH) -> pd.DataFrame:
    """
    Generate the full 5,000-row test dataset and save to output_path.

    Args:
        output_path: File path for the output Excel workbook.

    Returns:
        The final DataFrame.
    """
    print(f"\nBuilding base population of {TOTAL_ROWS:,} rows…")
    df = _build_base(TOTAL_ROWS)

    manifest: dict[str, list[int]] = {}

    # ── Plant anomalies ───────────────────────────────────────────────────────
    print("Planting anomalies…")

    # Round lakhs first (so later anomaly plants don't accidentally round them)
    manifest["Round Lakh Amounts"]       = _plant_round_lakhs(df, N_ROUND_LAKH)
    manifest["Benford Digit 5 & 7"]      = _plant_benford_anomalies(df, N_BENFORD)
    manifest["Weekend Postings"]         = _plant_weekend_postings(df, N_WEEKEND)
    manifest["After-Hours Postings"]     = _plant_after_hours(df, N_AFTER_HOURS)
    manifest["Period-End (last 3 days)"] = _plant_period_end(df, N_PERIOD_END)
    manifest["Unusual Account Combos"]   = _plant_unusual_combos(df, N_UNUSUAL_COMBO)
    manifest["Self-Approvals"]           = _plant_self_approvals(df, N_SELF_APPR)

    # Narration anomalies (avoid double-planting on same row)
    manifest["Blank Narrations"]  = _plant_blank_narrations(df, N_BLANK_NARR)
    manifest["Generic Narrations"]= _plant_generic_narrations(
        df, N_GENERIC_NARR, exclude=manifest["Blank Narrations"]
    )
    narr_used = manifest["Blank Narrations"] + manifest["Generic Narrations"]
    manifest["Keyword Narrations"]= _plant_keyword_narrations(
        df, N_KEYWORDS, exclude=narr_used
    )

    # Duplicates are appended (add rows)
    df, dup_exact_idxs = _plant_exact_duplicates(df, N_EXACT_DUP)
    manifest["Exact Duplicates (appended rows)"] = dup_exact_idxs

    df, dup_near_idxs  = _plant_near_duplicates(df, N_NEAR_DUP)
    manifest["Near Duplicates (appended rows)"]  = dup_near_idxs

    # Reset index after appends
    df = df.reset_index(drop=True)

    # Reassign JE numbers sequentially so each row has a unique identifier
    # (except intentional dup JE numbers come from the duplicate plants above)
    print(f"Final dataset: {len(df):,} rows")

    # ── Format dates as Python date objects (Excel will handle them natively) ─
    df["posting_date"] = pd.to_datetime(df["posting_date"]).dt.normalize()
    df["entry_date"]   = pd.to_datetime(df["entry_date"]).dt.normalize()

    # ── Save ──────────────────────────────────────────────────────────────────
    print(f"Saving to {output_path}…")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl", date_format="YYYY-MM-DD") as writer:
        df.to_excel(writer, sheet_name="JE Data", index=False)
        # Second sheet: anomaly manifest for reference
        manifest_rows = [
            {"Anomaly Type": k, "Count": len(v), "Sample Indices": str(v[:5])}
            for k, v in manifest.items()
        ]
        pd.DataFrame(manifest_rows).to_excel(
            writer, sheet_name="Anomaly Manifest", index=False
        )

    # ── Print manifest ─────────────────────────────────────────────────────────
    _print_manifest(manifest, df)

    return df


if __name__ == "__main__":
    generate()
    print(f"Done.  Open the Streamlit app and upload:  tests/sample_je_data.xlsx\n")

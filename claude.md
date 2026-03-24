# KKC Journal Entry Testing Tool
## Project Identity
- **Firm:** KKC & Associates LLP, Chartered Accountants
- **Purpose:** SA 240 Journal Entry Testing — automated, offline, audit-grade
- **Standard:** Designed for use in statutory audits under Standards on Auditing 
  applicable in India (ICAI), with documentation suitable for NFRA inspection
- **Data Security:** Fully offline. No external API calls. No cloud storage. 
  All data stays on the auditor's local machine.
- **Version:** 1.0.0
- **Last Updated:** [Update this when you make changes]

---

## Tech Stack
| Library | Purpose |
|---|---|
| Python 3.11+ | Core runtime |
| Streamlit | Browser-based UI (local only) |
| pandas | Data processing and analysis |
| openpyxl | Excel workpaper generation |
| scipy | Chi-square test for Benford's Law |
| plotly | Interactive charts in UI |
| rapidfuzz | Fuzzy column name matching |
| numpy | Statistical calculations |

---

## Branding
- **Primary Colour:** KKC Green `#7CB542` (RGB: 124, 181, 66)
- **Secondary Colour:** KKC Grey `#808285` (RGB: 128, 130, 133)
- **Font:** Source Sans Pro (use system sans-serif fallback in Streamlit CSS)
- **All output Excel files:** Prefixed with `KKC_JE_`
- **Header rows in Excel:** KKC Green fill, white bold text
- **Alternating data rows:** Light grey `#F2F2F2` every second row
- **Risk colour coding:**
  - High Risk: Red `#FF0000`
  - Medium Risk: Orange `#FFA500`
  - Low Risk: KKC Green `#7CB542`

---

## Project Folder Structure
```
JE-Testing-Tool/
│
├── CLAUDE.md                  ← This file
├── app.py                     ← Main Streamlit application
├── config.py                  ← Constants, thresholds, keyword lists
├── requirements.txt           ← All Python dependencies
├── run.bat                    ← Windows double-click launcher
├── README.md                  ← Team usage instructions
│
├── modules/
│   ├── __init__.py
│   ├── benfords.py            ← Module 1: Benford's Law
│   ├── duplicates.py          ← Module 2: Duplicate JE Detection
│   ├── round_numbers.py       ← Module 3: Round Number Detection
│   ├── after_hours.py         ← Module 4: After-Hours & Weekend Postings
│   ├── period_end.py          ← Module 5: Period-End Entry Concentration
│   ├── no_narration.py        ← Module 6: Missing Narration / Description
│   ├── account_combos.py      ← Module 7: Unusual Account Combinations
│   ├── user_analysis.py       ← Module 8: User-Level Posting Analysis
│   └── keywords.py            ← Module 9: High-Risk Keyword Flagging
│
├── utils/
│   ├── __init__.py
│   ├── column_mapper.py       ← Fuzzy column detection and override UI
│   └── excel_exporter.py      ← Builds the full Excel workpaper
│
└── tests/
    ├── __init__.py
    └── generate_sample_data.py ← Creates 5,000-row test dataset with 
                                   planted anomalies
```

---

## Input File Specification

### Accepted Formats
- Microsoft Excel: `.xlsx`, `.xls`
- Comma Separated Values: `.csv`

### Required Columns (auto-detected via fuzzy matching)
The tool will attempt to map uploaded column names to these standard fields.
If auto-detection fails or is incorrect, the user can override via dropdown.

| Standard Field | Common Column Names in GL Exports |
|---|---|
| `je_number` | JE No, Journal No, Voucher No, Doc No, Document Number |
| `posting_date` | Posting Date, Transaction Date, Date, Value Date |
| `entry_date` | Entry Date, Created Date, Input Date (may differ from posting date) |
| `entry_time` | Entry Time, Created Time, Input Time, Timestamp |
| `prepared_by` | Prepared By, User, Created By, Maker, Posted By, Entered By |
| `approved_by` | Approved By, Authorised By, Checker, Reviewer (optional) |
| `debit_account` | Debit Account, DR Account, Account Code (if single column) |
| `credit_account` | Credit Account, CR Account |
| `amount` | Amount, Debit Amount, DR Amount, Transaction Amount |
| `narration` | Narration, Description, Remarks, Particulars, Text |
| `entry_type` | Entry Type, Journal Type, Source (Manual / Auto / System) |
| `period` | Period, Month, Accounting Period, Fiscal Month |

### Minimum Required Fields
Tool will not run without at least these fields being mapped:
- `posting_date`
- `amount`
- One of `debit_account` or `credit_account`

All other fields: optional (modules that depend on missing fields will 
be skipped with a clear warning shown in the UI).

---

## Module Specifications

### Module 1 — Benford's Law (`modules/benfords.py`)
**SA Reference:** SA 240.A3

**Logic:**
- Extract the first significant digit from the `amount` column
- Only include entries where amount > 0 (exclude negatives and zeros)
- Compute observed frequency vs expected Benford frequency for digits 1-9
- Run chi-square goodness of fit test (scipy.stats.chisquare)
- Flag individual entries where their first digit falls in a category 
  with observed frequency > expected frequency + 2 standard deviations

**Outputs:**
- Chi-square statistic, degrees of freedom, p-value
- Pass/Fail determination
- Plotly bar chart: Observed vs Expected distribution (KKC Green bars, 
  Grey expected line)
- List of flagged entries

**Risk Rating:**
- High: p-value < 0.05 (statistically significant deviation)
- Medium: p-value 0.05 to 0.10
- Low: p-value > 0.10

---

### Module 2 — Duplicate Detection (`modules/duplicates.py`)
**SA Reference:** SA 240.A37

**Logic:**
- **Type A — Exact Duplicate (High):** Same `amount` + same `debit_account` 
  + same `credit_account` + same `posting_date` (same calendar day)
- **Type B — Near Duplicate (Medium):** Same `amount` + same `debit_account` 
  + same `credit_account` + different day within same calendar month
- **Type C — JE Number Duplicate:** Same `je_number` appearing more than once
  (data integrity flag — not necessarily fraud but requires explanation)

**Output columns:** JE Number, Date, Accounts, Amount, Duplicate Type, 
Count of Occurrences

**Risk Rating:**
- High: Any Type A duplicates exist
- Medium: Only Type B or Type C duplicates exist
- Low: No duplicates

---

### Module 3 — Round Number Detection (`modules/round_numbers.py`)
**SA Reference:** SA 240.A37

**Logic:**
- **Round Thousands:** Amount divisible by 1,000 exactly (e.g., 50,000 / 
  2,00,000 / 15,000) — flag as Medium
- **Round Lakhs:** Amount divisible by 1,00,000 exactly — flag as High
- **Round Crores:** Amount divisible by 1,00,00,000 exactly — flag as High
- Exclude amounts below ₹10,000 from round-number flagging to avoid noise
- Compute % of population that is round-number

**Indian number formatting:** Display amounts in Indian numbering system 
(lakhs, crores) throughout the tool wherever amounts are shown.

**Risk Rating:**
- High: Round Lakh or Crore entries > 5% of population
- Medium: Round Thousand entries > 10% of population, or any Round Lakh/Crore
- Low: Below thresholds

---

### Module 4 — After-Hours & Weekend Postings (`modules/after_hours.py`)
**SA Reference:** SA 240.A35

**Logic:**
- **Weekend:** `posting_date` falls on Saturday or Sunday — flag all
- **After Hours:** `entry_time` outside 09:00 to 19:00 — flag if time 
  column exists; skip time check gracefully if column is absent
- **Holiday:** If a holiday list is provided (optional CSV upload), 
  flag entries on public holidays
- Sub-analysis: Group flags by `prepared_by` user — show which users 
  post most entries outside business hours

**Output:** Flagged entries + User frequency table (top 10 after-hours users)

**Risk Rating:**
- High: After-hours or weekend entries > 5% of population
- Medium: 2-5%
- Low: < 2%

---

### Module 5 — Period-End Entry Concentration (`modules/period_end.py`)
**SA Reference:** SA 240.A36

**Logic:**
- Determine last day of each calendar month in the dataset
- **High Risk:** Entry falls in last 3 calendar days of the month
- **Medium Risk:** Entry falls in last 5 calendar days (but not last 3)
- Compute month-wise concentration: which months have highest % of 
  period-end entries
- Flag the final 3 days of the financial year (March 29, 30, 31) as 
  separately highlighted — year-end cut-off risk

**Output:** Flagged entries + Month-wise concentration bar chart

**Risk Rating:**
- High: Period-end entries (last 3 days) > 10% of monthly entries in 
  any month
- Medium: 5-10%
- Low: < 5%

---

### Module 6 — Missing Narration (`modules/no_narration.py`)
**SA Reference:** SA 315.A51

**Logic:**
Flag entries where `narration` is any of:
- `NaN` / `None` / blank / null
- Single character: `.` or `-` or `/`
- Generic placeholders: `NA`, `N/A`, `NIL`, `NONE`, `TEST`, `TEMP`
- Only whitespace characters

**Output:** Count and list of flagged entries, % of population

**Risk Rating:**
- High: > 10% of entries have missing/generic narration
- Medium: 5-10%
- Low: < 5%

---

### Module 7 — Unusual Account Combinations (`modules/account_combos.py`)
**SA Reference:** SA 315

**Logic — Part A: Statistical Rarity**
- Build frequency table of all `debit_account` + `credit_account` pairs
- Flag pairs that appear fewer than 3 times in the full population
- These are statistically unusual combinations requiring explanation

**Logic — Part B: Rule-Based High Risk Flags**
Flag any entry matching these combinations (regardless of frequency):
- Debit: Any Income/Revenue account → Credit: Cash/Bank 
  (unusual: income credited via cash receipt is typically reversed)
- Debit: Any P&L / Expense account → Credit: Cash/Bank 
  (possible direct expense without procurement process)
- Debit: Any Provision account → Credit: Any Income account 
  (provision reversal to income — cut-off / earnings management risk)
- Debit: Suspense account → Credit: Any account
- Debit: Any account → Credit: Suspense account
- Any entry involving accounts with "suspense", "clearing", 
  "adjustment", "transit" in the account name

Account classification (Revenue vs Expense vs Asset vs Liability) 
should be inferred from account code ranges if available, or allow 
user to upload a chart of accounts mapping file (optional CSV).

**Risk Rating:**
- High: Any Part B rule-based flag exists
- Medium: Part A rare combinations > 2% of population
- Low: Only infrequent rare combos, no rule-based flags

---

### Module 8 — User-Level Analysis (`modules/user_analysis.py`)
**SA Reference:** SA 240.A35

**Logic:**
- **Volume Outlier:** Flag users whose entry count > mean + 2 standard 
  deviations across all users
- **Amount Outlier:** Flag users whose total posted amount > mean + 2 
  standard deviations across all users
- **Self-Approval:** Flag entries where `prepared_by` == `approved_by` 
  (maker = checker — segregation of duties violation)
- **Single User Days:** Flag dates where only one user posted all entries 
  (possible override of normal workflow)

**Output:** 
- Top 10 users by volume (count of entries)
- Top 10 users by value (total amount posted)
- Self-approval list
- Volume/amount outlier list

**Risk Rating:**
- High: Any self-approval entries exist
- Medium: Volume or amount outliers exist (no self-approval)
- Low: No outliers or self-approval

---

### Module 9 — High-Risk Keyword Flagging (`modules/keywords.py`)
**SA Reference:** SA 240.A37

**Logic:**
- Scan `narration` column (case-insensitive) for keywords defined in 
  `config.py`
- Flag the entry and record which keyword triggered the flag
- A single entry can match multiple keywords
- Count frequency per keyword across population

**Default Keyword List (defined in config.py — user can add more in UI):**
```
adjustment, adjusted, correcting entry, correction, write-off, write off,
reversal, reversed, reverse, override, overriding, one-time, one time,
misc, miscellaneous, suspense, clearing entry, rectification, rectify,
error correction, prior period, back date, backdated, reclass,
reclassification, provision reversal, manual entry, direct entry,
management override, boss instruction, director instruction, off balance,
testing, test entry, dummy, trial
```

**Risk Rating:**
- High: Keyword flags > 3% of population, OR any entry contains 
  "override", "backdated", "director instruction", "boss instruction"
- Medium: Keyword flags 1-3%
- Low: < 1%

---

## Excel Workpaper Output Specification

### File Naming Convention
```
KKC_JE_Testing_[ClientName]_[Period]_[DDMMYYYY].xlsx
```
Example: `KKC_JE_Testing_ShriramFinance_Mar2025_15042025.xlsx`

### Workbook Structure (12 sheets in this order)

| Sheet # | Sheet Name | Contents |
|---|---|---|
| 1 | Summary Dashboard | Risk table, overall rating, engagement details |
| 2 | Benfords Analysis | Expected vs actual table + chi-square result |
| 3 | Duplicates | All duplicate entries with type classification |
| 4 | Round Numbers | All round-number entries |
| 5 | After Hours Weekend | All after-hours and weekend entries |
| 6 | Period End Entries | All period-end entries with month classification |
| 7 | Missing Narration | All entries with blank/generic narration |
| 8 | Unusual Acct Combos | All unusual account combinations |
| 9 | User Analysis | Outlier users + self-approval list |
| 10 | Keyword Flags | All keyword-flagged entries |
| 11 | Full Population | Original data + "Flags" column (pipe-separated) |
| 12 | Parameters | Run parameters: client, period, date, prepared by, thresholds |

### Sheet 1 — Summary Dashboard Layout
```
Row 1:  KKC & Associates LLP — Journal Entry Testing Workpaper
Row 2:  Client: [Name]    Period: [Month/Year]    Run Date: [DD Month YYYY]
Row 3:  Prepared By: [Name]    Total JE Population: [N]    Materiality: [₹]
Row 4:  [blank]
Row 5:  OVERALL ENGAGEMENT RISK RATING: [HIGH / MEDIUM / LOW]  ← Large, colour-coded
Row 6:  [blank]
Row 7:  [Table header] Module | JEs Flagged | % of Population | Risk Rating
Row 8+: One row per module
Last:   TOTAL FLAGS | [sum] | [%] |
```

### Formatting Rules (apply to all sheets)
- Header row: KKC Green fill (#7CB542), white bold text, 12pt
- Alternating data rows: White and light grey (#F2F2F2)
- Risk Rating cells: Colour-coded (Red/Orange/Green)
- Freeze top row on all sheets
- Auto-fit all column widths (max width cap: 50 characters)
- All date columns: Format DD-MMM-YYYY
- All amount columns: Indian number format `₹ #,##,##0.00`
- Sheet tabs: Colour-coded (Red = High risk sheet, Orange = Medium, 
  Green = Low, White = Summary/Full Population/Parameters)

---

## config.py Specification
This file must define:
```python
# Risk Thresholds (% of population)
RISK_HIGH = 0.05       # > 5% = High
RISK_MEDIUM = 0.01     # 1-5% = Medium (below 1% = Low)

# Round Number Thresholds (Indian)
ROUND_THOUSAND = 1000
ROUND_LAKH = 100000
ROUND_CRORE = 10000000
ROUND_MINIMUM_AMOUNT = 10000  # Don't flag round numbers below this

# After Hours Definition
BUSINESS_HOURS_START = 9   # 9:00 AM
BUSINESS_HOURS_END = 19    # 7:00 PM

# Period-End Definition
PERIOD_END_HIGH_DAYS = 3   # Last 3 days of month = High
PERIOD_END_MEDIUM_DAYS = 5 # Last 5 days of month = Medium

# Benford's Law
BENFORD_SIGNIFICANCE = 0.05  # p-value threshold

# Rare Account Combo Threshold
RARE_COMBO_THRESHOLD = 3  # Appears fewer than 3 times = unusual

# User Outlier Threshold (standard deviations)
USER_OUTLIER_STD = 2.0

# Self-Approval: field names that mean "same person approved own entry"
# (handled in column_mapper.py but referenced here)

# Keywords (Full list)
HIGH_RISK_KEYWORDS = [
    "adjustment", "adjusted", "correcting entry", "correction",
    "write-off", "write off", "reversal", "reversed", "reverse",
    "override", "overriding", "one-time", "one time",
    "misc", "miscellaneous", "suspense", "clearing entry",
    "rectification", "rectify", "error correction", "prior period",
    "back date", "backdated", "reclass", "reclassification",
    "provision reversal", "manual entry", "direct entry",
    "management override", "boss instruction", "director instruction",
    "off balance", "testing", "test entry", "dummy", "trial"
]

# Keywords that alone trigger HIGH risk (regardless of count)
ALWAYS_HIGH_KEYWORDS = [
    "override", "backdated", "director instruction", 
    "boss instruction", "management override"
]

# Branding
KKC_GREEN = "#7CB542"
KKC_GREY = "#808285"
KKC_LIGHT_GREY = "#F2F2F2"
RISK_RED = "#FF0000"
RISK_ORANGE = "#FFA500"

# Output
OUTPUT_PREFIX = "KKC_JE_"
DATE_FORMAT = "%d%m%Y"
DISPLAY_DATE_FORMAT = "%d %B %Y"
```

---

## app.py Specification

### Page Config
```python
st.set_page_config(
    page_title="KKC JE Testing Tool",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)
```

### Sidebar Contents
- KKC firm name (styled header)
- Client Name (text input, required)
- Audit Period (text input, e.g., "March 2025")
- Financial Year (text input, e.g., "FY 2024-25")
- Prepared By (text input)
- Materiality Amount (number input, optional, Indian ₹)
- Separator
- Tool version and date

### Main Area — 4 Tabs
1. **📁 Upload & Map** — File uploader + column mapping UI
2. **⚙️ Run Analysis** — Module checkboxes + "Run All Tests" button + 
   progress bar
3. **📊 Results** — Summary table + per-module expandable sections with 
   flagged entries and charts
4. **📥 Export** — Download button for Excel workpaper + run parameters 
   confirmation

### UX Requirements
- Show record count immediately after upload
- Show column mapping table before allowing analysis to run
- Show progress bar with module names as each runs
- Show final summary: "X entries tested | Y flags raised | 
  Overall Risk: HIGH/MEDIUM/LOW"
- All monetary amounts displayed in Indian format (₹ lakhs/crores)
- Disable Export tab until analysis has been run

---

## run.bat Specification
```batch
@echo off
echo Starting KKC Journal Entry Testing Tool...
echo.
streamlit run app.py
pause
```

---

## Code Quality Standards
- Every function must have a docstring explaining: purpose, inputs, outputs
- No hardcoded client names, amounts, or file paths anywhere in code
- All magic numbers must be referenced from config.py
- Each module must return a standardised dict:
```python
  {
      "module_name": str,
      "flagged_df": pd.DataFrame,   # Flagged entries only
      "flag_count": int,
      "population_count": int,
      "flag_pct": float,
      "risk_rating": str,           # "High", "Medium", "Low"
      "summary_stats": dict,        # Module-specific stats
      "chart": plotly figure or None
  }
```
- utils/excel_exporter.py must consume this standard dict format
- requirements.txt must be kept in sync with all imports used

---

## Testing Requirements
`tests/generate_sample_data.py` must create a 5,000-row dataset with 
these planted anomalies:

| Anomaly Type | Count | Notes |
|---|---|---|
| Exact duplicate entries | 50 | Same amount, accounts, date |
| Near duplicates | 30 | Same amount, accounts, different day |
| Round lakh entries | 80 | Amounts exactly divisible by ₹1,00,000 |
| Weekend postings | 60 | Saturday or Sunday |
| After-hours postings | 80 | Before 9am or after 7pm |
| Period-end entries (last 3 days) | 100 | Spread across months |
| Blank narration | 120 | Null or empty |
| Generic narration | 30 | "NA", "NIL", "misc" |
| Benford's anomalies | 40 | Inflated digit 5 and 7 frequency |
| Keyword hits | 50 | Mix of keywords from config.py |
| Self-approved entries | 8 | prepared_by == approved_by |
| Unusual account combos | 20 | Debit P&L / Credit Cash |

All other 4,000+ rows should be realistic, clean journal entries.
The generator must print a summary of planted anomalies so test 
results can be validated against known ground truth.

---

## What This Tool Does NOT Do
- Does NOT connect to the internet at any point
- Does NOT store client data anywhere outside the auditor's machine
- Does NOT send data to any API or cloud service
- Does NOT retain data between sessions (all data cleared on browser close)
- Does NOT replace auditor judgment — flags require human review
- Does NOT perform substantive testing — this is an analytical/risk tool

---

## ICAI / NFRA Compliance Notes
- Tool output constitutes analytical procedures documentation under SA 520
- Benford's Law testing is an accepted analytical procedure under SA 240
- All flags must be investigated and conclusions documented separately 
  by the engagement team
- The Parameters sheet in the output Excel serves as evidence of the 
  testing approach applied
- Tool should be version-controlled — output file must include tool 
  version in the Parameters sheet

---
*This file governs all Claude Code build decisions for this project.
When in doubt, refer back to this file before writing any code.*
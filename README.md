# KKC Journal Entry Testing Tool

**KKC & Associates LLP, Chartered Accountants**
Version 1.0.0 · SA 240 Compliant · Fully Offline

---

## What This Tool Does

The KKC Journal Entry Testing Tool is an offline, audit-grade analytics application designed for statutory auditors conducting journal entry testing under SA 240 (The Auditor's Responsibilities Relating to Fraud in an Audit of Financial Statements). It accepts a client's GL export as a CSV or Excel file, automatically maps column names, and runs nine analytical tests to identify entries that warrant further investigation — including round-number patterns, after-hours postings, period-end clustering, missing narrations, duplicate entries, unusual account combinations, and more. Results are presented in an interactive browser-based interface with charts and flagged-entry tables, and the entire output is packaged into a formatted 12-sheet Excel workpaper suitable for NFRA inspection. No data ever leaves the auditor's machine — the tool runs entirely on your local computer with no internet connection required.

---

## Installation

**You only need to do this once.**

### Step 1 — Install Python

1. Go to **https://www.python.org/downloads/**
2. Click the yellow **Download Python 3.11** (or newer) button
3. Run the installer
4. **Important:** On the first screen, tick the box that says **"Add Python to PATH"** before clicking Install

To verify Python installed correctly, open the Windows Start menu, search for **Command Prompt**, and type:
```
python --version
```
You should see something like `Python 3.11.x`.

### Step 2 — Download or Copy the Tool

Place the entire `JE testing tool` folder somewhere convenient, for example:
```
C:\KKC Tools\JE testing tool\
```

### Step 3 — Install Required Libraries

Open Command Prompt, navigate to the tool folder, and run:
```
cd "C:\KKC Tools\JE testing tool"
pip install -r requirements.txt
```
This downloads the required Python libraries (pandas, streamlit, openpyxl, etc.). It needs an internet connection once.

---

## Running the Tool

### Option A — Double-click launcher (recommended)

Double-click **`run.bat`** in the tool folder. A black command window will open, and after a few seconds your browser will automatically open at the tool.

> The command window must stay open while you use the tool. Close it when you are done.

### Option B — Command line

Open Command Prompt in the tool folder and run:
```
streamlit run app.py
```
Then open **http://localhost:8501** in your browser.

---

## How to Use the Tool

### Step 1 — Fill in Engagement Details (Sidebar)

Before uploading a file, fill in the left-hand sidebar:
- **Client Name** — e.g. `Shriram Finance Ltd`
- **Audit Period** — e.g. `March 2025`
- **Financial Year** — e.g. `FY 2024-25`
- **Prepared By** — your name or the assistant's name
- **Materiality** — optional, for workpaper reference

### Step 2 — Upload GL Export (Upload & Map tab)

Click **Browse files** and select your client's GL journal entry export (CSV or Excel).

- The tool will instantly show the row count and a data preview
- It will automatically match your column names to the 12 standard field names
- Review the mapping table — scores shown in green (≥ 85%) are high-confidence matches
- Use the dropdowns to correct any incorrect or missing matches

### Step 3 — Run Modules (Run Analysis tab)

- All 9 modules are pre-selected — untick any you do not need
- Optionally upload a holiday calendar CSV (one date per row) for holiday detection
- Optionally upload a Chart of Accounts CSV to improve account-type classification
- Optionally add extra keywords for the keyword scanner
- Click **Run Selected Tests** — a progress bar will show each module as it runs

### Step 4 — Review Results (Results tab)

- An overall risk banner (High / Medium / Low) appears at the top
- A summary table shows flags and risk rating for each module
- Click any module section to expand it and see:
  - An interactive chart
  - The list of flagged entries (first 500 shown)
  - Module-specific statistics

### Step 5 — Export Workpaper (Export tab)

- Click **Generate Excel Workpaper**
- Then click **Download** to save the file
- The file is named `KKC_JE_Testing_ClientName_Period_DDMMYYYY.xlsx`
- Store it in the engagement folder per your firm's document retention policy

---

## Input File Format

### Accepted File Types
- Microsoft Excel: `.xlsx` or `.xls`
- Comma-Separated Values: `.csv`

### Column Names

The tool uses fuzzy matching to automatically recognise your columns — you do not need to rename them. The table below shows what each standard field means and the kinds of names the tool will auto-detect.

| Standard Field | What It Is | Example Column Names in GL Exports |
|---|---|---|
| `posting_date` | Date the entry was posted to the ledger | Posting Date, Transaction Date, Date, Value Date |
| `amount` | Transaction amount (positive values) | Amount, Debit Amount, DR Amount, Voucher Amount |
| `debit_account` | Debit-side account code or name | Debit Account, DR Account, GL Account, Account Code |
| `credit_account` | Credit-side account code or name | Credit Account, CR Account |
| `je_number` | Journal entry / voucher reference number | JE No, Voucher No, Doc No, Journal Number |
| `narration` | Description or remarks field | Narration, Description, Remarks, Particulars |
| `prepared_by` | User who created the entry | Prepared By, Created By, Maker, User, Posted By |
| `approved_by` | User who approved the entry | Approved By, Checker, Authorised By |
| `entry_time` | Time the entry was input into the system | Entry Time, Created Time, Timestamp |
| `entry_date` | Date the entry was input (may differ from posting date) | Entry Date, Created Date, Input Date |
| `entry_type` | Manual / Automatic / System classification | Entry Type, Journal Type, Source |
| `period` | Accounting period label | Period, Accounting Period, Fiscal Month |

### Minimum Required Fields

The tool will not run without at least these three:
1. `posting_date`
2. `amount`
3. At least one of `debit_account` or `credit_account`

All other fields are optional — modules that need a missing field will skip gracefully and show a note.

---

## The Nine Analytical Modules

### 1. Benford's Law Analysis
**SA Reference: SA 240.A3**

Tests whether the leading digits of transaction amounts follow Benford's Law — the mathematically expected distribution of first digits in naturally occurring data. Genuine financial data follows this distribution closely. Manipulation often distorts it. Runs a chi-square goodness-of-fit test and flags entries in over-represented digit buckets (those exceeding expected frequency by more than 2 standard deviations).

- **High Risk:** p-value < 0.05 (statistically significant deviation from Benford's distribution)
- **Medium Risk:** p-value 0.05 – 0.10
- **Low Risk:** p-value > 0.10

### 2. Duplicate Detection
**SA Reference: SA 240.A37**

Identifies three types of duplicate journal entries:
- **Type A — Exact Duplicate:** Same amount, same debit account, same credit account, same posting date
- **Type B — Near Duplicate:** Same amount and accounts, but posted on a different day in the same calendar month (possible split or re-posting)
- **Type C — JE Number Duplicate:** The same journal entry number appears more than once (data integrity flag)

- **High Risk:** Any Type A exact duplicates found
- **Medium Risk:** Only Type B or Type C duplicates
- **Low Risk:** No duplicates

### 3. Round Number Detection
**SA Reference: SA 240.A37**

Flags entries with suspiciously round amounts. In normal business operations, transaction amounts rarely land on exact thousands or lakhs. Round amounts can indicate estimates posted instead of actuals, or fictitious entries.

- **Round Crore:** Divisible by ₹1,00,00,000 exactly → High
- **Round Lakh:** Divisible by ₹1,00,000 exactly → High
- **Round Thousand:** Divisible by ₹1,000 exactly → Medium
- Entries below ₹10,000 are excluded to avoid noise
- **High Risk:** Round lakh or crore entries > 5% of population
- **Medium Risk:** Round thousand entries > 10%, or any round lakh / crore present

### 4. After-Hours & Weekend Postings
**SA Reference: SA 240.A35**

Flags entries posted outside normal business operations:
- **Weekends:** Posted on Saturday or Sunday
- **After Hours:** Entry time before 09:00 or at/after 19:00
- **Public Holidays:** If a holiday calendar CSV is uploaded, entries on those dates are also flagged

Also produces a top-10 user breakdown showing which users post the most out-of-hours entries.

- **High Risk:** Flagged entries > 5% of population
- **Medium Risk:** 2–5%
- **Low Risk:** < 2%

### 5. Period-End Entry Concentration
**SA Reference: SA 240.A36**

Entries clustered in the last few days of a month or financial year are a classic earnings-management indicator. Management may post provisions, accruals, or reversals at period-end to hit reporting targets.

- **High Band:** Entry falls in the last 3 calendar days of its month
- **Medium Band:** Entry falls in the 4th or 5th day from month-end
- **Year-End Flag:** Entries dated 29, 30, or 31 March receive an additional year-end flag (Indian FY closes 31 March)

- **High Risk:** Any month where last-3-days entries exceed 10% of that month's total
- **Medium Risk:** Combined last-5-days entries exceed 5% in any month
- **Low Risk:** All months below 5%

### 6. Missing / Generic Narration
**SA Reference: SA 315.A51**

The narration field is the auditor's primary window into the business purpose of an entry. Entries without a meaningful description cannot be assessed for legitimacy without obtaining additional evidence.

Flags entries where narration is:
- Null, blank, or whitespace-only
- A single meaningless character: `.` `-` `/`
- A generic placeholder: `NA`, `N/A`, `NIL`, `NONE`, `TEST`, `TEMP`

- **High Risk:** > 10% of entries flagged
- **Medium Risk:** 5–10%
- **Low Risk:** < 5%

### 7. Unusual Account Combinations
**SA Reference: SA 315**

Identifies journal entry account pairings that are either statistically rare or are known to indicate control weaknesses or fraud risk.

- **Part A — Statistical Rarity:** Account combinations appearing fewer than 3 times in the full population
- **Part B — Rule-Based Flags (always High Risk):**
  - Debit Suspense / Clearing / Adjustment account → Credit any account
  - Debit Revenue account → Credit Cash (unusual reversal of income)
  - Debit Expense → Credit Cash (possible off-process payment)
  - Debit Provision → Credit Revenue (provision reversal to inflate income)

- **High Risk:** Any Part B rule-based flag exists
- **Medium Risk:** Part A rare combinations > 2% of population
- **Low Risk:** Only rare combos, no rule-based flags

### 8. User-Level Posting Analysis
**SA Reference: SA 240.A35**

Analyses posting patterns at the individual user level to identify control weaknesses and unusual behaviour.

- **Volume Outlier:** Users whose entry count exceeds mean + 2 standard deviations across all users
- **Amount Outlier:** Users whose total posted amount exceeds mean + 2 standard deviations
- **Self-Approval:** Entries where the preparer and approver are the same person (maker = checker — segregation of duties violation)
- **Single-User Days:** Dates where all entries were posted by exactly one user and there were at least 2 entries that day (possible override of normal review workflow)

- **High Risk:** Any self-approval entries exist
- **Medium Risk:** Volume or amount outliers exist but no self-approval
- **Low Risk:** No outliers and no self-approval

### 9. High-Risk Keyword Flagging
**SA Reference: SA 240.A37**

Scans the narration field for words and phrases that commonly appear in fraudulent, erroneous, or management-override journal entries. Matching is case-insensitive and detects the keyword anywhere within the narration text.

Default keyword list includes: `adjustment`, `reversal`, `write-off`, `override`, `backdated`, `prior period`, `suspense`, `manual entry`, `director instruction`, `boss instruction`, `dummy`, `test entry`, `reclassification`, and more (full list in `config.py`).

Additional keywords can be added per-engagement via the Run Analysis tab without modifying any code.

- **High Risk:** Flagged entries > 3% of population, **OR** any entry contains a critical keyword (`override`, `backdated`, `director instruction`, `boss instruction`, `management override`)
- **Medium Risk:** Flagged entries 1–3%
- **Low Risk:** < 1%

---

## Output — Excel Workpaper

The exported Excel workbook (`KKC_JE_Testing_ClientName_Period_DDMMYYYY.xlsx`) contains 12 sheets:

| # | Sheet | Contents |
|---|---|---|
| 1 | Summary Dashboard | Overall risk rating, engagement details, module summary table |
| 2 | Benfords Analysis | Chi-square statistics, frequency table, flagged entries |
| 3 | Duplicates | All exact, near, and JE-number duplicate entries |
| 4 | Round Numbers | All round-number entries with classification |
| 5 | After Hours Weekend | All out-of-hours and weekend entries |
| 6 | Period End Entries | All period-end entries with month classification |
| 7 | Missing Narration | All blank or generic narration entries |
| 8 | Unusual Acct Combos | All unusual account combination entries |
| 9 | User Analysis | Top-10 user tables, self-approvals, outlier entries |
| 10 | Keyword Flags | All keyword-matched entries with matched keywords |
| 11 | Full Population | Complete original dataset with a Flags column showing which modules flagged each row |
| 12 | Parameters | Run parameters and all thresholds applied — serves as audit trail |

Sheet tabs are colour-coded: **Red** = High Risk, **Orange** = Medium Risk, **Green** = Low Risk.

---

## Important Notes

- **This tool is fully offline.** No data is sent to any server, API, or cloud service at any point.
- **Data is not retained between sessions.** Closing the browser tab clears all data from memory.
- **This tool does not replace auditor judgment.** All flags require human investigation. The tool identifies entries that *may* warrant further scrutiny — it does not reach conclusions.
- **This tool performs analytical / risk procedures only** (SA 520). It is not a substitute for substantive testing.
- The Parameters sheet in the output workpaper documents the testing approach applied and is suitable for inclusion in the audit file for NFRA inspection purposes.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Double-clicking `run.bat` closes immediately | Right-click → Run as Administrator, or open Command Prompt and run `streamlit run app.py` manually |
| `pip install` fails with "not recognized" | Python was not added to PATH during installation. Reinstall Python and tick "Add Python to PATH" |
| Browser does not open automatically | Manually open **http://localhost:8501** in Chrome or Edge |
| Port 8501 already in use | Run `streamlit run app.py --server.port 8502` and open **http://localhost:8502** |
| File upload fails | Ensure the file is not open in Excel at the same time |
| Column mapping confidence is low | Use the dropdowns to manually select the correct column for each field |

---

## File Structure

```
JE testing tool/
├── app.py                    Main Streamlit application
├── config.py                 All thresholds, keywords, and branding constants
├── requirements.txt          Python library dependencies
├── run.bat                   Windows double-click launcher
├── README.md                 This file
├── modules/
│   ├── benfords.py           Module 1: Benford's Law
│   ├── duplicates.py         Module 2: Duplicate Detection
│   ├── round_numbers.py      Module 3: Round Number Detection
│   ├── after_hours.py        Module 4: After-Hours & Weekend Postings
│   ├── period_end.py         Module 5: Period-End Concentration
│   ├── no_narration.py       Module 6: Missing Narration
│   ├── account_combos.py     Module 7: Unusual Account Combinations
│   ├── user_analysis.py      Module 8: User-Level Analysis
│   └── keywords.py           Module 9: Keyword Flagging
├── utils/
│   ├── column_mapper.py      Fuzzy column name detection
│   └── excel_exporter.py     12-sheet Excel workpaper builder
└── tests/
    ├── generate_sample_data.py   5,000-row test dataset generator
    └── sample_je_data.xlsx       Pre-generated test file (upload this to test)
```

---

*For questions or issues, contact the KKC IT / Tools team.*
*Tool developed for internal audit use at KKC & Associates LLP.*

"""
utils/column_mapper.py
----------------------
Fuzzy column name detection and mapping for the KKC JE Testing Tool.

Attempts to automatically map uploaded file column names to the 12 standard
internal field names using rapidfuzz similarity scoring. When confidence is
below the acceptance threshold, the mapping is left unmapped so the Streamlit
UI can prompt the user to select the correct column via a dropdown.

Designed to be called from app.py (Tab 1 — Upload & Map).
"""

from __future__ import annotations

import pandas as pd
from rapidfuzz import fuzz, process
from typing import Optional


# ---------------------------------------------------------------------------
# Canonical field definitions
# Each key is the internal standard field name.
# The list contains all known aliases from real-world GL exports.
# ---------------------------------------------------------------------------
STANDARD_FIELDS: dict[str, list[str]] = {
    "je_number": [
        "je no", "je number", "journal no", "journal number", "journal entry no",
        "journal entry number", "voucher no", "voucher number", "doc no",
        "document no", "document number", "trans no", "transaction no",
        "entry no", "entry number", "ref no", "reference no", "reference number",
    ],
    "posting_date": [
        "posting date", "post date", "transaction date", "trans date",
        "date", "value date", "gl date", "accounting date", "book date",
        "document date",
    ],
    "entry_date": [
        "entry date", "created date", "creation date", "input date",
        "entered date", "input on", "created on",
    ],
    "entry_time": [
        "entry time", "created time", "creation time", "input time",
        "timestamp", "time", "entered time", "posting time",
    ],
    "prepared_by": [
        "prepared by", "user", "user name", "username", "created by",
        "maker", "posted by", "entered by", "input by", "made by",
        "booked by", "operator", "clerk",
    ],
    "approved_by": [
        "approved by", "authorised by", "authorized by", "checker",
        "reviewer", "approver", "verified by", "sanctioned by",
        "reviewed by",
    ],
    "debit_account": [
        "debit account", "dr account", "debit account code", "dr account code",
        "debit gl", "dr gl", "account code", "account no", "account number",
        "gl account", "gl code", "debit head", "dr head",
    ],
    "credit_account": [
        "credit account", "cr account", "credit account code", "cr account code",
        "credit gl", "cr gl", "credit head", "cr head",
    ],
    "amount": [
        "amount", "debit amount", "dr amount", "transaction amount",
        "voucher amount", "je amount", "value", "net amount", "gross amount",
        "local amount", "inr amount",
    ],
    "narration": [
        "narration", "description", "remarks", "particulars", "text",
        "details", "note", "notes", "memo", "purpose", "reason",
        "transaction description", "line description",
    ],
    "entry_type": [
        "entry type", "journal type", "je type", "source", "source type",
        "transaction type", "trans type", "voucher type", "posting type",
        "category",
    ],
    "period": [
        "period", "month", "accounting period", "fiscal month",
        "financial period", "fiscal period", "reporting period",
        "period name", "financial month",
    ],
}

# Minimum similarity score (0–100) to accept an automatic match.
# Scores below this leave the field as unmapped (None).
FUZZY_THRESHOLD = 70


# ---------------------------------------------------------------------------
# Core mapping logic
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """
    Normalise a column name for comparison.

    Strips leading/trailing whitespace, converts to lowercase, and removes
    common noise characters so that e.g. 'Trans.Date' and 'Trans Date'
    both become 'trans date'.

    Args:
        text: Raw column name string.

    Returns:
        Normalised lowercase string.
    """
    return (
        str(text)
        .strip()
        .lower()
        .replace("_", " ")
        .replace(".", " ")
        .replace("-", " ")
        .replace("/", " ")
        .replace("(", " ")
        .replace(")", " ")
    )


def auto_map_columns(
    df_columns: list[str],
    threshold: int = FUZZY_THRESHOLD,
) -> dict[str, Optional[str]]:
    """
    Automatically map a list of uploaded column names to standard field names.

    Uses rapidfuzz token_set_ratio scoring to handle word-order variations and
    partial matches (e.g. "Trans Date" → "posting_date", "Made By" → "prepared_by").

    Each standard field is assigned at most one uploaded column. If the best
    match for a field falls below `threshold`, the field maps to None (unmapped).
    A single uploaded column can only be assigned to one standard field; once
    claimed, it is removed from the candidate pool.

    Args:
        df_columns: List of column name strings from the uploaded file.
        threshold:  Minimum rapidfuzz score (0–100) to accept a match.

    Returns:
        Dict mapping each standard field name → matched uploaded column name,
        or None if no confident match was found.
        Example: {"posting_date": "Trans Date", "amount": "Voucher Amount", ...}
    """
    # Build a pool of (normalised_name, original_name) tuples
    candidate_pool: dict[str, str] = {
        _normalise(col): col for col in df_columns
    }

    mapping: dict[str, Optional[str]] = {}

    for field, aliases in STANDARD_FIELDS.items():
        best_col: Optional[str] = None
        best_score: float = 0.0

        for alias in aliases:
            norm_alias = _normalise(alias)

            if not candidate_pool:
                break

            # rapidfuzz.process.extractOne returns (match, score, index)
            result = process.extractOne(
                norm_alias,
                list(candidate_pool.keys()),
                scorer=fuzz.token_set_ratio,
                score_cutoff=threshold,
            )

            if result is not None:
                matched_norm, score, _ = result
                if score > best_score:
                    best_score = score
                    best_col = candidate_pool[matched_norm]
                    best_norm = matched_norm

        if best_col is not None:
            mapping[field] = best_col
            # Remove matched column from pool so it cannot be reused
            matched_key = _normalise(best_col)
            candidate_pool.pop(matched_key, None)
        else:
            mapping[field] = None

    return mapping


def get_mapping_confidence(
    df_columns: list[str],
    threshold: int = FUZZY_THRESHOLD,
) -> dict[str, dict]:
    """
    Return detailed mapping results including the confidence score for each field.

    Useful for displaying a review table in the Streamlit UI so auditors can
    see exactly how confident each auto-mapping is.

    Args:
        df_columns: List of column name strings from the uploaded file.
        threshold:  Minimum rapidfuzz score (0–100) to accept a match.

    Returns:
        Dict of field → {"mapped_to": str|None, "score": float, "status": str}
        where status is "auto-mapped", "unmapped", or "overridden" (set externally).
    """
    candidate_pool: dict[str, str] = {
        _normalise(col): col for col in df_columns
    }

    results: dict[str, dict] = {}

    for field, aliases in STANDARD_FIELDS.items():
        best_col: Optional[str] = None
        best_score: float = 0.0

        for alias in aliases:
            norm_alias = _normalise(alias)

            if not candidate_pool:
                break

            result = process.extractOne(
                norm_alias,
                list(candidate_pool.keys()),
                scorer=fuzz.token_set_ratio,
                score_cutoff=threshold,
            )

            if result is not None:
                matched_norm, score, _ = result
                if score > best_score:
                    best_score = score
                    best_col = candidate_pool[matched_norm]

        if best_col is not None:
            results[field] = {
                "mapped_to": best_col,
                "score": round(best_score, 1),
                "status": "auto-mapped",
            }
            matched_key = _normalise(best_col)
            candidate_pool.pop(matched_key, None)
        else:
            results[field] = {
                "mapped_to": None,
                "score": 0.0,
                "status": "unmapped",
            }

    return results


def apply_overrides(
    mapping: dict[str, Optional[str]],
    overrides: dict[str, str],
) -> dict[str, Optional[str]]:
    """
    Apply manual user overrides on top of an existing auto-mapped dict.

    Called from the Streamlit UI when an auditor uses a dropdown to correct
    an incorrect or missing auto-mapping.

    Args:
        mapping:   Existing auto-mapped dict (field → column name or None).
        overrides: Dict of field → user-selected column name from the UI.

    Returns:
        Updated mapping dict with overrides applied.
    """
    updated = mapping.copy()
    for field, col in overrides.items():
        if field in STANDARD_FIELDS:
            updated[field] = col if col != "" else None
    return updated


def validate_minimum_fields(
    mapping: dict[str, Optional[str]],
) -> tuple[bool, list[str]]:
    """
    Check whether the minimum required fields are mapped before analysis can run.

    Minimum requirements per CLAUDE.md:
      - posting_date must be mapped
      - amount must be mapped
      - At least one of debit_account or credit_account must be mapped

    Args:
        mapping: Field → column name dict (None means unmapped).

    Returns:
        Tuple of (is_valid: bool, missing_fields: list[str]).
        If is_valid is True, missing_fields will be an empty list.
    """
    missing: list[str] = []

    if not mapping.get("posting_date"):
        missing.append("posting_date")

    if not mapping.get("amount"):
        missing.append("amount")

    if not mapping.get("debit_account") and not mapping.get("credit_account"):
        missing.append("debit_account OR credit_account (at least one required)")

    return (len(missing) == 0, missing)


def get_mapped_df(
    df: pd.DataFrame,
    mapping: dict[str, Optional[str]],
) -> pd.DataFrame:
    """
    Return a renamed copy of the dataframe using the confirmed column mapping.

    Only renames columns that are successfully mapped (non-None). Unmapped
    columns are dropped from the output dataframe to keep it clean for the
    analysis modules.

    Args:
        df:      Original uploaded dataframe with raw column names.
        mapping: Confirmed field → column name dict.

    Returns:
        New dataframe with standard field names as column headers, containing
        only the mapped columns.
    """
    rename_map = {
        original_col: field
        for field, original_col in mapping.items()
        if original_col is not None
    }
    # Keep only the columns that appear in the rename map
    cols_to_keep = [c for c in df.columns if c in rename_map]
    return df[cols_to_keep].rename(columns=rename_map)


def render_mapping_table(
    mapping_detail: dict[str, dict],
    all_columns: list[str],
) -> None:
    """
    Render an interactive column mapping review table in the Streamlit UI.

    Displays each standard field, its auto-mapped column (with score), and a
    dropdown allowing the auditor to override the mapping. Returns the
    confirmed mapping via st.session_state after the user clicks Confirm.

    This function is only called when running inside a Streamlit context.
    It imports streamlit lazily to keep the module importable in plain Python
    (e.g. during tests).

    Args:
        mapping_detail: Output of get_mapping_confidence() — field-level detail.
        all_columns:    Full list of column names from the uploaded file, used
                        to populate override dropdowns.

    Returns:
        None. Writes confirmed mapping to st.session_state["confirmed_mapping"].
    """
    import streamlit as st  # lazy import — safe outside Streamlit context

    st.subheader("Column Mapping Review")
    st.caption(
        "Auto-detected column matches are shown below. "
        "Use the dropdowns to correct any incorrect or missing mappings."
    )

    dropdown_options = ["(unmapped)"] + sorted(all_columns)
    confirmed: dict[str, Optional[str]] = {}

    # Required fields marker
    required_fields = {"posting_date", "amount", "debit_account", "credit_account"}

    for field, detail in mapping_detail.items():
        col1, col2, col3 = st.columns([2, 3, 1])

        label = field.replace("_", " ").title()
        is_required = field in required_fields

        with col1:
            st.markdown(
                f"**{label}**" + (" ⚠️" if is_required else ""),
                help="Required field" if is_required else "Optional field",
            )

        with col2:
            current_index = 0
            if detail["mapped_to"] is not None and detail["mapped_to"] in dropdown_options:
                current_index = dropdown_options.index(detail["mapped_to"])

            selected = st.selectbox(
                label=f"map_{field}",
                options=dropdown_options,
                index=current_index,
                label_visibility="collapsed",
                key=f"colmap_{field}",
            )
            confirmed[field] = None if selected == "(unmapped)" else selected

        with col3:
            if detail["status"] == "auto-mapped":
                score = detail["score"]
                colour = "#7CB542" if score >= 85 else "#FFA500"
                st.markdown(
                    f'<span style="color:{colour};font-weight:bold">'
                    f'{score:.0f}%</span>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<span style="color:#FF0000">—</span>',
                    unsafe_allow_html=True,
                )

    st.session_state["confirmed_mapping"] = confirmed

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd


_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def build_closing_positions(
    net_df: pd.DataFrame, trade_date_iso: str
) -> Tuple[List[Dict], float, str]:
    """
    Build closing-position rows from netwise data.

    Returns:
        rows: list of table rows
        total_value: sum(net_qty * ltp) across included rows
        status: OK | MISSING | NO_OPEN_POSITIONS
    """
    if net_df is None or not isinstance(net_df, pd.DataFrame) or net_df.empty:
        return [], 0.0, "MISSING"

    contract_col = _find_first_column(
        net_df,
        [
            "TradingSymbol",
            "Trading Symbol",
            "Contract",
            "Strike",
            "Security",
            "Symbol",
        ],
    )
    net_qty_col = _find_first_column(
        net_df,
        ["NetQty", "Net Qty", "Net Quantity", "Net_Qty"],
    )
    if not contract_col or not net_qty_col:
        return [], 0.0, "MISSING"

    ltp_columns = _ordered_existing_columns(
        net_df,
        [
            "LastTradePrice",
            "Last Traded Price",
            "Last TradedPrice",
            "Last Trade Price",
            "Last Price",
            "LTP Price",
            "LTP",
            "ClosePrice",
            "Close Price",
            "MarketPrice",
            "MarkPrice",
            "Actual SellAvgPrice",
            "Actual BuyAvgPrice",
            "SellAvgPrice",
            "BuyAvgPrice",
        ],
    )
    expiry_col = _find_first_column(
        net_df,
        [
            "Expiry",
            "Expiry Date",
            "ExpiryDate",
            "Expiry Dt",
            "ExpDate",
            "Contract Expiry",
            "MaturityDate",
            "Maturity Date",
        ],
    )
    trade_date = _parse_date(trade_date_iso)

    rows: List[Dict] = []
    total_value = 0.0

    for _, row in net_df.iterrows():
        net_qty = _to_int(row.get(net_qty_col))
        if net_qty == 0:
            continue

        contract = str(row.get(contract_col, "") or "").strip()
        if not contract:
            contract = "N/A"

        if trade_date and _is_confidently_expired(row, contract, expiry_col, trade_date):
            continue

        ltp = _best_numeric_value(row, ltp_columns)
        value = float(net_qty) * ltp
        total_value += value

        rows.append(
            {
                "sr": len(rows) + 1,
                "contract": contract,
                "net_qty": net_qty,
                "ltp": ltp,
                "value": value,
            }
        )

    if not rows:
        return [], 0.0, "NO_OPEN_POSITIONS"

    return rows, float(total_value), "OK"


def _is_confidently_expired(
    row: pd.Series,
    contract: str,
    expiry_col: Optional[str],
    trade_date: date,
) -> bool:
    if expiry_col:
        explicit_expiry = _parse_date(row.get(expiry_col))
        if explicit_expiry:
            return explicit_expiry < trade_date

    parsed_expiry, confident = _parse_expiry_from_contract(contract, trade_date)
    if not parsed_expiry or not confident:
        return False
    return parsed_expiry < trade_date


def _parse_expiry_from_contract(contract: str, trade_date: date) -> Tuple[Optional[date], bool]:
    text = str(contract or "").upper()
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return None, False

    token_with_year = re.search(r"(?<!\d)(\d{1,2})([A-Z]{3})(\d{2,4})(?!\d)", text)
    if token_with_year:
        day_value = int(token_with_year.group(1))
        month_value = _MONTHS.get(token_with_year.group(2))
        year_value = _normalize_year(token_with_year.group(3))
        if month_value and year_value:
            try:
                return date(year_value, month_value, day_value), True
            except ValueError:
                pass

    dmy_match = re.search(r"(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})(?!\d)", text)
    if dmy_match:
        day_value = int(dmy_match.group(1))
        month_value = int(dmy_match.group(2))
        year_value = _normalize_year(dmy_match.group(3))
        if year_value:
            try:
                return date(year_value, month_value, day_value), True
            except ValueError:
                pass

    ymd_match = re.search(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", text)
    if ymd_match:
        year_value = int(ymd_match.group(1))
        month_value = int(ymd_match.group(2))
        day_value = int(ymd_match.group(3))
        try:
            return date(year_value, month_value, day_value), True
        except ValueError:
            pass

    token_without_year = re.search(r"(?<!\d)(\d{1,2})([A-Z]{3})(?!\d)", text)
    if token_without_year:
        day_value = int(token_without_year.group(1))
        month_value = _MONTHS.get(token_without_year.group(2))
        if month_value:
            try:
                return date(trade_date.year, month_value, day_value), False
            except ValueError:
                pass

    return None, False


def _normalize_year(value: str) -> Optional[int]:
    raw = str(value or "").strip()
    if not raw.isdigit():
        return None
    if len(raw) == 4:
        return int(raw)
    if len(raw) == 2:
        short = int(raw)
        return 2000 + short if short <= 79 else 1900 + short
    return None


def _parse_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()

    text = str(value or "").strip()
    if not text:
        return None

    for fmt in (
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%d%b%Y",
        "%d%b%y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _best_numeric_value(row: pd.Series, columns: List[str]) -> float:
    first_numeric: Optional[float] = None
    for column in columns:
        value = _to_float_or_none(row.get(column))
        if value is None:
            continue
        if first_numeric is None:
            first_numeric = value
        if abs(value) > 1e-9:
            return value
    if first_numeric is not None:
        return first_numeric
    return 0.0


def _to_int(value: object) -> int:
    numeric = _to_float_or_none(value)
    if numeric is None:
        return 0
    return int(round(numeric))


def _to_float_or_none(value: object) -> Optional[float]:
    if value is None:
        return None
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)


def _ordered_existing_columns(df: pd.DataFrame, candidates: List[str]) -> List[str]:
    existing: List[str] = []
    normalized_df_cols = {_normalize_col_name(col): col for col in df.columns}
    for candidate in candidates:
        matched = normalized_df_cols.get(_normalize_col_name(candidate))
        if matched and matched not in existing:
            existing.append(matched)
    return existing


def _find_first_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    columns = _ordered_existing_columns(df, candidates)
    return columns[0] if columns else None


def _normalize_col_name(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]", "", text)

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd


def parse_expiry(value: str) -> Optional[date]:
    """Parse expiry strings like 12Feb2026."""
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    compact = re.sub(r"\s+", "", text)
    match = re.match(r"^(\d{1,2})([a-zA-Z]{3})(\d{4})$", compact)
    if not match:
        return None

    day_value, month_token, year_value = match.groups()
    normalized = f"{int(day_value):02d}{month_token.title()}{year_value}"
    try:
        return datetime.strptime(normalized, "%d%b%Y").date()
    except ValueError:
        return None


def apply_expiry_settlement(
    net_df: pd.DataFrame, bill_date: date
) -> Tuple[pd.DataFrame, List[Dict], float, List[Dict]]:
    """
    Returns:
      net_df_for_closing, settlement_rows, settlement_total, pending_rows
    """
    if net_df is None or not isinstance(net_df, pd.DataFrame) or net_df.empty:
        empty = net_df.copy() if isinstance(net_df, pd.DataFrame) else pd.DataFrame()
        return empty, [], 0.0, []

    expiry_col = _find_column(net_df, ["Expiry"])
    if not expiry_col:
        return net_df.copy(), [], 0.0, []

    option_type_col = _find_column(net_df, ["Option Type"])
    net_qty_col = _find_column(net_df, ["NetQty", "Net Qty"])
    trading_symbol_col = _find_column(net_df, ["TradingSymbol", "Trading Symbol"])
    strike_col = _find_column(net_df, ["Strike Price"])
    underlying_close_col = _find_column(net_df, ["Underlying Close"])
    underlying_symbol_col = _find_column(net_df, ["Underlying Symbol"])
    lot_size_col = _find_column(net_df, ["Lot Size"])
    multiplier_col = _find_column(net_df, ["Multiplier"])
    net_lot_col = _find_column(net_df, ["Net Lot", "Net Lots"])

    parsed_expiry = net_df[expiry_col].map(parse_expiry)
    expired_on_bill_date_mask = parsed_expiry == bill_date

    net_df_for_closing = net_df.loc[~expired_on_bill_date_mask].copy()

    if not option_type_col or not net_qty_col:
        return net_df_for_closing, [], 0.0, []

    settlement_rows: List[Dict] = []
    pending_rows: List[Dict] = []
    settlement_total = 0.0

    expired_df = net_df.loc[expired_on_bill_date_mask].copy()
    for idx, row in expired_df.iterrows():
        option_type = str(row.get(option_type_col, "") or "").strip().upper()
        if option_type not in {"CE", "PE"}:
            continue

        net_qty = _to_float(row.get(net_qty_col))
        if abs(net_qty) < 1e-9:
            continue

        trading_symbol = _as_str(
            row.get(trading_symbol_col) if trading_symbol_col else ""
        )
        expiry_text = _as_str(row.get(expiry_col, ""))
        strike_value = _to_float_or_none(row.get(strike_col)) if strike_col else None
        underlying_close = (
            _to_float_or_none(row.get(underlying_close_col))
            if underlying_close_col
            else None
        )
        underlying_symbol = _as_str(
            row.get(underlying_symbol_col) if underlying_symbol_col else ""
        )

        base_payload = {
            "trading_symbol": trading_symbol,
            "expiry": expiry_text,
            "option_type": option_type,
            "strike": strike_value,
            "net_qty": net_qty,
            "underlying_symbol": underlying_symbol,
        }

        if underlying_close is None:
            pending_rows.append(
                {
                    **base_payload,
                    "underlying_close": None,
                    "intrinsic": None,
                    "action_status": "MISSING_UNDERLYING_CLOSE",
                    "settlement_amount": 0.0,
                }
            )
            continue

        if strike_value is None:
            pending_rows.append(
                {
                    **base_payload,
                    "underlying_close": underlying_close,
                    "intrinsic": None,
                    "action_status": "MISSING_STRIKE_PRICE",
                    "settlement_amount": 0.0,
                }
            )
            continue

        if option_type == "CE":
            intrinsic = max(0.0, underlying_close - strike_value)
        else:
            intrinsic = max(0.0, strike_value - underlying_close)

        multiplier = _resolve_multiplier(
            row=row,
            net_qty=net_qty,
            lot_size_col=lot_size_col,
            multiplier_col=multiplier_col,
            net_lot_col=net_lot_col,
        )
        settlement_amount = net_qty * intrinsic * multiplier

        if intrinsic == 0:
            action_status = "EXPIRE_OTM"
        elif net_qty > 0:
            action_status = "EXERCISE"
        else:
            action_status = "ASSIGN"

        settlement_rows.append(
            {
                **base_payload,
                "underlying_close": underlying_close,
                "intrinsic": intrinsic,
                "action_status": action_status,
                "settlement_amount": settlement_amount,
            }
        )
        settlement_total += settlement_amount

    return net_df_for_closing, settlement_rows, float(settlement_total), pending_rows


def _resolve_multiplier(
    *,
    row: pd.Series,
    net_qty: float,
    lot_size_col: Optional[str],
    multiplier_col: Optional[str],
    net_lot_col: Optional[str],
) -> float:
    multiplier_value = (
        _to_float_or_none(row.get(multiplier_col)) if multiplier_col else None
    )
    if multiplier_value is not None and multiplier_value > 0:
        return multiplier_value

    lot_size = _to_float_or_none(row.get(lot_size_col)) if lot_size_col else None
    net_lot = _to_float_or_none(row.get(net_lot_col)) if net_lot_col else None

    # If net qty appears to already be in lot units, multiply by lot size.
    if (
        lot_size is not None
        and lot_size > 0
        and net_lot is not None
        and abs(net_lot) > 1e-9
        and abs(abs(net_qty) - abs(net_lot)) <= 1e-9
    ):
        return lot_size

    return 1.0


def _find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    normalized_map = {_normalize_col_name(col): col for col in df.columns}
    for candidate in candidates:
        found = normalized_map.get(_normalize_col_name(candidate))
        if found:
            return found
    return None


def _normalize_col_name(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[^a-z0-9]", "", text)


def _as_str(value: object) -> str:
    return str(value or "").strip()


def _to_float(value: object) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return 0.0
    return float(numeric)


def _to_float_or_none(value: object) -> Optional[float]:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)

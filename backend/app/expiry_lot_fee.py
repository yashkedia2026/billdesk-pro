from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.expiry_settlement import parse_expiry

FEE_PER_LOT = 2.0


def compute_expiry_lot_fee(
    net_df: pd.DataFrame, bill_date: date
) -> Tuple[float, List[Dict]]:
    """
    Returns (total_fee, debug_rows).

    total_fee = sum(abs(NetLot) * 2) for expiring derivatives
    (options + futures) where NetQty != 0.
    """
    if net_df is None or not isinstance(net_df, pd.DataFrame) or net_df.empty:
        return 0.0, []

    expiry_col = _find_column(net_df, ["Expiry"])
    net_qty_col = _find_column(net_df, ["NetQty", "Net Qty"])
    if not expiry_col or not net_qty_col:
        return 0.0, []

    trading_symbol_col = _find_column(net_df, ["TradingSymbol", "Trading Symbol", "Symbol"])
    option_type_col = _find_column(net_df, ["Option Type"])
    instrument_type_col = _find_column(net_df, ["InstrumentType", "Instrument Type"])
    net_lot_col = _find_column(
        net_df,
        ["NetLot", "Net Lot", "Net Lots", "NetLotQty", "Net Lot Qty"],
    )
    lot_size_col = _find_column(net_df, ["LotSize", "Lot Size", "Lot_Size"])

    parsed_expiry = net_df[expiry_col].map(parse_expiry)
    net_qty_values = pd.to_numeric(net_df[net_qty_col], errors="coerce").fillna(0.0)
    expiring_mask = parsed_expiry == bill_date
    nonzero_qty_mask = net_qty_values != 0

    total_fee = 0.0
    debug_rows: List[Dict] = []

    for idx, row in net_df.loc[expiring_mask & nonzero_qty_mask].iterrows():
        trading_symbol = _as_text(row.get(trading_symbol_col) if trading_symbol_col else "")
        option_type = _as_text(row.get(option_type_col) if option_type_col else "").upper()
        instrument_type = _as_text(
            row.get(instrument_type_col) if instrument_type_col else ""
        ).upper()

        if not _is_derivative(
            trading_symbol=trading_symbol,
            option_type=option_type,
            instrument_type=instrument_type,
        ):
            continue

        net_qty = _to_float(row.get(net_qty_col))
        net_lot, lot_source = _resolve_net_lot(
            row=row,
            net_qty=net_qty,
            net_lot_col=net_lot_col,
            lot_size_col=lot_size_col,
        )

        if net_lot is None:
            fee = 0.0
            status = "MISSING_LOT_INFO"
        else:
            fee = abs(net_lot) * FEE_PER_LOT
            status = "OK"

        total_fee += fee
        debug_rows.append(
            {
                "TradingSymbol": trading_symbol,
                "Expiry": _as_text(row.get(expiry_col, "")),
                "NetQty": net_qty,
                "NetLot": net_lot,
                "LotSource": lot_source,
                "FeePerLot": FEE_PER_LOT,
                "Fee": round(fee, 2),
                "Status": status,
            }
        )

    return round(total_fee, 2), debug_rows


def _resolve_net_lot(
    *,
    row: pd.Series,
    net_qty: float,
    net_lot_col: Optional[str],
    lot_size_col: Optional[str],
) -> Tuple[Optional[float], str]:
    if net_lot_col:
        net_lot = _to_float_or_none(row.get(net_lot_col))
        if net_lot is not None:
            return float(net_lot), "NETLOT"

    if lot_size_col:
        lot_size = _to_float_or_none(row.get(lot_size_col))
        if lot_size is not None and abs(lot_size) > 1e-9:
            return float(net_qty) / float(lot_size), "QTY/LOTSIZE"

    return None, "MISSING"


def _is_derivative(
    *,
    trading_symbol: str,
    option_type: str,
    instrument_type: str,
) -> bool:
    symbol_upper = trading_symbol.upper()

    is_option = option_type in {"CE", "PE"} or bool(
        re.search(r"\bCE\b|\bPE\b", symbol_upper)
    )
    is_future = (
        "FUTIDX" in symbol_upper
        or "FUTSTK" in symbol_upper
        or bool(re.search(r"\bFUT\b", symbol_upper))
        or "FUT" in instrument_type
    )
    return is_option or is_future


def _find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    normalized_map = {_canonicalize(col): col for col in df.columns}
    for candidate in candidates:
        found = normalized_map.get(_canonicalize(candidate))
        if found:
            return found
    return None


def _canonicalize(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[^a-z0-9]", "", text)


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


def _as_text(value: object) -> str:
    return str(value or "").strip()

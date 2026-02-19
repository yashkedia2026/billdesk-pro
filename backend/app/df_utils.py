from __future__ import annotations

import re
from typing import Dict, Iterable, Optional

import pandas as pd


def normalize_optional_lot_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure optional lot-related columns use standardized names when present.

    Standardized output:
    - NetLot
    - LotSize
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df

    normalized = df.copy()
    candidates: Dict[str, Iterable[str]] = {
        "NetLot": (
            "NetLot",
            "Net Lot",
            "Net Lots",
            "NetLotQty",
            "Net Lot Qty",
        ),
        "LotSize": (
            "LotSize",
            "Lot Size",
            "Lot_Size",
        ),
    }

    existing = list(normalized.columns)
    for target, names in candidates.items():
        if target in normalized.columns:
            continue
        source = _find_first_matching_column(existing, names)
        if source and source in normalized.columns:
            normalized = normalized.rename(columns={source: target})
            existing = list(normalized.columns)

    return normalized


def _find_first_matching_column(
    columns: Iterable[object], candidates: Iterable[str]
) -> Optional[str]:
    canonical_map = {_canonicalize(col): str(col) for col in columns}
    for candidate in candidates:
        found = canonical_map.get(_canonicalize(candidate))
        if found:
            return found
    return None


def _canonicalize(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[^a-z0-9]", "", text)

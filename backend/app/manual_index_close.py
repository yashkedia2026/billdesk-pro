from __future__ import annotations

import math
from typing import Dict, Optional

INDEX_FIELD_MAP: Dict[str, str] = {
    "NIFTY": "close_nifty",
    "BANKNIFTY": "close_banknifty",
    "FINNIFTY": "close_finnifty",
    "MIDCPNIFTY": "close_midcpnifty",
    "NIFTYNXT50": "close_niftynxt50",
    "SENSEX": "close_sensex",
    "BANKEX": "close_bankex",
}


def build_manual_index_closes(**fields: Optional[str]) -> Dict[str, float]:
    closes: Dict[str, float] = {}
    for symbol, field_name in INDEX_FIELD_MAP.items():
        raw_value = fields.get(field_name)
        if raw_value is None:
            continue
        if not isinstance(raw_value, (str, int, float)):
            # Direct function calls in tests can pass FastAPI Form defaults.
            continue

        text = str(raw_value).strip()
        if not text:
            continue

        try:
            value = float(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid close for {symbol}") from exc

        if not math.isfinite(value):
            raise ValueError(f"Invalid close for {symbol}")

        closes[symbol.upper()] = value

    return closes

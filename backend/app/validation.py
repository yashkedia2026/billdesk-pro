import re
from typing import Dict, Iterable

REQUIRED_COLUMNS = [
    "TradingSymbol",
    "Exchg.Seg",
    "BuyQty",
    "SellQty",
    "NetQty",
    "BuyAvgPrice",
    "SellAvgPrice",
    "Actual Buy Value",
    "Actual Sell Value",
    "Actual Mark To Market",
]

TRADING_SYMBOL_PRIMARY = [
    "TradingSymbol",
    "Trading Symbol",
    "TRADING SYMBOL",
    "Trading_Symbol",
]

TRADING_SYMBOL_FALLBACK = ["Symbol"]

DAYWISE_SYNONYMS = {
    "TradingSymbol": TRADING_SYMBOL_PRIMARY + TRADING_SYMBOL_FALLBACK,
    "Exchg.Seg": [
        "Exchg.Seg",
        "Exchg Seg",
        "Exchg_Seg",
        "ExchgSeg",
        "ExchSeg",
        "Exchange",
        "Exch",
        "Exch Seg",
        "Exchange Segment",
    ],
    "BuyQty": [
        "BuyQty",
        "Buy Qty",
        "BUY QTY",
        "Buy_Qty",
        "Buy Quantity",
    ],
    "SellQty": [
        "SellQty",
        "Sell Qty",
        "SELL QTY",
        "Sell_Qty",
        "Sell Quantity",
    ],
    "NetQty": [
        "NetQty",
        "Net Qty",
        "NET QTY",
        "Net_Qty",
        "Net Quantity",
    ],
    "BuyAvgPrice": [
        "BuyAvgPrice",
        "Buy Avg Price",
        "BUY AVG PRICE",
        "Buy_Avg_Price",
        "BuyAveragePrice",
        "Buy Average Price",
        "Avg Buy Price",
    ],
    "SellAvgPrice": [
        "SellAvgPrice",
        "Sell Avg Price",
        "SELL AVG PRICE",
        "Sell_Avg_Price",
        "SellAveragePrice",
        "Sell Average Price",
        "Avg Sell Price",
    ],
}

NETWISE_SYNONYMS = DAYWISE_SYNONYMS


def _canonicalize_header(value: object) -> str:
    text = str(value).strip().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def normalize_columns(df, synonyms_map: Dict[str, Iterable[str]]):
    normalized = df.dropna(how="all")
    normalized.columns = [str(col).strip() for col in normalized.columns]

    canonical_columns = {_canonicalize_header(col) for col in normalized.columns}
    primary_canon = {_canonicalize_header(name) for name in TRADING_SYMBOL_PRIMARY}
    has_trading_symbol = bool(primary_canon.intersection(canonical_columns))

    effective_map = synonyms_map
    if has_trading_symbol and "TradingSymbol" in synonyms_map:
        effective_map = dict(synonyms_map)
        synonyms = [
            name
            for name in effective_map["TradingSymbol"]
            if _canonicalize_header(name) != _canonicalize_header("Symbol")
        ]
        effective_map["TradingSymbol"] = synonyms

    canonical_map = {}
    for target, synonyms in effective_map.items():
        canonical_map[_canonicalize_header(target)] = target
        for name in synonyms:
            canonical_map[_canonicalize_header(name)] = target

    rename_map = {}
    existing = set(normalized.columns)
    for col in normalized.columns:
        canonical = _canonicalize_header(col)
        target = canonical_map.get(canonical)
        if not target:
            continue
        if col == target:
            continue
        if target in existing:
            continue
        if target in rename_map.values():
            continue
        rename_map[col] = target

    normalized = normalized.rename(columns=rename_map) if rename_map else normalized

    for col in ("TradingSymbol", "Exchg.Seg"):
        if col in normalized.columns:
            series = normalized[col]
            series = series.where(series.notna(), "")
            normalized[col] = series.astype(str).str.strip()

    return normalized


def validate_csv_columns(df, required_cols, synonyms_map=None, label="CSV"):
    if isinstance(synonyms_map, str) and label == "CSV":
        label = synonyms_map
        synonyms_map = None

    detected_columns = [str(col).strip() for col in df.columns]
    normalized_df = normalize_columns(df, synonyms_map or {})
    missing = [col for col in required_cols if col not in normalized_df.columns]
    if missing:
        raise ValueError(
            f"Invalid {label} CSV format. Missing columns: {missing}. "
            f"Detected columns: {detected_columns}."
        )
    return normalized_df

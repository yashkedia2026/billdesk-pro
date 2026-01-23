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


def validate_csv_columns(df, required_cols, label) -> None:
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"{label} CSV missing required columns: {missing}")

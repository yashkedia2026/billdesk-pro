from typing import Dict, List, Tuple

import pandas as pd


NUMERIC_COLUMNS = [
    "BuyQty",
    "SellQty",
    "NetQty",
    "Actual Buy Value",
    "Actual Sell Value",
    "Actual Mark To Market",
]


def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned.columns = [str(col).strip() for col in cleaned.columns]
    cleaned = cleaned.loc[
        :, [col for col in cleaned.columns if not str(col).startswith("Unnamed:")]
    ]

    if "TradingSymbol" in cleaned.columns:
        symbols = cleaned["TradingSymbol"].fillna("").astype(str).str.strip()
        cleaned = cleaned.loc[symbols != ""].copy()
        cleaned["TradingSymbol"] = symbols[symbols != ""]

    return cleaned


def build_positions(day_df: pd.DataFrame) -> Tuple[List[Dict], Dict]:
    df = day_df.copy()
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    grouped = (
        df.groupby(["Exchg.Seg", "TradingSymbol"], dropna=False)
        .agg(
            {
                "BuyQty": "sum",
                "SellQty": "sum",
                "NetQty": "sum",
                "Actual Buy Value": "sum",
                "Actual Sell Value": "sum",
                "Actual Mark To Market": "sum",
            }
        )
        .reset_index()
    )

    grouped = grouped.sort_values(
        by=["TradingSymbol", "Exchg.Seg"], kind="mergesort"
    ).reset_index(drop=True)

    rows: List[Dict] = []
    total_buy_qty = 0
    total_buy_amount = 0.0
    total_sell_qty = 0
    total_sell_amount = 0.0
    total_mtm_amount = 0.0

    for index, row in grouped.iterrows():
        buy_qty_value = float(row["BuyQty"])
        sell_qty_value = float(row["SellQty"])
        net_qty_value = float(row["NetQty"])
        buy_amount_value = float(row["Actual Buy Value"])
        sell_amount_value = float(row["Actual Sell Value"])
        mtm_amount_value = float(row["Actual Mark To Market"])

        buy_rate = buy_amount_value / buy_qty_value if buy_qty_value > 0 else 0.0
        sell_rate = sell_amount_value / sell_qty_value if sell_qty_value > 0 else 0.0

        buy_qty = int(round(buy_qty_value))
        sell_qty = int(round(sell_qty_value))
        net_qty = int(round(net_qty_value))
        net_amount_value = sell_amount_value - buy_amount_value

        rows.append(
            {
                "sr": index + 1,
                "security": str(row["TradingSymbol"]),
                "bf_qty": 0,
                "bf_rate": 0,
                "bf_amount": 0,
                "buy_qty": buy_qty,
                "buy_rate": buy_rate,
                "buy_amount": buy_amount_value,
                "sell_qty": sell_qty,
                "sell_rate": sell_rate,
                "sell_amount": sell_amount_value,
                "brkg": 0,
                "net_qty": net_qty,
                "net_rate": 0,
                "net_amount": net_amount_value,
                "mtm_amount": mtm_amount_value,
            }
        )

        total_buy_qty += buy_qty
        total_buy_amount += buy_amount_value
        total_sell_qty += sell_qty
        total_sell_amount += sell_amount_value
        total_mtm_amount += mtm_amount_value

    totals = {
        "total_buy_qty": total_buy_qty,
        "total_buy_amount": total_buy_amount,
        "total_sell_qty": total_sell_qty,
        "total_sell_amount": total_sell_amount,
        "total_net_amount": total_sell_amount - total_buy_amount,
        "total_brkg": 0,
        "total_mtm_amount": total_mtm_amount,
    }

    return rows, totals

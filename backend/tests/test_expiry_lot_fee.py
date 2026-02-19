from datetime import date

import pandas as pd

from app.charges import compute_charges
from app.expiry_lot_fee import compute_expiry_lot_fee
from app.rate_card import get_rate_card


def test_expiry_lot_fee_uses_netlot_for_expiring_option() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 12FEB2026 CE 22000",
                "Option Type": "CE",
                "NetQty": -500,
                "NetLot": -100,
                "Expiry": "12Feb2026",
            }
        ]
    )

    total_fee, rows = compute_expiry_lot_fee(net_df, date(2026, 2, 12))

    assert total_fee == 200.0
    assert len(rows) == 1
    assert rows[0]["NetLot"] == -100.0
    assert rows[0]["LotSource"] == "NETLOT"
    assert rows[0]["Fee"] == 200.0
    assert rows[0]["Status"] == "OK"


def test_expiry_lot_fee_applies_for_otm_option_too() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "SENSEX 12FEB2026 PE 82000",
                "Option Type": "PE",
                "NetQty": 250,
                "NetLot": 50,
                "Expiry": "12Feb2026",
            }
        ]
    )

    total_fee, rows = compute_expiry_lot_fee(net_df, date(2026, 2, 12))

    assert total_fee == 100.0
    assert len(rows) == 1
    assert rows[0]["Fee"] == 100.0


def test_expiry_lot_fee_ignores_non_expiry_rows() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "BANKEX 19FEB2026 FUT",
                "NetQty": -75,
                "NetLot": -15,
                "Expiry": "19Feb2026",
            }
        ]
    )

    total_fee, rows = compute_expiry_lot_fee(net_df, date(2026, 2, 12))

    assert total_fee == 0.0
    assert rows == []


def test_expiry_lot_fee_ignores_zero_netqty() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 12FEB2026 CE 22000",
                "Option Type": "CE",
                "NetQty": 0,
                "NetLot": 0,
                "Expiry": "12Feb2026",
            }
        ]
    )

    total_fee, rows = compute_expiry_lot_fee(net_df, date(2026, 2, 12))

    assert total_fee == 0.0
    assert rows == []


def test_expiry_lot_fee_falls_back_to_qty_div_lotsize() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 12FEB2026 FUT",
                "NetQty": -150,
                "LotSize": 50,
                "Expiry": "12Feb2026",
            }
        ]
    )

    total_fee, rows = compute_expiry_lot_fee(net_df, date(2026, 2, 12))

    assert total_fee == 6.0
    assert len(rows) == 1
    assert rows[0]["NetLot"] == -3.0
    assert rows[0]["LotSource"] == "QTY/LOTSIZE"
    assert rows[0]["Status"] == "OK"


def test_expiry_lot_fee_marks_missing_lot_info() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 12FEB2026 FUT",
                "NetQty": 100,
                "Expiry": "12Feb2026",
            }
        ]
    )

    total_fee, rows = compute_expiry_lot_fee(net_df, date(2026, 2, 12))

    assert total_fee == 0.0
    assert len(rows) == 1
    assert rows[0]["NetLot"] is None
    assert rows[0]["LotSource"] == "MISSING"
    assert rows[0]["Fee"] == 0.0
    assert rows[0]["Status"] == "MISSING_LOT_INFO"


def test_compute_charges_adds_expiry_lot_fee_into_clearing_charges() -> None:
    day_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 12FEB2026 CE 22000",
                "Exchg.Seg": "NFO",
                "BuyQty": 10,
                "SellQty": 0,
                "NetQty": 10,
                "BuyAvgPrice": 100.0,
                "SellAvgPrice": 0.0,
                "Actual Buy Value": 1000.0,
                "Actual Sell Value": 0.0,
                "Actual Mark To Market": -1000.0,
            }
        ]
    )
    net_df = pd.DataFrame(columns=["TradingSymbol", "NetQty", "Exchg.Seg"])
    rate_card = get_rate_card()

    charges_base, _ = compute_charges(day_df, net_df, rate_card, expiry_lot_fee=0.0)
    charges_fee, _ = compute_charges(day_df, net_df, rate_card, expiry_lot_fee=200.0)

    base_clearing = next(
        line["amount"] for line in charges_base["bill_lines"] if line["code"] == "CLEARING"
    )
    fee_clearing = next(
        line["amount"] for line in charges_fee["bill_lines"] if line["code"] == "CLEARING"
    )
    assert round(abs(fee_clearing) - abs(base_clearing), 2) == 200.0

import pandas as pd

from app.closing_positions import build_closing_positions


def test_build_closing_positions_filters_zero_qty_and_expired_contracts() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 13FEB2026 CE 22000",
                "NetQty": -50,
                "LastTradePrice": 125.2,
            },
            {
                "TradingSymbol": "NIFTY 13JAN2026 PE 22000",
                "NetQty": 75,
                "LastTradePrice": 100.0,
            },
            {
                "TradingSymbol": "NIFTY 27JAN2026 CE 22000",
                "NetQty": 0,
                "LastTradePrice": 210.0,
            },
        ]
    )

    rows, total_value, status = build_closing_positions(net_df, "20-01-2026")

    assert status == "OK"
    assert len(rows) == 1
    assert rows[0]["contract"] == "NIFTY 13FEB2026 CE 22000"
    assert rows[0]["net_qty"] == -50
    assert rows[0]["ltp"] == 125.2
    assert round(total_value, 2) == -6260.0


def test_build_closing_positions_returns_missing_for_empty_input() -> None:
    rows, total_value, status = build_closing_positions(pd.DataFrame(), "20-01-2026")

    assert rows == []
    assert total_value == 0.0
    assert status == "MISSING"


def test_build_closing_positions_returns_no_open_positions() -> None:
    net_df = pd.DataFrame(
        [
            {"TradingSymbol": "NIFTY 13FEB2026 CE 22000", "NetQty": 0, "LastTradePrice": 1},
            {"TradingSymbol": "NIFTY 13FEB2026 PE 22000", "NetQty": 0, "LastTradePrice": 1},
        ]
    )

    rows, total_value, status = build_closing_positions(net_df, "20-01-2026")

    assert rows == []
    assert total_value == 0.0
    assert status == "NO_OPEN_POSITIONS"


def test_build_closing_positions_uses_explicit_expiry_column() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "BANKNIFTY 30JAN2026 CE 50000",
                "NetQty": 10,
                "LastTradePrice": 10.0,
                "Expiry Date": "2026-01-18",
            },
            {
                "TradingSymbol": "BANKNIFTY 30JAN2026 PE 50000",
                "NetQty": 5,
                "LastTradePrice": 20.0,
                "Expiry Date": "2026-01-20",
            },
        ]
    )

    rows, total_value, status = build_closing_positions(net_df, "2026-01-20")

    assert status == "OK"
    assert len(rows) == 1
    assert rows[0]["net_qty"] == 5
    assert round(total_value, 2) == 100.0


def test_build_closing_positions_safe_default_for_uncertain_expiry() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 13FEB CE 22000",
                "NetQty": 25,
                "LastTradePrice": 4.0,
            }
        ]
    )

    rows, total_value, status = build_closing_positions(net_df, "20-02-2026")

    assert status == "OK"
    assert len(rows) == 1
    assert round(total_value, 2) == 100.0

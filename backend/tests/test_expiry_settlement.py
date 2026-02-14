from datetime import date

import pandas as pd

from app.expiry_settlement import apply_expiry_settlement, parse_expiry


def test_parse_expiry_dd_mmm_yyyy() -> None:
    assert parse_expiry("12Feb2026") == date(2026, 2, 12)
    assert parse_expiry("12FEB2026") == date(2026, 2, 12)


def test_expired_option_missing_underlying_goes_pending_and_filtered_from_closing() -> None:
    net_df = pd.DataFrame(
        [
            {
                "Trading Symbol": "NIFTY 12FEB2026 CE 22000",
                "Net Qty": 50,
                "Option Type": "CE",
                "Strike Price": 22000,
                "Expiry": "12Feb2026",
            }
        ]
    )

    net_for_closing, settlement_rows, settlement_total, pending_rows = apply_expiry_settlement(
        net_df, date(2026, 2, 12)
    )

    assert net_for_closing.empty
    assert settlement_rows == []
    assert settlement_total == 0.0
    assert len(pending_rows) == 1
    assert pending_rows[0]["action_status"] == "MISSING_UNDERLYING_CLOSE"
    assert pending_rows[0]["settlement_amount"] == 0.0


def test_expired_option_with_underlying_close_creates_settlement_row() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 12FEB2026 CE 22000",
                "NetQty": 2,
                "Option Type": "CE",
                "Strike Price": 100,
                "Underlying Close": 120,
                "Expiry": "12Feb2026",
            }
        ]
    )

    net_for_closing, settlement_rows, settlement_total, pending_rows = apply_expiry_settlement(
        net_df, date(2026, 2, 12)
    )

    assert net_for_closing.empty
    assert pending_rows == []
    assert len(settlement_rows) == 1
    assert settlement_rows[0]["action_status"] == "EXERCISE"
    assert settlement_rows[0]["intrinsic"] == 20.0
    assert settlement_rows[0]["settlement_amount"] == 40.0
    assert settlement_total == 40.0


def test_non_expired_row_remains_in_closing() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 13FEB2026 CE 22000",
                "NetQty": -10,
                "Option Type": "CE",
                "Strike Price": 22000,
                "Expiry": "13Feb2026",
            }
        ]
    )

    net_for_closing, settlement_rows, settlement_total, pending_rows = apply_expiry_settlement(
        net_df, date(2026, 2, 12)
    )

    assert len(net_for_closing) == 1
    assert settlement_rows == []
    assert pending_rows == []
    assert settlement_total == 0.0


def test_expired_non_option_filtered_without_settlement_rows() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 12FEB2026 FUT",
                "NetQty": 25,
                "Option Type": "XX",
                "Expiry": "12Feb2026",
            }
        ]
    )

    net_for_closing, settlement_rows, settlement_total, pending_rows = apply_expiry_settlement(
        net_df, date(2026, 2, 12)
    )

    assert net_for_closing.empty
    assert settlement_rows == []
    assert pending_rows == []
    assert settlement_total == 0.0

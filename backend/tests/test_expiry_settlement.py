from datetime import date

import pandas as pd

from app.expiry_settlement import apply_expiry_settlement, parse_expiry


def test_parse_expiry_dd_mmm_yyyy() -> None:
    assert parse_expiry("12Feb2026") == date(2026, 2, 12)
    assert parse_expiry("12FEB2026") == date(2026, 2, 12)


def test_expired_option_missing_manual_close_goes_pending_and_filtered_from_closing() -> None:
    net_df = pd.DataFrame(
        [
            {
                "Trading Symbol": "SENSEX 12FEB2026 CE 84000",
                "Net Qty": 50,
                "Option Type": "CE",
                "Strike Price": 84000,
                "Expiry": "12Feb2026",
            }
        ]
    )

    net_for_closing, settlement_rows, settlement_total, pending_rows = apply_expiry_settlement(
        net_df,
        date(2026, 2, 12),
        manual_closes={},
    )

    assert net_for_closing.empty
    assert settlement_rows == []
    assert settlement_total == 0.0
    assert len(pending_rows) == 1
    assert pending_rows[0]["underlying_symbol"] == "SENSEX"
    assert pending_rows[0]["status"] == "MISSING_MANUAL_CLOSE"
    assert pending_rows[0]["source"] == "MANUAL_INPUT"
    assert pending_rows[0]["settlement_amount"] == 0.0


def test_expired_option_with_manual_close_creates_settlement_row() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 12FEB2026 CE 22000",
                "NetQty": 50,
                "Option Type": "CE",
                "Strike Price": 22000,
                "Expiry": "12Feb2026",
            }
        ]
    )

    net_for_closing, settlement_rows, settlement_total, pending_rows = apply_expiry_settlement(
        net_df,
        date(2026, 2, 12),
        manual_closes={"NIFTY": 22100.0},
    )

    assert net_for_closing.empty
    assert pending_rows == []
    assert len(settlement_rows) == 1
    assert settlement_rows[0]["underlying_symbol"] == "NIFTY"
    assert settlement_rows[0]["underlying_close"] == 22100.0
    assert settlement_rows[0]["verification_status"] == "VERIFIED_MANUAL"
    assert settlement_rows[0]["source"] == "MANUAL_INPUT"
    assert settlement_rows[0]["close_date"] == "2026-02-12"
    assert settlement_rows[0]["action_status"] == "EXERCISE"
    assert settlement_rows[0]["intrinsic"] == 100.0
    assert settlement_rows[0]["settlement_amount"] == 5000.0
    assert settlement_total == 5000.0


def test_manual_closes_ignored_for_non_expiry_rows() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "NIFTY 13FEB2026 PE 22000",
                "NetQty": -10,
                "Option Type": "PE",
                "Strike Price": 22000,
                "Expiry": "13Feb2026",
            }
        ]
    )

    net_for_closing, settlement_rows, settlement_total, pending_rows = apply_expiry_settlement(
        net_df,
        date(2026, 2, 12),
        manual_closes={"NIFTY": 21950.0},
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
        net_df,
        date(2026, 2, 12),
        manual_closes={"NIFTY": 21950.0},
    )

    assert net_for_closing.empty
    assert settlement_rows == []
    assert pending_rows == []
    assert settlement_total == 0.0


def test_closing_df_excludes_expired_rows_even_when_manual_close_is_present() -> None:
    net_df = pd.DataFrame(
        [
            {
                "TradingSymbol": "BANKEX 12FEB2026 CE 52000",
                "NetQty": -10,
                "Option Type": "CE",
                "Strike Price": 52000,
                "Expiry": "12Feb2026",
            },
            {
                "TradingSymbol": "BANKEX 19FEB2026 CE 52500",
                "NetQty": 5,
                "Option Type": "CE",
                "Strike Price": 52500,
                "Expiry": "19Feb2026",
            },
        ]
    )

    net_for_closing, settlement_rows, settlement_total, pending_rows = apply_expiry_settlement(
        net_df,
        date(2026, 2, 12),
        manual_closes={"BANKEX": 52300.0},
    )

    assert len(net_for_closing) == 1
    assert "19FEB2026" in str(net_for_closing.iloc[0]["TradingSymbol"])
    assert len(settlement_rows) == 1
    assert pending_rows == []
    assert settlement_total == -3000.0

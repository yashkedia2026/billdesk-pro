import pandas as pd
import pytest

from app.validation import NETWISE_SYNONYMS, REQUIRED_COLUMNS, validate_csv_columns


def _base_row() -> dict:
    return {
        "Actual Buy Value": 100,
        "Actual Sell Value": 120,
        "Actual Mark To Market": 20,
    }


def test_trading_symbol_preferred_over_symbol() -> None:
    df = pd.DataFrame(
        [
            {
                "Symbol": "NIFTY",
                "Trading Symbol": "NIFTY 23JAN2026 CE 25650",
                "Exchange": "NSE_FNO",
                "Buy Qty": 10,
                "Sell Qty": 10,
                "Net Qty": 0,
                "Buy Avg Price": 1,
                "Sell Avg Price": 1,
                **_base_row(),
            }
        ]
    )
    normalized = validate_csv_columns(
        df, REQUIRED_COLUMNS, NETWISE_SYNONYMS, "Netwise"
    )
    assert normalized.loc[0, "TradingSymbol"] == "NIFTY 23JAN2026 CE 25650"
    assert "Symbol" in normalized.columns


def test_all_empty_rows_are_dropped() -> None:
    df = pd.DataFrame(
        [
            {
                "Trading Symbol": None,
                "Exchange": None,
                "Buy Qty": None,
                "Sell Qty": None,
                "Net Qty": None,
                "Buy Avg Price": None,
                "Sell Avg Price": None,
                "Actual Buy Value": None,
                "Actual Sell Value": None,
                "Actual Mark To Market": None,
            },
            {
                "Trading Symbol": "NIFTY 23JAN2026 CE 25650",
                "Exchange": "NSE_FNO",
                "Buy Qty": 10,
                "Sell Qty": 10,
                "Net Qty": 0,
                "Buy Avg Price": 1,
                "Sell Avg Price": 1,
                **_base_row(),
            },
        ]
    )
    normalized = validate_csv_columns(
        df, REQUIRED_COLUMNS, NETWISE_SYNONYMS, "Netwise"
    )
    assert len(normalized) == 1


def test_invalid_headers_show_detected_columns() -> None:
    df = pd.DataFrame([{"Symbol": "NIFTY"}])
    with pytest.raises(ValueError) as exc_info:
        validate_csv_columns(df, REQUIRED_COLUMNS, NETWISE_SYNONYMS, "Netwise")
    message = str(exc_info.value)
    assert "Invalid Netwise CSV format" in message
    assert "Missing columns" in message
    assert "Detected columns" in message
    assert "Symbol" in message

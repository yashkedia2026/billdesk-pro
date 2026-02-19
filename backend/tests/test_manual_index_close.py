import pytest

from app.manual_index_close import build_manual_index_closes


def test_build_manual_index_closes_empty_returns_empty_dict() -> None:
    closes = build_manual_index_closes(
        close_nifty="",
        close_banknifty=None,
        close_finnifty="   ",
    )
    assert closes == {}


def test_build_manual_index_closes_parses_partial_values() -> None:
    closes = build_manual_index_closes(
        close_nifty="22456.25",
        close_sensex="74210",
    )
    assert closes == {"NIFTY": 22456.25, "SENSEX": 74210.0}


def test_build_manual_index_closes_invalid_value_raises() -> None:
    with pytest.raises(ValueError, match="Invalid close for NIFTY"):
        build_manual_index_closes(close_nifty="abc")

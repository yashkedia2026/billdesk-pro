import pandas as pd

from app.admin_batch import extract_group_indices, netwise_only_keys, resolve_group_columns
from app.positions import clean_df


def test_resolve_group_columns_prefers_account_id():
    day_df = pd.DataFrame({"Account Id": ["A1"], "User Id": ["U1"]})
    net_df = pd.DataFrame({"account_id": ["A1"], "user_id": ["U1"]})

    info = resolve_group_columns(day_df, net_df)
    assert info["group_key"] == "account_id"
    assert info["day_account_col"] == "Account Id"
    assert info["net_account_col"] == "account_id"


def test_resolve_group_columns_falls_back_to_user_id():
    day_df = pd.DataFrame({"User Code": ["U1"]})
    net_df = pd.DataFrame({"userid": ["U1"]})

    info = resolve_group_columns(day_df, net_df)
    assert info["group_key"] == "user_id"
    assert info["day_user_col"] == "User Code"
    assert info["net_user_col"] == "userid"


def test_extract_group_indices_with_fallback():
    day_df = pd.DataFrame(
        {
            "Account Id": ["A1", ""],
            "User Id": ["U1", "U2"],
        }
    )
    net_df = pd.DataFrame(
        {
            "Account Id": ["A1", ""],
            "User Id": ["U1", "U2"],
        }
    )

    info = resolve_group_columns(day_df, net_df)
    day_groups, net_groups, _, _ = extract_group_indices(
        day_df,
        net_df,
        info["group_key"],
        info["day_account_col"],
        info["day_user_col"],
        info["net_account_col"],
        info["net_user_col"],
    )

    assert "A1" in day_groups
    assert "U2" in day_groups
    assert "A1" in net_groups
    assert "U2" in net_groups


def test_daywise_groups_include_missing_netwise():
    day_df = pd.DataFrame({"Account Id": ["A1", "A2", "A3"]})
    net_df = pd.DataFrame({"Account Id": ["A1"]})

    info = resolve_group_columns(day_df, net_df)
    day_groups, net_groups, _, _ = extract_group_indices(
        day_df,
        net_df,
        info["group_key"],
        info["day_account_col"],
        info["day_user_col"],
        info["net_account_col"],
        info["net_user_col"],
    )

    assert set(day_groups.keys()) == {"A1", "A2", "A3"}
    assert set(net_groups.keys()) == {"A1"}


def test_blank_keys_are_ignored():
    day_df = pd.DataFrame({"Account Id": ["A1", "", None, "nan"]})
    net_df = pd.DataFrame({"Account Id": ["A1", "", None]})

    info = resolve_group_columns(day_df, net_df)
    day_groups, net_groups, _, _ = extract_group_indices(
        day_df,
        net_df,
        info["group_key"],
        info["day_account_col"],
        info["day_user_col"],
        info["net_account_col"],
        info["net_user_col"],
    )

    assert set(day_groups.keys()) == {"A1"}
    assert set(net_groups.keys()) == {"A1"}


def test_netwise_only_accounts_detected():
    day_df = pd.DataFrame({"Account Id": ["A1"]})
    net_df = pd.DataFrame({"Account Id": ["A1", "A2"]})

    info = resolve_group_columns(day_df, net_df)
    day_groups, net_groups, _, _ = extract_group_indices(
        day_df,
        net_df,
        info["group_key"],
        info["day_account_col"],
        info["day_user_col"],
        info["net_account_col"],
        info["net_user_col"],
    )

    assert netwise_only_keys(day_groups, net_groups) == ["A2"]


def test_empty_netwise_schema_retained():
    net_df = pd.DataFrame(
        {
            "Exchg.Seg": ["NFO"],
            "TradingSymbol": ["ABC"],
            "NetQty": [1],
            "SettlementType": ["E"],
            "Square Off Context": ["EXE"],
            "Actual Buy Value": [100.0],
            "Actual Sell Value": [50.0],
            "LastTradePrice": [10.0],
            "ProductType": ["NRML"],
        }
    )
    empty_df = net_df.head(0).copy()
    assert list(empty_df.columns) == list(net_df.columns)


def test_group_then_clean_can_drop_account_rows():
    day_df = pd.DataFrame(
        {
            "Account Id": ["A1", "A2", "A3"],
            "TradingSymbol": ["AAA", "", "CCC"],
            "Exchg.Seg": ["NFO", "NFO", "NFO"],
        }
    )
    net_df = pd.DataFrame({"Account Id": ["A1", "A2", "A3"]})

    info = resolve_group_columns(day_df, net_df)
    day_groups, _, _, _ = extract_group_indices(
        day_df,
        net_df,
        info["group_key"],
        info["day_account_col"],
        info["day_user_col"],
        info["net_account_col"],
        info["net_user_col"],
    )

    assert set(day_groups.keys()) == {"A1", "A2", "A3"}
    a2_clean = clean_df(day_df.loc[day_groups["A2"]])
    assert a2_clean.empty

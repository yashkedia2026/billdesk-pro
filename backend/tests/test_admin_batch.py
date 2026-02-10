import pandas as pd

from app.admin_batch import extract_group_indices, resolve_group_columns


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
    day_groups, net_groups, failures = extract_group_indices(
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
    assert not failures


def test_extract_group_indices_reports_missing_ids():
    day_df = pd.DataFrame(
        {
            "Account Id": ["A1", ""],
            "User Id": ["U1", ""],
        }
    )
    net_df = pd.DataFrame(
        {
            "Account Id": ["A1", ""],
            "User Id": ["U1", ""],
        }
    )

    info = resolve_group_columns(day_df, net_df)
    _, _, failures = extract_group_indices(
        day_df,
        net_df,
        info["group_key"],
        info["day_account_col"],
        info["day_user_col"],
        info["net_account_col"],
        info["net_user_col"],
    )

    assert any("missing Account Id or User Id" in item["error"] for item in failures)

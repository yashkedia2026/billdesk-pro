import re
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

ACCOUNT_ID_SYNONYMS = [
    "account id",
    "account_id",
    "account",
    "accountid",
    "client code",
    "client_code",
]

USER_ID_SYNONYMS = [
    "user id",
    "user_id",
    "userid",
    "user",
    "usercode",
    "user code",
]


def normalize_col(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def find_column(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    if df is None:
        return None
    normalized_candidates = [normalize_col(name) for name in candidates]
    normalized_cols = [(normalize_col(col), col) for col in df.columns]
    for candidate in normalized_candidates:
        for normalized, original in normalized_cols:
            if normalized == candidate:
                return original
    return None


def resolve_group_columns(day_df: pd.DataFrame, net_df: pd.DataFrame) -> Dict[str, Optional[str]]:
    day_account = find_column(day_df, ACCOUNT_ID_SYNONYMS)
    net_account = find_column(net_df, ACCOUNT_ID_SYNONYMS)
    day_user = find_column(day_df, USER_ID_SYNONYMS)
    net_user = find_column(net_df, USER_ID_SYNONYMS)

    if day_account and net_account:
        group_key = "account_id"
    elif day_user and net_user:
        group_key = "user_id"
    else:
        raise ValueError("Admin file must contain Account Id or User Id column.")

    return {
        "group_key": group_key,
        "day_account_col": day_account,
        "net_account_col": net_account,
        "day_user_col": day_user,
        "net_user_col": net_user,
    }


def extract_group_indices(
    day_df: pd.DataFrame,
    net_df: pd.DataFrame,
    group_key: str,
    day_account_col: Optional[str],
    day_user_col: Optional[str],
    net_account_col: Optional[str],
    net_user_col: Optional[str],
) -> Tuple[Dict[str, pd.Index], Dict[str, pd.Index], List[Dict[str, str]]]:
    failures: List[Dict[str, str]] = []
    day_groups = _build_group_indices(
        day_df,
        group_key,
        day_account_col,
        day_user_col,
        "Daywise",
        failures,
    )
    net_groups = _build_group_indices(
        net_df,
        group_key,
        net_account_col,
        net_user_col,
        "Netwise",
        failures,
    )
    return day_groups, net_groups, failures


def _normalize_series(series: pd.Series) -> pd.Series:
    cleaned = series.where(series.notna(), "")
    return cleaned.astype(str).str.strip()


def _build_group_indices(
    df: pd.DataFrame,
    group_key: str,
    account_col: Optional[str],
    user_col: Optional[str],
    source_label: str,
    failures: List[Dict[str, str]],
) -> Dict[str, pd.Index]:
    if group_key == "account_id":
        if not account_col:
            raise ValueError("Admin file must contain Account Id or User Id column.")
        account_series = _normalize_series(df[account_col])
        user_series = _normalize_series(df[user_col]) if user_col else None
        key_series = account_series
        if user_series is not None:
            key_series = account_series.where(account_series != "", user_series)
        missing_mask = key_series == ""
        missing_label = "Account Id or User Id" if user_series is not None else "Account Id"
    else:
        if not user_col:
            raise ValueError("Admin file must contain Account Id or User Id column.")
        key_series = _normalize_series(df[user_col])
        missing_mask = key_series == ""
        missing_label = "User Id"

    if missing_mask.any():
        for idx in df.index[missing_mask]:
            failures.append(
                {
                    "key": f"{source_label}_row_{idx}",
                    "error": f"{source_label} row missing {missing_label}.",
                }
            )

    valid_df = df.loc[~missing_mask]
    valid_keys = key_series.loc[~missing_mask]
    groups = valid_df.groupby(valid_keys, sort=False).groups
    return {str(key).strip(): indices for key, indices in groups.items()}

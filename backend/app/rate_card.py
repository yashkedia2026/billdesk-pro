import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


class RateCardError(ValueError):
    pass


_RATE_CARD_CACHE: Optional[Dict] = None


def get_rate_card() -> Dict:
    global _RATE_CARD_CACHE
    if _RATE_CARD_CACHE is not None:
        return _RATE_CARD_CACHE

    rate_card_path = _resolve_rate_card_path()
    rules = _parse_rate_card(rate_card_path)

    _RATE_CARD_CACHE = {"source": str(rate_card_path), "rules": rules}
    return _RATE_CARD_CACHE


def _resolve_rate_card_path() -> Path:
    env_path = os.getenv("RATE_CARD_PATH")
    if env_path:
        resolved = Path(env_path).expanduser()
        if not resolved.exists():
            raise RateCardError(f"Rate card not found at {resolved}")
        return resolved

    config_dir = Path(__file__).resolve().parent.parent / "config"
    default_path = config_dir / "rate_card.xlsx"
    fallback_path = config_dir / "FO CHARGES FORMULA.xlsx"
    if default_path.exists():
        return default_path
    if fallback_path.exists():
        return fallback_path

    raise RateCardError(
        "Rate card not found. Set RATE_CARD_PATH or place file at backend/config/rate_card.xlsx"
    )


def _parse_rate_card(rate_card_path: Path) -> List[Dict]:
    try:
        df = pd.read_excel(rate_card_path, sheet_name=0, header=0, engine="openpyxl")
    except Exception as exc:
        raise RateCardError(f"Rate card could not be read: {exc}") from None

    df = _normalize_columns(df)
    column_map = _detect_columns(list(df.columns))

    if not column_map["name_col"] or not column_map["gst_col"]:
        raise RateCardError(
            "Rate card missing required columns for charge name and GST."
        )

    rules = _build_rules(df, column_map)
    if len(rules) < 8:
        raise RateCardError("Rate card parse produced too few rules (< 8).")

    return rules


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(col).strip().lower() for col in normalized.columns]
    return normalized


def _detect_columns(columns: List[str]) -> Dict[str, Optional[str]]:
    name_col = _first_match(
        columns, lambda col: col.startswith("charges") or "charges" in col
    )

    futures_col = _first_match(
        columns, lambda col: col == "fut" or ("fut" in col and col != name_col)
    )
    options_col = _first_match(columns, lambda col: "opt" in col)

    assignment_col = _first_match(columns, lambda col: "asg" in col)
    if assignment_col is None:
        assignment_col = _first_match(
            columns, lambda col: "ex" in col and col != name_col
        )

    gst_col = _first_match(columns, lambda col: "gst" in col)
    side_col = _first_match(
        columns, lambda col: "b/s" in col or col == "b_s" or "side" in col
    )

    return {
        "name_col": name_col,
        "gst_col": gst_col,
        "side_col": side_col,
        "futures_col": futures_col,
        "options_col": options_col,
        "assignment_col": assignment_col,
    }


def _first_match(columns: List[str], predicate) -> Optional[str]:
    for column in columns:
        if predicate(column):
            return column
    return None


def _build_rules(df: pd.DataFrame, column_map: Dict[str, Optional[str]]) -> List[Dict]:
    name_col = column_map["name_col"]
    gst_col = column_map["gst_col"]
    side_col = column_map["side_col"]
    futures_col = column_map["futures_col"]
    options_col = column_map["options_col"]
    assignment_col = column_map["assignment_col"]

    rules: List[Dict] = []
    seen_keys: Dict[str, int] = {}

    for _, row in df.iterrows():
        label_raw = row[name_col] if name_col else None
        if pd.isna(label_raw):
            continue
        label = str(label_raw).strip()
        if not label:
            continue
        if _looks_numeric(label):
            raise RateCardError(f"Rate card label is numeric-like: {label}")

        key = _dedupe_key(_make_key(label), seen_keys)

        rule = {
            "key": key,
            "label": label,
            "base_side": _normalize_side(row[side_col] if side_col else None),
            "gst": _normalize_gst(row[gst_col] if gst_col else None),
            "rates": {
                "futures": parse_rate(row[futures_col] if futures_col else None),
                "options": parse_rate(row[options_col] if options_col else None),
                "assignment": parse_rate(
                    row[assignment_col] if assignment_col else None
                ),
            },
        }
        rules.append(rule)

    return rules


def parse_rate(value: object) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text.replace(",", ""))
    if match:
        return float(match.group(0))
    return 0.0


def _normalize_side(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "BOTH"
    text = str(value).strip().upper()
    if text in {"B", "BUY"}:
        return "BUY"
    if text in {"S", "SELL"}:
        return "SELL"
    if "B" in text and "S" in text:
        return "BOTH"
    if text in {"BOTH"}:
        return "BOTH"
    return "BOTH"


def _normalize_gst(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = str(value).strip().upper()
    if text in {"YES", "Y", "TRUE", "T", "1"}:
        return True
    if text in {"NO", "N", "FALSE", "F", "0"}:
        return False
    return False


def _make_key(label: str) -> str:
    key = re.sub(r"[^A-Z0-9]+", "_", label.strip().upper())
    key = re.sub(r"_+", "_", key).strip("_")
    return key or "UNKNOWN"


def _dedupe_key(key: str, seen_keys: Dict[str, int]) -> str:
    if key not in seen_keys:
        seen_keys[key] = 1
        return key
    seen_keys[key] += 1
    return f"{key}_{seen_keys[key]}"


def _looks_numeric(label: str) -> bool:
    text = label.strip()
    if not text:
        return False
    if re.fullmatch(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text) is None:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True

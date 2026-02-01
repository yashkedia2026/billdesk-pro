from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional


def parse_json_list(raw: Optional[str], label: str) -> List[Dict[str, Any]]:
    if raw is None or raw.strip() == "":
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(payload, list):
        raise ValueError(f"{label} must be a JSON array")
    return payload


def apply_user_edits(
    charges: Dict[str, Any],
    overrides: Iterable[Dict[str, Any]],
    additions: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    bill_lines = [dict(line) for line in charges.get("bill_lines", [])]
    index_by_code = {line.get("code"): idx for idx, line in enumerate(bill_lines)}

    overridden_codes: set[str] = set()
    for item in overrides or []:
        if not isinstance(item, dict):
            raise ValueError("override entries must be objects")
        code = str(item.get("code", "")).strip()
        if not code or code not in index_by_code:
            raise ValueError("override code not found in charges")
        amount = _parse_amount(item.get("amount"))
        bill_lines[index_by_code[code]]["amount"] = _neg_amount(amount)
        overridden_codes.add(code)

    computed_label_map = {
        normalize_name_key(line.get("label", "")): line.get("label", "")
        for line in bill_lines
    }
    additions_seen: set[str] = set()
    additions_lines: List[Dict[str, Any]] = []

    for item in additions or []:
        if not isinstance(item, dict):
            raise ValueError("addition entries must be objects")
        display_name = normalize_display_name(item.get("name", ""))
        if not display_name:
            raise ValueError("custom charge name is required")
        name_key = normalize_name_key(display_name)
        if name_key in computed_label_map or name_key in additions_seen:
            raise ValueError("Charge already exists; edit it instead.")
        amount = _parse_amount(item.get("amount"))
        gst_applicable = bool(item.get("gst_applicable", False))
        additions_seen.add(name_key)
        additions_lines.append(
            {
                "code": f"CUSTOM_{len(additions_lines) + 1}",
                "label": display_name,
                "amount": _neg_amount(amount),
                "gst_applicable": gst_applicable,
            }
        )

    gst_base = _round2(_gst_base_from_lines(bill_lines, additions_lines))

    cgst_value = _round2(gst_base * 0.09)
    sgst_value = _round2(gst_base * 0.09)

    if "CGST_9" in index_by_code and "CGST_9" in overridden_codes:
        cgst_value = abs(float(bill_lines[index_by_code["CGST_9"]]["amount"]))
    if "SGST_9" in index_by_code and "SGST_9" in overridden_codes:
        sgst_value = abs(float(bill_lines[index_by_code["SGST_9"]]["amount"]))

    _ensure_gst_line(bill_lines, index_by_code, "CGST_9", "CGST @ 9%", cgst_value, overridden_codes)
    _ensure_gst_line(bill_lines, index_by_code, "SGST_9", "SGST @ 9%", sgst_value, overridden_codes)

    updated_bill_lines = bill_lines + additions_lines

    total_expenses = _round2(sum(float(line.get("amount", 0)) for line in updated_bill_lines))
    net_amount = float(charges.get("net_amount", 0))
    total_bill_amount = _round2(net_amount + total_expenses)

    updated = dict(charges)
    updated["bill_lines"] = updated_bill_lines
    updated["gst_base"] = gst_base
    updated["gst_total"] = _round2(cgst_value + sgst_value)
    updated["total_expenses"] = total_expenses
    updated["total_bill_amount"] = total_bill_amount
    updated["gst_lines"] = [
        {"code": "CGST_9", "label": "CGST @ 9%", "amount": _neg_amount(cgst_value)},
        {"code": "SGST_9", "label": "SGST @ 9%", "amount": _neg_amount(sgst_value)},
    ]
    return updated


GST_APPLICABLE_CODES = {"TOC_NSE", "TOC_BSE", "CLEARING", "SEBI"}


def _gst_base_from_lines(
    bill_lines: Iterable[Dict[str, Any]], additions: Iterable[Dict[str, Any]]
) -> float:
    total = 0.0
    for line in bill_lines:
        if line.get("code") in GST_APPLICABLE_CODES:
            total += abs(float(line.get("amount", 0)))
    for line in additions:
        if line.get("gst_applicable"):
            total += abs(float(line.get("amount", 0)))
    return total


def _ensure_gst_line(
    bill_lines: List[Dict[str, Any]],
    index_by_code: Dict[str, int],
    code: str,
    label: str,
    value: float,
    overridden_codes: set[str],
) -> None:
    if code in index_by_code:
        if code not in overridden_codes:
            bill_lines[index_by_code[code]]["amount"] = _neg_amount(value)
        if not bill_lines[index_by_code[code]].get("label"):
            bill_lines[index_by_code[code]]["label"] = label
        return
    bill_lines.append({"code": code, "label": label, "amount": _neg_amount(value)})
    index_by_code[code] = len(bill_lines) - 1


def normalize_display_name(value: Any) -> str:
    text = str(value or "")
    return re.sub(r"\s+", " ", text.strip())


def normalize_name_key(value: Any) -> str:
    return normalize_display_name(value).lower()


def _parse_amount(value: Any) -> float:
    if value is None:
        raise ValueError("amount is required")
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("amount must be numeric") from exc


def _neg_amount(value: float) -> float:
    return -abs(float(value))


def _round2(value: float) -> float:
    return round(float(value) + 1e-9, 2)

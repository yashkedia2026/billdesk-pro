import re
from typing import Dict, List, Optional, Tuple

import pandas as pd


def compute_charges(
    day_df: pd.DataFrame,
    netwise_df: pd.DataFrame,
    rate_card: Dict,
    *,
    debug: bool = False,
) -> Tuple[Dict, Dict]:
    (
        segment_bases,
        turnover_bases,
        segment_defaults,
        instrument_debug,
    ) = _compute_turnover_bases(day_df)

    rules_map = {rule["key"]: rule for rule in rate_card.get("rules", [])}

    nfo_rule_keys = {
        "turnover": "NSE_TURNOVER",
        "clearing": "NSE_CLEARING",
        "sebi": "NSE_SEBIFEES",
        "stt": "NSE_STT",
        "stamp": "NSE_STAMPDUTY",
    }
    bfo_rule_keys = {
        "turnover": "BSE_TURNOVER",
        "clearing": "BSE_CLEARING",
        "sebi": "BSE_SEBIFEES",
        "stt": "BSE_STT",
        "stamp": "BSE_STAMPDUTY",
    }

    nfo_amounts = _segment_amounts(segment_bases["NFO"], rules_map, nfo_rule_keys)
    bfo_amounts = _segment_amounts(segment_bases["BFO"], rules_map, bfo_rule_keys)

    total_futures_turnover = (
        segment_bases["NFO"]["futures_buy"]
        + segment_bases["NFO"]["futures_sell"]
        + segment_bases["BFO"]["futures_buy"]
        + segment_bases["BFO"]["futures_sell"]
    )
    total_options_turnover = (
        segment_bases["NFO"]["options_buy"]
        + segment_bases["NFO"]["options_sell"]
        + segment_bases["BFO"]["options_buy"]
        + segment_bases["BFO"]["options_sell"]
    )
    ipft_amount = _apply_rates(
        total_futures_turnover, total_options_turnover, rules_map.get("IPFT")
    )

    _validate_toc_rates("NFO", segment_bases["NFO"], rules_map.get("NSE_TURNOVER"))
    _validate_toc_rates("BFO", segment_bases["BFO"], rules_map.get("BSE_TURNOVER"))

    assignment_result = _compute_assignment_stt(netwise_df, rules_map)

    rounding_debug: List[Dict] = []
    expense_lines: List[Dict] = []

    def add_line(code: str, label: str, raw_amount: float, gst_applicable: bool) -> None:
        rounded_amount, debug_row = _round_charge(code, raw_amount, label)
        expense_lines.append(
            {
                "code": code,
                "label": label,
                "amount": neg(rounded_amount),
                "gst_applicable": gst_applicable,
            }
        )
        if debug:
            debug_row["stored_amount"] = neg(rounded_amount)
            rounding_debug.append(debug_row)

    add_line("NFO_TURNOVER", "NFO Turnover Charges", nfo_amounts["turnover"], True)
    add_line("BFO_TURNOVER", "BFO Turnover Charges", bfo_amounts["turnover"], True)
    add_line("NFO_CLEARING", "NFO Clearing Charges", nfo_amounts["clearing"], True)
    add_line("BFO_CLEARING", "BFO Clearing Charges", bfo_amounts["clearing"], True)
    add_line("NFO_SEBI", "NFO SEBI Fees", nfo_amounts["sebi"], True)
    add_line("BFO_SEBI", "BFO SEBI Fees", bfo_amounts["sebi"], True)
    add_line("IPFT", "IPFT Charges", ipft_amount, True)
    add_line("NFO_STT_SELL", "NFO STT (Sell)", nfo_amounts["stt"], False)
    add_line("BFO_STT_SELL", "BFO STT (Sell)", bfo_amounts["stt"], False)
    add_line("NFO_STAMP_DUTY", "NFO Stamp Duty", nfo_amounts["stamp"], False)
    add_line("BFO_STAMP_DUTY", "BFO Stamp Duty", bfo_amounts["stamp"], False)

    if assignment_result["nfo_amount"] > 0:
        add_line(
            "NFO_STT_ASSIGNMENT",
            "NFO Assignment/Exercise STT",
            assignment_result["nfo_amount"],
            False,
        )
    if assignment_result["bfo_amount"] > 0:
        add_line(
            "BFO_STT_ASSIGNMENT",
            "BFO Assignment/Exercise STT",
            assignment_result["bfo_amount"],
            False,
        )

    # ---- Aggregate-then-round bill lines to match PDF ----
    toc_nse = _round_to(abs(nfo_amounts["turnover"]), 2)
    toc_bse = _round_to(abs(bfo_amounts["turnover"]), 2)

    raw_clearing = abs(nfo_amounts["clearing"]) + abs(bfo_amounts["clearing"])
    raw_sebi = abs(nfo_amounts["sebi"]) + abs(bfo_amounts["sebi"])
    raw_stamp = abs(nfo_amounts["stamp"]) + abs(bfo_amounts["stamp"])
    raw_ipft = abs(ipft_amount)
    raw_stt = (
        abs(nfo_amounts["stt"])
        + abs(bfo_amounts["stt"])
        + abs(assignment_result["nfo_amount"])
        + abs(assignment_result["bfo_amount"])
    )

    clearing_total = _round_to(raw_clearing, 2)
    sebi_total = _round_to(raw_sebi, 2)
    stamp_total = _round_to(raw_stamp, 2)
    ipft_total = _round_to(raw_ipft, 2)
    stt_total = _round_to(raw_stt, 0)

    gst_base = _round2(toc_nse + toc_bse + clearing_total + sebi_total + ipft_total)
    cgst = _round2(gst_base * 0.09)
    sgst = _round2(gst_base * 0.09)
    gst_total = _round2(cgst + sgst)

    gst_lines = [
        {"code": "CGST_9", "label": "CGST @ 9%", "amount": neg(cgst)},
        {"code": "SGST_9", "label": "SGST @ 9%", "amount": neg(sgst)},
    ]

    bill_lines = [
        _bill_line("TOC_NSE", "TOC NSE Exchange", toc_nse),
        _bill_line("TOC_BSE", "TOC BSE Exchange", toc_bse),
        _bill_line("CLEARING", "Clearing Charges", clearing_total),
        _bill_line("SEBI", "SEBI Fees", sebi_total),
        _bill_line("IPFT", "IPFT Charges", ipft_total),
        _bill_line("STT", "STT", stt_total),
        _bill_line("STAMP_DUTY", "Stamp Duty", stamp_total),
        _bill_line("CGST_9", "CGST @ 9%", cgst),
        _bill_line("SGST_9", "SGST @ 9%", sgst),
    ]

    total_expenses = _round2(sum(line["amount"] for line in bill_lines))

    net_amount = _round2(_net_amount_from_daywise(day_df))
    total_bill_amount = _round2(net_amount + total_expenses)

    charges = {
        "lines": expense_lines,
        "gst_lines": gst_lines,
        "bill_lines": bill_lines,
        "gst_base": gst_base,
        "gst_total": gst_total,
        "total_expenses": total_expenses,
        "net_amount": net_amount,
        "total_bill_amount": total_bill_amount,
    }

    debug_payload = {
        "rounding_policy": "Option A",
        "stt_rounding": "nearest_rupee_round",
        "turnover_bases": turnover_bases,
    }

    if debug:
        debug_payload.update(
            {
                "bill_aggregation": {
                    "raw": {
                        "clearing": _round6(raw_clearing),
                        "sebi": _round6(raw_sebi),
                        "ipft": _round6(raw_ipft),
                        "stt": _round6(raw_stt),
                        "stamp": _round6(raw_stamp),
                    },
                    "rounded": {
                        "toc_nse": toc_nse,
                        "toc_bse": toc_bse,
                        "clearing": clearing_total,
                        "sebi": sebi_total,
                        "ipft": ipft_total,
                        "stt": stt_total,
                        "stamp": stamp_total,
                    },
                    "gst_base": gst_base,
                },
                "line_rounding": rounding_debug,
                "segment_defaults": segment_defaults,
                "instrument_debug": instrument_debug,
                "assignment": {
                    "candidates": assignment_result["candidates"],
                    "charged": assignment_result["charged"],
                    "segment_defaults": assignment_result["segment_defaults"],
                },
            }
        )

    return charges, debug_payload


def _segment_amounts(
    bases: Dict[str, float], rules_map: Dict[str, Dict], rule_keys: Dict[str, str]
) -> Dict[str, float]:
    futures_turnover = bases["futures_buy"] + bases["futures_sell"]
    options_turnover = bases["options_buy"] + bases["options_sell"]

    buy_value_fut = bases["futures_buy"]
    buy_value_opt = bases["options_buy"]
    sell_value_fut = bases["futures_sell"]
    sell_value_opt = bases["options_sell"]

    turnover_amount = _apply_rates(
        futures_turnover, options_turnover, rules_map.get(rule_keys["turnover"])
    )
    clearing_amount = _apply_rates(
        futures_turnover, options_turnover, rules_map.get(rule_keys["clearing"])
    )
    sebi_amount = _apply_rates(
        futures_turnover, options_turnover, rules_map.get(rule_keys["sebi"])
    )
    stt_amount = _apply_rates(
        sell_value_fut, sell_value_opt, rules_map.get(rule_keys["stt"])
    )
    stamp_amount = _apply_rates(
        buy_value_fut, buy_value_opt, rules_map.get(rule_keys["stamp"])
    )

    return {
        "turnover": turnover_amount,
        "clearing": clearing_amount,
        "sebi": sebi_amount,
        "stt": stt_amount,
        "stamp": stamp_amount,
    }


def _apply_rates(futures_base: float, options_base: float, rule: Optional[Dict]) -> float:
    if not rule:
        return 0.0
    rates = rule.get("rates", {})
    futures_rate = eff(rates.get("futures", 0) or 0)
    options_rate = eff(rates.get("options", 0) or 0)
    return (futures_base * futures_rate) + (options_base * options_rate)


def _compute_turnover_bases(
    day_df: pd.DataFrame,
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, float]], Dict, Dict]:
    segment_bases = {
        "NFO": _init_segment_bases(),
        "BFO": _init_segment_bases(),
    }
    defaulted_rows: List[Dict] = []
    instrument_debug = {
        "options": 0,
        "futures": 0,
        "note": "Instrument type inferred from TradingSymbol (CE/PE => options).",
    }

    for idx, row in day_df.iterrows():
        original_seg = row.get("Exchg.Seg", "")
        segment = normalize_segment(original_seg)
        if segment is None:
            segment = "NFO"
            defaulted_rows.append(_default_debug(row, idx, segment, original_seg))

        instrument = _classify_instrument(row)
        instrument_debug[instrument] += 1

        buy_value = _to_float(row.get("Actual Buy Value", 0))
        sell_value = _to_float(row.get("Actual Sell Value", 0))

        if instrument == "options":
            segment_bases[segment]["options_buy"] += buy_value
            segment_bases[segment]["options_sell"] += sell_value
        else:
            segment_bases[segment]["futures_buy"] += buy_value
            segment_bases[segment]["futures_sell"] += sell_value

    turnover_bases = {
        "nfo": _segment_summary(segment_bases["NFO"]),
        "bfo": _segment_summary(segment_bases["BFO"]),
        "combined": _segment_summary(
            {
                "futures_buy": segment_bases["NFO"]["futures_buy"]
                + segment_bases["BFO"]["futures_buy"],
                "futures_sell": segment_bases["NFO"]["futures_sell"]
                + segment_bases["BFO"]["futures_sell"],
                "options_buy": segment_bases["NFO"]["options_buy"]
                + segment_bases["BFO"]["options_buy"],
                "options_sell": segment_bases["NFO"]["options_sell"]
                + segment_bases["BFO"]["options_sell"],
            }
        ),
    }

    defaults_payload = {
        "count": len(defaulted_rows),
        "rows": defaulted_rows[:10],
        "note": "Missing/blank Exchg.Seg defaulted to NFO.",
    }

    return segment_bases, turnover_bases, defaults_payload, instrument_debug


def _compute_assignment_stt(netwise_df: pd.DataFrame, rules_map: Dict[str, Dict]) -> Dict:
    candidates: List[Dict] = []
    charged: List[Dict] = []
    defaulted_rows: List[Dict] = []

    nfo_amount = 0.0
    bfo_amount = 0.0

    for idx, row in netwise_df.iterrows():
        net_qty = _to_float(row.get("NetQty", 0))
        if net_qty == 0:
            continue

        original_seg = row.get("Exchg.Seg", "")
        segment = normalize_segment(original_seg)
        if segment is None:
            segment = "NFO"
            defaulted_rows.append(_default_debug(row, idx, segment, original_seg))

        if segment not in {"NFO", "BFO"}:
            continue

        instrument = _classify_instrument(row)
        is_option = instrument == "options"

        settlement_type = str(row.get("SettlementType", "") or "").strip()
        square_off_context = str(row.get("Square Off Context", "") or "").strip()
        qualifies = _is_assignment_event(settlement_type, square_off_context)

        candidate_payload = {
            "trading_symbol": str(row.get("TradingSymbol", "")).strip(),
            "segment": segment,
            "segment_raw": str(original_seg).strip(),
            "product_type": str(row.get("ProductType", "")).strip() or "UNKNOWN",
            "instrument": instrument,
            "net_qty": int(round(net_qty)),
            "settlement_type": settlement_type,
            "square_off_context": square_off_context,
            "qualifies": qualifies and is_option,
        }
        candidates.append(candidate_payload)

        if not is_option or not qualifies:
            continue

        buy_value = _to_float(row.get("Actual Buy Value", 0))
        sell_value = _to_float(row.get("Actual Sell Value", 0))
        base_value = buy_value + sell_value
        if base_value == 0:
            last_trade_price = _to_float(row.get("LastTradePrice", 0))
            base_value = abs(net_qty) * last_trade_price

        rate_key = "NSE_STT" if segment == "NFO" else "BSE_STT"
        rule = rules_map.get(rate_key, {})
        rate = eff(rule.get("rates", {}).get("assignment", 0) or 0)
        amount = base_value * rate

        charged_payload = {
            "trading_symbol": candidate_payload["trading_symbol"],
            "segment": segment,
            "net_qty": candidate_payload["net_qty"],
            "base": _round2(base_value),
            "rate": rate,
            "amount": _round2(amount),
        }
        charged.append(charged_payload)

        if segment == "NFO":
            nfo_amount += amount
        else:
            bfo_amount += amount

    return {
        "nfo_amount": nfo_amount,
        "bfo_amount": bfo_amount,
        "candidates": candidates,
        "charged": charged,
        "segment_defaults": {
            "count": len(defaulted_rows),
            "rows": defaulted_rows[:10],
            "note": "Missing/blank Exchg.Seg defaulted to NFO.",
        },
    }


def _bill_line(code: str, label: str, amount: float) -> Dict:
    return {"code": code, "label": label, "amount": neg(amount)}


def _round_charge(code: str, amount: float, label: str) -> Tuple[float, Dict]:
    decimals = 0 if code in _STT_CODES else 2
    normalized = abs(amount)
    rounded = _round_to(normalized, decimals)
    debug_row = {
        "code": code,
        "label": label,
        "pre_round": _round6(normalized),
        "post_round": rounded,
        "decimals": decimals,
    }
    return rounded, debug_row


def _validate_toc_rates(segment: str, bases: Dict[str, float], rule: Optional[Dict]) -> None:
    futures_turnover = bases["futures_buy"] + bases["futures_sell"]
    options_turnover = bases["options_buy"] + bases["options_sell"]
    total_turnover = futures_turnover + options_turnover
    if total_turnover == 0:
        return

    if not rule:
        raise ValueError(
            f"{segment} TOC rule missing. Update rate card to match broker PDF."
        )

    rates = rule.get("rates", {})
    futures_rate = eff(rates.get("futures", 0) or 0)
    options_rate = eff(rates.get("options", 0) or 0)
    if futures_rate == 0 and options_rate == 0:
        raise ValueError(
            f"{segment} TOC rates are zero. Ensure rate card matches broker PDF."
        )


def _net_amount_from_daywise(day_df: pd.DataFrame) -> float:
    buy_total = 0.0
    sell_total = 0.0
    for _, row in day_df.iterrows():
        buy_total += _to_float(row.get("Actual Buy Value", 0))
        sell_total += _to_float(row.get("Actual Sell Value", 0))
    return sell_total - buy_total


def normalize_segment(value: object) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text in {"NFO", "NSEFO"}:
        return "NFO"
    if text in {"BFO", "BSEFO"}:
        return "BFO"
    return None


def detect_instrument(trading_symbol: object) -> str:
    text = str(trading_symbol or "").upper()
    if re.search(r"\bCE\b", text) or re.search(r"\bPE\b", text):
        return "options"
    return "futures"


def _classify_instrument(row: pd.Series) -> str:
    symbol = str(row.get("TradingSymbol", "")).strip()
    return detect_instrument(symbol)


def _is_assignment_event(settlement_type: str, square_off_context: str) -> bool:
    pattern = re.compile(r"(EXE|EXERCISE|ASSIGN)", re.IGNORECASE)
    if pattern.search(settlement_type or ""):
        return True
    if pattern.search(square_off_context or ""):
        return True
    return False


def eff(rate: float) -> float:
    return float(rate or 0.0) / 100.0


_STT_CODES = {
    "NFO_STT_SELL",
    "BFO_STT_SELL",
    "NFO_STT_ASSIGNMENT",
    "BFO_STT_ASSIGNMENT",
}


def _round2(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def _round_to(value: float, decimals: int) -> float:
    return round(float(value) + 1e-9, decimals)


def _round6(value: float) -> float:
    return round(float(value) + 1e-9, 6)


def neg(value: float) -> float:
    return -abs(float(value or 0.0))


def _to_float(value: object) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    numeric = pd.to_numeric(value, errors="coerce")
    return float(0.0 if pd.isna(numeric) else numeric)


def _init_segment_bases() -> Dict[str, float]:
    return {
        "futures_buy": 0.0,
        "futures_sell": 0.0,
        "options_buy": 0.0,
        "options_sell": 0.0,
    }


def _segment_summary(segment_bases: Dict[str, float]) -> Dict[str, float]:
    futures_turnover = segment_bases["futures_buy"] + segment_bases["futures_sell"]
    options_turnover = segment_bases["options_buy"] + segment_bases["options_sell"]
    buy_value = segment_bases["futures_buy"] + segment_bases["options_buy"]
    sell_value = segment_bases["futures_sell"] + segment_bases["options_sell"]
    return {
        "futures_turnover": _round2(futures_turnover),
        "options_turnover": _round2(options_turnover),
        "buy_value": _round2(buy_value),
        "sell_value": _round2(sell_value),
    }


def _default_debug(
    row: pd.Series, index: int, segment: str, original_segment: object
) -> Dict:
    return {
        "row_index": int(index),
        "trading_symbol": str(row.get("TradingSymbol", "")).strip(),
        "segment_used": segment,
        "segment_raw": str(original_segment).strip(),
    }

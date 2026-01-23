import io
import re
from pathlib import Path

import pandas as pd
import pytest
from pypdf import PdfReader

from app.charges import compute_charges
from app.positions import build_positions, clean_df
from app.rate_card import get_rate_card
from app.validation import REQUIRED_COLUMNS, validate_csv_columns


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"
PDF_MAP = {
    "19.01.2026": "LEDGER 19.01.2026 DLL13516.pdf",
    "20.01.2026": "LEDGER 20.01.2026 DLL13516.pdf",
}


def _read_csv(path: Path) -> pd.DataFrame:
    raw_bytes = path.read_bytes()
    try:
        text_data = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text_data = raw_bytes.decode("latin-1")
    return pd.read_csv(io.StringIO(text_data))


def _read_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _parse_amount(value: str) -> float:
    cleaned = value.replace(",", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        return -float(cleaned[1:-1])
    return float(cleaned)


def _extract_amount(text: str, label_pattern: str) -> float:
    flat_text = re.sub(r"\s+", " ", text)
    pattern = re.compile(
        rf"{label_pattern}\s+([-\(]?\d[\d,]*(?:\.\d{{2}})?\)?)", re.IGNORECASE
    )
    match = pattern.search(flat_text)
    if not match:
        raise AssertionError(f"Label not found in PDF text: {label_pattern}")
    return _parse_amount(match.group(1))


def _assert_amount_match(computed: float, pdf_amount: float) -> None:
    assert _round2(computed) == _round2(pdf_amount)


def _extract_positions_totals(text: str) -> dict:
    flat_text = re.sub(r"\s+", " ", text)
    pattern = re.compile(
        r"TOTAL\s+(\d[\d,]*)\s+(\(?-?\d[\d,]*\.\d{2}\)?)\s+"
        r"(\d[\d,]*)\s+(\(?-?\d[\d,]*\.\d{2}\)?)\s+(\(?-?\d[\d,]*\.\d{2}\)?)",
        re.IGNORECASE,
    )
    match = pattern.search(flat_text)
    if not match:
        raise AssertionError("TOTAL row not found in PDF text.")

    return {
        "total_buy_qty": int(match.group(1).replace(",", "")),
        "total_buy_amount": _parse_amount(match.group(2)),
        "total_sell_qty": int(match.group(3).replace(",", "")),
        "total_sell_amount": _parse_amount(match.group(4)),
        "total_net_amount": _parse_amount(match.group(5)),
    }


def _find_sample_file(date_prefix: str, keyword: str) -> Path:
    matches = list(SAMPLE_DIR.glob(f"{date_prefix}*{keyword}*.csv"))
    if not matches:
        raise FileNotFoundError(f"No sample file for {date_prefix} {keyword}")
    if len(matches) > 1:
        raise FileNotFoundError(f"Multiple sample files for {date_prefix} {keyword}")
    return matches[0]


@pytest.mark.parametrize("date_prefix", ["19.01.2026", "20.01.2026"])
def test_pdf_reconciliation(date_prefix: str) -> None:
    pdf_path = SAMPLE_DIR / PDF_MAP[date_prefix]
    if not pdf_path.exists():
        pytest.skip(f"Missing PDF: {pdf_path}")

    day_path = _find_sample_file(date_prefix, "DAY WISE")
    net_path = _find_sample_file(date_prefix, "NET WISE")

    day_df = clean_df(_read_csv(day_path))
    net_df = clean_df(_read_csv(net_path))

    validate_csv_columns(day_df, REQUIRED_COLUMNS, "Day wise")
    validate_csv_columns(net_df, REQUIRED_COLUMNS, "Net wise")

    positions_rows, positions_totals = build_positions(day_df)
    assert positions_rows

    rate_card = get_rate_card()
    charges, _ = compute_charges(day_df, net_df, rate_card)

    pdf_text = _read_pdf_text(pdf_path)

    bill_line_map = {line["code"]: line["amount"] for line in charges["bill_lines"]}
    assert bill_line_map

    _assert_amount_match(
        bill_line_map["TOC_NSE"],
        _extract_amount(pdf_text, r"TOC\s+NSE\s+EXCHANGE"),
    )
    _assert_amount_match(
        bill_line_map["TOC_BSE"],
        _extract_amount(pdf_text, r"TOC\s+BSE\s+EXCHANGE"),
    )
    _assert_amount_match(
        bill_line_map["CLEARING"],
        _extract_amount(pdf_text, r"CLEARING\s+CHARGES"),
    )
    _assert_amount_match(
        bill_line_map["SEBI"], _extract_amount(pdf_text, r"SEBI\s+FEES")
    )
    _assert_amount_match(bill_line_map["STT"], _extract_amount(pdf_text, r"STT"))
    _assert_amount_match(
        bill_line_map["STAMP_DUTY"],
        _extract_amount(pdf_text, r"STAMP\s*DUTY"),
    )
    _assert_amount_match(
        bill_line_map["CGST_9"],
        _extract_amount(pdf_text, r"CGST\s*@\s*9%"),
    )
    _assert_amount_match(
        bill_line_map["SGST_9"],
        _extract_amount(pdf_text, r"SGST\s*@\s*9%"),
    )

    _assert_amount_match(
        charges["total_expenses"], _extract_amount(pdf_text, r"TOTAL\s+EXPENSES")
    )
    assert charges["total_bill_amount"] == _extract_amount(
        pdf_text, r"TOTAL\s+BILL\s+AMOUNT"
    )

    totals_from_pdf = _extract_positions_totals(pdf_text)
    assert positions_totals["total_buy_qty"] == totals_from_pdf["total_buy_qty"]
    assert _round2(positions_totals["total_buy_amount"]) == _round2(
        totals_from_pdf["total_buy_amount"]
    )
    assert positions_totals["total_sell_qty"] == totals_from_pdf["total_sell_qty"]
    assert _round2(positions_totals["total_sell_amount"]) == _round2(
        totals_from_pdf["total_sell_amount"]
    )
    assert _round2(positions_totals["total_net_amount"]) == _round2(
        totals_from_pdf["total_net_amount"]
    )


def _round2(value: float) -> float:
    return round(float(value) + 1e-9, 2)

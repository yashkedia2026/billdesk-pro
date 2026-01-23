import io
import re
from pathlib import Path

import pandas as pd
import pytest
from pypdf import PdfReader

from app.charges import compute_charges
from app.pdf import build_pdf_context, render_bill_pdf
from app.positions import build_positions, clean_df
from app.rate_card import get_rate_card
from app.validation import REQUIRED_COLUMNS, validate_csv_columns

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DAYWISE_PATH = FIXTURES_DIR / "20.01.2026 DAY WISE 13516.csv"
NETWISE_PATH = FIXTURES_DIR / "20.01.2026 NET WISE 13516.csv"


def _read_csv(path: Path) -> pd.DataFrame:
    raw_bytes = path.read_bytes()
    try:
        text_data = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text_data = raw_bytes.decode("latin-1")
    return pd.read_csv(io.StringIO(text_data))


def _pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _assert_contains(text: str, pattern: str, label: str) -> None:
    if not re.search(pattern, text):
        raise AssertionError(f"Missing {label} in PDF text.")


def test_pdf_golden() -> None:
    if not DAYWISE_PATH.exists() or not NETWISE_PATH.exists():
        pytest.skip("Missing CSV fixtures for golden PDF test.")

    day_df = clean_df(_read_csv(DAYWISE_PATH))
    net_df = clean_df(_read_csv(NETWISE_PATH))

    validate_csv_columns(day_df, REQUIRED_COLUMNS, "Day wise")
    validate_csv_columns(net_df, REQUIRED_COLUMNS, "Net wise")

    positions_rows, positions_totals = build_positions(day_df)
    rate_card = get_rate_card()
    charges, _ = compute_charges(day_df, net_df, rate_card)

    context = build_pdf_context(
        account="QWERT",
        trade_date="2026-01-20",
        daywise_df=day_df,
        positions_rows=positions_rows,
        positions_totals=positions_totals,
        charges=charges,
    )

    pdf_bytes = render_bill_pdf(context)
    generated_text = _normalize_text(_pdf_text_from_bytes(pdf_bytes))

    _assert_contains(
        generated_text,
        r"Total Bill Amount:?\\s+-?330,?179\\.19",
        "Total Bill Amount",
    )
    _assert_contains(generated_text, r"Total\\s+-?1,?624\\.31", "Total Expenses")
    _assert_contains(generated_text, r"\\bSTT\\b\\s+-?806\\b", "STT line")
    _assert_contains(
        generated_text,
        r"TOC NSE Exchange\\s+-?390\\.92",
        "TOC NSE",
    )
    _assert_contains(
        generated_text,
        r"TOC BSE Exchange\\s+-?250\\.2(0)?",
        "TOC BSE",
    )
    _assert_contains(generated_text, r"CGST\\s+-?61\\.33", "CGST")
    _assert_contains(generated_text, r"SGST\\s+-?61\\.33", "SGST")

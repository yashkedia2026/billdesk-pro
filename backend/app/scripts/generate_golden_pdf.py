import io
from pathlib import Path

import pandas as pd

from app.charges import compute_charges
from app.pdf import build_pdf_context, render_bill_pdf
from app.positions import build_positions, clean_df
from app.rate_card import get_rate_card
from app.validation import REQUIRED_COLUMNS, validate_csv_columns

ACCOUNT = "QWERT"
TRADE_DATE = "2026-01-20"


def _read_csv(path: Path) -> pd.DataFrame:
    raw_bytes = path.read_bytes()
    try:
        text_data = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text_data = raw_bytes.decode("latin-1")
    return pd.read_csv(io.StringIO(text_data))


def main() -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    day_path = fixtures_dir / "20.01.2026 DAY WISE 13516.csv"
    net_path = fixtures_dir / "20.01.2026 NET WISE 13516.csv"
    output_path = fixtures_dir / f"expected_bill_{ACCOUNT}_{TRADE_DATE}.pdf"

    if not day_path.exists() or not net_path.exists():
        raise SystemExit("Missing CSV fixtures under tests/fixtures.")

    day_df = clean_df(_read_csv(day_path))
    net_df = clean_df(_read_csv(net_path))

    validate_csv_columns(day_df, REQUIRED_COLUMNS, "Day wise")
    validate_csv_columns(net_df, REQUIRED_COLUMNS, "Net wise")

    positions_rows, positions_totals = build_positions(day_df)
    rate_card = get_rate_card()
    charges, _ = compute_charges(day_df, net_df, rate_card)

    context = build_pdf_context(
        account=ACCOUNT,
        trade_date=TRADE_DATE,
        daywise_df=day_df,
        positions_rows=positions_rows,
        positions_totals=positions_totals,
        charges=charges,
    )

    pdf_bytes = render_bill_pdf(context)
    output_path.write_bytes(pdf_bytes)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()

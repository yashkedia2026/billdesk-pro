import io
import json
from pathlib import Path

import pandas as pd

from app.charges import compute_charges
from app.positions import clean_df
from app.rate_card import get_rate_card
from app.validation import REQUIRED_COLUMNS, validate_csv_columns


def _read_csv(path: Path) -> pd.DataFrame:
    raw_bytes = path.read_bytes()
    try:
        text_data = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text_data = raw_bytes.decode("latin-1")
    return pd.read_csv(io.StringIO(text_data))


def main() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    sample_dir = backend_dir / "sample_data"

    day_path = sample_dir / "20.01.2026 DAY WISE 13516.csv"
    net_path = sample_dir / "20.01.2026 NET WISE 13516.csv"

    day_df = clean_df(_read_csv(day_path))
    net_df = clean_df(_read_csv(net_path))

    validate_csv_columns(day_df, REQUIRED_COLUMNS, "Day wise")
    validate_csv_columns(net_df, REQUIRED_COLUMNS, "Net wise")

    rate_card = get_rate_card()
    charges, debug = compute_charges(day_df, net_df, rate_card, debug=True)

    payload = {
        "charges": {
            "lines": charges.get("lines", []),
            "gst_lines": charges.get("gst_lines", []),
            "bill_lines": charges.get("bill_lines", []),
            "gst_base": charges.get("gst_base"),
            "gst_total": charges.get("gst_total"),
            "total_expenses": charges.get("total_expenses"),
            "net_amount": charges.get("net_amount"),
            "total_bill_amount": charges.get("total_bill_amount"),
        },
        "debug": debug,
    }

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

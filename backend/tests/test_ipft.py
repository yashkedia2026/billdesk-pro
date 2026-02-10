import pandas as pd

from app.charges import _round2, compute_charges
from app.rate_card import get_rate_card


def test_ipft_included_in_gst_base():
    day_df = pd.DataFrame(
        [
            {
                "Exchg.Seg": "NFO",
                "TradingSymbol": "NIFTY25MARFUT",
                "Actual Buy Value": 100000,
                "Actual Sell Value": 50000,
            },
            {
                "Exchg.Seg": "BFO",
                "TradingSymbol": "BANKNIFTY25MARCE",
                "Actual Buy Value": 20000,
                "Actual Sell Value": 10000,
            },
        ]
    )
    netwise_df = pd.DataFrame([])

    charges, _ = compute_charges(day_df, netwise_df, get_rate_card(), debug=True)

    ipft_line = next(line for line in charges["bill_lines"] if line["code"] == "IPFT")
    ipft_total = abs(ipft_line["amount"])
    gst_base = charges["gst_base"]

    base_without_ipft = _round2(
        sum(
            abs(line["amount"])
            for line in charges["bill_lines"]
            if line["code"] in {"TOC_NSE", "TOC_BSE", "CLEARING", "SEBI"}
        )
    )

    assert gst_base == _round2(base_without_ipft + ipft_total)

    cgst_line = next(line for line in charges["bill_lines"] if line["code"] == "CGST_9")
    sgst_line = next(line for line in charges["bill_lines"] if line["code"] == "SGST_9")
    expected_tax = _round2(gst_base * 0.09)
    assert abs(cgst_line["amount"]) == expected_tax
    assert abs(sgst_line["amount"]) == expected_tax

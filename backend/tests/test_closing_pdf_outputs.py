import io

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.pdf import (
    render_admin_consolidated_pdf,
    render_admin_summary_pdf,
    render_bill_pdf,
    render_closing_positions_pdf,
)


def _simple_pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    c.setFont("Helvetica", 12)
    c.drawString(10 * mm, landscape(A4)[1] - 15 * mm, text)
    c.save()
    return buffer.getvalue()


def _pdf_text_pages(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(page.extract_text() or "") for page in reader.pages]


def test_admin_consolidated_pdf_groups_bill_then_closing_per_account() -> None:
    accounts_bundle = [
        {
            "account_code": "PR01",
            "bill_pdf_bytes": _simple_pdf("BILL A"),
            "account_meta": {"account_code": "PR01", "trade_date": "2026-01-20"},
            "closing_rows": [
                {
                    "sr": 1,
                    "contract": "CLOSE A",
                    "net_qty": 1,
                    "ltp": 10.0,
                    "value": 10.0,
                }
            ],
            "closing_total": 10.0,
            "closing_status": "OK",
        },
        {
            "account_code": "PR02",
            "bill_pdf_bytes": _simple_pdf("BILL B"),
            "account_meta": {"account_code": "PR02", "trade_date": "2026-01-20"},
            "closing_rows": [
                {
                    "sr": 1,
                    "contract": "CLOSE B",
                    "net_qty": -2,
                    "ltp": 5.0,
                    "value": -10.0,
                }
            ],
            "closing_total": -10.0,
            "closing_status": "OK",
        },
    ]

    pdf_bytes = render_admin_consolidated_pdf(accounts_bundle, "2026-01-20")
    pages = _pdf_text_pages(pdf_bytes)

    assert len(pages) == 4
    assert "BILL A" in pages[0]
    assert "Closing Positions" in pages[1] and "CLOSE A" in pages[1]
    assert "BILL B" in pages[2]
    assert "Closing Positions" in pages[3] and "CLOSE B" in pages[3]


def test_admin_consolidated_pdf_sorts_accounts_by_pr_code() -> None:
    accounts_bundle = [
        {
            "account_code": "PR10",
            "bill_pdf_bytes": _simple_pdf("BILL PR10"),
            "account_meta": {"account_code": "PR10", "trade_date": "2026-01-20"},
            "closing_rows": [
                {
                    "sr": 1,
                    "contract": "CLOSE PR10",
                    "net_qty": 1,
                    "ltp": 1.0,
                    "value": 1.0,
                }
            ],
            "closing_total": 1.0,
            "closing_status": "OK",
        },
        {
            "account_code": "PR05",
            "bill_pdf_bytes": _simple_pdf("BILL PR05"),
            "account_meta": {"account_code": "PR05", "trade_date": "2026-01-20"},
            "closing_rows": [
                {
                    "sr": 1,
                    "contract": "CLOSE PR05",
                    "net_qty": 1,
                    "ltp": 1.0,
                    "value": 1.0,
                }
            ],
            "closing_total": 1.0,
            "closing_status": "OK",
        },
        {
            "account_code": "PR6",
            "bill_pdf_bytes": _simple_pdf("BILL PR6"),
            "account_meta": {"account_code": "PR6", "trade_date": "2026-01-20"},
            "closing_rows": [
                {
                    "sr": 1,
                    "contract": "CLOSE PR6",
                    "net_qty": 1,
                    "ltp": 1.0,
                    "value": 1.0,
                }
            ],
            "closing_total": 1.0,
            "closing_status": "OK",
        },
    ]

    pdf_bytes = render_admin_consolidated_pdf(accounts_bundle, "2026-01-20")
    pages = _pdf_text_pages(pdf_bytes)

    assert len(pages) == 6
    assert "BILL PR05" in pages[0]
    assert "CLOSE PR05" in pages[1]
    assert "BILL PR6" in pages[2]
    assert "CLOSE PR6" in pages[3]
    assert "BILL PR10" in pages[4]
    assert "CLOSE PR10" in pages[5]


def test_admin_consolidated_pdf_account_section_heading_order_smoke() -> None:
    account = {
        "account_code": "PR25",
        "account_meta": {"account_code": "PR25", "trade_date": "2026-02-12"},
        "bill_context": {
            "code": "PR25",
            "exchange": "BSE_FO",
            "market_type": "FO",
            "trade_date_display": "12-02-2026",
            "positions_rows": [
                {
                    "sr": 1,
                    "security": "SENSEX 12FEB2026 CE 84000",
                    "bf_qty": 0,
                    "bf_rate": 0,
                    "bf_amount": 0,
                    "buy_qty": 0,
                    "buy_rate": 0,
                    "buy_amount": 0,
                    "sell_qty": 20,
                    "sell_rate": 100,
                    "sell_amount": 2000,
                    "brkg": 0,
                    "net_qty": -20,
                    "net_rate": 0,
                    "net_amount": 2000,
                }
            ],
            "positions_totals": {
                "total_buy_qty": 0,
                "total_buy_amount": 0,
                "total_sell_qty": 20,
                "total_sell_amount": 2000,
                "total_net_amount": 2000,
            },
            "total_net_qty": -20,
            "expiry_settlement_rows": [],
            "expiry_pending_rows": [
                {
                    "trading_symbol": "SENSEX 12FEB2026 CE 84000",
                    "expiry": "12Feb2026",
                    "option_type": "CE",
                    "strike": 84000.0,
                    "net_qty": -20,
                    "underlying_close": None,
                    "intrinsic": None,
                    "action_status": "MISSING_UNDERLYING_CLOSE",
                    "settlement_amount": 0.0,
                }
            ],
            "expiry_settlement_total": 0.0,
            "expense_rows": [{"sr": 1, "label": "STT", "amount": -10, "decimals": 0}],
            "total_expenses": -10,
            "total_bill_amount": 1990,
        },
        "closing_rows": [],
        "closing_total": 0.0,
        "closing_status": "MISSING",
    }
    pdf_bytes = render_admin_consolidated_pdf([account], "2026-02-12")
    text = " ".join(_pdf_text_pages(pdf_bytes))

    bill_idx = text.find("Bill Summary Report")
    pending_idx = text.find("Pending Expiry Settlement")
    expenses_idx = text.find("Expenses")
    total_idx = text.find("Total Bill Amount")
    closing_idx = text.find("Closing Positions")
    no_open_idx = text.find("No open positions.")

    assert bill_idx != -1
    assert pending_idx != -1
    assert expenses_idx != -1
    assert total_idx != -1
    assert closing_idx != -1
    assert no_open_idx != -1
    assert bill_idx < pending_idx < expenses_idx < total_idx < closing_idx < no_open_idx


def test_closing_page_pdf_renders_unavailable_message() -> None:
    pdf_bytes = render_closing_positions_pdf(
        {"account_code": "ACCT-1", "account_name": "ACCT-1", "trade_date": "2026-01-20"},
        [],
        0.0,
        "MISSING",
    )

    all_text = " ".join(_pdf_text_pages(pdf_bytes))
    assert "Closing Positions" in all_text
    assert "No open positions." in all_text
    assert "Total Value of Closing Positions (Account-wise): 0.00" in all_text


def test_admin_summary_pdf_renders_totals_and_missing_note() -> None:
    rows = [
        {
            "sr": 1,
            "account_code": "A1",
            "drcr_amount": 100.0,
            "closing_total": 40.0,
            "final_adjusted": 140.0,
            "closing_status": "OK",
        },
        {
            "sr": 2,
            "account_code": "A2",
            "drcr_amount": -10.0,
            "closing_total": 0.0,
            "final_adjusted": -10.0,
            "closing_status": "MISSING",
        },
    ]
    totals = {
        "total_drcr": 90.0,
        "total_closing": 40.0,
        "final_adjusted": 130.0,
        "missing_count": 1,
    }

    pdf_bytes = render_admin_summary_pdf(rows, totals, "2026-01-20")
    all_text = " ".join(_pdf_text_pages(pdf_bytes))

    assert "Admin Closing Adjustment Summary" in all_text
    assert "Total Closing Positions" in all_text
    assert "Final Adjusted" in all_text
    assert "A1" in all_text and "100.00" in all_text and "40.00" in all_text and "140.00" in all_text
    assert "A2" in all_text and "-10.00" in all_text and "0.00" in all_text and "-10.00" in all_text
    assert "Total" in all_text and "90.00" in all_text and "130.00" in all_text
    assert "Closing adjustment computed only for accounts where netwise data was available." not in all_text


def test_expiry_settlement_table_includes_net_lot_column() -> None:
    context = {
        "code": "PR01",
        "exchange": "BSE_FO",
        "market_type": "FO",
        "trade_date_display": "12-02-2026",
        "positions_rows": [],
        "positions_totals": {
            "total_buy_qty": 0,
            "total_buy_amount": 0.0,
            "total_sell_qty": 0,
            "total_sell_amount": 0.0,
            "total_net_amount": 0.0,
        },
        "total_net_qty": 0,
        "expiry_settlement_rows": [
            {
                "trading_symbol": "SENSEX 12FEB2026 CE 84000",
                "net_lot": -3.5,
                "net_qty": -350,
                "underlying_close": 84100.0,
                "source": "MANUAL_INPUT",
                "intrinsic": 100.0,
                "action_status": "ASSIGN",
                "settlement_amount": -35000.0,
            }
        ],
        "expiry_pending_rows": [],
        "expiry_settlement_total": -35000.0,
        "expense_rows": [],
        "total_expenses": 0.0,
        "total_bill_amount": 0.0,
    }

    pdf_bytes = render_bill_pdf(context)
    text = " ".join(_pdf_text_pages(pdf_bytes))

    assert "Expiry Settlement (Exercise/Assignment)" in text
    assert "Net Lot" in text
    assert "-3.5" in text or "-3.50" in text

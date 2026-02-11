import io

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.pdf import (
    render_admin_consolidated_pdf,
    render_admin_summary_pdf,
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


def test_admin_consolidated_pdf_orders_bill_pages_then_closing_pages() -> None:
    accounts_bundle = [
        {
            "bill_pdf_bytes": _simple_pdf("BILL A"),
            "closing_pdf_bytes": _simple_pdf("CLOSE A"),
        },
        {
            "bill_pdf_bytes": _simple_pdf("BILL B"),
            "closing_pdf_bytes": _simple_pdf("CLOSE B"),
        },
    ]

    pdf_bytes = render_admin_consolidated_pdf(accounts_bundle, "2026-01-20")
    pages = _pdf_text_pages(pdf_bytes)

    assert len(pages) == 4
    assert "BILL A" in pages[0]
    assert "BILL B" in pages[1]
    assert "CLOSE A" in pages[2]
    assert "CLOSE B" in pages[3]


def test_closing_page_pdf_renders_unavailable_message() -> None:
    pdf_bytes = render_closing_positions_pdf(
        {"account_code": "ACCT-1", "account_name": "ACCT-1", "trade_date": "2026-01-20"},
        [],
        0.0,
        "MISSING",
    )

    all_text = " ".join(_pdf_text_pages(pdf_bytes))
    assert "Closing Positions" in all_text
    assert "Closing positions not available" in all_text
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

import asyncio
import io
import json
import zipfile

from fastapi import UploadFile

from app import main as main_module
from app.utils_sort import natural_pr_sort_key


DAYWISE_CSV = """Account Id,TradingSymbol,Exchg.Seg,BuyQty,SellQty,NetQty,BuyAvgPrice,SellAvgPrice,Actual Buy Value,Actual Sell Value,Actual Mark To Market
PR10,SENSEX 20FEB2026 CE 85000,BFO,0,20,-20,0,100,0,2000,2000
PR05,SENSEX 20FEB2026 CE 85100,BFO,0,10,-10,0,80,0,800,800
PR6,SENSEX 20FEB2026 CE 85200,BFO,0,15,-15,0,90,0,1350,1350
"""

NETWISE_CSV = """Account Id,TradingSymbol,Exchg.Seg,BuyQty,SellQty,NetQty,BuyAvgPrice,SellAvgPrice,Actual Buy Value,Actual Sell Value,Actual Mark To Market,LastTradePrice
PR10,SENSEX 20FEB2026 CE 85000,BFO,0,20,-20,0,100,0,2000,2000,100
PR05,SENSEX 20FEB2026 CE 85100,BFO,0,10,-10,0,80,0,800,800,80
PR6,SENSEX 20FEB2026 CE 85200,BFO,0,15,-15,0,90,0,1350,1350,90
"""


def _fake_compute_charges(*args, **kwargs):
    settlement_total = float(kwargs.get("expiry_settlement_total", 0.0))
    return (
        {
            "bill_lines": [],
            "total_expenses": 0.0,
            "net_amount": 0.0,
            "total_bill_amount": 0.0,
            "gst_base": 0.0,
            "gst_total": 0.0,
            "expiry_settlement_total": settlement_total,
        },
        {"turnover_bases": {}},
    )


def test_generate_admin_zip_lists_account_pdfs_in_natural_pr_order(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "get_rate_card", lambda: {"source": "test", "rules": []})
    monkeypatch.setattr(main_module, "compute_charges", _fake_compute_charges)
    monkeypatch.setattr(main_module, "render_bill_pdf", lambda context: b"bill")
    monkeypatch.setattr(
        main_module,
        "render_closing_positions_pdf",
        lambda account_meta, rows, total, status: b"closing",
    )
    monkeypatch.setattr(main_module, "merge_pdf_documents", lambda pdfs: b"merged")
    monkeypatch.setattr(
        main_module,
        "render_admin_consolidated_pdf",
        lambda accounts_bundle, trade_date: b"admin",
    )
    monkeypatch.setattr(
        main_module,
        "render_admin_summary_pdf",
        lambda summary_rows, totals, trade_date: b"summary",
    )

    daywise_file = UploadFile(
        filename="daywise.csv",
        file=io.BytesIO(DAYWISE_CSV.encode("utf-8")),
    )
    netwise_file = UploadFile(
        filename="netwise.csv",
        file=io.BytesIO(NETWISE_CSV.encode("utf-8")),
    )

    response = asyncio.run(
        main_module.generate_admin(
            trade_date="12-02-2026",
            daywise_file=daywise_file,
            netwise_file=netwise_file,
            debug=False,
        )
    )

    assert response.status_code == 200
    assert response.media_type == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.body), "r") as archive:
        names = archive.namelist()
        pdf_names = [name for name in names if name.lower().endswith(".pdf")]
        account_pdfs = [name for name in pdf_names if name.startswith("Bill_PR")]
        assert account_pdfs == [
            "Bill_PR10_12-02-2026.pdf",
            "Bill_PR6_12-02-2026.pdf",
            "Bill_PR05_12-02-2026.pdf",
        ]
        non_account_pdfs = [name for name in pdf_names if not name.startswith("Bill_PR")]
        assert non_account_pdfs == sorted(non_account_pdfs, key=natural_pr_sort_key)

        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        manifest_account_pdfs = [entry["pdf"] for entry in manifest["success"]]
        assert manifest_account_pdfs == [
            "Bill_PR05_12-02-2026.pdf",
            "Bill_PR6_12-02-2026.pdf",
            "Bill_PR10_12-02-2026.pdf",
        ]
        assert manifest["files"] == sorted(pdf_names, key=natural_pr_sort_key)
        assert manifest["zip_write_order"] == pdf_names

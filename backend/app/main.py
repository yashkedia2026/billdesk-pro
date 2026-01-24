import io
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pandas.errors import EmptyDataError, ParserError

from app.charges import compute_charges
from app.pdf import build_pdf_context, render_bill_pdf
from app.positions import build_positions, clean_df
from app.rate_card import get_rate_card
from app.validation import (
    DAYWISE_SYNONYMS,
    NETWISE_SYNONYMS,
    REQUIRED_COLUMNS,
    validate_csv_columns,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"

app = FastAPI()

# Serve files in app/static at /static.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root() -> FileResponse:
    """Return the static index page."""
    return FileResponse(INDEX_FILE, media_type="text/html")


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}


@app.get("/rate-card")
async def rate_card() -> dict:
    try:
        return get_rate_card()
    except ValueError as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/generate")
async def generate(
    account: Optional[str] = Form(None),
    trade_date: Optional[str] = Form(None),
    daywise_file: Optional[UploadFile] = File(None),
    netwise_file: Optional[UploadFile] = File(None),
    debug: bool = Query(False),
) -> Response:
    if not account:
        return JSONResponse(status_code=400, content={"error": "account is required"})
    if not trade_date:
        return JSONResponse(status_code=400, content={"error": "trade_date is required"})
    if daywise_file is None:
        return JSONResponse(
            status_code=400, content={"error": "daywise CSV file is required"}
        )
    if netwise_file is None:
        return JSONResponse(
            status_code=400, content={"error": "netwise CSV file is required"}
        )

    try:
        daywise_df = _read_upload_csv(daywise_file, "Day wise")
        netwise_df = _read_upload_csv(netwise_file, "Net wise")

        daywise_df = clean_df(daywise_df)
        netwise_df = clean_df(netwise_df)

        daywise_df = validate_csv_columns(
            daywise_df, REQUIRED_COLUMNS, DAYWISE_SYNONYMS, "Daywise"
        )
        netwise_df = validate_csv_columns(
            netwise_df, REQUIRED_COLUMNS, NETWISE_SYNONYMS, "Netwise"
        )

        buy_turnover = _numeric_sum(daywise_df, "Actual Buy Value")
        sell_turnover = _numeric_sum(daywise_df, "Actual Sell Value")
        net_amount = _numeric_sum(daywise_df, "Actual Mark To Market")

        net_qty = pd.to_numeric(netwise_df["NetQty"], errors="coerce").fillna(0)
        nonzero_netqty_rows = int((net_qty != 0).sum())

        positions_rows, positions_totals = build_positions(daywise_df)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    try:
        rate_card = get_rate_card()
        charges, debug_payload = compute_charges(
            daywise_df, netwise_df, rate_card, debug=debug
        )
    except ValueError as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    if debug:
        response_payload = {
            "status": "parsed",
            "account": account,
            "trade_date": trade_date,
            "daywise": {
                "rows": int(daywise_df.shape[0]),
                "columns": [str(col) for col in daywise_df.columns],
                "buy_turnover": buy_turnover,
                "sell_turnover": sell_turnover,
                "net_amount": net_amount,
            },
            "netwise": {
                "rows": int(netwise_df.shape[0]),
                "columns": [str(col) for col in netwise_df.columns],
                "nonzero_netqty_rows": nonzero_netqty_rows,
            },
            "positions": {"rows": positions_rows, "totals": positions_totals},
            "rate_card": {
                "source": rate_card["source"],
                "rules_count": len(rate_card["rules"]),
                "sample": rate_card["rules"][:5],
            },
            "turnover_bases": debug_payload["turnover_bases"],
            "charges": charges,
            "debug": debug_payload,
        }
        return JSONResponse(status_code=200, content=response_payload)

    context = build_pdf_context(
        account=account,
        trade_date=trade_date,
        daywise_df=daywise_df,
        positions_rows=positions_rows,
        positions_totals=positions_totals,
        charges=charges,
    )
    pdf_bytes = render_bill_pdf(context)
    filename = _safe_pdf_filename(account, trade_date)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


def _safe_pdf_filename(account: str, trade_date: str) -> str:
    safe_account = _sanitize_filename_part(account)
    safe_trade_date = _sanitize_filename_part(trade_date)
    return f"Bill_{safe_account}_{safe_trade_date}.pdf"


def _sanitize_filename_part(value: str) -> str:
    sanitized = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip()
    )
    return sanitized or "UNKNOWN"


def _read_upload_csv(upload_file: UploadFile, label: str) -> pd.DataFrame:
    """Read an uploaded CSV into a DataFrame with safe decoding."""
    try:
        upload_file.file.seek(0)
    except Exception:
        pass

    raw_bytes = upload_file.file.read()
    if not raw_bytes:
        raise ValueError(f"{label} CSV file is empty")

    try:
        text_data = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text_data = raw_bytes.decode("latin-1")
        except UnicodeDecodeError:
            raise ValueError(f"{label} CSV file could not be decoded") from None

    try:
        df = pd.read_csv(io.StringIO(text_data))
    except (EmptyDataError, ParserError, UnicodeDecodeError, ValueError):
        raise ValueError(f"{label} CSV could not be parsed") from None

    if df.empty and len(df.columns) == 0:
        raise ValueError(f"{label} CSV file is empty")

    return df


def _numeric_sum(df: pd.DataFrame, column: str) -> float:
    """Sum a column after coercing non-numeric values to 0."""
    series = pd.to_numeric(df[column], errors="coerce").fillna(0)
    return float(series.sum())

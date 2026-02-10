import io
import json
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pandas.errors import EmptyDataError, ParserError

from app.admin_batch import extract_group_indices, resolve_group_columns
from app.charges import compute_charges
from app.charges_edit import apply_user_edits, parse_json_list
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
    overrides_json: Optional[str] = Form(None),
    additions_json: Optional[str] = Form(None),
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

    try:
        overrides = parse_json_list(overrides_json, "overrides_json")
        additions = parse_json_list(additions_json, "additions_json")
        if overrides or additions:
            charges = apply_user_edits(charges, overrides, additions)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

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


@app.post("/preview")
async def preview(
    account: Optional[str] = Form(None),
    trade_date: Optional[str] = Form(None),
    daywise_file: Optional[UploadFile] = File(None),
    netwise_file: Optional[UploadFile] = File(None),
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

        rate_card = get_rate_card()
        charges, _ = compute_charges(daywise_df, netwise_df, rate_card, debug=False)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})

    payload = {
        "ok": True,
        "charges": {
            "bill_lines": charges["bill_lines"],
            "net_amount": charges["net_amount"],
            "total_expenses": charges["total_expenses"],
            "total_bill_amount": charges["total_bill_amount"],
            "gst_base": charges["gst_base"],
            "gst_total": charges["gst_total"],
        },
    }
    return JSONResponse(status_code=200, content=payload)


@app.post("/generate-admin")
async def generate_admin(
    trade_date: Optional[str] = Form(None),
    daywise_file: Optional[UploadFile] = File(None),
    netwise_file: Optional[UploadFile] = File(None),
    debug: bool = Query(False),
) -> Response:
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

        resolve_group_columns(daywise_df, netwise_df)

        daywise_df = validate_csv_columns(
            daywise_df, REQUIRED_COLUMNS, DAYWISE_SYNONYMS, "Daywise"
        )
        netwise_df = validate_csv_columns(
            netwise_df, REQUIRED_COLUMNS, NETWISE_SYNONYMS, "Netwise"
        )

        group_info = resolve_group_columns(daywise_df, netwise_df)
        day_groups, net_groups, failures = extract_group_indices(
            daywise_df,
            netwise_df,
            group_info["group_key"],
            group_info["day_account_col"],
            group_info["day_user_col"],
            group_info["net_account_col"],
            group_info["net_user_col"],
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    manifest = {
        "trade_date": trade_date,
        "group_key_used": group_info["group_key"],
        "success": [],
        "failed": failures,
    }

    if debug:
        manifest["debug"] = {
            "daywise_rows": int(daywise_df.shape[0]),
            "netwise_rows": int(netwise_df.shape[0]),
            "daywise_groups": len(day_groups),
            "netwise_groups": len(net_groups),
        }

    try:
        rate_card = get_rate_card()
    except ValueError as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for key in day_groups:
            if key not in net_groups:
                manifest["failed"].append(
                    {"key": key, "error": "Missing in netwise file."}
                )
                continue

            day_subdf = daywise_df.loc[day_groups[key]]
            net_subdf = netwise_df.loc[net_groups[key]]

            try:
                positions_rows, positions_totals = build_positions(day_subdf)
                charges, _ = compute_charges(
                    day_subdf, net_subdf, rate_card, debug=False
                )
                context = build_pdf_context(
                    account=key,
                    trade_date=trade_date,
                    daywise_df=day_subdf,
                    positions_rows=positions_rows,
                    positions_totals=positions_totals,
                    charges=charges,
                )
                pdf_bytes = render_bill_pdf(context)
                filename = _safe_pdf_filename(key, trade_date)
                zip_file.writestr(filename, pdf_bytes)
                manifest["success"].append({"key": key, "pdf": filename})
            except Exception as exc:
                manifest["failed"].append(
                    {"key": key, "error": _truncate_error(exc)}
                )

        for key in net_groups:
            if key not in day_groups:
                manifest["failed"].append(
                    {"key": key, "error": "Missing in daywise file."}
                )

        zip_file.writestr("manifest.json", json.dumps(manifest, indent=2))

    zip_buffer.seek(0)
    safe_trade_date = _sanitize_filename_part(trade_date)
    zip_name = f"Bills_{safe_trade_date}.zip"
    headers = {"Content-Disposition": f'attachment; filename="{zip_name}"'}
    return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers=headers)


def _truncate_error(exc: Exception, limit: int = 300) -> str:
    message = str(exc)
    if len(message) <= limit:
        return message
    return message[: limit - 3] + "..."


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

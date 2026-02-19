import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pandas.errors import EmptyDataError, ParserError

from app.admin_batch import (
    ACCOUNT_ID_SYNONYMS,
    USER_ID_SYNONYMS,
    extract_group_indices,
    find_column,
    netwise_only_keys,
    resolve_group_columns,
)
from app.charges import compute_charges
from app.charges_edit import apply_user_edits, parse_json_list
from app.closing_positions import build_closing_positions
from app.expiry_settlement import apply_expiry_settlement
from app.manual_index_close import build_manual_index_closes
from app.pdf import (
    build_pdf_context,
    merge_pdf_documents,
    render_admin_consolidated_pdf,
    render_admin_summary_pdf,
    render_bill_pdf,
    render_closing_positions_pdf,
)
from app.positions import build_positions, clean_df
from app.rate_card import get_rate_card
from app.utils_sort import extract_pr_number, natural_pr_sort_key
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
    close_nifty: Optional[str] = Form(None),
    close_banknifty: Optional[str] = Form(None),
    close_finnifty: Optional[str] = Form(None),
    close_midcpnifty: Optional[str] = Form(None),
    close_niftynxt50: Optional[str] = Form(None),
    close_sensex: Optional[str] = Form(None),
    close_bankex: Optional[str] = Form(None),
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
        bill_date = _parse_trade_date(trade_date)
        manual_closes = build_manual_index_closes(
            close_nifty=close_nifty,
            close_banknifty=close_banknifty,
            close_finnifty=close_finnifty,
            close_midcpnifty=close_midcpnifty,
            close_niftynxt50=close_niftynxt50,
            close_sensex=close_sensex,
            close_bankex=close_bankex,
        )
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

        (
            netwise_for_closing,
            expiry_settlement_rows,
            expiry_settlement_total,
            expiry_pending_rows,
        ) = apply_expiry_settlement(
            netwise_df,
            bill_date,
            manual_closes=manual_closes,
        )

        positions_rows, positions_totals = build_positions(daywise_df)
        closing_rows, closing_total, closing_status = build_closing_positions(
            netwise_for_closing, trade_date
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    try:
        rate_card = get_rate_card()
        charges, debug_payload = compute_charges(
            daywise_df,
            netwise_df,
            rate_card,
            expiry_settlement_total=expiry_settlement_total,
            debug=debug,
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
            "closing_positions": {
                "status": closing_status,
                "rows": closing_rows,
                "total_value": closing_total,
            },
            "expiry_settlement": {
                "settlement_total": expiry_settlement_total,
                "settlement_rows": expiry_settlement_rows,
                "pending_rows": expiry_pending_rows,
            },
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
        expiry_settlement_rows=expiry_settlement_rows,
        expiry_pending_rows=expiry_pending_rows,
        expiry_settlement_total=expiry_settlement_total,
    )
    account_meta = {
        "account_code": account,
        "account_name": account,
        "trade_date": trade_date,
    }
    bill_pdf_bytes = render_bill_pdf(context)
    closing_pdf_bytes = render_closing_positions_pdf(
        account_meta,
        closing_rows,
        closing_total,
        closing_status,
    )
    pdf_bytes = merge_pdf_documents([bill_pdf_bytes, closing_pdf_bytes])
    filename = _safe_pdf_filename(account, trade_date)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@app.post("/preview")
async def preview(
    account: Optional[str] = Form(None),
    trade_date: Optional[str] = Form(None),
    daywise_file: Optional[UploadFile] = File(None),
    netwise_file: Optional[UploadFile] = File(None),
    close_nifty: Optional[str] = Form(None),
    close_banknifty: Optional[str] = Form(None),
    close_finnifty: Optional[str] = Form(None),
    close_midcpnifty: Optional[str] = Form(None),
    close_niftynxt50: Optional[str] = Form(None),
    close_sensex: Optional[str] = Form(None),
    close_bankex: Optional[str] = Form(None),
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
        bill_date = _parse_trade_date(trade_date)
        manual_closes = build_manual_index_closes(
            close_nifty=close_nifty,
            close_banknifty=close_banknifty,
            close_finnifty=close_finnifty,
            close_midcpnifty=close_midcpnifty,
            close_niftynxt50=close_niftynxt50,
            close_sensex=close_sensex,
            close_bankex=close_bankex,
        )
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
        _, _, expiry_settlement_total, _ = apply_expiry_settlement(
            netwise_df,
            bill_date,
            manual_closes=manual_closes,
        )
        charges, _ = compute_charges(
            daywise_df,
            netwise_df,
            rate_card,
            expiry_settlement_total=expiry_settlement_total,
            debug=False,
        )
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
    close_nifty: Optional[str] = Form(None),
    close_banknifty: Optional[str] = Form(None),
    close_finnifty: Optional[str] = Form(None),
    close_midcpnifty: Optional[str] = Form(None),
    close_niftynxt50: Optional[str] = Form(None),
    close_sensex: Optional[str] = Form(None),
    close_bankex: Optional[str] = Form(None),
    debug: bool = Query(False),
) -> Response:
    if not trade_date:
        return JSONResponse(status_code=400, content={"error": "trade_date is required"})
    if daywise_file is None:
        return JSONResponse(
            status_code=400, content={"error": "daywise CSV file is required"}
        )

    try:
        bill_date = _parse_trade_date(trade_date)
        manual_closes = build_manual_index_closes(
            close_nifty=close_nifty,
            close_banknifty=close_banknifty,
            close_finnifty=close_finnifty,
            close_midcpnifty=close_midcpnifty,
            close_niftynxt50=close_niftynxt50,
            close_sensex=close_sensex,
            close_bankex=close_bankex,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    netwise_warnings: List[str] = []

    try:
        daywise_raw = _drop_unnamed_columns(_read_upload_csv(daywise_file, "Day wise"))
        daywise_df = validate_csv_columns(
            daywise_raw, REQUIRED_COLUMNS, DAYWISE_SYNONYMS, "Daywise"
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    netwise_raw = pd.DataFrame()
    netwise_df = pd.DataFrame()
    netwise_valid = False

    if netwise_file is not None:
        try:
            netwise_raw = _drop_unnamed_columns(_read_upload_csv(netwise_file, "Net wise"))
            netwise_df = validate_csv_columns(
                netwise_raw, REQUIRED_COLUMNS, NETWISE_SYNONYMS, "Netwise"
            )
            netwise_valid = True
        except ValueError as exc:
            netwise_warnings.append(
                "Netwise file was not usable; closing positions will be treated as unavailable. "
                f"Reason: {exc}"
            )
            netwise_df = pd.DataFrame()
            netwise_raw = pd.DataFrame()
    else:
        netwise_warnings.append(
            "Netwise file was not provided; closing positions will be treated as unavailable."
        )

    try:
        if netwise_valid and _has_group_columns(netwise_df):
            group_info = resolve_group_columns(daywise_df, netwise_df)
        else:
            group_info = _resolve_daywise_group_columns(daywise_df)

        day_groups, net_groups, day_missing, net_missing = extract_group_indices(
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
        "failed": [],
        "warnings": [],
        "counts": {
            "daywise_rows_total": int(daywise_raw.shape[0]),
            "netwise_rows_total": int(netwise_raw.shape[0]),
            "daywise_unique_keys": len(day_groups),
            "netwise_unique_keys": len(net_groups),
            "daywise_rows_missing_key": day_missing,
            "netwise_rows_missing_key": net_missing,
            "accounts_empty_after_cleaning": 0,
            "generated_pdfs": 0,
        },
    }
    for warning in netwise_warnings:
        manifest["warnings"].append({"key": "__global__", "warning": warning})

    try:
        rate_card = get_rate_card()
    except ValueError as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    zip_buffer = io.BytesIO()
    safe_trade_date = _sanitize_filename_part(trade_date)
    accounts_bundle: List[Dict] = []
    summary_rows: List[Dict] = []
    generated_account_files: List[Dict] = []
    ordered_account_keys = sorted(day_groups.keys(), key=natural_pr_sort_key)

    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for key in ordered_account_keys:
            day_sub_raw = daywise_df.loc[day_groups[key]]
            day_subdf = clean_df(day_sub_raw)
            if day_subdf.empty:
                manifest["failed"].append(
                    {
                        "key": key,
                        "error": "No tradable rows after cleaning (TradingSymbol empty).",
                    }
                )
                manifest["counts"]["accounts_empty_after_cleaning"] += 1
                continue
            has_net_rows = key in net_groups
            if has_net_rows:
                net_subdf = netwise_df.loc[net_groups[key]]
            else:
                net_subdf = netwise_df.head(0).copy()
                manifest["warnings"].append(
                    {
                        "key": key,
                        "warning": (
                            "Netwise rows missing; assignment STT assumed 0 and closing "
                            "positions will be marked unavailable."
                        ),
                    }
                )

            try:
                (
                    net_subdf_for_closing,
                    expiry_settlement_rows,
                    expiry_settlement_total,
                    expiry_pending_rows,
                ) = apply_expiry_settlement(
                    net_subdf,
                    bill_date,
                    manual_closes=manual_closes,
                )
                positions_rows, positions_totals = build_positions(day_subdf)
                charges, _ = compute_charges(
                    day_subdf,
                    net_subdf,
                    rate_card,
                    expiry_settlement_total=expiry_settlement_total,
                    debug=False,
                )
                context = build_pdf_context(
                    account=key,
                    trade_date=trade_date,
                    daywise_df=day_subdf,
                    positions_rows=positions_rows,
                    positions_totals=positions_totals,
                    charges=charges,
                    expiry_settlement_rows=expiry_settlement_rows,
                    expiry_pending_rows=expiry_pending_rows,
                    expiry_settlement_total=expiry_settlement_total,
                )
                closing_rows, closing_total, closing_status = build_closing_positions(
                    net_subdf_for_closing, trade_date
                )
                account_meta = {
                    "account_code": key,
                    "account_name": key,
                    "trade_date": trade_date,
                }

                bill_pdf_bytes = render_bill_pdf(context)
                closing_pdf_bytes = render_closing_positions_pdf(
                    account_meta,
                    closing_rows,
                    closing_total,
                    closing_status,
                )
                pdf_bytes = merge_pdf_documents([bill_pdf_bytes, closing_pdf_bytes])
                filename = _safe_pdf_filename(key, trade_date)
                generated_account_files.append(
                    {
                        "key": key,
                        "filename": filename,
                        "pdf_bytes": pdf_bytes,
                    }
                )
                manifest["success"].append({"key": key, "pdf": filename})
                manifest["counts"]["generated_pdfs"] += 1
                accounts_bundle.append(
                    {
                        "account_code": key,
                        "account_meta": account_meta,
                        "drcr_amount": float(context.get("total_bill_amount", 0.0)),
                        "closing_rows": closing_rows,
                        "closing_total": float(closing_total),
                        "closing_status": closing_status,
                        "bill_context": context,
                        "bill_pdf_bytes": bill_pdf_bytes,
                        "closing_pdf_bytes": closing_pdf_bytes,
                    }
                )
            except Exception as exc:
                manifest["failed"].append({"key": key, "error": _truncate_error(exc)})

        for key in netwise_only_keys(day_groups, net_groups):
            manifest["failed"].append({"key": key, "error": "Missing in daywise file."})

        accounts_bundle = sorted(
            accounts_bundle,
            key=lambda item: natural_pr_sort_key(item.get("account_code", "")),
        )
        consolidated_bytes = render_admin_consolidated_pdf(accounts_bundle, trade_date)
        consolidated_filename = f"Bill_Admin_{safe_trade_date}.pdf"

        for index, account in enumerate(accounts_bundle, start=1):
            drcr_amount = float(account["drcr_amount"])
            closing_total = float(account["closing_total"])
            summary_rows.append(
                {
                    "sr": index,
                    "account_code": account["account_code"],
                    "drcr_amount": drcr_amount,
                    "closing_total": closing_total,
                    "final_adjusted": drcr_amount + closing_total,
                    "closing_status": account["closing_status"],
                }
            )

        total_drcr = sum(float(row["drcr_amount"]) for row in summary_rows)
        total_closing = sum(
            float(row["closing_total"])
            for row in summary_rows
            if row.get("closing_status") == "OK"
        )
        missing_count = sum(
            1 for row in summary_rows if row.get("closing_status") != "OK"
        )
        summary_totals = {
            "total_drcr": total_drcr,
            "total_closing": total_closing,
            "final_adjusted": total_drcr + total_closing,
            "missing_count": missing_count,
        }

        summary_pdf_bytes = render_admin_summary_pdf(
            summary_rows, summary_totals, trade_date
        )
        summary_filename = f"Summary_Admin_Closing_Adjustment_{safe_trade_date}.pdf"

        pdf_outputs = [
            (consolidated_filename, consolidated_bytes),
            (summary_filename, summary_pdf_bytes),
        ]
        pdf_outputs.extend(
            (entry["filename"], entry["pdf_bytes"]) for entry in generated_account_files
        )
        sorted_pdf_outputs = sorted(
            pdf_outputs,
            key=lambda item: natural_pr_sort_key(item[0]),
        )
        account_pdf_outputs: List[tuple[str, bytes]] = []
        non_account_pdf_outputs: List[tuple[str, bytes]] = []
        for filename, pdf_bytes in sorted_pdf_outputs:
            if _is_pr_account_pdf_name(filename):
                account_pdf_outputs.append((filename, pdf_bytes))
            else:
                non_account_pdf_outputs.append((filename, pdf_bytes))

        # Finder commonly opens extracted folders in Date Added (desc). Writing PR files
        # high->low makes that default view appear low->high for PR account PDFs.
        zip_write_outputs = non_account_pdf_outputs + list(reversed(account_pdf_outputs))

        for filename, pdf_bytes in zip_write_outputs:
            zip_file.writestr(filename, pdf_bytes)

        manifest["success"] = sorted(
            manifest["success"],
            key=lambda item: natural_pr_sort_key(item.get("pdf", "")),
        )
        manifest["files"] = [filename for filename, _ in sorted_pdf_outputs]
        manifest["zip_write_order"] = [filename for filename, _ in zip_write_outputs]

        zip_file.writestr("manifest.json", json.dumps(manifest, indent=2))

    zip_buffer.seek(0)
    zip_name = f"Bills_{safe_trade_date}.zip"
    headers = {"Content-Disposition": f'attachment; filename="{zip_name}"'}
    return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers=headers)


def _has_group_columns(df: pd.DataFrame) -> bool:
    return bool(
        find_column(df, ACCOUNT_ID_SYNONYMS) or find_column(df, USER_ID_SYNONYMS)
    )


def _resolve_daywise_group_columns(daywise_df: pd.DataFrame) -> Dict[str, Optional[str]]:
    day_account_col = find_column(daywise_df, ACCOUNT_ID_SYNONYMS)
    day_user_col = find_column(daywise_df, USER_ID_SYNONYMS)

    if day_account_col:
        group_key = "account_id"
    elif day_user_col:
        group_key = "user_id"
    else:
        raise ValueError("Admin file must contain Account Id or User Id column.")

    return {
        "group_key": group_key,
        "day_account_col": day_account_col,
        "net_account_col": None,
        "day_user_col": day_user_col,
        "net_user_col": None,
    }


def _truncate_error(exc: Exception, limit: int = 300) -> str:
    message = str(exc)
    if len(message) <= limit:
        return message
    return message[: limit - 3] + "..."


def _safe_pdf_filename(account: str, trade_date: str) -> str:
    safe_account = _sanitize_filename_part(account)
    safe_trade_date = _sanitize_filename_part(trade_date)
    return f"Bill_{safe_account}_{safe_trade_date}.pdf"


def _is_pr_account_pdf_name(filename: str) -> bool:
    text = str(filename or "").strip()
    lower = text.lower()
    if not lower.endswith(".pdf"):
        return False
    if not lower.startswith("bill_") or lower.startswith("bill_admin_"):
        return False
    return extract_pr_number(text) is not None


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


def _drop_unnamed_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[:, [col for col in df.columns if not str(col).startswith("Unnamed:")]]


def _numeric_sum(df: pd.DataFrame, column: str) -> float:
    """Sum a column after coercing non-numeric values to 0."""
    series = pd.to_numeric(df[column], errors="coerce").fillna(0)
    return float(series.sum())


def _parse_trade_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise ValueError("trade_date is required")

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        raise ValueError("Invalid trade_date format.")
    return parsed.date()

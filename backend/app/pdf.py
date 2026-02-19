from __future__ import annotations

import io
from typing import Dict, List, Optional, Sequence

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.charges import normalize_segment
from app.utils_sort import natural_pr_sort_key


def render_bill_pdf(context: Dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "bill-title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=13,
        alignment=1,
        spaceAfter=4,
    )

    elements: List = [Paragraph("Bill Summary Report", title_style)]

    meta_table = _build_meta_table(context, doc.width)
    elements.append(meta_table)
    elements.append(Spacer(0, 6))

    positions_table = _build_positions_table(context, doc.width)
    elements.append(positions_table)
    elements.append(Spacer(0, 8))

    expiry_rows = context.get("expiry_settlement_rows", []) or []
    pending_rows = context.get("expiry_pending_rows", []) or []
    expiry_total = float(context.get("expiry_settlement_total", 0.0) or 0.0)

    if expiry_rows:
        elements.append(_build_section_heading("Expiry Settlement (Exercise/Assignment)"))
        elements.append(
            _build_expiry_settlement_table(
                expiry_rows,
                doc.width,
                include_total=True,
                total_amount=expiry_total,
            )
        )
        elements.append(Spacer(0, 8))

    if pending_rows:
        elements.append(
            _build_section_heading(
                "Pending Expiry Settlement (Missing Manual Index Close)"
            )
        )
        elements.append(
            _build_pending_expiry_settlement_table(
                pending_rows,
                doc.width,
            )
        )
        elements.append(Spacer(0, 8))

    expenses_table = _build_expenses_table(context, doc.width * 0.3)
    total_bill_box = _build_total_bill_box(context, doc.width * 0.3)

    expenses_stack = Table(
        [[expenses_table], [Spacer(0, 6)], [total_bill_box]],
        colWidths=[doc.width * 0.3],
    )
    expenses_stack.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    expenses_layout = Table(
        [["", expenses_stack]],
        colWidths=[doc.width * 0.7, doc.width * 0.3],
    )
    expenses_layout.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    elements.append(expenses_layout)

    doc.build(elements, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


def render_bill_pages(context: Dict) -> bytes:
    """Compatibility helper for bill-only pages."""
    return render_bill_pdf(context)


def draw_closing_positions_page(
    c: canvas.Canvas,
    account_meta: Dict,
    rows: List[Dict],
    total_value: float,
    status: str,
    *,
    start_new_page: bool = True,
) -> None:
    if start_new_page:
        c.showPage()

    page_width, page_height = landscape(A4)
    left = 12 * mm
    right = page_width - 12 * mm
    top = page_height - 12 * mm

    c.setFont("Helvetica-Bold", 14)
    c.drawString(left, top, "Closing Positions")

    account_code = str(
        account_meta.get("account_code")
        or account_meta.get("code")
        or account_meta.get("account")
        or ""
    ).strip()
    trade_date = _format_trade_date(account_meta.get("trade_date", ""))

    y = top - 7 * mm
    c.setFont("Helvetica", 9)
    c.drawString(left, y, f"Account Id / User Id: {account_code or '-'}")
    y -= 5 * mm
    c.drawString(left, y, f"Trade Date: {trade_date}")
    y -= 7 * mm

    if status != "OK" or not rows:
        message = (
            "No open positions."
            if status == "NO_OPEN_POSITIONS"
            else "Closing positions not available (NETWISE missing / no matching data)."
        )
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(left, y, message)
        y -= 10 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawRightString(
            right,
            y,
            "Total Value of Closing Positions (Account-wise): 0.00",
        )
        return

    headers = [
        "Sr. No.",
        "Strike / Contract",
        "Net Quantity",
        "LTP",
        "Value of Closing Position (LTP x Net Qty)",
    ]
    table_data = [headers]
    for row in rows:
        table_data.append(
            [
                str(row.get("sr", "")),
                str(row.get("contract", "")),
                _format_qty(row.get("net_qty")),
                _format_amount(row.get("ltp", 0), 2),
                _format_amount(row.get("value", 0), 2),
            ]
        )
    table_data.append(
        [
            "",
            "Total",
            "",
            "",
            _format_amount(total_value, 2),
        ]
    )

    col_widths = _scale_widths([14, 74, 26, 22, 44], right - left)
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efede2")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#efede2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    available_height = max(20 * mm, y - 18 * mm)
    _, height = table.wrap(right - left, available_height)
    table.drawOn(c, left, y - height)


def render_closing_positions_pdf(
    account_meta: Dict,
    rows: List[Dict],
    total_value: float,
    status: str,
) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    draw_closing_positions_page(
        c,
        account_meta,
        rows,
        total_value,
        status,
        start_new_page=False,
    )
    c.save()
    return buffer.getvalue()


def merge_pdf_documents(pdf_documents: Sequence[bytes]) -> bytes:
    writer = PdfWriter()

    for pdf_bytes in pdf_documents:
        if not pdf_bytes:
            continue
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)

    output = io.BytesIO()
    if len(writer.pages) == 0:
        blank = canvas.Canvas(output, pagesize=landscape(A4))
        blank.setFont("Helvetica", 9)
        blank.drawString(10 * mm, landscape(A4)[1] - 12 * mm, "No pages generated.")
        blank.save()
        return output.getvalue()

    writer.write(output)
    return output.getvalue()


def render_admin_consolidated_pdf(accounts_bundle: List[Dict], trade_date: str) -> bytes:
    del trade_date  # kept for API compatibility

    ordered_accounts = sorted(
        accounts_bundle,
        key=lambda account: natural_pr_sort_key(account.get("account_code", "")),
    )
    ordered_parts: List[bytes] = []

    for account in ordered_accounts:
        bill_pdf = account.get("bill_pdf_bytes")
        if not bill_pdf and account.get("bill_context"):
            bill_pdf = render_bill_pages(account["bill_context"])
        if bill_pdf:
            ordered_parts.append(bill_pdf)
        account_meta = dict(account.get("account_meta", {}) or {})
        if not account_meta and account.get("bill_context"):
            context = account["bill_context"]
            account_meta = {
                "account_code": context.get("code", ""),
                "trade_date": context.get("trade_date", ""),
            }

        closing_rows = account.get("closing_rows", []) or []
        closing_total = float(account.get("closing_total", 0.0))
        closing_status = str(account.get("closing_status", "MISSING"))
        if not closing_rows:
            # For ADMIN combined PDF, empty closing sections should read as no open positions.
            closing_status = "NO_OPEN_POSITIONS"
        closing_pdf = render_closing_positions_pdf(
            account_meta,
            closing_rows,
            closing_total,
            closing_status,
        )
        ordered_parts.append(closing_pdf)

    return merge_pdf_documents(ordered_parts)


def render_admin_summary_pdf(summary_rows: List[Dict], totals: Dict, trade_date: str) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    page_width, page_height = landscape(A4)

    left = 12 * mm
    right = page_width - 12 * mm
    top = page_height - 12 * mm

    c.setFont("Helvetica-Bold", 14)
    c.drawString(left, top, "Admin Closing Adjustment Summary")
    c.setFont("Helvetica", 9)
    c.drawString(left, top - 6 * mm, f"Trade Date: {_format_trade_date(trade_date)}")

    table_data = [
        [
            "Sr. No.",
            "Account Code",
            "Total Bill Amount",
            "Total Closing Positions",
            "Final Adjusted",
        ]
    ]
    for row in summary_rows:
        drcr_amount = float(row.get("drcr_amount", 0))
        closing_total = float(row.get("closing_total", 0))
        final_adjusted = float(row.get("final_adjusted", drcr_amount + closing_total))
        table_data.append(
            [
                str(row.get("sr", "")),
                str(row.get("account_code", "")),
                _format_signed_amount(drcr_amount, 2),
                _format_signed_amount(closing_total, 2),
                _format_signed_amount(final_adjusted, 2),
            ]
        )
    if len(table_data) == 1:
        table_data.append(["", "No accounts generated", "0.00", "0.00", "0.00"])

    table_data.append(
        [
            "",
            "Total",
            _format_signed_amount(totals.get("total_drcr", 0.0), 2),
            _format_signed_amount(totals.get("total_closing", 0.0), 2),
            _format_signed_amount(totals.get("final_adjusted", 0.0), 2),
        ]
    )

    summary_table = Table(
        table_data,
        colWidths=_scale_widths([12, 52, 30, 30, 34], right - left),
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efede2")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#efede2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("ALIGN", (2, 0), (4, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    y = top - 14 * mm
    _, table_height = summary_table.wrap(right - left, page_height)
    summary_table.drawOn(c, left, y - table_height)

    c.save()
    return buffer.getvalue()


def build_pdf_context(
    *,
    account: str,
    trade_date: str,
    daywise_df,
    positions_rows: List[Dict],
    positions_totals: Dict,
    charges: Dict,
    expiry_settlement_rows: Optional[List[Dict]] = None,
    expiry_pending_rows: Optional[List[Dict]] = None,
    expiry_settlement_total: Optional[float] = None,
) -> Dict:
    exchange = _exchange_label(daywise_df)
    total_net_qty = sum(int(round(row.get("net_qty", 0))) for row in positions_rows)

    expense_rows = []
    expense_map = {line.get("code"): line for line in charges.get("bill_lines", [])}
    ordered_codes = [
        "SGST_9",
        "CGST_9",
        "SEBI",
        "CLEARING",
        "STAMP_DUTY",
        "TOC_NSE",
        "TOC_BSE",
        "STT",
    ]
    ordered_lines = [expense_map.get(code) for code in ordered_codes if code in expense_map]
    ordered_lines += [
        line for line in charges.get("bill_lines", []) if line.get("code") not in ordered_codes
    ]

    for idx, line in enumerate(ordered_lines, start=1):
        if not line:
            continue
        decimals = 0 if line.get("code") == "STT" else 2
        label = _display_label(line.get("code"), line.get("label", ""))
        expense_rows.append(
            {
                "sr": idx,
                "label": label,
                "amount": line.get("amount", 0),
                "decimals": decimals,
            }
        )

    return {
        "code": account,
        "exchange": exchange,
        "market_type": "FO",
        "trade_date": trade_date,
        "trade_date_display": _format_trade_date(trade_date),
        "positions_rows": positions_rows,
        "positions_totals": positions_totals,
        "total_net_qty": total_net_qty,
        "expense_rows": expense_rows,
        "total_expenses": charges.get("total_expenses", 0),
        "total_bill_amount": charges.get("total_bill_amount", 0),
        "expiry_settlement_rows": expiry_settlement_rows or [],
        "expiry_pending_rows": expiry_pending_rows or [],
        "expiry_settlement_total": float(
            charges.get("expiry_settlement_total", 0.0)
            if expiry_settlement_total is None
            else expiry_settlement_total
        ),
    }


def _build_meta_table(context: Dict, width: float) -> Table:
    style = ParagraphStyle(
        "meta",
        fontName="Helvetica",
        fontSize=9,
        leading=11,
    )
    data = [
        [
            Paragraph(f"<b>Code</b> : {context.get('code', '')}", style),
            Paragraph(f"<b>Exchange</b> : {context.get('exchange', '')}", style),
            Paragraph(
                f"<b>Market Type</b> : {context.get('market_type', '')}", style
            ),
            Paragraph(
                f"<b>Trade Date</b> : {context.get('trade_date_display', '')}", style
            ),
        ]
    ]
    table = Table(data, colWidths=[width / 4] * 4)
    table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _build_section_heading(text: str) -> Paragraph:
    style = ParagraphStyle(
        "section-heading",
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        spaceAfter=3,
    )
    return Paragraph(text, style)


def _build_expiry_settlement_table(
    rows: List[Dict],
    width: float,
    *,
    include_total: bool,
    total_amount: float,
) -> Table:
    action_status_style = ParagraphStyle(
        "action-status-cell",
        fontName="Helvetica",
        fontSize=6.8,
        leading=7.6,
        wordWrap="CJK",
    )

    headers = [
        "Trading Symbol",
        "Net Qty",
        "Underlying Close",
        "Source",
        "Intrinsic",
        "Action / Status",
        "Settlement Amount",
    ]
    data: List[List[object]] = [headers]

    for row in rows:
        data.append(
            [
                str(row.get("trading_symbol", "")),
                _format_qty(row.get("net_qty")),
                _format_optional_amount(row.get("underlying_close")),
                _format_source(row.get("source")),
                _format_optional_amount(row.get("intrinsic")),
                Paragraph(
                    _format_action_status(
                        row.get("action_status", row.get("status", ""))
                    ),
                    action_status_style,
                ),
                _format_amount(row.get("settlement_amount", 0.0), 2),
            ]
        )

    if include_total:
        data.append(
            [
                "",
                "",
                "",
                "",
                "",
                "Total",
                _format_amount(total_amount, 2),
            ]
        )

    col_widths = _scale_widths([92, 24, 34, 28, 24, 48, 36], width)
    table = Table(data, colWidths=col_widths, repeatRows=1)

    style_rows = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efede2")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.0),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "LEFT"),
        ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("ALIGN", (5, 0), (5, -1), "LEFT"),
        ("ALIGN", (6, 0), (6, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if include_total:
        style_rows.extend(
            [
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#efede2")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        )

    table.setStyle(TableStyle(style_rows))
    return table


def _build_pending_expiry_settlement_table(rows: List[Dict], width: float) -> Table:
    headers = [
        "Trading Symbol",
        "Net Qty",
        "Status",
        "Settlement Amount",
    ]

    data: List[List[object]] = [headers]
    for row in rows:
        data.append(
            [
                str(row.get("trading_symbol", "")),
                _format_qty(row.get("net_qty")),
                _format_action_status(row.get("status", row.get("action_status", ""))),
                _format_amount(row.get("settlement_amount", 0.0), 2),
            ]
        )

    col_widths = _scale_widths([108, 28, 64, 40], width)
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efede2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("ALIGN", (2, 0), (2, -1), "LEFT"),
                ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _build_positions_table(context: Dict, width: float) -> Table:
    headers = [
        "Sr",
        "Security",
        "BF Qty",
        "BF Rate",
        "BF Amount",
        "Buy Qty",
        "Buy Rate",
        "Buy Amount",
        "Sell Qty",
        "Sell Rate",
        "Sell Amount",
        "Brkg",
        "Net Qty",
        "Net Rate",
        "Net Amount",
    ]

    data = [headers]
    for row in context.get("positions_rows", []):
        data.append(
            [
                row.get("sr", ""),
                row.get("security", ""),
                _format_qty(row.get("bf_qty")),
                _format_amount(row.get("bf_rate"), 2),
                _format_amount(row.get("bf_amount"), 2),
                _format_qty(row.get("buy_qty")),
                _format_amount(row.get("buy_rate"), 2),
                _format_amount(row.get("buy_amount"), 2),
                _format_qty(row.get("sell_qty")),
                _format_amount(row.get("sell_rate"), 2),
                _format_amount(row.get("sell_amount"), 2),
                _format_amount(row.get("brkg"), 2),
                _format_qty(row.get("net_qty")),
                _format_amount(row.get("net_rate"), 2),
                _format_amount(row.get("net_amount"), 2),
            ]
        )

    totals = context.get("positions_totals", {})
    data.append(
        [
            "",
            "TOTAL",
            "0",
            "0.00",
            "0.00",
            _format_qty(totals.get("total_buy_qty", 0)),
            "",
            _format_amount(totals.get("total_buy_amount", 0), 2),
            _format_qty(totals.get("total_sell_qty", 0)),
            "",
            _format_amount(totals.get("total_sell_amount", 0), 2),
            "0.00",
            _format_qty(context.get("total_net_qty", 0)),
            "",
            _format_amount(totals.get("total_net_amount", 0), 2),
        ]
    )

    col_weights = [
        16,
        80,
        24,
        30,
        38,
        28,
        30,
        40,
        28,
        30,
        40,
        26,
        28,
        30,
        40,
    ]
    col_widths = _scale_widths(col_weights, width)

    header_color = colors.HexColor("#efede2")
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), header_color),
                ("BACKGROUND", (0, -1), (-1, -1), header_color),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _build_expenses_table(context: Dict, width: float) -> Table:
    data = [["Sr", "Expenses", "Amount"]]
    for row in context.get("expense_rows", []):
        data.append(
            [
                row.get("sr", ""),
                row.get("label", ""),
                _format_amount(row.get("amount", 0), int(row.get("decimals", 2))),
            ]
        )

    data.append(
        [
            "",
            "Total",
            _format_amount(context.get("total_expenses", 0), 2),
        ]
    )

    col_weights = [14, 96, 50]
    col_widths = _scale_widths(col_weights, width)

    header_color = colors.HexColor("#efede2")
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), header_color),
                ("BACKGROUND", (0, -1), (-1, -1), header_color),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _build_total_bill_box(context: Dict, width: float) -> Table:
    data = [
        ["Total Bill Amount:", _format_amount(context.get("total_bill_amount", 0), 2)],
    ]
    table = Table(data, colWidths=[width * 0.65, width * 0.35])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#efede2")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _draw_footer(canvas_obj, doc, page_num: int, total_pages: int) -> None:
    canvas_obj.saveState()
    bar_height = 8 * mm
    if doc:
        x = doc.leftMargin
        bar_width = doc.width
    else:
        page_width = canvas_obj._pagesize[0]
        x = 10 * mm
        bar_width = page_width - 2 * x
    y = 4 * mm
    canvas_obj.setFillColor(colors.HexColor("#efede2"))
    canvas_obj.rect(x, y, bar_width, bar_height, fill=1, stroke=1)
    canvas_obj.setFillColor(colors.black)
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.drawRightString(
        x + bar_width - 4, y + 2.5 * mm, f"Page {page_num} of {total_pages}"
    )
    canvas_obj.restoreState()


def _format_trade_date(value: object) -> str:
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        if len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        if len(parts[0]) == 2 and len(parts[1]) == 2 and len(parts[2]) == 4:
            return text
    return text


def _format_amount(value: object, decimals: int = 2) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return ""
    fmt = f"{{:,.{decimals}f}}"
    return fmt.format(amount)


def _format_optional_amount(value: object, decimals: int = 2) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text == "":
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if numeric != numeric:  # NaN check
        return ""
    return _format_amount(value, decimals)


def _format_action_status(value: object) -> str:
    status = str(value or "").strip().upper()
    status_map = {
        "MISSING_MANUAL_CLOSE": "Pending: Missing Manual Close",
        "MISSING_UNDERLYING_CLOSE": "Pending: Missing Underlying Close",
        "MISSING_STRIKE_PRICE": "Pending: Missing Strike Price",
        "EXPIRE_OTM": "Expired OTM",
        "EXERCISE": "Exercise",
        "ASSIGN": "Assignment",
    }
    if status in status_map:
        return status_map[status]
    if not status:
        return ""
    return status.replace("_", " ").title()


def _format_verification(value: object) -> str:
    status = str(value or "").strip().upper()
    status_map = {
        "VERIFIED_MANUAL": "Verified Manual",
        "PENDING": "Pending",
    }
    if status in status_map:
        return status_map[status]
    if not status:
        return ""
    return status.replace("_", " ").title()


def _format_source(value: object) -> str:
    status = str(value or "").strip().upper()
    status_map = {
        "MANUAL_INPUT": "Manual Input",
    }
    if status in status_map:
        return status_map[status]
    if not status:
        return ""
    return status.replace("_", " ").title()


def _format_drcr(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    side = "CR" if amount >= 0 else "DR"
    return f"{_format_amount(abs(amount), 2)} {side}"


def _format_signed_amount(value: object, decimals: int = 2) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    if amount < 0:
        return f"-{_format_amount(abs(amount), decimals)}"
    return _format_amount(amount, decimals)


def _format_qty(value: object) -> str:
    try:
        return f"{int(round(float(value)))}"
    except (TypeError, ValueError):
        return "0"


def _scale_widths(weights: List[float], total_width: float) -> List[float]:
    total_weight = sum(weights)
    if total_weight <= 0:
        return [total_width / len(weights)] * len(weights)
    return [total_width * (weight / total_weight) for weight in weights]


def _exchange_label(daywise_df) -> str:
    if "Exchg.Seg" not in daywise_df.columns:
        return "NFO"
    segments = set()
    for value in daywise_df["Exchg.Seg"]:
        segment = normalize_segment(value)
        segments.add(segment or "NFO")
    if segments == {"BFO"}:
        return "BSE_FO"
    if segments == {"NFO"}:
        return "NSE_FNO"
    return "NSE_FNO/BSE_FO"


class _NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total_pages = len(self._saved_page_states)
        for page_num, state in enumerate(self._saved_page_states, start=1):
            self.__dict__.update(state)
            _draw_footer(self, None, page_num, total_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)


def _display_label(code: object, fallback: str) -> str:
    label_map = {
        "SGST_9": "SGST",
        "CGST_9": "CGST",
        "SEBI": "SEBI FEES",
        "CLEARING": "CLEARING CHARGES",
        "STAMP_DUTY": "STAMPDUTY",
        "TOC_NSE": "TOC NSE Exchange",
        "TOC_BSE": "TOC BSE Exchange",
        "STT": "STT",
    }
    return label_map.get(str(code), fallback)

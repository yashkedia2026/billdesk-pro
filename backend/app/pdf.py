from __future__ import annotations

import io
from typing import Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.charges import normalize_segment


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


def build_pdf_context(
    *,
    account: str,
    trade_date: str,
    daywise_df,
    positions_rows: List[Dict],
    positions_totals: Dict,
    charges: Dict,
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


def _format_qty(value: object) -> str:
    try:
        return f"{int(round(float(value))):,}"
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

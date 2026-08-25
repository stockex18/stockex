"""The printed ledger — the plain, ruled statement accounting software emits.

Deliberately not styled like the rest of the app's PDFs: no brand colour, no
rounded anything. A ledger gets handed to an accountant, and it is easier to
check against their books when it looks like the ones they already read —
firm header, date range, account name, ruled columns, totals that square.

Fonts are borrowed from `report_pdf_service`, which already solved finding a
face that can draw the rupee sign.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal

from reportlab.lib import colors as rl_colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.report_pdf_service import _FONT_BOLD, _FONT_NAME

RULE = rl_colors.HexColor("#000000")
_BASE = getSampleStyleSheet()


def _st(size: float, *, bold: bool = False, align: int = 0, leading: float | None = None):
    return ParagraphStyle(
        f"lg{size}{bold}{align}",
        parent=_BASE["Normal"],
        fontName=_FONT_BOLD if bold else _FONT_NAME,
        fontSize=size,
        leading=leading or size + 2,
        alignment=align,          # 0 left, 1 centre, 2 right
        textColor=rl_colors.black,
    )


def _money(v) -> str:
    """Indian grouping (23,11,735.00), the way the printed ledgers being
    reconciled against are written. Blank at zero — a ledger never prints
    0.00 in a column the line does not touch."""
    try:
        n = Decimal(str(v or 0))
    except Exception:  # noqa: BLE001
        return ""
    if n == 0:
        return ""
    sign = "-" if n < 0 else ""
    whole, _, frac = f"{abs(n):.2f}".partition(".")
    # Last three digits, then pairs: 2311735 -> 23,11,735
    head, tail = whole[:-3], whole[-3:]
    if head:
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        tail = ",".join(parts) + "," + tail
    return sign + tail + "." + frac


def _bal(v, side) -> str:
    """Balance with its side. Blank at zero — a lone "Dr" against no figure
    reads as a missing number rather than a nil balance."""
    m = _money(v)
    return (m + " " + str(side or "")).strip() if m else ""


def _date(v) -> str:
    if not v:
        return ""
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return str(v)
    return d.strftime("%d-%m-%Y")


def _range(start, end) -> str:
    if not start and not end:
        return "( All entries )"
    return "( From " + (_date(start) or "beginning") + " to " + (_date(end) or "date") + " )"


def build_ledger_pdf(statement: dict, firm: dict | None = None) -> bytes:
    firm = firm or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="Ledger — " + str(statement.get("book", {}).get("name", "")),
    )
    flow: list = []

    # ── Header block ────────────────────────────────────────────────
    name = (firm.get("name") or "").strip()
    if name:
        flow.append(Paragraph(name, _st(13, bold=True, align=1)))
    for line in ("address", "statutory"):
        txt = (firm.get(line) or "").strip()
        if txt:
            flow.append(Paragraph(txt, _st(7.5, align=1)))
    flow.append(Spacer(1, 4))
    flow.append(Paragraph("L E D G E R", _st(10, bold=True, align=1)))
    flow.append(Paragraph(_range(statement.get("start"), statement.get("end")), _st(8, align=1)))
    flow.append(Paragraph(
        "Account : " + str(statement.get("book", {}).get("name", "")),
        _st(9, bold=True, align=1),
    ))
    flow.append(Spacer(1, 6))

    # ── Rows ────────────────────────────────────────────────────────
    # A statement whose rows carry a running payable gets a ninth column. Only
    # the security accounts do; the cash books are unchanged by this.
    rows_in = statement.get("rows") or []
    with_payable = any("payable_balance" in r for r in rows_in)

    head = ["Date", "Type", "Vch No.", "Particulars", "Narration",
            "Debit (Rs.)", "Credit (Rs.)", "Balance (Rs.)"]
    if with_payable:
        head.append("Payable (Rs.)")
    data: list[list] = [[Paragraph(h, _st(8, bold=True, align=2 if i >= 5 else 0)) for i, h in enumerate(head)]]

    opening = statement.get("opening_balance") or "0"
    op_side = statement.get("opening_side") or "Dr"
    data.append([
        Paragraph(_date(statement.get("start")), _st(7.5)),
        "", "",
        Paragraph("Opening Balance", _st(7.5)),
        "",
        Paragraph(_money(opening) if op_side == "Dr" else "", _st(7.5, align=2)),
        Paragraph(_money(opening) if op_side == "Cr" else "", _st(7.5, align=2)),
        Paragraph(_bal(opening, op_side), _st(7.5, align=2)),
    ])
    if with_payable:
        data[-1].append("")

    for r in rows_in:
        data.append([
            Paragraph(_date(r.get("entry_date")), _st(7.5)),
            Paragraph(str(r.get("voucher_type") or ""), _st(7.5)),
            Paragraph(str(r.get("voucher_no") or ""), _st(7.5)),
            Paragraph(str(r.get("particulars") or ""), _st(7.5)),
            Paragraph(str(r.get("narration") or ""), _st(7.5)),
            Paragraph(_money(r.get("debit")), _st(7.5, align=2)),
            Paragraph(_money(r.get("credit")), _st(7.5, align=2)),
            Paragraph(_bal(r.get("balance"), r.get("balance_side")), _st(7.5, align=2)),
        ])
        if with_payable:
            data[-1].append(Paragraph(_money(r.get("payable_balance")), _st(7.5, align=2)))

    # A4 is 210mm; 12mm margins leave 186mm. These add to exactly that — the
    # earlier set totalled 202mm and ran off the right edge of the page.
    # Type is wide enough for a mode the operator named ("Brokerage", "bank").
    widths = (
        [16 * mm, 19 * mm, 21 * mm, 25 * mm, 28 * mm, 18 * mm, 18 * mm, 20 * mm, 21 * mm]
        if with_payable
        else [18 * mm, 22 * mm, 24 * mm, 28 * mm, 36 * mm, 19 * mm, 19 * mm, 20 * mm]
    )
    assert sum(widths) == 186 * mm
    tbl = Table(data, colWidths=widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, RULE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(tbl)

    # ── Totals ──────────────────────────────────────────────────────
    closing = statement.get("closing_balance") or "0"
    cl_side = statement.get("closing_side") or "Dr"
    grand = statement.get("grand_total") or "0"
    # The closing figure squares the two columns: it joins whichever side is
    # short, so both add up to the same grand total.
    foot = [
        ["", Paragraph("Total", _st(8, bold=True, align=2)),
         Paragraph(_money(statement.get("total_debit")), _st(8, align=2)),
         Paragraph(_money(statement.get("total_credit")), _st(8, align=2))],
        ["", Paragraph(("Debit Balance" if cl_side == "Dr" else "Credit Balance"), _st(8, bold=True, align=2)),
         Paragraph(_money(closing) if cl_side == "Cr" else "", _st(8, align=2)),
         Paragraph(_money(closing) if cl_side == "Dr" else "", _st(8, align=2))],
        ["", Paragraph("Grand Total", _st(8, bold=True, align=2)),
         Paragraph(_money(grand), _st(8, bold=True, align=2)),
         Paragraph(_money(grand), _st(8, bold=True, align=2))],
    ]
    ft = Table(foot, colWidths=[88 * mm, 40 * mm, 19 * mm, 39 * mm])
    ft.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (2, 1), (-1, 1), 0.6, RULE),
        ("LINEBELOW", (2, 2), (-1, 2), 0.8, RULE),
    ]))
    flow.append(Spacer(1, 2))
    flow.append(ft)

    doc.build(flow)
    return buf.getvalue()

"""
PDF rendering for tax reports and analytics reports.

Built on ReportLab Platypus. Each ``render_*`` function takes the dict
returned by ``reports.build_*`` plus the requesting User, and returns a
``BytesIO`` containing a ready-to-stream PDF.

The page geometry, fonts, and colour palette are kept consistent across
both report types so the user gets a coherent "Folio Reports" look:
A4 portrait, 1.6 cm side margins, Helvetica family, accent purple for
section headings.
"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ── Shared style scaffolding ──────────────────────────────────────────────

ACCENT = colors.HexColor("#4f46e5")
ACCENT_LIGHT = colors.HexColor("#818cf8")
SUCCESS = colors.HexColor("#0d9b6d")
DANGER = colors.HexColor("#dc2626")
TEXT_PRIMARY = colors.HexColor("#0f172a")
TEXT_SECONDARY = colors.HexColor("#475569")
TEXT_MUTED = colors.HexColor("#94a3b8")
BORDER = colors.HexColor("#cbd5e1")
ROW_ALT = colors.HexColor("#f8fafc")
HEAD_BG = colors.HexColor("#1e293b")


def _styles():
    base = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle(
            "T", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=22, leading=26, textColor=TEXT_PRIMARY, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "Sub", parent=base["Normal"], fontName="Helvetica",
            fontSize=11, leading=15, textColor=TEXT_SECONDARY, spaceAfter=2,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=14, leading=18, textColor=ACCENT,
            spaceBefore=14, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "H3", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=11, leading=15, textColor=TEXT_PRIMARY,
            spaceBefore=10, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=13, textColor=TEXT_PRIMARY,
        ),
        "muted": ParagraphStyle(
            "Muted", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.5, leading=12, textColor=TEXT_MUTED,
        ),
        "right": ParagraphStyle(
            "Right", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=13, textColor=TEXT_PRIMARY, alignment=TA_RIGHT,
        ),
        "footnote": ParagraphStyle(
            "Foot", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=8, leading=11, textColor=TEXT_MUTED,
        ),
    }
    return s


def _page_decorator(title_line):
    """Returns an onPage callback that draws the running header + footer."""
    def decorate(canvas, doc):
        canvas.saveState()
        # Header line
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(1.6 * cm, A4[1] - 1.4 * cm, A4[0] - 1.6 * cm, A4[1] - 1.4 * cm)
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(1.6 * cm, A4[1] - 1.1 * cm, "Folio")
        canvas.drawRightString(A4[0] - 1.6 * cm, A4[1] - 1.1 * cm, title_line)
        # Footer
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(TEXT_MUTED)
        page_num = canvas.getPageNumber()
        canvas.drawCentredString(A4[0] / 2, 1.1 * cm, f"Page {page_num}")
        canvas.drawString(
            1.6 * cm, 1.1 * cm,
            "Estimate only — verify with your Steuerberater before filing.",
        )
        canvas.restoreState()
    return decorate


def _money(value, with_sign=False):
    """Format a USD amount as a string."""
    if value is None:
        return "—"
    sign = ""
    if with_sign and value > 0:
        sign = "+"
    elif value < 0:
        sign = "-"
        value = abs(value)
    return f"{sign}${value:,.2f}"


def _pnl_color(value):
    if value is None:
        return TEXT_MUTED
    return SUCCESS if value >= 0 else DANGER


def _kv_table(rows, col_widths, value_align=TA_RIGHT, accent_keys=None):
    """
    Render a label/value summary table. ``rows`` is a list of
    (label, value, optional-color) tuples — the third element overrides
    the value's text colour.
    """
    accent_keys = accent_keys or set()
    data = []
    style = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (1, 0), (1, -1), "RIGHT" if value_align == TA_RIGHT else "LEFT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, BORDER),
        ("TEXTCOLOR", (0, 0), (0, -1), TEXT_SECONDARY),
        ("TEXTCOLOR", (1, 0), (1, -1), TEXT_PRIMARY),
    ])
    for i, row in enumerate(rows):
        label = row[0]
        value = row[1]
        color = row[2] if len(row) > 2 else None
        data.append([label, value])
        if color:
            style.add("TEXTCOLOR", (1, i), (1, i), color)
        if label in accent_keys:
            style.add("FONTNAME", (0, i), (1, i), "Helvetica-Bold")
            style.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eef2ff"))

    t = Table(data, colWidths=col_widths)
    t.setStyle(style)
    return t


def _ledger_table(headers, rows, col_widths, pnl_col_idx=None):
    """
    Render a striped ledger table. ``rows`` is list-of-lists matching
    ``headers``. If ``pnl_col_idx`` is given, that column's text colour
    is set per-row based on a sign-detect of the cell text.
    """
    data = [headers] + rows
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, BORDER),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
    ]
    # Right-align all numeric-looking columns (everything past col 2 by convention)
    if rows and len(rows[0]) > 2:
        for c in range(2, len(rows[0])):
            style_cmds.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))

    if pnl_col_idx is not None:
        for i, row in enumerate(rows, start=1):
            cell = str(row[pnl_col_idx])
            color = SUCCESS if "-" not in cell or cell.startswith("+") else (
                DANGER if cell.startswith("-") else TEXT_PRIMARY
            )
            style_cmds.append(("TEXTCOLOR", (pnl_col_idx, i), (pnl_col_idx, i), color))

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Tax report ────────────────────────────────────────────────────────────


def render_tax_report_pdf(report):
    """Build the tax-report PDF and return a ready-to-stream BytesIO."""
    user = report["user"]
    s = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=2.0 * cm, bottomMargin=1.8 * cm,
        title=f"Tax Report — {report['period_label']}",
        author="Folio",
    )
    story = []

    # ── Title block ──
    story.append(Paragraph("Capital-Gains Tax Report", s["title"]))
    story.append(Paragraph(report["period_label"], s["subtitle"]))
    story.append(Spacer(1, 0.4 * cm))

    meta_rows = [
        ["Account", f"{user.first_name} {user.last_name}".strip() or user.email],
        ["Email", user.email],
        ["Period", f"{report['start_date'].isoformat()} → {report['end_date'].isoformat()}"],
        ["Generated", report["generated_at"].strftime("%Y-%m-%d %H:%M")],
        ["EUR/USD rate used", f"{report['eur_usd_rate']:.4f}"],
        ["Jurisdiction", "Germany — Kapitalertragsteuer + Solidaritätszuschlag"],
    ]
    t = Table(meta_rows, colWidths=[5 * cm, 11.5 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), TEXT_SECONDARY),
        ("TEXTCOLOR", (1, 0), (1, -1), TEXT_PRIMARY),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5 * cm))

    # ── Summary panel ──
    story.append(Paragraph("Summary", s["h2"]))
    summary_rows = [
        ("Stocks — Net P&L", _money(report["stocks"]["net"], True), _pnl_color(report["stocks"]["net"])),
        ("ETFs — Net P&L", _money(report["etfs"]["net"], True), _pnl_color(report["etfs"]["net"])),
        ("Capital-gains net (stocks + ETFs)", _money(report["capital_gains_net"], True),
         _pnl_color(report["capital_gains_net"])),
        ("Crypto — Short-term net (taxable basis)", _money(report["crypto"]["short_term_net"], True),
         _pnl_color(report["crypto"]["short_term_net"])),
        ("Crypto — Long-term gains (tax-free)", _money(report["crypto"]["long_term_gains"]), SUCCESS),
    ]
    if report["is_full_year"]:
        summary_rows += [
            ("Freibetrag (Sparer-Pauschbetrag)", _money(report["freibetrag"])),
            ("Freibetrag used", _money(report["freibetrag_used"])),
            ("Taxable capital gains", _money(report["taxable_capital"])),
            (f"Estimated capital-gains tax (@ {report['tax_rate_pct']}%)",
             _money(report["estimated_tax"]), DANGER),
            ("Net after tax (capital gains)", _money(report["net_after_tax"], True),
             _pnl_color(report["net_after_tax"])),
            ("Crypto Freigrenze", _money(report["freigrenze"])),
            ("Crypto short-term tax status",
             "Freigrenze EXCEEDED — fully taxable" if report["crypto_exceeds_freigrenze"]
             else "Within Freigrenze — tax-free",
             DANGER if report["crypto_exceeds_freigrenze"] else SUCCESS),
        ]
    else:
        summary_rows.append((
            "Freibetrag / Freigrenze",
            "Not computed — applies per calendar year only", TEXT_MUTED,
        ))
    story.append(_kv_table(
        summary_rows, [11 * cm, 5.5 * cm],
        accent_keys={
            "Capital-gains net (stocks + ETFs)",
            "Estimated capital-gains tax (@ {}%)".format(report["tax_rate_pct"]),
        },
    ))

    # ── Stock events ──
    story.append(Paragraph("Stocks — Realized events", s["h2"]))
    if report["stocks"]["events"]:
        headers = ["Date", "Symbol", "Amount", "Sell ($)", "Avg cost ($)", "Fee", "Proceeds", "P&L", "Running"]
        rows = [
            [
                e["date"].isoformat(),
                e["symbol"],
                f"{e['amount']:.6f}".rstrip("0").rstrip("."),
                f"${e['sell_price']:,.2f}",
                f"${e['avg_cost']:,.2f}",
                _money(e["fee"]),
                _money(e["proceeds"]),
                _money(e["pnl"], with_sign=True),
                _money(e["running_total"], with_sign=True),
            ]
            for e in report["stocks"]["events"]
        ]
        story.append(_ledger_table(
            headers, rows,
            col_widths=[1.9 * cm, 1.5 * cm, 1.9 * cm, 1.7 * cm, 1.9 * cm, 1.4 * cm, 1.9 * cm, 1.9 * cm, 2.1 * cm],
            pnl_col_idx=7,
        ))
        _append_class_totals(story, "Stocks", report["stocks"], s)
    else:
        story.append(Paragraph("No stock sells recorded in this period.", s["muted"]))

    # ── ETF events ──
    story.append(Paragraph("ETFs — Realized events", s["h2"]))
    if report["etfs"]["events"]:
        headers = ["Date", "Symbol", "Amount", "Sell ($)", "Avg cost ($)", "Fee", "Proceeds", "P&L", "Running"]
        rows = [
            [
                e["date"].isoformat(),
                e["symbol"],
                f"{e['amount']:.6f}".rstrip("0").rstrip("."),
                f"${e['sell_price']:,.2f}",
                f"${e['avg_cost']:,.2f}",
                _money(e["fee"]),
                _money(e["proceeds"]),
                _money(e["pnl"], with_sign=True),
                _money(e["running_total"], with_sign=True),
            ]
            for e in report["etfs"]["events"]
        ]
        story.append(_ledger_table(
            headers, rows,
            col_widths=[1.9 * cm, 1.5 * cm, 1.9 * cm, 1.7 * cm, 1.9 * cm, 1.4 * cm, 1.9 * cm, 1.9 * cm, 2.1 * cm],
            pnl_col_idx=7,
        ))
        _append_class_totals(story, "ETFs", report["etfs"], s)
    else:
        story.append(Paragraph("No ETF sells recorded in this period.", s["muted"]))

    # ── Crypto events (FIFO-matched, possibly multi-row per sell) ──
    story.append(Paragraph("Crypto — Realized lot events (FIFO)", s["h2"]))
    if report["crypto"]["events"]:
        headers = ["Date", "Symbol", "Amount", "Sell ($)", "Lot ($)",
                   "Held d", "Type", "Proceeds", "P&L", "ST run."]
        rows = []
        for e in report["crypto"]["events"]:
            term = "Long" if e["is_long_term"] else "Short"
            rows.append([
                e["date"].isoformat(),
                e["symbol"],
                f"{e['amount']:.8f}".rstrip("0").rstrip("."),
                f"${e['sell_price']:,.2f}",
                f"${e['lot_price']:,.2f}",
                str(e["holding_days"]),
                term,
                _money(e["proceeds"]),
                _money(e["pnl"], with_sign=True),
                _money(e["short_term_running"], with_sign=True),
            ])
        story.append(_ledger_table(
            headers, rows,
            col_widths=[1.9 * cm, 1.5 * cm, 2.0 * cm, 1.6 * cm, 1.6 * cm,
                        1.0 * cm, 1.0 * cm, 1.7 * cm, 1.7 * cm, 1.9 * cm],
            pnl_col_idx=8,
        ))
        story.append(Spacer(1, 0.2 * cm))
        crypto_totals = [
            ("Short-term gains", _money(report["crypto"]["short_term_gains"]), SUCCESS),
            ("Short-term losses", _money(report["crypto"]["short_term_losses"]), DANGER),
            ("Short-term net", _money(report["crypto"]["short_term_net"], True),
             _pnl_color(report["crypto"]["short_term_net"])),
            ("Long-term gains (tax-free)", _money(report["crypto"]["long_term_gains"]), SUCCESS),
            ("Long-term losses", _money(report["crypto"]["long_term_losses"]), DANGER),
        ]
        story.append(_kv_table(crypto_totals, [11 * cm, 5.5 * cm]))
    else:
        story.append(Paragraph("No crypto sells recorded in this period.", s["muted"]))

    # ── Tax notes ──
    story.append(PageBreak())
    story.append(Paragraph("German tax notes", s["h2"]))
    notes = [
        "<b>Sparer-Pauschbetrag (Freibetrag).</b> Annual tax-free allowance on "
        "capital gains: €1,000 for singles, €2,000 jointly (since 2023). It is "
        "applied to the combined Net of stocks and ETFs in this report. The "
        "remainder is taxed at 25% Kapitalertragsteuer + 5.5% Solidaritätszuschlag "
        "= 26.375%. Church tax (Kirchensteuer) is NOT included.",
        "<b>ETF Teilfreistellung.</b> This estimate does NOT apply the partial "
        "exemption (typically 30% for equity ETFs / 15% for mixed) — your filed "
        "tax will usually be lower than what's shown here.",
        "<b>Vorabpauschale.</b> Any pre-paid annual ETF taxation already paid at "
        "the broker is not deducted in this estimate.",
        "<b>Crypto (private sale, §23 EStG).</b> Lots held longer than 365 days "
        "are 100% tax-free regardless of size. Lots sold inside 365 days fall "
        "under the €1,000 Freigrenze: if your annual short-term net is at or "
        "under the limit it is tax-free; once you cross it, the ENTIRE net is "
        "taxable at your personal income-tax rate (Einkommensteuersatz), not "
        "the 25% capital-gains rate.",
        "<b>Loss-offset rules.</b> Stock losses can only offset stock gains; "
        "ETF losses offset ETF gains; crypto short-term losses offset crypto "
        "short-term gains. Cross-class offsetting (e.g. stock loss against "
        "crypto gain) is generally not allowed.",
        "<b>This report is an estimate.</b> Always cross-check with your "
        "Steuerberater or your broker's annual Steuerbescheinigung before "
        "filing. Folio is not tax-advisory software.",
    ]
    for n in notes:
        story.append(Paragraph(n, s["body"]))
        story.append(Spacer(1, 0.2 * cm))

    decorate = _page_decorator(f"Tax Report — {report['period_label']}")
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    buf.seek(0)
    return buf


def _append_class_totals(story, label, agg, s):
    story.append(Spacer(1, 0.2 * cm))
    rows = [
        (f"{label} — Realized gains", _money(agg["gains"]), SUCCESS),
        (f"{label} — Realized losses", _money(agg["losses"]), DANGER),
        (f"{label} — Net P&L", _money(agg["net"], True), _pnl_color(agg["net"])),
        (f"{label} — Sells in period", str(agg["count"])),
    ]
    story.append(_kv_table(rows, [11 * cm, 5.5 * cm]))


# ── Analytics report ──────────────────────────────────────────────────────


def render_analytics_report_pdf(report):
    """Build the analytics-report PDF and return a ready-to-stream BytesIO."""
    user = report["user"]
    s = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=2.0 * cm, bottomMargin=1.8 * cm,
        title="Portfolio Analytics Report",
        author="Folio",
    )
    story = []

    # ── Title block ──
    story.append(Paragraph("Portfolio Analytics Report", s["title"]))
    story.append(Paragraph(
        f"Snapshot generated {report['generated_at'].strftime('%Y-%m-%d %H:%M')}",
        s["subtitle"],
    ))
    story.append(Spacer(1, 0.4 * cm))

    meta_rows = [
        ["Account", f"{user.first_name} {user.last_name}".strip() or user.email],
        ["Email", user.email],
        ["EUR/USD rate used", f"{report['eur_usd_rate']:.4f}"],
    ]
    t = Table(meta_rows, colWidths=[5 * cm, 11.5 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), TEXT_SECONDARY),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5 * cm))

    # ── Portfolio totals ──
    cs = report["cash_summary"]
    story.append(Paragraph("Portfolio totals", s["h2"]))
    overall = [
        ("Net invested (cash in − cash out)", _money(cs["net_invested_usd"])),
        ("Portfolio worth (mark-to-market)", _money(report["portfolio_worth"])),
        ("Real P&L vs invested", _money(report["real_pnl"], True), _pnl_color(report["real_pnl"])),
        ("Real P&L %", f"{report['real_pnl_pct']:+.2f}%", _pnl_color(report["real_pnl"])),
    ]
    story.append(_kv_table(overall, [11 * cm, 5.5 * cm], accent_keys={"Portfolio worth (mark-to-market)"}))

    # ── Per-kind aggregate ──
    story.append(Paragraph("Per-asset-class summary", s["h2"]))
    headers = ["Class", "Assets", "Held", "Invested", "Cost basis",
               "Sold", "Realized P&L", "Current value", "Unrealized P&L"]
    rows = []
    for kind in ("stock", "etf", "crypto"):
        sm = report["summary"][kind]
        rows.append([
            kind.capitalize(),
            str(sm["asset_count"]),
            str(sm["currently_held"]),
            _money(sm["invested"]),
            _money(sm["cost_basis"]),
            _money(sm["sold"]),
            _money(sm["realized_pnl"], with_sign=True),
            _money(sm["current_value"]),
            _money(sm["unrealized_pnl"], with_sign=True),
        ])
    story.append(_ledger_table(
        headers, rows,
        col_widths=[1.6 * cm, 1.3 * cm, 1.2 * cm, 1.9 * cm, 2.0 * cm,
                    1.8 * cm, 2.1 * cm, 2.1 * cm, 2.1 * cm],
        pnl_col_idx=6,
    ))

    # ── Per-asset detail ──
    story.append(Paragraph("Per-asset detail", s["h2"]))
    if not report["rows"]:
        story.append(Paragraph("No transactions yet.", s["muted"]))
    else:
        headers = ["Symbol", "Name", "Kind", "Holdings",
                   "Avg cost", "Cost basis", "Current", "Value",
                   "Realized P&L", "Unrealized P&L"]
        rows = []
        for r in report["rows"]:
            a = r["analytics"] or {}
            warn = a.get("warning")
            rows.append([
                r["symbol"],
                _truncate(r["name"], 22),
                r["kind"].capitalize(),
                _format_units(a.get("units")),
                _money(a.get("avg_price")) if not warn else "—",
                _money(a.get("cost_basis")) if not warn else "—",
                _money(a.get("current_price")) if a.get("current_price") is not None else "—",
                _money(a.get("current_value")) if a.get("current_value") is not None else "—",
                _money(a.get("realized_pnl"), with_sign=True),
                _money(a.get("unrealized_pnl"), with_sign=True) if a.get("unrealized_pnl") is not None else "—",
            ])
        story.append(_ledger_table(
            headers, rows,
            col_widths=[1.5 * cm, 3.2 * cm, 1.2 * cm, 1.8 * cm,
                        1.5 * cm, 1.7 * cm, 1.4 * cm, 1.7 * cm,
                        1.7 * cm, 1.7 * cm],
            pnl_col_idx=8,
        ))

    # ── Notes ──
    story.append(Paragraph("Notes & methodology", s["h2"]))
    notes = [
        "<b>Cost basis.</b> Stocks &amp; ETFs use weighted-average cost basis "
        "(buys add price × amount + fee; sells reduce units, leaving the "
        "average per-unit cost unchanged). Crypto uses FIFO — each sell is "
        "matched against the oldest unsold buy lots.",
        "<b>Realized vs Unrealized P&L.</b> Realized is locked in by past "
        "sells (sell price − weighted-avg or FIFO lot price, minus the sell "
        "fee). Unrealized is current market value minus the cost basis of "
        "units still held; it becomes realized the moment those units are sold.",
        "<b>Current price source.</b> Live prices are pulled from Finnhub "
        "(stocks and ETFs) and CoinGecko / Binance (crypto). Assets with no "
        "cached live price are shown as “—” and excluded from current value.",
        "<b>Real P&L vs invested.</b> Compares the mark-to-market portfolio "
        "worth to your cumulative cash deposits minus withdrawals. Includes "
        "both realized AND unrealized P&L on a single line.",
    ]
    for n in notes:
        story.append(Paragraph(n, s["body"]))
        story.append(Spacer(1, 0.2 * cm))

    decorate = _page_decorator("Analytics Report")
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    buf.seek(0)
    return buf


def _format_units(v):
    if v is None:
        return "—"
    if v == 0:
        return "0"
    return f"{v:.6f}".rstrip("0").rstrip(".") or "0"


def _truncate(s, n):
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"
